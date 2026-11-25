"""Working with one job email: details, resume match, ready-made replies, and what needs action."""
import json
import re

import requests
from flask import current_app, jsonify, request

from . import ai, jobinfo, matchlocal, templates
from .api import bp, cfg, conn, login_required
from .api_extra import DETAIL_FIELDS
from .sync import now_iso

# categories where a human reply is normally expected
ACTION_CATEGORIES = ("interview", "assessment", "offer", "recruiter")


def _email(c, email_id):
    return c.one("SELECT * FROM emails WHERE id=?", (email_id,))


def _profile(c):
    row = c.one("SELECT full_name, profile_text, resume_text, resume_filename, LENGTH(resume_data) AS size, "
                + ", ".join(DETAIL_FIELDS) + " FROM profile WHERE id=1") or {}
    return row


def _resume_text(prof):
    return (prof.get("resume_text") or prof.get("profile_text") or "").strip()


def _cached_match(row):
    try:
        return json.loads(row.get("match_json") or "") or None
    except ValueError:
        return None


@bp.get("/api/emails/<int:email_id>/details")
@login_required
def email_details(email_id):
    """Everything the reading pane needs beyond the email itself."""
    c = conn()
    row = _email(c, email_id)
    if not row:
        return jsonify(error="not_found"), 404
    prof = _profile(c)
    thread = []
    if row["thread_id"]:
        thread = c.all("SELECT id, subject, sender, snippet, received_at, category FROM emails"
                       " WHERE thread_id=? AND id != ? ORDER BY received_at ASC", (row["thread_id"], email_id))
    local = matchlocal.compare(row, _resume_text(prof)) if _resume_text(prof) else None
    return jsonify(info=jobinfo.extract(row), thread=thread, local_match=local, ai_match=_cached_match(row),
                   has_resume=bool(prof.get("resume_filename") and prof.get("size")),
                   replied_at=row["replied_at"], done=bool(row["done"]),
                   templates=templates.catalog(row["category"]))


@bp.post("/api/emails/<int:email_id>/match")
@login_required
def ai_match(email_id):
    """AI comparison of this email against the resume. Cached on the email; send {"refresh": true} to redo it."""
    if not ai.enabled(cfg):
        return jsonify(error="ai_disabled"), 400
    c = conn()
    row = _email(c, email_id)
    if not row:
        return jsonify(error="not_found"), 404
    body = request.get_json(silent=True) or {}
    cached = _cached_match(row)
    if cached and not body.get("refresh"):
        return jsonify(cached)
    text = _resume_text(_profile(c))
    if not text:
        return jsonify(error="no_resume"), 400
    try:
        out = ai.match_email(cfg, row, text)
    except ai.AIError as exc:
        current_app.logger.error("AI match failed: kind=%s status=%s", exc.kind, exc.status)
        return jsonify(error="ai_failed", kind=exc.kind, help=ai.help_text(exc.kind, cfg)), 502
    except (requests.RequestException, ValueError):
        return jsonify(error="ai_failed", kind="bad_reply", help=ai.help_text("bad_reply", cfg)), 502
    c.execute("UPDATE emails SET match_json=? WHERE id=?", (json.dumps(out), email_id))
    c.commit()
    return jsonify(out)


@bp.post("/api/emails/<int:email_id>/template")
@login_required
def fill_template(email_id):
    """A ready-made message (no AI) filled from the email and the profile."""
    c = conn()
    row = _email(c, email_id)
    if not row:
        return jsonify(error="not_found"), 404
    d = request.get_json(silent=True) or {}
    prof = _profile(c)
    app_row = c.one("SELECT company, role, status FROM applications WHERE id=?", (row["application_id"],)) \
        if row["application_id"] else None
    local = matchlocal.compare(row, _resume_text(prof)) if _resume_text(prof) else None
    prof_view = {**prof, "email_contact": prof.get("contact_email", "")}
    out = templates.render(str(d.get("template_id", "")), row, app_row, prof_view, (local or {}).get("matched"))
    if not out:
        return jsonify(error="unknown_template"), 400
    from . import mailbuild  # local import keeps module load order simple
    info = jobinfo.extract(row)
    if out["new_thread"]:
        to = (info["apply_to"] or [""])[0] or mailbuild.first_address(row["reply_to"] or row["sender"])
    else:
        to = mailbuild.first_address(row["reply_to"] or row["sender"])
    has_resume = bool(prof.get("resume_filename") and prof.get("size"))
    return jsonify(subject=out["subject"], body=out["body"], to=to, new_thread=out["new_thread"],
                   attach=out["attach"] and has_resume, has_resume=has_resume,
                   no_reply=bool(re.search(r"no-?reply|do-?not-?reply|donotreply", to)),
                   missing=sorted(set(re.findall(r"\[[^\]]{2,60}\]", out["body"]))))


@bp.post("/api/emails/<int:email_id>/done")
@login_required
def mark_done(email_id):
    """Mark an email as dealt with (or put it back on the to-do list)."""
    c = conn()
    if not _email(c, email_id):
        return jsonify(error="not_found"), 404
    done = 1 if (request.get_json(silent=True) or {}).get("done", True) else 0
    c.execute("UPDATE emails SET done=? WHERE id=?", (done, email_id))
    c.commit()
    return jsonify(done=bool(done))


def action_rows(c, limit=100):
    """Job emails that likely need a reply from you, newest first, with the reason."""
    rows = c.all(
        "SELECT e.id, e.subject, e.sender, e.snippet, e.received_at, e.category, e.company, e.role, e.is_unread,"
        " e.ai_summary, e.fit_score, e.replied_at, e.application_id FROM emails e"
        " WHERE e.done=0 AND e.replied_at IS NULL AND e.category IN ('interview','assessment','offer','recruiter')"
        " ORDER BY e.received_at DESC LIMIT ?", (limit,))
    reasons = {"interview": "Interview: confirm or share availability", "assessment": "Assessment: check the deadline",
               "offer": "Offer: respond", "recruiter": "Recruiter: reply with your details"}
    for r in rows:
        r["reason"] = reasons[r["category"]]
    return rows


@bp.get("/api/actions")
@login_required
def actions():
    rows = action_rows(conn())
    return jsonify(items=rows, total=len(rows))
