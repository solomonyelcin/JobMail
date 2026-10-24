from urllib.parse import parse_qs, urlparse


def sync_all(c):
    out = {"remaining": 1}
    while out["remaining"]:
        r = c.post("/api/sync", json={})
        assert r.status_code == 200, r.get_json()
        out = r.get_json()
    return out


def test_health(client):
    assert client.get("/healthz").get_json() == {"status": "ok"}


def test_index_and_headers(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


def test_requires_login(client):
    assert client.get("/api/emails").status_code == 401
    assert client.get("/api/me").get_json() == {"authenticated": False}


def test_wrong_email_session_rejected(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["email"] = "someone-else@example.com"
    assert c.get("/api/applications").status_code == 401


def test_csrf_header_required_for_writes(auth_client):
    auth_client.environ_base.pop("HTTP_X_REQUESTED_WITH")
    assert auth_client.post("/api/sync", json={}).status_code == 400


def test_login_redirects_to_google_with_state(client):
    r = client.get("/auth/login")
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["Location"]).query)
    assert q["client_id"] == ["cid"]
    assert q["redirect_uri"] == ["http://localhost:8000/auth/callback"]
    assert q["access_type"] == ["offline"]
    assert "gmail.readonly" in q["scope"][0]
    assert q["state"][0]


def test_callback_rejects_bad_state(client):
    client.get("/auth/login")
    r = client.get("/auth/callback?code=x&state=wrong")
    assert "auth_error=state_mismatch" in r.headers["Location"]


def test_callback_stores_encrypted_token_and_rejects_other_accounts(app, client, monkeypatch):
    from app import api

    def run(email):
        client.get("/auth/login")
        with client.session_transaction() as s:
            state = s["oauth_state"]
        monkeypatch.setattr(api.gmail, "exchange_code",
                            lambda *a: {"access_token": "at", "refresh_token": "plain-refresh"})
        monkeypatch.setattr(api.gmail, "get_userinfo", lambda t: {"email": email, "email_verified": True})
        return client.get(f"/auth/callback?code=c&state={state}")

    assert "auth_error=account_not_allowed" in run("intruder@example.com").headers["Location"]
    assert client.get("/api/me").get_json()["authenticated"] is False

    assert run("me@example.com").headers["Location"] == "/"
    assert client.get("/api/me").get_json()["authenticated"] is True
    c = app.extensions["jobmail_db"].connect()
    stored = c.one("SELECT refresh_token_enc FROM accounts")["refresh_token_enc"]
    assert "plain-refresh" not in stored
    assert app.extensions["jobmail_cipher"].decrypt(stored) == "plain-refresh"


def test_sync_batches_classifies_and_tracks(auth_client):
    r = auth_client.post("/api/sync", json={})
    first = r.get_json()
    assert first["checked"] == 3 and first["remaining"] == 2
    sync_all(auth_client)

    emails = auth_client.get("/api/emails").get_json()
    assert emails["total"] == 4  # pizza email is not stored
    cats = {e["subject"]: e["category"] for e in emails["items"]}
    assert cats["Interview invitation - Backend Engineer"] == "interview"
    assert cats["New jobs for you: Data Analyst"] == "opening"

    apps = {a["company"]: a for a in auth_client.get("/api/applications").get_json()["items"]}
    assert set(apps) == {"Acme", "Globex"}
    assert apps["Acme"]["status"] == "interview"  # latest email wins
    assert apps["Acme"]["email_count"] == 2
    assert apps["Globex"]["status"] == "rejected"

    # syncing again does not duplicate anything
    again = auth_client.post("/api/sync", json={}).get_json()
    assert again == {"checked": 0, "stored": 0, "remaining": 0}
    assert auth_client.get("/api/emails").get_json()["total"] == 4
    assert auth_client.get("/api/me").get_json()["last_sync_at"]


def test_search_and_filters(auth_client):
    sync_all(auth_client)
    g = lambda qs: auth_client.get("/api/emails?" + qs).get_json()
    assert g("q=interview")["total"] == 1
    assert g("q=ACME")["total"] == 2
    assert g("q=acme+interview")["total"] == 1
    assert g("category=opening")["total"] == 1
    assert g("status=rejected")["total"] == 1
    assert g("company=glob")["total"] == 1
    assert g("from=2026-10-04&to=2026-10-05")["total"] == 1
    assert g("q=%25")["total"] == 0  # wildcard characters are escaped


def test_application_crud_and_lock(auth_client):
    sync_all(auth_client)
    acme = next(a for a in auth_client.get("/api/applications").get_json()["items"] if a["company"] == "Acme")

    r = auth_client.patch(f"/api/applications/{acme['id']}", json={"status": "offer", "notes": "great"})
    assert r.get_json()["status"] == "offer" and r.get_json()["notes"] == "great"
    assert auth_client.patch(f"/api/applications/{acme['id']}", json={"status": "bogus"}).status_code == 400

    created = auth_client.post("/api/applications", json={"company": "Initech", "role": "Dev"})
    assert created.status_code == 201
    assert auth_client.post("/api/applications", json={"company": "initech", "role": "dev"}).status_code == 409
    assert auth_client.post("/api/applications", json={"company": ""}).status_code == 400

    assert auth_client.get("/api/applications?q=initech").get_json()["items"][0]["source"] == "manual"
    stats = auth_client.get("/api/stats").get_json()
    assert stats["applications"]["offer"] == 1 and stats["total_emails"] == 4

    assert auth_client.delete(f"/api/applications/{created.get_json()['id']}").status_code == 200
    assert auth_client.get("/api/applications?q=initech").get_json()["items"] == []


def test_reauth_when_google_rejects_refresh_token(app, auth_client):
    import requests

    def boom(cfg, refresh):
        resp = requests.Response()
        resp.status_code = 400
        raise requests.HTTPError(response=resp)

    app.extensions["gmail_factory"] = boom
    r = auth_client.post("/api/sync", json={})
    assert r.status_code == 401 and r.get_json()["error"] == "reauth"
