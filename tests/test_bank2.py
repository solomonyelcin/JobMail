from datetime import date, timedelta

import pytest

from app.bank import build_summary, dedupe, detect_recurring, parse_bank_email as P
from test_workspaces import BANK, WsGmail, sync_ws


def parse(subject, body, sender="alerts@hdfcbank.net"):
    return P(subject, body, body, sender, "2026-10-12T10:00:00Z")


def test_failed_and_balance_first_amounts():
    assert parse("Alert", "Your UPI payment of Rs. 500 to Swiggy has failed") is None
    t = parse("Alert", "Avl Bal Rs. 50,000.00. Rs. 750.00 debited from a/c XX1234 at Amazon")
    assert t["amount"] == 750.0 and t["balance"] == 50000.0


def test_card_bill_payment_not_double_counted():
    t = parse("Payment received", "Payment of Rs. 12,430.50 received towards your credit card XX4321. Thank you", "cards@hdfcbank.net")
    assert t["kind"] == "card_payment" and t["spend_cat"] == "Credit card payment"
    d = parse("Alert", "Rs. 12,430.50 debited from a/c XX1234 to CRED Club credit card bill payment. UPI Ref 991234567890")
    assert d["spend_cat"] == "Credit card payment" and d["ref"] == "991234567890"


def _row(i, kind, amount, day, cat="Other", merchant="", src="hdfcbank.net", ref="", cur="INR", account="1234"):
    return {"id": i, "txn_date": day + "T10:00:00Z", "kind": kind, "amount": amount, "currency": cur, "merchant": merchant,
            "spend_cat": cat, "channel": "UPI", "account": account, "balance": None, "min_due": None, "due_date": "",
            "src": src, "ref": ref}


def test_dedupe_by_reference_across_senders():
    rows = [_row(1, "debit", 450, "2026-10-12", ref="UPI12345678", src="hdfcbank.net"),
            _row(2, "debit", 450, "2026-10-13", ref="UPI12345678", src="phonepe.com")]
    assert len(dedupe(rows)) == 1


def test_card_payments_excluded_from_spend_and_income():
    rows = [_row(1, "debit", 5000, "2026-10-10", "Groceries", "dmart"),
            _row(2, "debit", 12000, "2026-10-11", "Credit card payment", "CRED"),
            _row(3, "card_payment", 12000, "2026-10-11", "Credit card payment", "HDFC", src="cards.hdfcbank.net"),
            _row(4, "credit", 80000, "2026-10-01", "Salary")]
    s = build_summary(rows, 90, today=date(2026, 10, 20))
    assert s["totals"]["debit"] == 5000 and s["totals"]["credit"] == 80000 and s["totals"]["card_bills_paid"] == 12000


def test_recurring_budget_and_unusual():
    rows = [_row(i, "debit", 649, (date(2026, 7, 5) + timedelta(days=30 * i)).isoformat(), "Subscriptions", "Netflix", ref=f"R{i}ABCDEFG")
            for i in range(4)]
    assert detect_recurring(rows)[0]["merchant"] == "Netflix"
    rows += [_row(10 + i, "debit", 300, f"2026-10-{i + 1:02d}", "Food & Dining", f"Cafe{i}") for i in range(8)]
    rows.append(_row(30, "debit", 6000, "2026-10-15", "Food & Dining", "Banquet"))
    s = build_summary(rows, 90, today=date(2026, 10, 20), budgets={"Food & Dining": 5000})
    assert s["recurring"] and s["unusual"][0]["merchant"] == "Banquet"
    b = s["budgets"][0]
    assert b["spent"] == 8400 and b["pct"] == 168
    s2 = build_summary(rows, 30, today=date(2026, 10, 20), start="2026-10-01", end="2026-10-31")
    assert s2["from"] == "2026-10-01" and s2["to"] == "2026-10-20"


def test_budget_exclude_reparse_api(app, auth_client):
    app.extensions["gmail_factory"] = lambda cfg, r: WsGmail(BANK)
    sync_ws(auth_client, "bank")
    assert auth_client.put("/api/bank/budgets", json={"category": "Food & Dining", "amount": 1000}).status_code == 200
    assert auth_client.put("/api/bank/budgets", json={"category": "Nope", "amount": 5}).status_code == 400
    s = auth_client.get("/api/bank/summary?from=2026-10-01&to=2026-10-31").get_json()
    assert s["budgets"][0]["category"] == "Food & Dining" and "vs_previous" in s and len(s["weekday"]) == 7
    t = auth_client.get("/api/bank/transactions?kind=debit").get_json()["items"]
    tid = t[0]["id"]
    assert auth_client.patch(f"/api/bank/transactions/{tid}", json={"excluded": True}).status_code == 200
    assert auth_client.get("/api/bank/transactions?kind=debit").get_json()["total"] == len(t) - 1
    assert auth_client.patch(f"/api/bank/transactions/{t[1]['id']}", json={"merchant": "My Cafe"}).status_code == 200
    r = auth_client.post("/api/bank/reparse", json={}).get_json()
    assert r["checked"] >= 3 and r["removed"] == 0
    # exclusion and manual merchant survive a reparse
    assert auth_client.get("/api/bank/transactions?kind=debit").get_json()["total"] == len(t) - 1


def test_ask_ai(app, auth_client, monkeypatch):
    from app import ai
    app.extensions["gmail_factory"] = lambda cfg, r: WsGmail(BANK)
    sync_ws(auth_client, "bank")
    assert auth_client.post("/api/bank/ask", json={"question": "hi"}).status_code == 400  # AI off in tests
    app.config["GEMINI_API_KEY"] = "k"
    seen = {}

    def fake(cfg, system, user, model, max_tokens=600):
        seen["user"] = user
        return "You spent most on Food."
    monkeypatch.setattr(ai, "complete", fake)
    r = auth_client.post("/api/bank/ask", json={"question": "What did I spend most on?"}).get_json()
    assert r["answer"] == "You spent most on Food." and "QUESTION: What did I spend most on?" in seen["user"]
