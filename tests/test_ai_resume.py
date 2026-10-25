import base64
import email as emaillib
import io
import json
import os
import tempfile
import zipfile

import helpers
from helpers import STATE, sync_all
from app import ai as ai_mod
from app.db import Database
from app.mailbuild import build_raw, first_address


def enable_ai(app, monkeypatch):
    app.config["ANTHROPIC_API_KEY"] = "test-key"

    def fake(cfg, system, user, model, max_tokens=600):
        if system.startswith("You write email replies"):
            return json.dumps({"subject": "Interview availability", "body": "Hello,\nI am available Monday.\nThanks,\nSam"})
        if "Pizza" in user:
            return json.dumps({"is_job": False})
        if "Data Analyst" in user:
            return json.dumps({"is_job": True, "category": "opening", "company": "Initech", "role": "Data Analyst",
                               "summary": "Job alert", "fit_score": 85, "fit_reason": "Matches your SQL skills"})
        if "Globex" in user:
            return "Sure! " + json.dumps({"is_job": True, "category": "rejected", "company": "Globex", "role": "",
                                          "summary": "Rejected", "fit_score": 40, "fit_reason": ""})
        cat = "interview" if "Interview" in user else "applied"
        return json.dumps({"is_job": True, "category": cat, "company": "Acme", "role": "Backend Engineer",
                           "summary": "x", "fit_score": None, "fit_reason": ""})

    monkeypatch.setattr(ai_mod, "complete", fake)


def make_docx(text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>")
    return buf.getvalue()


def upload(c, name, data):
    return c.post("/api/resume", data={"file": (io.BytesIO(data), name)}, content_type="multipart/form-data")


# ---------- unread ----------
def test_unread_flag_follows_gmail(auth_client):
    STATE["unread"] = {"m2"}
    sync_all(auth_client)
    items = {e["subject"]: e for e in auth_client.get("/api/emails").get_json()["items"]}
    assert items["Interview invitation - Backend Engineer"]["is_unread"] == 1
    assert auth_client.get("/api/emails?unread=1").get_json()["total"] == 1
    assert auth_client.get("/api/stats").get_json()["unread"] == 1

    STATE["unread"] = set()  # the user read it in Gmail
    auth_client.post("/api/sync", json={})
    assert auth_client.get("/api/emails?unread=1").get_json()["total"] == 0


def test_rescan_recovers_mail_skipped_earlier(app, auth_client):
    sync_all(auth_client)
    db = app.extensions["jobmail_db"]
    c = db.connect()
    c.execute("DELETE FROM emails WHERE gmail_id='m5'")  # as if an old rule had dropped it
    c.execute("INSERT INTO seen_messages (gmail_id) VALUES ('m5') ON CONFLICT DO NOTHING")
    c.commit(); c.close()
    assert auth_client.get("/api/emails").get_json()["total"] == 3
    sync_all(auth_client, rescan=True)
    assert auth_client.get("/api/emails").get_json()["total"] == 4


def test_old_database_gets_new_columns():
    path = os.path.join(tempfile.mkdtemp(), "old.db")
    import sqlite3
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE emails (id INTEGER PRIMARY KEY, gmail_id TEXT UNIQUE NOT NULL, subject TEXT, sender TEXT,"
                " sender_email TEXT, snippet TEXT, body_text TEXT, received_at TEXT NOT NULL, category TEXT NOT NULL,"
                " company TEXT, role TEXT, application_id INTEGER, thread_id TEXT)")
    raw.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, email TEXT, refresh_token_enc TEXT, created_at TEXT, last_sync_at TEXT)")
    raw.commit(); raw.close()
    db = Database("sqlite:///" + path)
    db.init_schema()
    c = db.connect()
    cols = {r["name"] for r in c.all("PRAGMA table_info(emails)")}
    assert {"is_unread", "ai_status", "fit_score", "message_id", "reply_to"} <= cols
    assert "scope" in {r["name"] for r in c.all("PRAGMA table_info(accounts)")}


# ---------- profile and resume ----------
def test_resume_upload_download_delete(auth_client):
    assert auth_client.get("/api/profile").get_json()["resume"] is None
    r = upload(auth_client, "My Resume.txt", b"Python developer, 5 years, SQL, Flask")
    assert r.status_code == 200
    prof = r.get_json()
    assert prof["resume"]["filename"] == "My_Resume.txt" and prof["resume"]["text_extracted"]
    assert "Python developer" in prof["profile_text"]  # profile pre-filled from the resume

    auth_client.put("/api/profile", json={"full_name": "Sam Doe", "profile_text": "Backend dev, Python"})
    again = upload(auth_client, "cv.docx", make_docx("Senior engineer with Django")).get_json()
    assert again["profile_text"] == "Backend dev, Python"  # existing profile text is never overwritten

    dl = auth_client.get("/api/resume")
    assert dl.status_code == 200 and "attachment" in dl.headers["Content-Disposition"]
    assert dl.headers["X-Content-Type-Options"] == "nosniff"
    assert auth_client.delete("/api/resume").get_json()["resume"] is None
    assert auth_client.get("/api/resume").status_code == 404


def test_resume_validation(auth_client):
    assert upload(auth_client, "evil.exe", b"MZ").get_json()["error"] == "unsupported_type"
    assert upload(auth_client, "fake.pdf", b"not a pdf").get_json()["error"] == "not_a_pdf"
    assert upload(auth_client, "big.txt", b"a" * (2 * 1024 * 1024 + 1)).get_json()["error"] == "too_large"
    assert upload(auth_client, "empty.txt", b"").get_json()["error"] == "empty_file"
    assert auth_client.post("/api/resume", data={}, content_type="multipart/form-data").status_code == 400


def test_docx_text_extraction():
    from app.resume import extract_text
    assert "Django" in extract_text(".docx", make_docx("Senior engineer with Django"))


# ---------- AI ----------
def test_ai_disabled_by_default(auth_client):
    assert auth_client.get("/api/me").get_json()["ai_enabled"] is False
    assert auth_client.post("/api/ai/analyze", json={}).status_code == 400
    assert auth_client.post("/api/emails/1/compose", json={}).status_code == 400


def test_ai_analysis_categorises_scores_and_highlights_matches(app, auth_client, monkeypatch):
    enable_ai(app, monkeypatch)
    auth_client.put("/api/profile", json={"full_name": "Sam", "profile_text": "SQL and Python analyst"})
    sync_all(auth_client)
    assert auth_client.get("/api/stats").get_json()["pending_ai"] == 5  # pizza stored as pending, hidden from lists
    assert all(e["subject"] != "50% off pizza tonight" for e in auth_client.get("/api/emails").get_json()["items"])

    out = {"remaining": 1}
    while out["remaining"]:
        out = auth_client.post("/api/ai/analyze", json={}).get_json()
    assert out["errors"] == 0

    subjects = [e["subject"] for e in auth_client.get("/api/emails").get_json()["items"]]
    assert "50% off pizza tonight" not in subjects  # AI said not job related
    m = auth_client.get("/api/matches").get_json()["items"]
    assert len(m) == 1 and m[0]["fit_score"] == 85 and m[0]["company"] == "Initech"
    assert auth_client.get("/api/matches?min=90").get_json()["items"] == []
    assert auth_client.get("/api/stats").get_json()["strong_matches"] == 1
    assert {a["company"] for a in auth_client.get("/api/applications").get_json()["items"]} == {"Acme", "Globex"}


def test_ai_errors_are_marked_and_retryable(app, auth_client, monkeypatch):
    enable_ai(app, monkeypatch)
    monkeypatch.setattr(ai_mod, "complete", lambda *a, **k: "not json")
    sync_all(auth_client)
    out = auth_client.post("/api/ai/analyze", json={}).get_json()
    assert out["errors"] > 0 and out["analyzed"] == 0
    enable_ai(app, monkeypatch)
    out = {"remaining": 1}
    first = True
    while out["remaining"]:
        out = auth_client.post("/api/ai/analyze", json={"retry": first}).get_json(); first = False
    assert auth_client.get("/api/emails").get_json()["total"] >= 3


def test_ai_output_is_validated():
    bad = json.dumps({"is_job": True, "category": "hacked", "company": "A" * 500, "fit_score": 999})
    ai_mod_complete = ai_mod.complete
    try:
        ai_mod.complete = lambda *a, **k: bad
        res = ai_mod.analyze_email(lambda k: "x", {"subject": "s", "sender": "a", "body_text": "b"}, "")
    finally:
        ai_mod.complete = ai_mod_complete
    assert res["category"] == "opening" and res["fit_score"] == 100 and len(res["company"]) == 100


# ---------- reply drafts ----------
def test_compose_and_create_draft_with_resume(app, auth_client, monkeypatch):
    enable_ai(app, monkeypatch)
    sync_all(auth_client)
    upload(auth_client, "resume.txt", b"Python developer")
    mail = next(e for e in auth_client.get("/api/emails").get_json()["items"] if e["subject"].startswith("Interview inv"))

    comp = auth_client.post(f"/api/emails/{mail['id']}/compose", json={"instructions": "keep it short"}).get_json()
    assert comp["to"] == "jobs@acme.com" and comp["subject"].startswith("Re:") and comp["has_resume"]
    assert comp["no_reply"] is False

    r = auth_client.post(f"/api/emails/{mail['id']}/draft",
                         json={"to": comp["to"], "subject": comp["subject"] + "\r\nBcc: x@evil.com", "body": comp["body"]})
    assert r.status_code == 200 and r.get_json()["attached"] is True
    assert r.get_json()["url"].endswith("compose=mm1")

    raw, thread = STATE["drafts"][0]
    assert thread == "t-m2"
    msg = emaillib.message_from_bytes(base64.urlsafe_b64decode(raw))
    assert msg["To"] == "jobs@acme.com" and msg["In-Reply-To"] == "<m2@mail.test>"
    assert "evil.com" not in str(msg.keys()) and msg["Bcc"] is None  # header injection neutralised
    names = [p.get_filename() for p in msg.walk() if p.get_filename()]
    assert names == ["resume.txt"]


def test_draft_requires_compose_permission(app, auth_client):
    sync_all(auth_client)
    c = app.extensions["jobmail_db"].connect()
    c.execute("UPDATE accounts SET scope='openid email https://www.googleapis.com/auth/gmail.readonly'")
    c.commit(); c.close()
    mail = auth_client.get("/api/emails").get_json()["items"][0]
    r = auth_client.post(f"/api/emails/{mail['id']}/draft", json={"body": "hi"})
    assert r.status_code == 403 and r.get_json()["error"] == "reauth_scope"
    assert auth_client.get("/api/me").get_json()["can_draft"] is False


def test_mailbuild_helpers():
    assert first_address("Acme HR <HR@Acme.com>, other@x.com") == "hr@acme.com"
    assert first_address("not an address") == ""
    try:
        build_raw("bad", "s", "b")
    except ValueError:
        pass
    else:
        raise AssertionError("accepted bad address")


# ---------- AI error reporting ----------
def _failing(kind_status, message):
    import requests

    class R:
        status_code = kind_status
        def json(self):
            return {"type": "error", "error": {"type": "x", "message": message}}
    return lambda *a, **k: R()


def test_api_errors_are_classified(monkeypatch):
    cases = [(401, "invalid x-api-key", "auth"), (400, "Your credit balance is too low", "billing"),
             (404, "model: nope", "model"), (403, "forbidden", "permission"), (400, "bad", "bad_request")]
    for status, msg, kind in cases:
        monkeypatch.setattr(ai_mod.requests, "post", _failing(status, msg))
        try:
            ai_mod.complete(lambda k: "x", "s", "u", "m")
        except ai_mod.AIError as exc:
            assert exc.kind == kind, (status, exc.kind)
        else:
            raise AssertionError("no error raised")


def test_compose_reports_the_reason(app, auth_client, monkeypatch):
    app.config["ANTHROPIC_API_KEY"] = "k"
    monkeypatch.setattr(ai_mod.requests, "post", _failing(400, "Your credit balance is too low to access the API"))
    sync_all(auth_client)
    mail = auth_client.get("/api/emails").get_json()["items"][0]
    r = auth_client.post(f"/api/emails/{mail['id']}/compose", json={})
    body = r.get_json()
    assert r.status_code == 502 and body["kind"] == "billing" and "credit" in body["help"].lower()


def test_fatal_ai_errors_keep_emails_pending_and_show_banner(app, auth_client, monkeypatch):
    app.config["ANTHROPIC_API_KEY"] = "k"
    monkeypatch.setattr(ai_mod.requests, "post", _failing(401, "invalid x-api-key"))
    sync_all(auth_client)
    out = auth_client.post("/api/ai/analyze", json={}).get_json()
    assert out["error_kind"] == "auth" and out["analyzed"] == 0 and out["errors"] > 0
    stats = auth_client.get("/api/stats").get_json()
    assert stats["pending_ai"] == 5  # nothing was marked as failed: they retry once the key is fixed
    assert stats["ai_error"]["kind"] == "auth" and "API key" in stats["ai_error"]["help"]


def test_ai_connection_test_endpoint(app, auth_client, monkeypatch):
    app.config["ANTHROPIC_API_KEY"] = "k"
    monkeypatch.setattr(ai_mod.requests, "post", _failing(404, "model: claude-x"))
    res = auth_client.post("/api/ai/test", json={}).get_json()
    assert res["ok"] is False and res["results"][0]["kind"] == "model"

    class Ok:
        status_code = 200
        def json(self):
            return {"content": [{"type": "text", "text": "OK"}]}
    monkeypatch.setattr(ai_mod.requests, "post", lambda *a, **k: Ok())
    assert auth_client.post("/api/ai/test", json={}).get_json()["ok"] is True
    assert auth_client.get("/api/stats").get_json()["ai_error"] is None


def test_gemini_provider_free_path(app, monkeypatch):
    from app import ai
    app.config["GEMINI_API_KEY"] = "g-key"
    cfg = lambda k: app.config.get(k, "")
    assert ai.enabled(cfg) and ai.provider(cfg) == "gemini" and ai.model_for(cfg, "analyze") == "gemini-2.5-flash"
    seen = {}

    class R:
        status_code = 200
        def json(self): return {"choices": [{"message": {"content": "OK"}}]}

    def post(url, headers, json, timeout):
        seen.update(url=url, auth=headers["Authorization"], model=json["model"])
        return R()
    monkeypatch.setattr(ai.requests, "post", post)
    assert ai.complete(cfg, "s", "u", "gemini-2.5-flash") == "OK"
    assert "generativelanguage" in seen["url"] and seen["auth"] == "Bearer g-key"
    assert "Google Gemini" in ai.help_text("billing", cfg)


def test_gemini_model_autodiscovery(app, monkeypatch):
    from app import ai
    ai._GEMINI_PICK.clear()
    app.config["GEMINI_API_KEY"] = "g2"
    cfg = lambda k: app.config.get(k, "")
    calls = []

    class R:
        def __init__(self, code, body): self.status_code, self._b = code, body
        def json(self): return self._b

    def post(url, headers, json, timeout):
        calls.append(json["model"])
        if json["model"] == "gemini-2.5-flash":
            return R(404, {"error": {"message": "models/gemini-2.5-flash is not found"}})
        return R(200, {"choices": [{"message": {"content": "OK"}}]})

    def get(url, headers, timeout):
        return R(200, {"models": [{"name": "models/gemini-3.8-flash"}, {"name": "models/gemini-3.8-flash-lite"},
                                  {"name": "models/gemini-3.5-flash"}, {"name": "models/gemini-3.8-pro"}]})
    monkeypatch.setattr(ai.requests, "post", post)
    monkeypatch.setattr(ai.requests, "get", get)
    assert ai.complete(cfg, "s", "u", ai.model_for(cfg, "analyze")) == "OK"
    assert calls == ["gemini-2.5-flash", "gemini-3.8-flash"]
    assert ai.model_for(cfg, "compose") == "gemini-3.8-flash"
    ai._GEMINI_PICK.clear()


def test_gemini_drops_reasoning_option_if_rejected(app, monkeypatch):
    from app import ai
    ai._GEMINI_PICK.clear()
    app.config["GEMINI_API_KEY"] = "g3"
    cfg = lambda k: app.config.get(k, "")
    sent = []

    class R:
        def __init__(self, code, body): self.status_code, self._b = code, body
        def json(self): return self._b

    def post(url, headers, json, timeout):
        sent.append("reasoning_effort" in json)
        if "reasoning_effort" in json:
            return R(400, {"error": {"message": "Unknown field reasoning_effort"}})
        return R(200, {"choices": [{"message": {"content": "OK"}}]})
    monkeypatch.setattr(ai.requests, "post", post)
    assert ai.complete(cfg, "s", "u", "gemini-x") == "OK" and sent == [True, False]


def test_groq_model_autodiscovery(app, monkeypatch):
    from app import ai
    ai._GROQ_PICK.clear()
    app.config["GROQ_API_KEY"] = "gq"
    app.config["GEMINI_API_KEY"] = ""
    cfg = lambda k: app.config.get(k, "")
    calls = []

    class R:
        def __init__(self, code, body): self.status_code, self._b = code, body
        def json(self): return self._b

    def post(url, headers, json, timeout):
        calls.append(json["model"])
        if json["model"] == "llama-3.3-70b-versatile":
            return R(404, {"error": {"message": "The model does not exist"}})
        return R(200, {"choices": [{"message": {"content": "OK"}}]})

    def get(url, headers, timeout):
        return R(200, {"data": [{"id": "whisper-large-v3"}, {"id": "llama-guard-4-12b"},
                                {"id": "meta-llama/llama-4-scout-17b-16e-instruct"}, {"id": "openai/gpt-oss-120b"}]})
    monkeypatch.setattr(ai.requests, "post", post)
    monkeypatch.setattr(ai.requests, "get", get)
    assert ai.provider(cfg) == "groq"
    assert ai.complete(cfg, "s", "u", ai.model_for(cfg, "analyze")) == "OK"
    assert calls[-1] == "openai/gpt-oss-120b" and ai.model_for(cfg, "compose") == "openai/gpt-oss-120b"
    ai._GROQ_PICK.clear()
