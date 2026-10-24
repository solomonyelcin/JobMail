"""HTTP routes: Google sign-in, sync, search, application tracking."""
import secrets
from functools import wraps

import requests
from flask import Blueprint, current_app, g, jsonify, redirect, request, session

from . import gmail
from .sync import now_iso, norm, run_sync

bp = Blueprint("api", __name__)

STATUSES = ["saved", "applied", "assessment", "interview", "offer", "rejected", "withdrawn"]
CATEGORIES = ["applied", "assessment", "interview", "offer", "rejected", "opening"]
PAGE = 25


# ---------- helpers ----------
def conn():
    if "conn" not in g:
        g.conn = current_app.extensions["jobmail_db"].connect()
    return g.conn


@bp.teardown_app_request
def _close(_exc):
    c = g.pop("conn", None)
    if c is not None:
        c.close()


def cfg(key):
    return current_app.config[key]


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        email = session.get("email")
        if not email or email != cfg("ALLOWED_EMAIL"):
            return jsonify(error="unauthenticated"), 401
        if request.method in ("POST", "PATCH", "PUT", "DELETE") and request.headers.get("X-Requested-With") != "JobMail":
            return jsonify(error="missing X-Requested-With header"), 400
        return fn(*a, **kw)

    return wrapper


def redirect_uri():
    return cfg("BASE_URL") + "/auth/callback"


def like_clause(columns, term):
    esc = term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    clause = "(" + " OR ".join(f"LOWER({c}) LIKE ? ESCAPE '\\'" for c in columns) + ")"
    return clause, [f"%{esc}%"] * len(columns)


def is_unique_violation(exc):
    return "unique" in str(exc).lower() or "duplicate" in str(exc).lower()


# ---------- auth ----------
@bp.get("/auth/login")
def login():
    if not cfg("GOOGLE_CLIENT_ID") or not cfg("ALLOWED_EMAIL"):
        return "Server is missing GOOGLE_CLIENT_ID or ALLOWED_EMAIL configuration.", 500
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    return redirect(gmail.build_auth_url(cfg("GOOGLE_CLIENT_ID"), redirect_uri(), state))


@bp.get("/auth/callback")
def callback():
    if request.args.get("error"):
        return redirect("/?auth_error=" + request.args["error"][:50])
    expected = session.pop("oauth_state", None)
    if not expected or not secrets.compare_digest(expected, request.args.get("state", "")):
        return redirect("/?auth_error=state_mismatch")
    try:
        tokens = gmail.exchange_code(cfg("GOOGLE_CLIENT_ID"), cfg("GOOGLE_CLIENT_SECRET"), redirect_uri(),
                                     request.args.get("code", ""))
        info = gmail.get_userinfo(tokens["access_token"])
    except requests.RequestException:
        return redirect("/?auth_error=google_request_failed")
    email = (info.get("email") or "").lower()
    if not info.get("email_verified") or email != cfg("ALLOWED_EMAIL"):
        return redirect("/?auth_error=account_not_allowed")

    c = conn()
    existing = c.one("SELECT * FROM accounts WHERE email=?", (email,))
    refresh = tokens.get("refresh_token")
    if not refresh and not (existing and existing["refresh_token_enc"]):
        return redirect("/?auth_error=no_refresh_token")
    enc = current_app.extensions["jobmail_cipher"].encrypt(refresh) if refresh else existing["refresh_token_enc"]
    if existing:
        c.execute("UPDATE accounts SET refresh_token_enc=? WHERE id=?", (enc, existing["id"]))
    else:
        c.execute("INSERT INTO accounts (email, refresh_token_enc, created_at) VALUES (?,?,?)",
                  (email, enc, now_iso()))
    c.commit()
    session.clear()
    session["email"] = email
    session.permanent = True
    return redirect("/")


@bp.post("/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.get("/api/me")
def me():
    email = session.get("email")
    if not email or email != cfg("ALLOWED_EMAIL"):
        return jsonify(authenticated=False)
    acct = conn().one("SELECT last_sync_at FROM accounts WHERE email=?", (email,))
    return jsonify(authenticated=True, email=email, last_sync_at=acct["last_sync_at"] if acct else None,
                   statuses=STATUSES, categories=CATEGORIES)


# ---------- sync ----------
@bp.post("/api/sync")
@login_required
def sync():
    c = conn()
    acct = c.one("SELECT * FROM accounts WHERE email=?", (session["email"],))
    if not acct or not acct["refresh_token_enc"]:
        return jsonify(error="reauth"), 401
    body = request.get_json(silent=True) or {}
    days = max(1, min(int(body.get("days", cfg("SYNC_DAYS"))), 730))
    try:
        refresh = current_app.extensions["jobmail_cipher"].decrypt(acct["refresh_token_enc"])
        client = current_app.extensions["gmail_factory"](cfg, refresh)
        result = run_sync(current_app.extensions["jobmail_db"], client, days, cfg("SYNC_BATCH"))
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        if status in (400, 401):
            return jsonify(error="reauth"), 401
        current_app.logger.error("Gmail API error %s", status)
        return jsonify(error=f"gmail_error_{status}"), 502
    except requests.RequestException:
        return jsonify(error="gmail_unreachable"), 502
    if result["remaining"] == 0:
        c.execute("UPDATE accounts SET last_sync_at=? WHERE id=?", (now_iso(), acct["id"]))
        c.commit()
    return jsonify(result)


# ---------- emails ----------
@bp.get("/api/emails")
@login_required
def list_emails():
    where, params = ["1=1"], []
    for term in request.args.get("q", "").split():
        cl, p = like_clause(["e.subject", "e.sender", "e.snippet", "e.body_text", "e.company", "e.role"], term)
        where.append(cl)
        params += p
    if request.args.get("category") in CATEGORIES:
        where.append("e.category=?")
        params.append(request.args["category"])
    if request.args.get("company"):
        cl, p = like_clause(["e.company"], request.args["company"])
        where.append(cl)
        params += p
    if request.args.get("status") in STATUSES:
        where.append("a.status=?")
        params.append(request.args["status"])
    if request.args.get("application_id", "").isdigit():
        where.append("e.application_id=?")
        params.append(int(request.args["application_id"]))
    if request.args.get("from"):
        where.append("e.received_at >= ?")
        params.append(request.args["from"][:10] + "T00:00:00Z")
    if request.args.get("to"):
        where.append("e.received_at <= ?")
        params.append(request.args["to"][:10] + "T23:59:59Z")
    w = " AND ".join(where)
    base = f"FROM emails e LEFT JOIN applications a ON a.id=e.application_id WHERE {w}"
    total = conn().one(f"SELECT COUNT(*) AS n {base}", params)["n"]
    page = max(1, int(request.args.get("page", 1) or 1))
    rows = conn().all(
        "SELECT e.id, e.subject, e.sender, e.snippet, e.received_at, e.category, e.company, e.role,"
        f" e.application_id, a.status AS application_status {base}"
        " ORDER BY e.received_at DESC LIMIT ? OFFSET ?",
        params + [PAGE, (page - 1) * PAGE],
    )
    return jsonify(items=rows, total=total, page=page, page_size=PAGE)


@bp.get("/api/emails/<int:email_id>")
@login_required
def get_email(email_id):
    row = conn().one("SELECT * FROM emails WHERE id=?", (email_id,))
    return (jsonify(row), 200) if row else (jsonify(error="not_found"), 404)


# ---------- applications ----------
APP_SELECT = (
    "SELECT a.id, a.company, a.role, a.status, a.notes, a.source, a.first_seen_at, a.last_activity_at,"
    " (SELECT COUNT(*) FROM emails e WHERE e.application_id=a.id) AS email_count FROM applications a"
)


@bp.get("/api/applications")
@login_required
def list_applications():
    where, params = ["1=1"], []
    for term in request.args.get("q", "").split():
        cl, p = like_clause(["a.company", "a.role", "a.notes"], term)
        where.append(cl)
        params += p
    if request.args.get("status") in STATUSES:
        where.append("a.status=?")
        params.append(request.args["status"])
    rows = conn().all(f"{APP_SELECT} WHERE {' AND '.join(where)} ORDER BY a.last_activity_at DESC", params)
    return jsonify(items=rows)


@bp.post("/api/applications")
@login_required
def create_application():
    d = request.get_json(silent=True) or {}
    company, role = (d.get("company") or "").strip(), (d.get("role") or "").strip()
    status = d.get("status", "saved")
    if not company or len(company) > 100 or len(role) > 100 or status not in STATUSES:
        return jsonify(error="invalid_input"), 400
    c, ts = conn(), now_iso()
    try:
        cur = c.execute(
            "INSERT INTO applications (company, company_key, role, role_key, status, notes, source,"
            " status_locked, first_seen_at, last_activity_at) VALUES (?,?,?,?,?,?,?,?,?,?) RETURNING id",
            (company, norm(company), role, norm(role), status, (d.get("notes") or "")[:2000], "manual", 1, ts, ts),
        )
        new_id = cur.fetchone()["id"]
        c.commit()
    except Exception as exc:
        c.rollback()
        if is_unique_violation(exc):
            return jsonify(error="already_exists"), 409
        raise
    return jsonify(c.one(f"{APP_SELECT} WHERE a.id=?", (new_id,))), 201


@bp.patch("/api/applications/<int:app_id>")
@login_required
def update_application(app_id):
    c = conn()
    row = c.one("SELECT * FROM applications WHERE id=?", (app_id,))
    if not row:
        return jsonify(error="not_found"), 404
    d = request.get_json(silent=True) or {}
    sets, params = [], []
    if "status" in d:
        if d["status"] not in STATUSES:
            return jsonify(error="invalid_status"), 400
        sets += ["status=?", "status_locked=1"]
        params.append(d["status"])
    if "notes" in d:
        sets.append("notes=?")
        params.append(str(d["notes"])[:2000])
    company = (d.get("company", row["company"]) or "").strip()
    role = (d.get("role", row["role"]) or "").strip()
    if ("company" in d or "role" in d):
        if not company or len(company) > 100 or len(role) > 100:
            return jsonify(error="invalid_input"), 400
        sets += ["company=?", "company_key=?", "role=?", "role_key=?"]
        params += [company, norm(company), role, norm(role)]
    if not sets:
        return jsonify(error="nothing_to_update"), 400
    try:
        c.execute(f"UPDATE applications SET {', '.join(sets)} WHERE id=?", params + [app_id])
        c.commit()
    except Exception as exc:
        c.rollback()
        if is_unique_violation(exc):
            return jsonify(error="already_exists"), 409
        raise
    return jsonify(c.one(f"{APP_SELECT} WHERE a.id=?", (app_id,)))


@bp.delete("/api/applications/<int:app_id>")
@login_required
def delete_application(app_id):
    c = conn()
    c.execute("UPDATE emails SET application_id=NULL WHERE application_id=?", (app_id,))
    c.execute("DELETE FROM applications WHERE id=?", (app_id,))
    c.commit()
    return jsonify(ok=True)


# ---------- stats ----------
@bp.get("/api/stats")
@login_required
def stats():
    c = conn()
    apps = {r["status"]: r["n"] for r in c.all("SELECT status, COUNT(*) AS n FROM applications GROUP BY status")}
    cats = {r["category"]: r["n"] for r in c.all("SELECT category, COUNT(*) AS n FROM emails GROUP BY category")}
    return jsonify(applications=apps, emails=cats, total_emails=sum(cats.values()),
                   total_applications=sum(apps.values()))
