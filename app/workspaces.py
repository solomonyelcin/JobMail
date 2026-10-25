"""Banking and Personal workspaces: Gmail queries, syncing, and people (contacts) handling."""
import re

from .bank import parse_bank_email
from .sync import _addr

BANK_SENDERS = (
    "hdfcbank.net OR hdfcbank.com OR icicibank.com OR sbi.co.in OR onlinesbi.com OR axisbank.com OR kotak.com OR "
    "yesbank.in OR idfcfirstbank.com OR indusind.com OR pnb.co.in OR bankofbaroda.in OR canarabank.com OR "
    "unionbankofindia.co.in OR federalbank.co.in OR rblbank.com OR aubank.in OR paytm.com OR phonepe.com OR "
    "bajajfinserv.in OR bajajfinance.com OR americanexpress.com OR citi.com OR hsbc.co.in OR sc.com OR "
    "cred.club OR slice.com OR icicilombard.com OR hdfclife.com OR bank"
)
BANK_KEYWORDS = (
    'debited OR credited OR "transaction alert" OR UPI OR "a/c" OR "account statement" OR "credit card" OR EMI OR '
    'loan OR "payment received" OR "payment successful" OR "amount due" OR NEFT OR IMPS OR "salary credited" OR '
    '"bill payment" OR "due date" OR "e-statement"'
)
NO_PERSON = re.compile(r"no-?reply|do-?not-?reply|newsletter|mailer-daemon|notifications?@|updates?@|marketing|promo", re.I)
RELATIONS = ("family", "friend", "other")


def bank_query(days):
    return f"newer_than:{int(days)}d -in:spam -in:trash (from:({BANK_SENDERS}) OR ({BANK_KEYWORDS}))"


def personal_query(days, emails):
    parts = ["is:starred", "(is:important -category:promotions -category:updates -category:social -category:forums)"]
    if emails:
        parts.insert(0, "from:(" + " OR ".join(emails[:80]) + ")")
    return f"newer_than:{int(days)}d -in:spam -in:trash (" + " OR ".join(parts) + ")"


def people_map(conn):
    return {r["email"]: r for r in conn.all("SELECT email, name, relation FROM people")}


def personal_category(sender_email, labels, people):
    p = people.get(sender_email)
    if p:
        return {"family": "family", "friend": "friend"}.get(p["relation"], "people")
    if "STARRED" in labels:
        return "starred"
    if "IMPORTANT" in labels and not NO_PERSON.search(sender_email):
        return "important"
    return ""


def query_for(conn, ws, days):
    if ws == "bank":
        return bank_query(days)
    return personal_query(days, sorted(people_map(conn)))


def run_ws_sync(db, gmail, ws, days, batch):
    """Fetch up to `batch` unseen messages for the workspace. Returns {"checked","stored","remaining"}."""
    conn = db.connect()
    try:
        people = people_map(conn) if ws == "personal" else {}
        ids = gmail.list_message_ids(query_for(conn, ws, days))
        seen = {r["gmail_id"] for r in conn.all("SELECT gmail_id FROM wseen WHERE ws=?", (ws,))}
        existing = {r["gmail_id"] for r in conn.all("SELECT gmail_id FROM wmails WHERE ws=?", (ws,))}
        other = set()
        if ws == "personal":  # job and bank mail stay in their own workspaces
            other = {r["gmail_id"] for r in conn.all("SELECT gmail_id FROM emails")}
            other |= {r["gmail_id"] for r in conn.all("SELECT gmail_id FROM wmails WHERE ws='bank'")}
        new_ids = [i for i in ids if i not in seen and i not in existing]
        todo, remaining = new_ids[:batch], max(0, len(new_ids) - batch)
        fetched = gmail.get_messages(todo)
        messages = sorted((m for m in (fetched.get(i) for i in todo) if m), key=lambda m: m["received_at"])
        for i in todo:
            if fetched.get(i) is None:
                conn.execute("INSERT INTO wseen (ws, gmail_id) VALUES (?,?) ON CONFLICT DO NOTHING", (ws, i))
        stored = 0
        for m in messages:
            conn.execute("INSERT INTO wseen (ws, gmail_id) VALUES (?,?) ON CONFLICT DO NOTHING", (ws, m["gmail_id"]))
            sender_email = _addr(m["sender"])
            labels = m.get("labels", [])
            txn = None
            if ws == "bank":
                txn = parse_bank_email(m["subject"], m["snippet"], m["body_text"], sender_email, m["received_at"])
                if not txn:
                    continue
                cat = txn["category"]
            else:
                cat = personal_category(sender_email, labels, people)
                if not cat or (m["gmail_id"] in other and sender_email not in people):
                    continue
                if NO_PERSON.search(sender_email) and sender_email not in people and "STARRED" not in labels:
                    continue
            cur = conn.execute(
                "INSERT INTO wmails (ws, gmail_id, thread_id, subject, sender, sender_email, snippet, body_text,"
                " received_at, category, is_unread, is_starred, is_important)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (gmail_id) DO NOTHING RETURNING id",
                (ws, m["gmail_id"], m["thread_id"], m["subject"], m["sender"], sender_email, m["snippet"],
                 m["body_text"], m["received_at"], cat, m.get("is_unread", 0), 1 if "STARRED" in labels else 0,
                 1 if "IMPORTANT" in labels else 0))
            row = cur.fetchone()
            if not row:
                continue
            if txn:
                conn.execute(
                    "INSERT INTO transactions (mail_id, txn_date, kind, amount, currency, merchant, spend_cat, channel,"
                    " account, balance, min_due, due_date, src) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (row["id"], m["received_at"], txn["kind"], txn["amount"], txn["currency"], txn["merchant"],
                     txn["spend_cat"], txn["channel"], txn["account"], txn["balance"], txn["min_due"],
                     txn["due_date"], txn["src"]))
            stored += 1
        if remaining == 0 and hasattr(gmail, "list_message_ids"):
            refresh_ws_unread(conn, gmail, ws, query_for(conn, ws, days))
        conn.commit()
        return {"checked": len(todo), "stored": stored, "remaining": remaining}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def refresh_ws_unread(conn, gmail, ws, query):
    unread = set(gmail.list_message_ids(query + " is:unread"))
    for r in conn.all("SELECT gmail_id, is_unread FROM wmails WHERE ws=?", (ws,)):
        want = 1 if r["gmail_id"] in unread else 0
        if want != r["is_unread"]:
            conn.execute("UPDATE wmails SET is_unread=? WHERE gmail_id=?", (want, r["gmail_id"]))


def apply_people_change(conn):
    """After the people list changes: re-label stored personal mails and schedule a rescan so older mail from
    newly added people is picked up."""
    people = people_map(conn)
    for r in conn.all("SELECT id, sender_email, is_starred, is_important FROM wmails WHERE ws='personal'"):
        labels = (["STARRED"] if r["is_starred"] else []) + (["IMPORTANT"] if r["is_important"] else [])
        cat = personal_category(r["sender_email"], labels, people)
        if cat:
            conn.execute("UPDATE wmails SET category=? WHERE id=?", (cat, r["id"]))
        else:
            conn.execute("DELETE FROM wmails WHERE id=?", (r["id"],))
    conn.execute("DELETE FROM wseen WHERE ws='personal'")
