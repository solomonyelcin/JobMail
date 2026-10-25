"""Routes for the Banking and Personal workspaces."""
import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone

import requests
from flask import Response, current_app, jsonify, request, session

from . import ai, bank, wsai
from .api import bp, conn, cfg, like_clause, login_required, is_unique_violation
from .bank import ALL_CATEGORIES, build_summary
from .sync import get_meta, now_iso, set_meta
from .workspaces import RELATIONS, apply_people_change, run_ws_sync

PAGE = 30
WS = ("bank", "personal")


def _ai_help(kind):
    return ai.help_text(kind, cfg) if kind else ""


@bp.post("/api/ws/<ws>/sync")
@login_required
def ws_sync(ws):
    if ws not in WS:
        return jsonify(error="not_found"), 404
    c = conn()
    acct = c.one("SELECT * FROM accounts WHERE email=?", (session["email"],))
    if not acct or not acct["refresh_token_enc"]:
        return jsonify(error="reauth"), 401
    body = request.get_json(silent=True) or {}
    days = max(1, min(int(body.get("days", cfg("SYNC_DAYS"))), 730))
    if body.get("rescan"):
        c.execute("DELETE FROM wseen WHERE ws=?", (ws,))
        set_meta(c, f"needs_rescan_{ws}", "1")
        c.commit()
    last_s = get_meta(c, f"last_sync_{ws}")
    if last_s and get_meta(c, f"needs_rescan_{ws}") != "1" and "days" not in body:
        try:
            last = datetime.strptime(last_s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            days = min(days, max(2, (datetime.now(timezone.utc) - last).days + 2))
        except ValueError:
            pass
    try:
        refresh = current_app.extensions["jobmail_cipher"].decrypt(acct["refresh_token_enc"])
        client = current_app.extensions["gmail_factory"](cfg, refresh)
        result = run_ws_sync(current_app.extensions["jobmail_db"], client, ws, days, cfg("SYNC_BATCH"))
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        if status in (400, 401):
            return jsonify(error="reauth"), 401
        current_app.logger.error("Gmail API error %s", status)
        return jsonify(error=f"gmail_error_{status}"), 502
    except requests.RequestException:
        return jsonify(error="gmail_unreachable"), 502
    if result["remaining"] == 0:
        set_meta(c, f"last_sync_{ws}", now_iso())
        set_meta(c, f"needs_rescan_{ws}", "0")
        c.commit()
    return jsonify(result)


@bp.post("/api/ws/<ws>/analyze")
@login_required
def ws_analyze(ws):
    if ws not in WS:
        return jsonify(error="not_found"), 404
    if not ai.enabled(cfg):
        return jsonify(done=0, remaining=0, error_kind="", help="", ai_enabled=False)
    db = current_app.extensions["jobmail_db"]
    fn = wsai.categorise_transactions if ws == "bank" else wsai.summarise_personal
    return jsonify(fn(db, cfg))


@bp.get("/api/ws/stats")
@login_required
def ws_stats():
    c = conn()
    n = lambda sql, p=(): c.one(sql, p)["n"]
    people = n("SELECT COUNT(*) AS n FROM people")
    return jsonify(
        bank={"mails": n("SELECT COUNT(*) AS n FROM wmails WHERE ws='bank'"),
              "upcoming": n("SELECT COUNT(*) AS n FROM transactions WHERE kind IN ('due','emi_due') AND due_date >= ?",
                            (datetime.now(timezone.utc).date().isoformat(),)),
              "last_sync": get_meta(c, "last_sync_bank") or None,
              "pending_ai": n("SELECT COUNT(*) AS n FROM transactions WHERE kind='debit' AND cat_src='rule' AND spend_cat IN ('Other','')")},
        personal={"mails": n("SELECT COUNT(*) AS n FROM wmails WHERE ws='personal'"),
                  "unread": n("SELECT COUNT(*) AS n FROM wmails WHERE ws='personal' AND is_unread=1"),
                  "needs_reply": n("SELECT COUNT(*) AS n FROM wmails WHERE ws='personal' AND needs_reply=1"),
                  "family": n("SELECT COUNT(*) AS n FROM wmails WHERE ws='personal' AND category='family'"),
                  "friend": n("SELECT COUNT(*) AS n FROM wmails WHERE ws='personal' AND category='friend'"),
                  "starred": n("SELECT COUNT(*) AS n FROM wmails WHERE ws='personal' AND category IN ('starred','important')"),
                  "people": people, "last_sync": get_meta(c, "last_sync_personal") or None,
                  "pending_ai": n("SELECT COUNT(*) AS n FROM wmails WHERE ws='personal' AND ai_status=''")},
        ai_error={"kind": get_meta(c, "ai_last_error"), "help": _ai_help(get_meta(c, "ai_last_error"))}
        if get_meta(c, "ai_last_error") else None)


# ---------- banking ----------
def _txn_rows(c, days=None):
    sql = ("SELECT t.id, t.txn_date, t.kind, t.amount, t.currency, t.merchant, t.spend_cat, t.channel, t.account,"
           " t.balance, t.min_due, t.due_date, t.src FROM transactions t")
    return c.all(sql)


@bp.get("/api/bank/summary")
@login_required
def bank_summary():
    days = max(7, min(int(request.args.get("days", 90) or 90), 365))
    s = build_summary(_txn_rows(conn()), days)
    c = conn()
    cached = get_meta(c, "bank_insights")
    try:
        s["ai_insights"] = json.loads(cached) if cached else None
    except ValueError:
        s["ai_insights"] = None
    s["categories"] = ALL_CATEGORIES
    return jsonify(s)


@bp.post("/api/bank/insights")
@login_required
def bank_insights():
    if not ai.enabled(cfg):
        return jsonify(error="ai_off", help="Turn on AI first (add an AI key on your host)."), 400
    days = max(7, min(int((request.get_json(silent=True) or {}).get("days", 90)), 365))
    summary = build_summary(_txn_rows(conn()), days)
    try:
        items = wsai.bank_insights(cfg, summary)
    except ai.AIError as exc:
        return jsonify(error="ai_failed", kind=exc.kind, help=_ai_help(exc.kind)), 502
    payload = {"items": items, "at": now_iso()}
    set_meta(conn(), "bank_insights", json.dumps(payload))
    conn().commit()
    return jsonify(payload)


@bp.get("/api/bank/transactions")
@login_required
def bank_transactions():
    where, params = ["1=1"], []
    for term in request.args.get("q", "").split():
        cl, p = like_clause(["t.merchant", "t.spend_cat", "w.subject", "t.channel"], term)
        where.append(cl)
        params += p
    kind = request.args.get("kind", "")
    if kind == "spend":
        where.append("t.kind IN ('debit','emi')")
    elif kind in ("debit", "credit", "emi", "due", "emi_due", "loan"):
        where.append("t.kind=?")
        params.append(kind)
    if request.args.get("category"):
        where.append("t.spend_cat=?")
        params.append(request.args["category"])
    w = " AND ".join(where)
    base = f"FROM transactions t JOIN wmails w ON w.id=t.mail_id WHERE {w}"
    total = conn().one(f"SELECT COUNT(*) AS n {base}", params)["n"]
    page = max(1, int(request.args.get("page", 1) or 1))
    rows = conn().all(
        "SELECT t.id, t.mail_id, t.txn_date, t.kind, t.amount, t.currency, t.merchant, t.spend_cat, t.cat_src,"
        " t.channel, t.account, t.balance, t.due_date, w.subject, w.thread_id "
        f"{base} ORDER BY t.txn_date DESC LIMIT ? OFFSET ?", params + [PAGE, (page - 1) * PAGE])
    return jsonify(items=rows, total=total, page=page, page_size=PAGE)


@bp.patch("/api/bank/transactions/<int:tid>")
@login_required
def bank_update(tid):
    body = request.get_json(silent=True) or {}
    cat = body.get("category")
    if cat not in ALL_CATEGORIES:
        return jsonify(error="invalid category"), 400
    c = conn()
    row = c.one("SELECT merchant FROM transactions WHERE id=?", (tid,))
    if not row:
        return jsonify(error="not_found"), 404
    c.execute("UPDATE transactions SET spend_cat=?, cat_src='user' WHERE id=?", (cat, tid))
    changed = 1
    if row["merchant"] and body.get("apply_to_merchant", True):  # teach: same shop, same category
        cur = c.execute("UPDATE transactions SET spend_cat=?, cat_src='user' WHERE LOWER(merchant)=LOWER(?) AND cat_src<>'user'",
                        (cat, row["merchant"]))
        changed += max(0, cur.rowcount or 0)
    c.commit()
    return jsonify(ok=True, changed=changed)


def _csv_safe(v):
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


@bp.get("/api/bank/export.csv")
@login_required
def bank_export():
    rows = conn().all("SELECT txn_date, kind, amount, currency, merchant, spend_cat, channel, account, balance, due_date"
                      " FROM transactions ORDER BY txn_date DESC")
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["date", "type", "amount", "currency", "merchant", "category", "channel", "account", "balance", "due_date"])
    for r in rows:
        w.writerow([r["txn_date"][:10], r["kind"], r["amount"], r["currency"], _csv_safe(r["merchant"]),
                    r["spend_cat"], r["channel"], r["account"], "" if r["balance"] is None else r["balance"], r["due_date"]])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=smartmail-transactions.csv"})


# ---------- personal ----------
@bp.get("/api/personal/mails")
@login_required
def personal_mails():
    where, params = ["ws='personal'"], []
    for term in request.args.get("q", "").split():
        cl, p = like_clause(["subject", "sender", "snippet", "ai_summary"], term)
        where.append(cl)
        params += p
    f = request.args.get("filter", "")
    if f == "unread":
        where.append("is_unread=1")
    elif f == "needs_reply":
        where.append("needs_reply=1")
    elif f in ("family", "friend"):
        where.append("category=?")
        params.append(f)
    elif f == "starred":
        where.append("category IN ('starred','important')")
    w = " AND ".join(where)
    total = conn().one(f"SELECT COUNT(*) AS n FROM wmails WHERE {w}", params)["n"]
    page = max(1, int(request.args.get("page", 1) or 1))
    rows = conn().all(
        "SELECT id, thread_id, subject, sender, snippet, received_at, category, is_unread, is_starred, ai_summary,"
        f" needs_reply FROM wmails WHERE {w} ORDER BY received_at DESC LIMIT ? OFFSET ?", params + [PAGE, (page - 1) * PAGE])
    return jsonify(items=rows, total=total, page=page, page_size=PAGE)


@bp.get("/api/ws/mails/<int:mid>")
@login_required
def ws_mail(mid):
    row = conn().one("SELECT id, ws, thread_id, subject, sender, sender_email, snippet, body_text, received_at, category,"
                     " is_unread, ai_summary, needs_reply FROM wmails WHERE id=?", (mid,))
    return (jsonify(row), 200) if row else (jsonify(error="not_found"), 404)


@bp.get("/api/people")
@login_required
def people_list():
    return jsonify(items=conn().all("SELECT id, email, name, relation FROM people ORDER BY LOWER(name), email"),
                   relations=list(RELATIONS))


@bp.post("/api/people")
@login_required
def people_add():
    body = request.get_json(silent=True) or {}
    email = str(body.get("email", "")).strip().lower()
    name = re.sub(r"\s+", " ", str(body.get("name", ""))).strip()[:80]
    rel = body.get("relation") if body.get("relation") in RELATIONS else "friend"
    if not re.fullmatch(r"[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+", email) or len(email) > 200:
        return jsonify(error="Enter a valid email address."), 400
    c = conn()
    try:
        c.execute("INSERT INTO people (email, name, relation) VALUES (?,?,?)", (email, name, rel))
    except Exception as exc:
        c.rollback()
        if is_unique_violation(exc):
            c.execute("UPDATE people SET name=?, relation=? WHERE email=?", (name, rel, email))
        else:
            raise
    apply_people_change(c)
    c.commit()
    return jsonify(ok=True), 201


@bp.delete("/api/people/<int:pid>")
@login_required
def people_delete(pid):
    c = conn()
    c.execute("DELETE FROM people WHERE id=?", (pid,))
    apply_people_change(c)
    c.commit()
    return jsonify(ok=True)
