import base64
import email as emaillib
import json

import helpers
from helpers import STATE, sync_all
from app import ai as ai_mod, jobinfo, matchlocal, templates
from test_ai_resume import upload

RESUME = (b"Solomon Yelcin. Senior engineer, 9+ years. C#, .NET 8, ASP.NET Core, Angular, SQL Server, Azure, Docker, "
          b"Kubernetes, RabbitMQ, microservices.")

JD = ("We are hiring a Senior .NET Developer. 6+ years of experience in C#, ASP.NET Core, Azure and Kafka. "
      "Location: Chennai / Hybrid. Send your updated resume to careers.team@acme.com by 30 Nov 2026. "
      "Apply: https://acme.com/jobs/123.")


# ---------- details extraction ----------
def test_jobinfo_extracts_apply_address_links_dates_location():
    info = jobinfo.extract({"subject": "Senior .NET Developer", "body_text": JD, "sender_email": "noreply@x.com"})
    assert info["apply_to"][0] == "careers.team@acme.com"
    assert "https://acme.com/jobs/123" in info["links"]
    assert info["dates"][0]["kind"] == "deadline" and info["dates"][0]["date"] == "2026-11-30"
    assert info["location"].startswith("Chennai")
    assert "hybrid" in info["work_mode"]
    assert "6+ years" in info["experience"]


def test_jobinfo_ignores_noreply_addresses():
    assert jobinfo.find_apply_addresses("Contact noreply@acme.com or donotreply@acme.com") == []


# ---------- offline resume match ----------
def test_local_match_reports_matched_and_missing():
    r = matchlocal.compare({"subject": "Senior .NET Developer", "body_text": JD}, RESUME.decode())
    assert {"C#", "ASP.NET Core", "Azure"} <= set(r["matched"])
    assert "Kafka" in r["missing"]
    assert r["years_required"] == 6 and r["years_have"] == 9
    assert r["score"] is not None and r["score"] >= 50


def test_local_match_with_no_known_skills():
    r = matchlocal.compare({"subject": "Hello", "body_text": "Are you free to talk?"}, RESUME.decode())
    assert r["score"] is None and r["matched"] == []


# ---------- templates ----------
def test_template_uses_profile_and_leaves_placeholders():
    out = templates.render("share_details", {"sender": "Priya Sharma <p@x.com>", "subject": "Opening", "company": "Acme"},
                           None, {"full_name": "Solomon Yelcin", "notice_period": "30 days"})
    assert out["body"].startswith("Hi Priya,")
    assert "Notice period: 30 days" in out["body"]
    assert "[current CTC]" in out["body"]
    assert out["body"].rstrip().endswith("Solomon Yelcin")


def test_template_greeting_skips_team_senders():
    assert templates.first_name("Acme Careers Team <jobs@acme.com>") == ""
    assert templates.first_name("Priya Sharma <p@x.com>") == "Priya"
    assert templates.first_name("jobs@acme.com") == ""


def test_every_template_renders():
    for tid in templates.TEMPLATES:
        out = templates.render(tid, {"sender": "A <a@b.com>", "subject": "S"}, None, {})
        assert out and out["body"] and out["subject"]


# ---------- routes ----------
def _setup(auth_client):
    sync_all(auth_client)
    upload(auth_client, "cv.txt", RESUME)
    auth_client.put("/api/profile", json={"full_name": "Solomon Yelcin", "profile_text": RESUME.decode(),
                                          "notice_period": "60 days", "location": "Chennai"})
    return {e["subject"]: e["id"] for e in auth_client.get("/api/emails").get_json()["items"]}


def _add_jd(app):
    c = app.extensions["jobmail_db"].connect()
    c.execute("INSERT INTO emails (gmail_id, thread_id, subject, sender, sender_email, snippet, body_text, received_at,"
              " category, company, role, message_id) VALUES ('jd1','t-jd1','Senior .NET Developer',"
              " 'Acme HR <noreply@acme.com>','noreply@acme.com','hiring',?, '2026-11-20T10:00:00Z','opening','Acme',"
              "'Senior .NET Developer','<jd1@x>')", (JD,))
    c.commit()
    eid = c.one("SELECT id FROM emails WHERE gmail_id='jd1'")["id"]
    c.close()
    return eid


def test_details_route(app, auth_client):
    _setup(auth_client)
    eid = _add_jd(app)
    d = auth_client.get(f"/api/emails/{eid}/details").get_json()
    assert d["info"]["apply_to"][0] == "careers.team@acme.com"
    assert d["local_match"]["matched"] and d["has_resume"] is True and d["done"] is False
    assert any(t["id"] == "apply" and t["suggested"] for t in d["templates"])
    assert auth_client.get("/api/emails/99999/details").status_code == 404


def test_apply_template_targets_the_address_in_the_body_and_attaches_resume(app, auth_client):
    _setup(auth_client)
    eid = _add_jd(app)
    t = auth_client.post(f"/api/emails/{eid}/template", json={"template_id": "apply"}).get_json()
    assert t["to"] == "careers.team@acme.com" and t["new_thread"] is True and t["attach"] is True
    assert "Senior .NET Developer" in t["subject"] and "Solomon Yelcin" in t["subject"]
    assert "Notice period: 60 days" in t["body"] and "[current CTC]" in t["missing"] or "[current CTC]" in t["body"]
    assert auth_client.post(f"/api/emails/{eid}/template", json={"template_id": "nope"}).status_code == 400


def test_apply_draft_is_a_new_thread_with_resume_and_marks_replied(app, auth_client):
    _setup(auth_client)
    eid = _add_jd(app)
    r = auth_client.post(f"/api/emails/{eid}/draft", json={
        "to": "careers.team@acme.com", "subject": "Application", "body": "Please find my resume.",
        "attach_resume": True, "new_thread": True})
    assert r.status_code == 200 and r.get_json()["attached"] is True
    raw, thread_id = STATE["drafts"][-1]
    assert thread_id is None  # a fresh conversation, not a reply in the job-alert thread
    msg = emaillib.message_from_bytes(base64.urlsafe_b64decode(raw))
    assert msg["In-Reply-To"] is None and msg["To"] == "careers.team@acme.com"
    assert any(p.get_filename() for p in msg.walk())
    assert auth_client.get(f"/api/emails/{eid}/details").get_json()["replied_at"]


def test_reply_draft_stays_in_thread(app, auth_client):
    ids = _setup(auth_client)
    eid = ids["Interview invitation - Backend Engineer"]
    auth_client.post(f"/api/emails/{eid}/draft", json={"to": "jobs@acme.com", "subject": "Re: x", "body": "Yes."})
    assert STATE["drafts"][-1][1] == "t-m2"


def test_actions_list_and_done(app, auth_client):
    ids = _setup(auth_client)
    items = auth_client.get("/api/actions").get_json()["items"]
    subjects = [i["subject"] for i in items]
    assert "Interview invitation - Backend Engineer" in subjects
    assert all(i["category"] in ("interview", "assessment", "offer", "recruiter") for i in items)
    n = auth_client.get("/api/stats").get_json()["needs_action"]
    eid = ids["Interview invitation - Backend Engineer"]
    assert auth_client.post(f"/api/emails/{eid}/done", json={"done": True}).get_json()["done"] is True
    assert auth_client.get("/api/stats").get_json()["needs_action"] == n - 1
    assert eid not in [i["id"] for i in auth_client.get("/api/actions").get_json()["items"]]
    auth_client.post(f"/api/emails/{eid}/done", json={"done": False})
    assert eid in [i["id"] for i in auth_client.get("/api/actions").get_json()["items"]]


def test_profile_reply_details_round_trip(auth_client):
    auth_client.put("/api/profile", json={"full_name": "S", "profile_text": "x", "phone": "+91 99999 00000",
                                          "notice_period": "30 days", "expected_ctc": "28 LPA"})
    p = auth_client.get("/api/profile").get_json()
    assert p["phone"] == "+91 99999 00000" and p["notice_period"] == "30 days" and p["expected_ctc"] == "28 LPA"
    assert p["location"] == ""


def test_ai_match_is_cached_and_needs_ai(app, auth_client, monkeypatch):
    _setup(auth_client)
    eid = _add_jd(app)
    assert auth_client.post(f"/api/emails/{eid}/match", json={}).status_code == 400  # AI off
    app.config["ANTHROPIC_API_KEY"] = "k"
    calls = []

    def fake(cfg, system, user, model, max_tokens=600):
        calls.append(1)
        return json.dumps({"fit_score": 82, "verdict": "Good fit", "strengths": ["C#", "Azure"], "gaps": ["Kafka"],
                           "emphasise": ["9 years"], "questions": ["Is it remote?"], "next_step": "Apply today"})

    monkeypatch.setattr(ai_mod, "complete", fake)
    r = auth_client.post(f"/api/emails/{eid}/match", json={}).get_json()
    assert r["fit_score"] == 82 and r["gaps"] == ["Kafka"]
    auth_client.post(f"/api/emails/{eid}/match", json={})
    assert len(calls) == 1  # second call served from the cache
    auth_client.post(f"/api/emails/{eid}/match", json={"refresh": True})
    assert len(calls) == 2
    assert auth_client.get(f"/api/emails/{eid}/details").get_json()["ai_match"]["verdict"] == "Good fit"
