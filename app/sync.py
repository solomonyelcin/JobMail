"""Gmail -> database synchronisation and application tracking."""
import re
from datetime import datetime, timezone

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


def run_sync(db, gmail, days, batch, ai_enabled=False):
    """Fetch up to `batch` unseen messages and keep the job-related ones.

    With ai_enabled, messages the rules cannot place are stored as category "pending" so the AI step decides.
    Returns {"checked", "stored", "remaining"}; call again while remaining > 0.
    """
    conn = db.connect()
    try:
        ids = gmail.list_message_ids(build_query(days))
        skip = {r["gmail_id"] for r in conn.all("SELECT gmail_id FROM seen_messages")}
        skip |= {r["gmail_id"] for r in conn.all("SELECT gmail_id FROM ignored_messages")}
        existing = {r["gmail_id"] for r in conn.all("SELECT gmail_id FROM emails")}
        for gid in existing:  # stored already (e.g. after a rescan): just remember them
            conn.execute("INSERT INTO seen_messages (gmail_id) VALUES (?) ON CONFLICT DO NOTHING", (gid,))
        new_ids = [i for i in ids if i not in skip and i not in existing]
        todo, remaining = new_ids[:batch], max(0, len(new_ids) - batch)

        fetched = gmail.get_messages(todo)
        messages = []
        for mid in todo:
            m = fetched.get(mid)
            if m is None:  # deleted in Gmail since listing
                conn.execute("INSERT INTO seen_messages (gmail_id) VALUES (?) ON CONFLICT DO NOTHING", (mid,))
            else:
                messages.append(m)
        messages.sort(key=lambda m: m["received_at"])

        stored = 0
        for m in messages:
            conn.execute("INSERT INTO seen_messages (gmail_id) VALUES (?) ON CONFLICT DO NOTHING", (m["gmail_id"],))
            cat = classify(m["subject"], m["snippet"], m["body_text"], m["sender"])
            if not cat and ai_enabled:
                cat = "pending"
            if not cat:
                continue
            company = extract_company(m["sender"], m["subject"])
            role = extract_role(m["subject"], m["body_text"])
            app_id = None
            if cat in STATUS_BY_CATEGORY and company:
                app_id = upsert_application(conn, company, role, STATUS_BY_CATEGORY[cat], m["received_at"])
            conn.execute(
                "INSERT INTO emails (gmail_id, thread_id, subject, sender, sender_email, snippet, body_text,"
                " received_at, category, company, role, application_id, is_unread, message_id, reply_to)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (gmail_id) DO NOTHING",
                (m["gmail_id"], m["thread_id"], m["subject"], m["sender"], _addr(m["sender"]), m["snippet"],
                 m["body_text"], m["received_at"], cat, company, role, app_id, m.get("is_unread", 0),
                 m.get("message_id", ""), m.get("reply_to", "")),
            )
            stored += 1
        if remaining == 0 and hasattr(gmail, "list_unread_ids"):
            refresh_unread(conn, gmail, days)
        conn.commit()
        return {"checked": len(todo), "stored": stored, "remaining": remaining}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def refresh_unread(conn, gmail, days):
    """Copy Gmail's current unread state onto stored emails (so reading mail in Gmail is reflected here)."""
    unread = set(gmail.list_unread_ids(days))
    current = {r["gmail_id"]: r["is_unread"] for r in conn.all("SELECT gmail_id, is_unread FROM emails")}
    for gid, flag in current.items():
        want = 1 if gid in unread else 0
        if want != flag:
            conn.execute("UPDATE emails SET is_unread=? WHERE gmail_id=?", (want, gid))


def _addr(sender):
    m = re.search(r"<([^>]+)>", sender or "")
    return (m.group(1) if m else (sender or "")).strip().lower()


CLASSIFIER_VERSION = "3"


def reclassify_all(db):
    """Re-run the rules on stored emails and rebuild automatic applications.

    AI-analysed emails keep their AI category. Applications whose status the user edited (status_locked)
    and manual ones are kept.
    """
    conn = db.connect()
    try:
        rows = conn.all("SELECT id, subject, sender, snippet, body_text, received_at, category, company, role,"
                        " ai_status FROM emails ORDER BY received_at")
        conn.execute("UPDATE emails SET application_id=NULL")
        conn.execute("DELETE FROM applications WHERE source='auto' AND status_locked=0")
        for r in rows:
            if r["ai_status"] == "done" or r["category"] == "pending":
                cat, company, role = r["category"], r["company"], r["role"]
            else:
                cat = classify(r["subject"], r["snippet"], r["body_text"], r["sender"])
                if not cat:
                    conn.execute("DELETE FROM emails WHERE id=?", (r["id"],))
                    continue
                company = extract_company(r["sender"], r["subject"])
                role = extract_role(r["subject"], r["body_text"])
            app_id = None
            if cat in STATUS_BY_CATEGORY and company:
                app_id = upsert_application(conn, company, role, STATUS_BY_CATEGORY[cat], r["received_at"])
            conn.execute("UPDATE emails SET category=?, company=?, role=?, application_id=? WHERE id=?",
                         (cat, company, role, app_id, r["id"]))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_classifier_current(db):
    """When the rules change: re-classify stored emails and schedule a one-time rescan of the sync window.

    Messages dropped by older rules are remembered in seen_messages; clearing it lets them be evaluated again.
    """
    conn = db.connect()
    try:
        row = conn.one("SELECT value FROM meta WHERE key='classifier_version'")
        if row and row["value"] == CLASSIFIER_VERSION:
            return
        has_emails = conn.one("SELECT COUNT(*) AS n FROM emails")["n"] > 0
    finally:
        conn.close()
    if has_emails:
        reclassify_all(db)
    conn = db.connect()
    try:
        conn.execute("DELETE FROM seen_messages")
        set_meta(conn, "needs_rescan", "1")
        set_meta(conn, "classifier_version", CLASSIFIER_VERSION)
        conn.commit()
    finally:
        conn.close()


def set_meta(conn, key, value):
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value=excluded.value",
                 (key, value))


def get_meta(conn, key, default=""):
    row = conn.one("SELECT value FROM meta WHERE key=?", (key,))
    return row["value"] if row else default
