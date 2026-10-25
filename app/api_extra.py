"""Profile + resume, job matches, AI analysis and reply drafting routes."""
import re

import requests
from flask import Response, current_app, jsonify, request, session
from werkzeug.utils import secure_filename

from . import ai, mailbuild, resume
from .analysis import analyze_pending
from .api import bp, conn, cfg, login_required
from .sync import now_iso, set_meta


def _profile_row(c):
    row = c.one("SELECT full_name, profile_text, resume_filename, resume_mime, resume_updated_at,"
                " LENGTH(resume_data) AS resume_size, LENGTH(resume_text) AS resume_text_len FROM profile WHERE id=1")
    if not row:
        return {"full_name": "", "profile_text": "", "resume": None, "ai_enabled": ai.enabled(cfg)}
    has = bool(row["resume_filename"] and row["resume_size"])
    return {
        "full_name": row["full_name"], "profile_text": row["profile_text"], "ai_enabled": ai.enabled(cfg),
        "resume": {"filename": row["resume_filename"], "size": row["resume_size"],
                   "updated_at": row["resume_updated_at"], "text_extracted": bool(row["resume_text_len"])} if has else None,
    }


# ---------- profile + resume ----------
@bp.get("/api/profile")
@login_required
def get_profile():
    return jsonify(_profile_row(conn()))


@bp.put("/api/profile")
@login_required
def put_profile():
    d = request.get_json(silent=True) or {}
    name = str(d.get("full_name", "")).strip()[:100]
    text = str(d.get("profile_text", "")).strip()[:8000]
    c = conn()
    c.execute("INSERT INTO profile (id, full_name, profile_text) VALUES (1, ?, ?)"
              " ON CONFLICT (id) DO UPDATE SET full_name=excluded.full_name, profile_text=excluded.profile_text",
              (name, text))
    c.commit()
    return jsonify(_profile_row(c))


@bp.post("/api/resume")
@login_required
def upload_resume():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="no_file"), 400
    data = f.read(resume.MAX_BYTES + 1)
    filename = secure_filename(f.filename) or "resume"
    try:
        ext, mime = resume.validate(filename, data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    text = resume.extract_text(ext, data)
    c = conn()
    c.execute(
        "INSERT INTO profile (id, resume_filename, resume_mime, resume_data, resume_text, resume_updated_at)"
        " VALUES (1, ?, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET resume_filename=excluded.resume_filename,"
        " resume_mime=excluded.resume_mime, resume_data=excluded.resume_data, resume_text=excluded.resume_text,"
        " resume_updated_at=excluded.resume_updated_at",
        (filename, mime, data, text, now_iso()))
    if text:  # first upload: use the resume text as the profile unless the user already wrote one
        c.execute("UPDATE profile SET profile_text=? WHERE id=1 AND profile_text=''", (text[:8000],))
    c.commit()
    return jsonify(_profile_row(c))


@bp.get("/api/resume")
@login_required
def download_resume():
    row = conn().one("SELECT resume_filename, resume_mime, resume_data FROM profile WHERE id=1")
    if not row or not row["resume_data"]:
        return jsonify(error="not_found"), 404
    return Response(bytes(row["resume_data"]), mimetype=row["resume_mime"] or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{row["resume_filename"]}"',
                             "X-Content-Type-Options": "nosniff"})


@bp.delete("/api/resume")
@login_required
def delete_resume():
    c = conn()
    c.execute("UPDATE profile SET resume_filename='', resume_mime='', resume_data=NULL, resume_text='',"
              " resume_updated_at=NULL WHERE id=1")
    c.commit()
    return jsonify(_profile_row(c))


# ---------- matches ----------
@bp.get("/api/matches")
@login_required
def matches():
    try:
        minimum = max(0, min(100, int(request.args.get("min", 0))))
    except ValueError:
        minimum = 0
    rows = conn().all(
        "SELECT id, subject, sender, snippet, received_at, category, company, role, is_unread, ai_summary,"
        " fit_score, fit_reason FROM emails WHERE category IN ('opening','recruiter') AND fit_score IS NOT NULL"
        " AND fit_score >= ? ORDER BY fit_score DESC, received_at DESC LIMIT 100", (minimum,))
    return jsonify(items=rows)


# ---------- AI analysis ----------
@bp.post("/api/ai/analyze")
@login_required
def ai_analyze():
    if not ai.enabled(cfg):
        return jsonify(error="ai_disabled"), 400
    body = request.get_json(silent=True) or {}
    if body.get("retry"):
        c = conn()
        c.execute("UPDATE emails SET ai_status='' WHERE ai_status='error'")
        c.commit()
    if body.get("reanalyze"):  # e.g. after uploading a new resume: re-score everything
        c = conn()
        c.execute("UPDATE emails SET ai_status='' WHERE ai_status='done'")
        c.commit()
    return jsonify(analyze_pending(current_app.extensions["jobmail_db"], cfg, cfg("AI_BATCH")))


@bp.post("/api/ai/test")
@login_required
def ai_test():
    """Tiny request to each configured model so the user sees exactly what is wrong (key, credit, model name)."""
    if not ai.enabled(cfg):
        return jsonify(error="ai_disabled"), 400
    results = ai.check_models(cfg)
    ok = all(r["ok"] for r in results)
    c = conn()
    if ok:
        set_meta(c, "ai_last_error", "")
        c.commit()
    return jsonify(ok=ok, results=results)


# ---------- reply drafting ----------
def _email_and_app(c, email_id):
    row = c.one("SELECT * FROM emails WHERE id=?", (email_id,))
    app_row = c.one("SELECT company, role, status FROM applications WHERE id=?", (row["application_id"],)) \
        if row and row["application_id"] else None
    return row, app_row


@bp.post("/api/emails/<int:email_id>/compose")
@login_required
def compose(email_id):
    if not ai.enabled(cfg):
        return jsonify(error="ai_disabled"), 400
    c = conn()
    row, app_row = _email_and_app(c, email_id)
    if not row:
        return jsonify(error="not_found"), 404
    prof = c.one("SELECT full_name, profile_text, resume_text, resume_filename, LENGTH(resume_data) AS size"
                 " FROM profile WHERE id=1") or {}
    has_resume = bool(prof.get("resume_filename") and prof.get("size"))
    d = request.get_json(silent=True) or {}
    try:
        out = ai.compose_reply(cfg, row, app_row, prof.get("full_name", ""),
                               prof.get("profile_text") or prof.get("resume_text") or "", has_resume,
                               str(d.get("instructions", ""))[:300])
    except ai.AIError as exc:
        current_app.logger.error("AI compose failed: kind=%s status=%s detail=%s", exc.kind, exc.status, exc.detail)
        return jsonify(error="ai_failed", kind=exc.kind, help=ai.help_text(exc.kind, cfg)), 502
    except (requests.RequestException, ValueError):
        return jsonify(error="ai_failed", kind="bad_reply", help=ai.help_text("bad_reply", cfg)), 502
    to = mailbuild.first_address(row["reply_to"] or row["sender"])
    subject = out["subject"] or row["subject"]
    if not re.match(r"(?i)^re:", subject):
        subject = "Re: " + subject
    return jsonify(subject=subject, body=out["body"], to=to, has_resume=has_resume,
                   no_reply=bool(re.search(r"no-?reply|do-?not-?reply|donotreply", to)))


@bp.post("/api/emails/<int:email_id>/draft")
@login_required
def create_draft(email_id):
    c = conn()
    row, _ = _email_and_app(c, email_id)
    if not row:
        return jsonify(error="not_found"), 404
    acct = c.one("SELECT * FROM accounts WHERE email=?", (session["email"],))
    if not acct or "gmail.compose" not in (acct["scope"] or ""):
        return jsonify(error="reauth_scope"), 403
    d = request.get_json(silent=True) or {}
    to = mailbuild.first_address(str(d.get("to") or "")) or mailbuild.first_address(row["reply_to"] or row["sender"])
    body = str(d.get("body", "")).strip()[:6000]
    if not to or not body:
        return jsonify(error="invalid_input"), 400
    attachment = None
    if d.get("attach_resume", True):
        prof = c.one("SELECT resume_filename, resume_mime, resume_data FROM profile WHERE id=1")
        if prof and prof["resume_data"]:
            attachment = (prof["resume_filename"], prof["resume_mime"], bytes(prof["resume_data"]))
    try:
        raw = mailbuild.build_raw(to, str(d.get("subject", "")) or "Re: " + row["subject"], body,
                                  row["message_id"], attachment)
        refresh = current_app.extensions["jobmail_cipher"].decrypt(acct["refresh_token_enc"])
        client = current_app.extensions["gmail_factory"](cfg, refresh)
        result = client.create_draft(raw, row["thread_id"] or None)
    except ValueError:
        return jsonify(error="invalid_input"), 400
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        return (jsonify(error="reauth_scope"), 403) if status in (401, 403) else (jsonify(error="gmail_error"), 502)
    except requests.RequestException:
        return jsonify(error="gmail_unreachable"), 502
    msg_id = (result.get("message") or {}).get("id", "")
    url = f"https://mail.google.com/mail/u/0/#drafts?compose={msg_id}" if msg_id else "https://mail.google.com/mail/u/0/#drafts"
    return jsonify(draft_id=result.get("id", ""), url=url, attached=bool(attachment))
