import os

import pytest
from cryptography.fernet import Fernet

import helpers
from app import create_app


class FakeGmail:
    def __init__(self, messages):
        self.messages = messages

    def list_message_ids(self, query, max_total=1000):
        return [m["gmail_id"] for m in self.messages]

    def get_message(self, mid):
        return next(m for m in self.messages if m["gmail_id"] == mid)

    def list_unread_ids(self, days, max_total=1000):
        return list(helpers.STATE["unread"])

    def create_draft(self, raw, thread_id=None):
        helpers.STATE["drafts"].append((raw, thread_id))
        return {"id": "d1", "message": {"id": "mm1", "threadId": thread_id}}

    def get_messages(self, ids, workers=8):
        return {i: next((m for m in self.messages if m["gmail_id"] == i), None) for i in ids}


def msg(gid, subject, sender, snippet="", body="", when="2026-10-01T10:00:00Z", unread=0):
    return {"gmail_id": gid, "thread_id": "t-" + gid, "subject": subject, "sender": sender,
            "snippet": snippet, "body_text": body, "received_at": when, "is_unread": unread,
            "message_id": f"<{gid}@mail.test>", "reply_to": ""}


SAMPLE = [
    msg("m1", "Thank you for applying to Acme", "Acme Careers <jobs@acme.com>",
        "We received your application for the Backend Engineer position", when="2026-10-01T10:00:00Z"),
    msg("m2", "Interview invitation - Backend Engineer", "Acme Careers <jobs@acme.com>",
        "We would like to schedule an interview", when="2026-10-05T10:00:00Z"),
    msg("m3", "Update on your application to Globex", "Globex Recruiting <no-reply@globex.io>",
        "Unfortunately we are not moving forward", when="2026-10-03T10:00:00Z"),
    msg("m4", "50% off pizza tonight", "Pizza <deals@pizza.com>", "Order now", when="2026-10-04T10:00:00Z"),
    msg("m5", "New jobs for you: Data Analyst", "LinkedIn Job Alerts <jobalerts@linkedin.com>",
        "job alert: 12 new jobs", when="2026-10-06T10:00:00Z"),
]


@pytest.fixture()
def app():
    os.environ.setdefault("TZ", "UTC")
    a = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:"),
        "ALLOWED_EMAIL": "me@example.com",
        "GOOGLE_CLIENT_ID": "cid",
        "GOOGLE_CLIENT_SECRET": "secret",
        "BASE_URL": "http://localhost:8000",
        "SYNC_BATCH": 3,
        "ANTHROPIC_API_KEY": "",
    })
    helpers.STATE.update(unread=set(), drafts=[], ai=None)
    a.extensions["gmail_factory"] = lambda cfg, refresh: FakeGmail(SAMPLE)
    db = a.extensions["jobmail_db"]
    # start every test from empty tables (matters when TEST_DATABASE_URL points at Postgres)
    c = db.connect()
    for t in ("transactions", "wmails", "wseen", "people", "emails", "applications", "seen_messages", "ignored_messages", "profile", "meta", "accounts"):
        c.execute(f"DELETE FROM {t}")
    c.commit()
    c.close()
    return a


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_client(app):
    """A client that is signed in and has a stored (encrypted) refresh token."""
    db = app.extensions["jobmail_db"]
    c = db.connect()
    enc = app.extensions["jobmail_cipher"].encrypt("refresh-token")
    c.execute("INSERT INTO accounts (email, refresh_token_enc, created_at, scope) VALUES (?,?,?,?)",
              ("me@example.com", enc, "2026-10-01T00:00:00Z",
               "openid email https://www.googleapis.com/auth/gmail.readonly "
               "https://www.googleapis.com/auth/gmail.compose"))
    c.commit()
    c.close()
    cl = app.test_client()
    with cl.session_transaction() as s:
        s["email"] = "me@example.com"
    cl.environ_base["HTTP_X_REQUESTED_WITH"] = "JobMail"
    return cl
