"""Rule-based classification of job-related emails.

Categories: offer, rejected, interview, assessment, applied, opening.
Anything else returns None and is not stored.
"""
import re

STATUS_BY_CATEGORY = {
    "applied": "applied",
    "assessment": "assessment",
    "interview": "interview",
    "offer": "offer",
    "rejected": "rejected",
}

# Order matters: the first matching category wins.
RULES = [
    ("offer", [
        r"offer letter", r"pleased to offer", r"job offer", r"excited to offer",
        r"extend (?:you )?an offer", r"offer of employment", r"formal offer",
    ]),
    ("rejected", [
        r"unfortunately", r"regret to inform", r"not (?:be )?moving forward",
        r"decided to (?:move|proceed) forward with (?:other|another)",
        r"not (?:been )?selected", r"position has been filled", r"other candidates",
        r"will not be proceeding", r"unable to offer you",
    ]),
    ("interview", [
        r"interview (?:invitation|invite|schedule|scheduled|scheduling|confirmation|confirmed|slot|round|"
        r"request|availability|details|reminder|link|call)",
        r"(?:invite|inviting) you (?:to|for) (?:an? |the )?(?:\w+ )?interview",
        r"(?:schedule|scheduling|reschedule|book) (?:an |your |the |a )?(?:\w+ )?interview",
        r"your (?:upcoming |scheduled )?interview", r"(?:technical|hr|video|onsite|virtual) interview",
        r"phone screen", r"screening call", r"schedule a (?:call|chat|time)",
        r"meet with (?:our|the) team", r"invite you to (?:a |an )?(?:call|chat|meeting|discuss)",
        r"availability for a (?:call|chat)", r"next round",
    ]),
    ("assessment", [
        r"assessment", r"coding challenge", r"take-?home", r"hackerrank", r"codility",
        r"online test", r"technical test", r"case study",
    ]),
    ("applied", [
        r"thank(?:s| you) for applying", r"application (?:has been )?(?:received|submitted)",
        r"we(?:'ve| have)? received your application", r"your application (?:to|for|at|was)",
        r"successfully applied", r"thanks for your interest in", r"thank you for your interest in",
        r"you applied to", r"you(?:'ve| have) applied",
    ]),
    ("opening", [
        r"job alert", r"new jobs?\b", r"is hiring", r"we(?:'re| are) hiring", r"open positions?",
        r"job openings?", r"recommended jobs", r"jobs? for you", r"career opportunit",
        r"opportunity at", r"recruiter", r"hiring for", r"vacanc(?:y|ies)",
    ]),
]
_COMPILED = [(cat, [re.compile(p, re.I) for p in pats]) for cat, pats in RULES]

# Learning-platform / newsletter subjects that mention interviews or assessments without being one.
MARKETING = re.compile(
    r"interview (?:prep|preparation|questions|tips|course|kit|guide|series|mastery)|crack(?:ing)? (?:the )?"
    r"(?:coding )?interview|\bmaster(?:ing)?\b|webinar|newsletter|% off|discount|\bcourse\b|bootcamp|"
    r"\benroll|free (?:skill )?assessment|learn |tutorial|roadmap|cheat ?sheet|\bblog\b",
    re.I,
)
MARKETING_SENSITIVE = {"interview", "assessment"}

NOISE_NAME_WORDS = re.compile(
    r"\b(careers?|recruit(?:ing|ment|ers?)|talent|acquisition|hr|human resources|jobs?|team|"
    r"no-?reply|notifications?|hiring|people|staffing|mailer|updates?|alerts?)\b|\bvia\b.*",
    re.I,
)
GENERIC_DOMAINS = {
    "gmail", "yahoo", "outlook", "hotmail", "icloud", "proton", "protonmail",
    "greenhouse-mail", "greenhouse", "lever", "myworkday", "workday", "workable", "ashbyhq",
    "smartrecruiters", "icims", "jobvite", "linkedin", "indeed", "naukri", "glassdoor",
    "wellfound", "instahyre", "monster", "ziprecruiter", "bamboohr", "breezy", "recruitee",
    "successfactors", "taleo", "mail", "email", "notifications", "hire", "hirevue", "hackerrank",
}
GENERIC_NAMES = {"", "linkedin", "indeed", "naukri", "glassdoor", "greenhouse", "lever", "workday", "gmail"}

SUBJECT_COMPANY = re.compile(
    r"(?:\bat|\bto|\bwith|\bfrom|\bjoin(?:ing)?)\s+"
    r"([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,3})"
)
ROLE_PATTERNS = [
    re.compile(r"(?i:application|applying|applied|interview|opening|offer)\s+for\s+(?:the\s+|a\s+|an\s+)?"
               r"([A-Z][\w/&+.\- ]{2,60}?)(?=\s+(?:position|role|job|at|with|\-|–|—|\||,)|\s*[:!.\n]|$)"),
    re.compile(r"\b(?:for|as)\s+(?:the\s+|a\s+|an\s+)([A-Z][\w/&+.\- ]{2,60}?)\s+(?:position|role|job|opening)"),
    re.compile(r"(?:position|role)\s*[:\-–]\s*([A-Z][^\n|]{2,60})"),
]


def classify(subject: str, snippet: str, body: str):
    """Return the category for a message, or None if it does not look job related."""
    subject = subject or ""
    text = f"{subject}\n{snippet or ''}\n{(body or '')[:2000]}"
    marketing = bool(MARKETING.search(subject))
    for cat, patterns in _COMPILED:
        if marketing and cat in MARKETING_SENSITIVE:
            continue
        for p in patterns:
            if p.search(subject) or p.search(text):
                return cat
    return None


def _clean_name(name: str) -> str:
    name = re.sub(r"[\"<>]", "", name or "")
    name = NOISE_NAME_WORDS.sub(" ", name)
    return re.sub(r"\s+", " ", name).strip(" -–|,:")


def _company_from_name(name: str) -> str:
    cleaned = _clean_name(name)
    # "Zach at Educative" / "Priya from Acme" / "Careers at Google" -> the company part
    m = re.match(r"^(?:.*\s)?(?:at|from|@)\s+(.+)$", cleaned, re.I)
    if m:
        cleaned = m.group(1).strip()
    cleaned = re.sub(r"^the\s+", "", cleaned, flags=re.I)
    return cleaned


def parse_sender(raw: str):
    """Split 'Name <addr@host>' into (name, address)."""
    m = re.match(r"\s*\"?([^\"<]*)\"?\s*<([^>]+)>", raw or "")
    if m:
        return m.group(1).strip(), m.group(2).strip().lower()
    return "", (raw or "").strip().lower()


def extract_company(sender_raw: str, subject: str) -> str:
    name, addr = parse_sender(sender_raw)
    cleaned = _company_from_name(name)
    if cleaned and cleaned.lower() not in GENERIC_NAMES and len(cleaned) <= 40:
        return cleaned
    m = SUBJECT_COMPANY.search(subject or "")
    if m:
        cand = m.group(1).strip()
        if cand.lower() not in GENERIC_NAMES:
            return cand
    domain = addr.split("@")[-1] if "@" in addr else ""
    parts = domain.split(".")
    label = parts[-2] if len(parts) >= 2 else ""
    if label and label.lower() not in GENERIC_DOMAINS:
        return label.replace("-", " ").title()
    return ""


def extract_role(subject: str, body: str) -> str:
    for text in (subject or "", (body or "")[:600]):
        for pat in ROLE_PATTERNS:
            m = pat.search(text)
            if m:
                role = m.group(1).strip(" -–|,:.")
                if 2 < len(role) <= 60:
                    return role
    return ""
