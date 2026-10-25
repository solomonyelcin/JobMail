import conftest
from conftest import msg


class WsGmail(conftest.FakeGmail):
    def list_message_ids(self, query, max_total=1000):
        ids = [m["gmail_id"] for m in self.messages]
        if query.endswith("is:unread"):
            return [m["gmail_id"] for m in self.messages if m["is_unread"]]
        return ids


def labelled(m, labels):
    m["labels"] = labels
    return m


BANK = [
    msg("b1", "Transaction alert", "HDFC Bank <alerts@hdfcbank.net>",
        "Rs. 450.00 debited from a/c XX1234 on 12-10-26 to VPA swiggy@icici. UPI Ref 1. Avl Bal Rs. 12,345.60",
        "Rs. 450.00 debited from a/c XX1234 to VPA swiggy@icici. UPI Ref 1. Avl Bal Rs. 12,345.60", when="2026-10-12T10:00:00Z"),
    msg("b2", "Salary credited", "ICICI <alerts@icicibank.com>", "INR 85,000.00 credited to your account XX1234 salary",
        "INR 85,000.00 credited to your account XX1234 salary", when="2026-10-01T10:00:00Z"),
    msg("b3", "Your credit card statement", "HDFC Cards <cards@hdfcbank.net>", "Total amount due Rs. 12,430.50",
        "Total amount due Rs. 12,430.50. Minimum amount due Rs. 620. Payment due date 05-11-2026", when="2026-10-20T10:00:00Z"),
    msg("b4", "Your OTP", "SBI <a@sbi.co.in>", "Your OTP is 123456", "Your OTP is 123456"),
    msg("b5", "Transaction alert", "UPI <noreply@phonepe.com>", "Rs. 450.00 debited from a/c XX1234 to swiggy",
        "Rs. 450.00 debited from a/c XX1234 to VPA swiggy@icici", when="2026-10-12T11:00:00Z"),
]


def sync_ws(c, ws):
    for _ in range(10):
        r = c.post(f"/api/ws/{ws}/sync", json={})
        assert r.status_code == 200, r.data
        if not r.get_json()["remaining"]:
            return r.get_json()


def test_bank_sync_and_summary(app, auth_client):
    app.extensions["gmail_factory"] = lambda cfg, r: WsGmail(BANK)
    sync_ws(auth_client, "bank")
    t = auth_client.get("/api/bank/transactions").get_json()
    assert t["total"] == 4  # OTP dropped
    s = auth_client.get("/api/bank/summary?days=90").get_json()
    assert s["totals"]["credit"] == 85000.0
    assert s["totals"]["debit"] == 450.0  # the duplicate alert from PhonePe is not double counted
    assert s["by_category"][0]["name"] == "Food & Dining"
    assert s["upcoming"] and s["upcoming"][0]["due_date"] == "2026-11-05" and s["upcoming"][0]["min_due"] == 620.0
    assert s["accounts"][0]["balance"] == 12345.6


def test_bank_category_edit_teaches_merchant(app, auth_client):
    app.extensions["gmail_factory"] = lambda cfg, r: WsGmail(BANK)
    sync_ws(auth_client, "bank")
    t = auth_client.get("/api/bank/transactions?kind=debit").get_json()["items"]
    r = auth_client.patch(f"/api/bank/transactions/{t[0]['id']}", json={"category": "Groceries"})
    assert r.status_code == 200 and r.get_json()["changed"] >= 1
    assert auth_client.patch(f"/api/bank/transactions/{t[0]['id']}", json={"category": "Nope"}).status_code == 400
    assert auth_client.get("/api/bank/export.csv").data.startswith(b"date,type")


def test_personal_people_and_filters(app, auth_client):
    mails = [
        labelled(msg("p1", "Dinner Sunday?", "Mom <mom@family.com>", "Are you coming?", unread=1), ["INBOX", "UNREAD"]),
        labelled(msg("p2", "Newsletter", "News <no-reply@news.com>", "weekly", unread=0), ["IMPORTANT"]),
        labelled(msg("p3", "Starred note", "Boss <boss@work.com>", "see this"), ["STARRED"]),
        labelled(msg("p4", "Hi", "Friend <pal@x.com>", "yo"), ["INBOX"]),
    ]
    app.extensions["gmail_factory"] = lambda cfg, r: WsGmail(mails)
    assert auth_client.post("/api/people", json={"email": "bad"}).status_code == 400
    assert auth_client.post("/api/people", json={"email": "mom@family.com", "name": "Mom", "relation": "family"}).status_code == 201
    assert auth_client.post("/api/people", json={"email": "pal@x.com", "name": "Pal", "relation": "friend"}).status_code == 201
    sync_ws(auth_client, "personal")
    allm = auth_client.get("/api/personal/mails").get_json()
    subjects = {i["subject"] for i in allm["items"]}
    assert subjects == {"Dinner Sunday?", "Starred note", "Hi"}  # no-reply newsletter dropped
    assert auth_client.get("/api/personal/mails?filter=family").get_json()["total"] == 1
    assert auth_client.get("/api/personal/mails?filter=unread").get_json()["total"] == 1
    st = auth_client.get("/api/ws/stats").get_json()["personal"]
    assert st["family"] == 1 and st["friend"] == 1 and st["starred"] == 1 and st["people"] == 2
    pid = auth_client.get("/api/people").get_json()["items"][0]["id"]
    assert auth_client.delete(f"/api/people/{pid}").status_code == 200
    assert auth_client.get("/api/ws/stats").get_json()["personal"]["people"] == 1


def test_ws_requires_auth_and_valid_ws(client, auth_client):
    assert client.get("/api/bank/summary").status_code == 401
    assert auth_client.post("/api/ws/nope/sync", json={}).status_code == 404


def test_ai_batches(app, auth_client, monkeypatch):
    from app import ai
    app.extensions["gmail_factory"] = lambda cfg, r: WsGmail(BANK)
    sync_ws(auth_client, "bank")
    app.config["GEMINI_API_KEY"] = "k"
    calls = []

    def fake(cfg, system, user, model, max_tokens=600):
        calls.append(user)
        return '{"items":[{"i":0,"merchant":"Local Shop","category":"Groceries"}], "insights":["Spend is steady."]}'
    monkeypatch.setattr(ai, "complete", fake)
    # force one uncategorised debit
    c = app.extensions["jobmail_db"].connect()
    c.execute("UPDATE transactions SET spend_cat='Other', merchant='' WHERE kind='debit'")
    c.commit(); c.close()
    r = auth_client.post("/api/ws/bank/analyze", json={}).get_json()
    assert r["done"] >= 1 and len(calls) == 1
    t = auth_client.get("/api/bank/transactions?kind=debit").get_json()["items"]
    assert t[0]["spend_cat"] == "Groceries" and t[0]["cat_src"] == "ai"
    ins = auth_client.post("/api/bank/insights", json={}).get_json()
    assert ins["items"] == ["Spend is steady."]
    assert auth_client.get("/api/bank/summary").get_json()["ai_insights"]["items"] == ["Spend is steady."]
