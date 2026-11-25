"""Pull practical details out of a job email: where to apply, links, deadlines, location and more.

Everything here is plain pattern matching (no AI), so it works offline and costs nothing.
"""
import re
from datetime import datetime, timezone

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
JUNK_LOCAL = re.compile(r"(?i)^(no-?reply|do-?not-?reply|donotreply|mailer-daemon|bounce|notifications?|alerts?|unsubscribe)")
APPLY_HINT = re.compile(
    r"(?i)(send|share|forward|email|mail|submit|drop|attach)[^.\n]{0,60}?(resume|cv|profile|application|updated)")
CONTACT_HINT = re.compile(r"(?i)(contact|reach|write to|apply (at|to|via|through)|interested)[^.\n]{0,40}")
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
DATE_PATTERNS = [
    re.compile(rf"(?i)\b(\d{{1,2}})(?:st|nd|rd|th)?[\s\-/]+({MONTHS})[a-z]*\.?,?[\s\-/]+(\d{{2,4}})?"),
    re.compile(rf"(?i)\b({MONTHS})[a-z]*\.?\s+(\d{{1,2}})(?!\d)(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?"),
]
DEADLINE_HINT = re.compile(r"(?i)(deadline|last date|apply (by|before)|\bby\b|expires?|due (on|by)|\bbefore\b|\buntil\b)")
SCHEDULE_HINT = re.compile(r"(?i)(interview|call|meeting|slot|schedule|assessment|test|round|walk-?in)")
EXPERIENCE_RE = re.compile(r"(?i)(\d{1,2})\s*(?:\+|-|to|–)?\s*(\d{1,2})?\s*\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:relevant\s+)?(?:experience|exp)")
LOCATION_RE = re.compile(r"(?i)\b(?:location|based (?:in|at)|work location|job location|office)\s*[:\-–]\s*([A-Za-z ,/()\-]{3,60})")
CTC_RE = re.compile(r"(?i)(?:ctc|salary|compensation|package|budget)\s*[:\-–]?\s*([^\n.]{3,60})")
NOTICE_RE = re.compile(r"(?i)(immediate joiners?|notice period[^\n.]{0,40}|\b\d{1,3}\s*(?:days|weeks)\s*notice)")
MODE_RE = re.compile(r"(?i)\b(remote|hybrid|work from home|wfh|on-?site|work from office|wfo)\b")


def _clean_url(u):
    return u.rstrip(".,;:!?)")


def find_links(text, limit=8):
    seen, out = set(), []
    for m in URL_RE.finditer(text or ""):
        u = _clean_url(m.group(0))
        if u not in seen and len(u) < 500:
            seen.add(u)
            out.append(u)
        if len(out) >= limit:
            break
    return out


def find_apply_addresses(text, sender_email="", limit=4):
    """Addresses in the body that look like places to send an application. Best guesses first."""
    text = text or ""
    found = []
    for m in EMAIL_RE.finditer(text):
        addr = m.group(0).lower().rstrip(".")
        local = addr.split("@", 1)[0]
        if JUNK_LOCAL.match(local) or addr in [a for a, _ in found]:
            continue
        window = text[max(0, m.start() - 120):m.end() + 40]
        score = 0
        if APPLY_HINT.search(window):
            score += 3
        if CONTACT_HINT.search(window):
            score += 1
        if re.match(r"(?i)^(hr|jobs?|careers?|recruit|talent|hiring|resumes?|cv|apply|applications?)", local):
            score += 2
        if addr == (sender_email or "").lower():
            score -= 1
        found.append((addr, score))
    found.sort(key=lambda x: -x[1])
    return [a for a, s in found[:limit]]


def _parse_date(m, today):
    g = m.groups()
    try:
        if g[0].isdigit():
            day, mon, year = int(g[0]), g[1][:3].title(), g[2]
        else:
            mon, day, year = g[0][:3].title(), int(g[1]), g[2]
        year = int(year) if year else today.year
        if year < 100:
            year += 2000
        d = datetime.strptime(f"{day} {mon} {year}", "%d %b %Y").date()
        if not g[2] and d < today.date() and (today.date() - d).days > 60:
            d = d.replace(year=d.year + 1)
        return d
    except ValueError:
        return None


def find_dates(text, now=None, limit=5):
    """Dates mentioned with a nearby deadline / schedule word. Returns [{"date","kind","context"}]."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    out, seen = [], set()
    for pat in DATE_PATTERNS:
        for m in pat.finditer(text or ""):
            d = _parse_date(m, now)
            if not d:
                continue
            ctx = (text[max(0, m.start() - 70):m.end() + 30]).replace("\n", " ").strip()
            kind = "deadline" if DEADLINE_HINT.search(ctx) else "schedule" if SCHEDULE_HINT.search(ctx) else "date"
            key = (d, kind)
            if key in seen:
                continue
            seen.add(key)
            out.append({"date": d.isoformat(), "kind": kind, "context": re.sub(r"\s+", " ", ctx)[:140]})
    order = {"deadline": 0, "schedule": 1, "date": 2}
    out.sort(key=lambda x: (order[x["kind"]], x["date"]))
    return out[:limit]


def extract(email, now=None):
    """All the practical details for one stored email row (dict)."""
    text = "\n".join([email.get("subject") or "", email.get("body_text") or email.get("snippet") or ""])
    exp = EXPERIENCE_RE.search(text)
    loc = LOCATION_RE.search(text)
    ctc = CTC_RE.search(text)
    notice = NOTICE_RE.search(text)
    modes = sorted({m.group(1).lower() for m in MODE_RE.finditer(text)})
    return {
        "apply_to": find_apply_addresses(email.get("body_text") or "", email.get("sender_email", "")),
        "links": find_links(email.get("body_text") or ""),
        "dates": find_dates(text, now),
        "experience": exp.group(0).strip() if exp else "",
        "location": re.sub(r"\s+", " ", loc.group(1)).strip(" ,-") if loc else "",
        "work_mode": modes[:3],
        "pay": re.sub(r"\s+", " ", ctc.group(1)).strip() if ctc else "",
        "notice": re.sub(r"\s+", " ", notice.group(1)).strip() if notice else "",
    }
