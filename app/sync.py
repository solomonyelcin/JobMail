"""Gmail -> database synchronisation and application tracking."""
import re
from datetime import datetime, timezone

import requests

from .classify import STATUS_BY_CATEGORY, classify, extract_company, extract_role
from .gmail import build_query


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def upsert_application(conn, company, role, status, ts):
    """Create or update the application for (company, role); return its id."""
    ck, rk = norm(company), norm(role)
    row = conn.one("SELECT * FROM applications WHERE company_key=? AND role_key=?", (ck, rk))
    if not row and rk:
        # an earlier email knew the company but not the role: adopt this role
        row = conn.one("SELECT * FROM applications WHERE company_key=? AND role_key=''", (ck,))
        if row:
            conn.execute("UPDATE applications SET role=?, role_key=? WHERE id=?", (role, rk, row["id"]))
    elif not row:
        row = conn.one(
            "SELECT * FROM applications WHERE company_key=? ORDER BY last_activity_at DESC LIMIT 1", (ck,)
        )
    if not row:
        cur = conn.execute(
            "INSERT INTO applications (company, company_key, role, role_key, status, source,"
            " first_seen_at, last_activity_at) VALUES (?,?,?,?,?,?,?,?) RETURNING id",
            (company, ck, role, rk, status, "auto", ts, ts),
        )
        return cur.fetchone()["id"]
    if ts >= row["last_activity_at"]:
        conn.execute("UPDATE applications SET last_activity_at=? WHERE id=?", (ts, row["id"]))
        if not row["status_locked"]:
            conn.execute("UPDATE applications SET status=? WHERE id=?", (status, row["id"]))
    if ts < row["first_seen_at"]:
        conn.execute("UPDATE applications SET first_seen_at=? WHERE id=?", (ts, row["id"]))
    return row["id"]


def run_sync(db, gmail, days, batch):
    """Fetch up to `batch` unseen messages, keep the job-related ones.

    Returns {"checked", "stored", "remaining"}; call again while remaining > 0.
    """
    conn = db.connect()
    try:
        ids = gmail.list_message_ids(build_query(days))
        seen = {r["gmail_id"] for r in conn.all("SELECT gmail_id FROM seen_messages")}
        new_ids = [i for i in ids if i not in seen]
        todo, remaining = new_ids[:batch], max(0, len(new_ids) - batch)

        messages = []
        for mid in todo:
            try:
                messages.append(gmail.get_message(mid))
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    conn.execute("INSERT INTO seen_messages (gmail_id) VALUES (?) ON CONFLICT DO NOTHING", (mid,))
                    continue
                raise
        messages.sort(key=lambda m: m["received_at"])

        stored = 0
        for m in messages:
            conn.execute("INSERT INTO seen_messages (gmail_id) VALUES (?) ON CONFLICT DO NOTHING", (m["gmail_id"],))
            cat = classify(m["subject"], m["snippet"], m["body_text"])
            if not cat:
                continue
            company = extract_company(m["sender"], m["subject"])
            role = extract_role(m["subject"], m["body_text"])
            app_id = None
            if cat in STATUS_BY_CATEGORY and company:
                app_id = upsert_application(conn, company, role, STATUS_BY_CATEGORY[cat], m["received_at"])
            conn.execute(
                "INSERT INTO emails (gmail_id, thread_id, subject, sender, sender_email, snippet, body_text,"
                " received_at, category, company, role, application_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT (gmail_id) DO NOTHING",
                (m["gmail_id"], m["thread_id"], m["subject"], m["sender"], _addr(m["sender"]), m["snippet"],
                 m["body_text"], m["received_at"], cat, company, role, app_id),
            )
            stored += 1
        conn.commit()
        return {"checked": len(todo), "stored": stored, "remaining": remaining}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _addr(sender):
    m = re.search(r"<([^>]+)>", sender or "")
    return (m.group(1) if m else (sender or "")).strip().lower()
