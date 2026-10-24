"""AI analysis of stored emails: category, company/role, summary and job-fit score."""
from concurrent.futures import ThreadPoolExecutor

from . import ai
from .classify import STATUS_BY_CATEGORY
from .sync import upsert_application


def profile_text(conn) -> str:
    row = conn.one("SELECT profile_text, resume_text FROM profile WHERE id=1") or {}
    return (row.get("profile_text") or row.get("resume_text") or "").strip()


def cleanup_orphan_applications(conn):
    conn.execute(
        "DELETE FROM applications WHERE source='auto' AND status_locked=0"
        " AND id NOT IN (SELECT application_id FROM emails WHERE application_id IS NOT NULL)")


def analyze_pending(db, cfg, limit):
    """Analyse up to `limit` emails that have not been through the AI yet.

    Returns {"analyzed", "removed", "errors", "remaining"}; call again while remaining > 0.
    """
    # worker threads have no Flask app context, so read the settings they need up front
    settings = {k: cfg(k) for k in ("ANTHROPIC_API_KEY", "AI_MODEL", "AI_COMPOSE_MODEL")}
    conn = db.connect()
    try:
        ptxt = profile_text(conn)
        rows = conn.all(
            "SELECT id, subject, sender, snippet, body_text, received_at, company, role FROM emails"
            " WHERE ai_status='' ORDER BY received_at DESC LIMIT ?", (limit,))

        def work(r):
            try:
                return r, ai.analyze_email(settings.__getitem__, r, ptxt), None
            except Exception as exc:  # network, bad JSON, API error: mark and move on
                return r, None, exc

        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(work, rows))

        analyzed = removed = errors = 0
        for r, res, err in sorted(outcomes, key=lambda o: o[0]["received_at"]):
            if err is not None:
                conn.execute("UPDATE emails SET ai_status='error' WHERE id=?", (r["id"],))
                errors += 1
                continue
            if not res["is_job"]:
                conn.execute("DELETE FROM emails WHERE id=?", (r["id"],))
                removed += 1
                continue
            cat = res["category"]
            company = res["company"] or r["company"]
            role = res["role"] or r["role"]
            app_id = None
            if cat in STATUS_BY_CATEGORY and company:
                app_id = upsert_application(conn, company, role, STATUS_BY_CATEGORY[cat], r["received_at"])
            conn.execute(
                "UPDATE emails SET category=?, company=?, role=?, application_id=?, ai_summary=?, fit_score=?,"
                " fit_reason=?, ai_status='done' WHERE id=?",
                (cat, company, role, app_id, res["summary"], res["fit_score"], res["fit_reason"], r["id"]))
            analyzed += 1
        cleanup_orphan_applications(conn)
        conn.commit()
        remaining = conn.one("SELECT COUNT(*) AS n FROM emails WHERE ai_status=''")["n"]
        return {"analyzed": analyzed, "removed": removed, "errors": errors, "remaining": remaining}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
