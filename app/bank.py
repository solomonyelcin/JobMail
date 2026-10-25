"""Banking workspace: read transaction / EMI / bill emails (rules), categorise spending, build analytics."""
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

SPEND_CATEGORIES = [
    "Food & Dining", "Groceries", "Shopping", "Transport", "Fuel", "Travel", "Bills & Utilities", "Subscriptions",
    "Entertainment", "Health", "Education", "Rent & Housing", "Insurance", "Investments", "EMI & Loans",
    "Transfers", "Cash withdrawal", "Fees & Charges", "Other",
]
INCOME_CATEGORIES = ["Salary", "Refund", "Interest", "Transfer in", "Other income"]
ALL_CATEGORIES = SPEND_CATEGORIES + INCOME_CATEGORIES

# (category, keywords found in merchant or message text)
CATEGORY_RULES = [
    ("Food & Dining", ("swiggy", "zomato", "restaurant", "cafe", "coffee", "starbucks", "mcdonald", "domino", "pizza",
                       "kfc", "burger", "dunzo", "eatfit", "bakery", "biryani", "dining", "food")),
    ("Groceries", ("bigbasket", "blinkit", "zepto", "grofers", "dmart", "d-mart", "reliance fresh", "more retail",
                   "supermarket", "grocery", "instamart", "jiomart", "fresh")),
    ("Shopping", ("amazon", "flipkart", "myntra", "ajio", "nykaa", "meesho", "croma", "decathlon", "shoppers stop",
                  "lifestyle", "tata cliq", "reliance digital", "ikea")),
    ("Transport", ("uber", "ola ", "olacabs", "rapido", "metro", "irctc", "redbus", "namma", "fastag", "cab ")),
    ("Fuel", ("petrol", "fuel", "hpcl", "bpcl", "iocl", "indian oil", "shell", "bharat petroleum", "reliance bp")),
    ("Travel", ("makemytrip", "goibibo", "cleartrip", "airline", "indigo", "air india", "vistara", "airbnb", "oyo",
                "booking.com", "hotel", "yatra", "akasa")),
    ("Bills & Utilities", ("electricity", "bescom", "tneb", "water bill", "gas", "broadband", "airtel", "jio", "vodafone",
                           "bsnl", "recharge", "postpaid", "dth", "tata play", "bill payment", "billdesk", "act fibernet",
                           "mobile bill", "municipal")),
    ("Subscriptions", ("netflix", "spotify", "prime video", "hotstar", "youtube", "apple", "google play", "icloud",
                       "subscription", "sonyliv", "zee5", "linkedin", "openai", "chatgpt", "microsoft", "adobe")),
    ("Entertainment", ("bookmyshow", "pvr", "inox", "cinema", "movie", "steam", "playstation", "game")),
    ("Health", ("pharmacy", "apollo", "medplus", "netmeds", "1mg", "pharmeasy", "hospital", "clinic", "diagnostic",
                "lab", "doctor", "practo", "dental")),
    ("Education", ("udemy", "coursera", "byju", "unacademy", "school", "college", "tuition", "course", "exam", "fees")),
    ("Rent & Housing", ("rent", "landlord", "maintenance", "society", "nobroker", "housing")),
    ("Insurance", ("insurance", "lic ", "premium", "policybazaar", "acko", "digit")),
    ("Investments", ("mutual fund", "zerodha", "groww", "upstox", "sip", "nps", "ppf", "demat", "coin by", "smallcase",
                     "kuvera", "stock")),
    ("EMI & Loans", ("emi", "loan", "bajaj finserv", "bajaj finance", "installment", "instalment")),
    ("Cash withdrawal", ("atm", "cash withdrawal", "cash wdl")),
    ("Fees & Charges", ("charges", "gst", "annual fee", "late fee", "penalty", "convenience fee", "sms charges")),
]
INCOME_RULES = [
    ("Salary", ("salary", "payroll", "sal credit")),
    ("Refund", ("refund", "reversal", "cashback", "reversed")),
    ("Interest", ("interest", "int.pd", "int pd", "dividend")),
]

DEBIT_WORDS = r"debited|spent|withdrawn|paid|purchase|deducted|payment of|sent|transferred to|debit alert"
CREDIT_WORDS = r"credited|received|deposited|refund|credit alert|salary|reversed"
AMOUNT_RE = re.compile(
    r"(?:rs\.?|inr|₹|usd|us\$|\$|eur|€|gbp|£)\s*([\d,]+(?:\.\d{1,2})?)|([\d,]+(?:\.\d{1,2})?)\s*(?:rs\.?|inr)\b", re.I)
CURRENCY_MAP = {"rs": "INR", "inr": "INR", "₹": "INR", "usd": "USD", "us$": "USD", "$": "USD", "eur": "EUR", "€": "EUR",
                "gbp": "GBP", "£": "GBP"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _num(s):
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def find_amounts(text):
    """[(amount, currency, position)] for every money amount in the text."""
    out = []
    for m in AMOUNT_RE.finditer(text):
        raw = m.group(1) or m.group(2)
        val = _num(raw)
        if val is None or val <= 0:
            continue
        cur_m = re.match(r"(rs|inr|₹|usd|us\$|\$|eur|€|gbp|£)", m.group(0).lower())
        cur = CURRENCY_MAP.get(cur_m.group(1).rstrip("."), "INR") if cur_m else "INR"
        out.append((val, cur, m.start()))
    return out


def parse_date_text(s, ref_year):
    """Find the first date in s (dd-mm-yyyy, dd Mon yyyy, Mon dd, yyyy). Returns ISO date string or ''."""
    s = s or ""
    m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s-]+([A-Za-z]{3})[a-z]*[\s,.-]+(\d{2,4})?", s)
    if m and m.group(2).lower() in MONTHS:
        y = int(m.group(3)) if m.group(3) else ref_year
        y = y + 2000 if y < 100 else y
        try:
            return date(y, MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
        except ValueError:
            pass
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", s)
    if m and m.group(1).lower() in MONTHS:
        try:
            return date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
        except ValueError:
            pass
    return ""


def _clean_merchant(s):
    s = re.sub(r"\s+", " ", (s or "")).strip(" .,:;-*/")
    s = re.sub(r"(?i)^(vpa|upi|info:?|the)\s+", "", s)
    if "@" in s:  # a UPI handle such as swiggy@icici: keep the name part
        s = re.sub(r"[._\-\d]+", " ", s.split("@")[0]).strip()
    s = re.sub(r"(?i)\s+upi\b.*$", "", s)
    s = re.sub(r"(?i)\b(on|via|using|ref|txn|transaction|from|a/c|account|bank|ltd|limited|pvt)\b.*$", "", s).strip(" .,:;-*/")
    return s[:60]


def extract_merchant(text, direction):
    pats = []
    if direction == "credit":
        pats = [r"(?:from|by)\s+(?:vpa\s+)?([A-Za-z0-9@&.\- ]{2,50})", r"(?:credited by)\s+([A-Za-z0-9@&.\- ]{2,50})"]
    else:
        pats = [r"(?:info[:\-]\s*)(?:upi|neft|imps)?[/-]*[\w]*[/-]*([A-Za-z][A-Za-z0-9&.\- ]{2,40})",
                r"(?:at|to|towards|for)\s+(?:vpa\s+)?([A-Za-z0-9@&.\- ]{2,50})",
                r"(?:merchant|payee)[:\s]+([A-Za-z0-9&.\- ]{2,40})"]
    for p in pats:
        for m in re.finditer(p, text, re.I):
            cand = _clean_merchant(m.group(1))
            if len(cand) >= 3 and not re.fullmatch(r"(?i)(your|my|the|a|an|this|xx+\d*|\d+|account|card|bank|rs|inr|you)\b.*", cand):
                if re.search(r"[A-Za-z]{3}", cand):
                    return cand.title() if cand == cand.lower() else cand
    return ""


def guess_category(merchant, text, direction):
    hay = f"{merchant} {text}".lower()
    if direction == "credit":
        for cat, words in INCOME_RULES:
            if any(w in hay for w in words):
                return cat
        return "Transfer in" if re.search(r"\b(upi|imps|neft|from)\b", hay) else "Other income"
    m = (merchant or "").lower()
    for cat, words in CATEGORY_RULES:  # merchant name first: more specific than the whole message
        if m and any(w in m for w in words):
            return cat
    for cat, words in CATEGORY_RULES:
        if any(w in hay for w in words if len(w) > 4):
            return cat
    if re.search(r"\bupi\b", hay) and re.search(r"@[a-z]{2,}", hay):
        return "Transfers"
    return "Other"


def detect_channel(text):
    t = text.lower()
    for name, pat in (("UPI", r"\bupi\b"), ("Credit card", r"credit card|\bcc\b"), ("Debit card", r"debit card"),
                      ("Card", r"\bcard\b"), ("NEFT/IMPS", r"\b(neft|imps|rtgs)\b"), ("ATM", r"\batm\b"),
                      ("Auto-debit", r"auto[- ]?debit|\bnach\b|mandate|standing instruction"),
                      ("Net banking", r"net ?banking|internet banking")):
        if re.search(pat, t):
            return name
    return ""


BRANDS = {"hdfcbank": "HDFC Bank", "icicibank": "ICICI Bank", "sbi": "SBI", "onlinesbi": "SBI", "axisbank": "Axis Bank",
          "kotak": "Kotak", "yesbank": "Yes Bank", "idfcfirstbank": "IDFC First Bank", "indusind": "IndusInd Bank",
          "bajajfinserv": "Bajaj Finserv", "bajajfinance": "Bajaj Finance", "americanexpress": "American Express",
          "hsbc": "HSBC", "phonepe": "PhonePe", "paytm": "Paytm", "cred": "CRED", "federalbank": "Federal Bank"}


def _src_domain(sender_email):
    d = (sender_email or "").rsplit("@", 1)[-1].lower()
    parts = d.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else d


def parse_bank_email(subject, snippet, body, sender_email, received_at):
    """Turn a bank email into a transaction dict, or None when it is not a money event (OTP, promo, ...)."""
    text = f"{subject}\n{body or snippet}"[:4500]
    low = text.lower()
    year = int(received_at[:4]) if received_at[:4].isdigit() else date.today().year
    amounts = find_amounts(text)
    has_emi, has_loan = bool(re.search(r"\bemi\b|instal?lment", low)), bool(re.search(r"\bloan\b", low))
    due_ctx = bool(re.search(r"(total|minimum) (amount )?due|amount due|payment due|due date|due on|bill (is )?due|"
                             r"statement (is )?(ready|generated)|e-?statement|credit card statement|pay by|pay before", low))
    upcoming = bool(re.search(r"\bupcoming\b|will be (debited|deducted|auto)|scheduled|reminder|is due|due on|due date|"
                              r"please (pay|ensure)|maintain (sufficient )?balance|before the due", low))
    d_pos = [m.start() for m in re.finditer(r"\b(" + DEBIT_WORDS + r")\b", low)]
    c_pos = [m.start() for m in re.finditer(r"\b(" + CREDIT_WORDS + r")\b", low)]
    direction = ""
    if d_pos or c_pos:
        direction = "debit" if (d_pos and (not c_pos or min(d_pos) < min(c_pos))) else "credit"

    promo = re.search(r"pre-?approved|apply now|limited[- ]time|cashback offer|win\b|reward points|upgrade your|"
                      r"refer (and|&) earn|exclusive offer|offer (valid|ends)|webinar|newsletter", low)
    otp_only = re.search(r"\botp\b|one[- ]time (password|pin)|verification code", low) and not (d_pos or c_pos)
    if otp_only:
        return None

    kind = ""
    if has_emi and upcoming and amounts:
        kind = "emi_due"
    elif has_emi and amounts and (direction != "credit" or "received" in low or "paid" in low):
        kind = "emi"
    elif due_ctx and amounts and not (direction and not upcoming and "statement" not in low and "due" not in low):
        kind = "due"
    elif direction and amounts:
        kind = direction
    elif has_loan and (has_emi or re.search(r"outstanding|overdue|disburs|sanction|foreclos", low)) and amounts:
        kind = "loan"
    if not kind or (promo and kind in ("credit", "loan") and not re.search(r"credited|debited|a/c|account", low)):
        return None
    if promo and kind == "due":
        return None

    # amount: for dues prefer the figure next to "total due / amount due", for others the first amount
    amount, cur = amounts[0][0], amounts[0][1]
    min_due = None
    if kind in ("due", "emi_due"):
        m = re.search(r"(?:total|amount)\s*(?:amount\s*)?due[^0-9₹]{0,40}(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d{1,2})?)", low)
        if m and _num(m.group(1)):
            amount = _num(m.group(1))
        m2 = re.search(r"minimum\s*(?:amount\s*)?due[^0-9₹]{0,40}(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d{1,2})?)", low)
        if m2:
            min_due = _num(m2.group(1))
    due_date = ""
    if kind in ("due", "emi_due"):
        m = re.search(r"(?:due (?:date|on|by)|pay(?:able)? by|on or before|before)[^0-9a-z]{0,6}([^\n]{0,30})", low)
        if m:
            due_date = parse_date_text(m.group(1), year)
        if not due_date:
            due_date = parse_date_text(text, year)
    bal = None
    mb = re.search(r"(?:avl\.?|avail(?:able)?|net)\s*(?:bal(?:ance)?|limit)\.?\s*(?:is)?\s*:?\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d{1,2})?)", low)
    if mb:
        bal = _num(mb.group(1))
    acc = ""
    ma = re.search(r"(?:a/c|acct?|account|card)\s*(?:no\.?|number)?\s*(?:ending|ending with|xx+|\*+|x+)?\s*[:\-]?\s*[x*]*(\d{3,4})\b", low)
    if ma:
        acc = ma.group(1)

    eff_dir = direction if kind in ("debit", "credit") else ("debit" if kind in ("emi",) else "")
    merchant = extract_merchant(text, eff_dir or "debit")
    if kind in ("due", "emi_due", "emi", "loan"):  # the lender / card issuer is the sender's brand
        first = _src_domain(sender_email).split(".")[0]
        merchant = BRANDS.get(first, first.title())
    spend_cat = ""
    if kind == "debit":
        spend_cat = guess_category(merchant, text, "debit")
    elif kind == "credit":
        spend_cat = guess_category(merchant, text, "credit")
    elif kind in ("emi", "emi_due", "loan"):
        spend_cat = "EMI & Loans"
    elif kind == "due":
        spend_cat = "Bills & Utilities"
    return {
        "kind": kind, "amount": amount, "currency": cur, "merchant": merchant, "spend_cat": spend_cat,
        "channel": detect_channel(text), "account": acc, "balance": bal, "min_due": min_due, "due_date": due_date,
        "src": _src_domain(sender_email), "category": {"emi_due": "emi", "due": "bill"}.get(kind, kind),
    }


# ---------- analytics ----------
def _month_key(iso):
    return iso[:7]


def dedupe(rows):
    """The same payment often triggers two emails (bank + UPI app). Within one (day, amount, kind) group keep
    as many as the busiest single sender produced, so genuine repeats are kept but cross-sender copies are not."""
    groups = defaultdict(list)
    for r in rows:
        groups[(r["txn_date"][:10], round(r["amount"], 2), r["kind"])].append(r)
    keep = []
    for g in groups.values():
        by_src = defaultdict(list)
        for r in g:
            by_src[r["src"]].append(r)
        best = max(by_src.values(), key=len)
        keep += best
    return sorted(keep, key=lambda r: r["txn_date"], reverse=True)


def build_summary(rows, days, today=None):
    """Aggregate transaction rows (dicts) into the analytics payload the Banking dashboard shows."""
    today = today or datetime.now(timezone.utc).date()
    cutoff = (today - timedelta(days=days)).isoformat()
    all_rows = dedupe([r for r in rows])
    money = [r for r in all_rows if r["kind"] in ("debit", "credit", "emi") and r["txn_date"][:10] >= cutoff]
    cur_counts = defaultdict(int)
    for r in money:
        cur_counts[r["currency"]] += 1
    currency = max(cur_counts, key=cur_counts.get) if cur_counts else "INR"
    money = [r for r in money if r["currency"] == currency]
    debits = [r for r in money if r["kind"] in ("debit", "emi")]
    credits = [r for r in money if r["kind"] == "credit"]
    d_total, c_total = sum(r["amount"] for r in debits), sum(r["amount"] for r in credits)

    monthly = defaultdict(lambda: {"debit": 0.0, "credit": 0.0})
    for r in money:
        monthly[_month_key(r["txn_date"])]["debit" if r["kind"] in ("debit", "emi") else "credit"] += r["amount"]
    months = []
    y, m = today.year, today.month
    for _ in range(max(1, min(12, days // 30 + 1))):
        months.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    monthly_list = [{"month": k, "debit": round(monthly[k]["debit"], 2), "credit": round(monthly[k]["credit"], 2)} for k in months]

    cats = defaultdict(lambda: [0.0, 0])
    merchants = defaultdict(lambda: [0.0, 0])
    channels = defaultdict(lambda: [0.0, 0])
    for r in debits:
        c = r["spend_cat"] or "Other"
        cats[c][0] += r["amount"]
        cats[c][1] += 1
        if r["merchant"]:
            key = r["merchant"].title()
            merchants[key][0] += r["amount"]
            merchants[key][1] += 1
        if r["channel"]:
            channels[r["channel"]][0] += r["amount"]
            channels[r["channel"]][1] += 1
    pack = lambda d, n=10: [{"name": k, "amount": round(v[0], 2), "count": v[1]}
                            for k, v in sorted(d.items(), key=lambda kv: -kv[1][0])[:n]]
    income = defaultdict(lambda: [0.0, 0])
    for r in credits:
        income[r["spend_cat"] or "Other income"][0] += r["amount"]
        income[r["spend_cat"] or "Other income"][1] += 1

    # upcoming dues and EMIs (due date today or later), newest information per (merchant, amount)
    today_s = today.isoformat()
    dues = {}
    for r in all_rows:
        if r["kind"] in ("due", "emi_due") and r["due_date"]:
            key = (r["merchant"].lower() or r["src"], r["kind"], r["due_date"][:7])
            if key not in dues or r["txn_date"] > dues[key]["txn_date"]:
                dues[key] = r
    due_list = []
    for r in dues.values():
        dd = r["due_date"]
        days_left = (date.fromisoformat(dd) - today).days
        if days_left < -10:  # long past: not "pending"
            continue
        paid = any(p["kind"] in ("debit", "emi") and p["currency"] == r["currency"] and abs(p["amount"] - r["amount"]) < 1
                   and dd >= p["txn_date"][:10] >= (date.fromisoformat(dd) - timedelta(days=12)).isoformat()
                   for p in all_rows) or any(
            p["kind"] in ("debit", "emi") and p["txn_date"][:10] >= (date.fromisoformat(dd) - timedelta(days=12)).isoformat()
            and p["txn_date"][:10] <= (date.fromisoformat(dd) + timedelta(days=5)).isoformat() and p["src"] == r["src"]
            and p["txn_date"] > r["txn_date"] for p in all_rows)
        if paid:
            continue
        due_list.append({"id": r["id"], "title": r["merchant"] or r["src"], "kind": "EMI" if r["kind"] == "emi_due" else "Bill",
                         "amount": r["amount"], "min_due": r["min_due"], "currency": r["currency"], "due_date": dd,
                         "days_left": days_left, "overdue": days_left < 0})
    due_list.sort(key=lambda x: x["due_date"])

    # loans: group EMI payments / notices by lender
    loans = {}
    for r in all_rows:
        if r["kind"] in ("emi", "emi_due", "loan"):
            key = (r["merchant"] or r["src"]).title()
            l = loans.setdefault(key, {"lender": key, "emi_amount": 0.0, "payments": 0, "last_date": "", "currency": r["currency"]})
            if r["kind"] == "emi":
                l["payments"] += 1
            if r["txn_date"] > l["last_date"]:
                l["last_date"], l["emi_amount"] = r["txn_date"], r["amount"]
    loan_list = sorted(loans.values(), key=lambda x: -x["emi_amount"])
    emi_monthly = sum(l["emi_amount"] for l in loan_list if l["currency"] == currency)

    accounts = {}
    for r in all_rows:
        if r["balance"] is not None and r["account"]:
            if r["account"] not in accounts or r["txn_date"] > accounts[r["account"]]["as_of"]:
                accounts[r["account"]] = {"account": r["account"], "balance": r["balance"], "as_of": r["txn_date"][:10],
                                          "currency": r["currency"]}
    span = max(1, min(days, (today - date.fromisoformat(min((r["txn_date"][:10] for r in money), default=today_s))).days + 1))

    insights = []
    if cats:
        top = max(cats.items(), key=lambda kv: kv[1][0])
        insights.append(f"Your biggest spending category is {top[0]} ({top[1][0] / d_total * 100:.0f}% of spend).")
    if len(monthly_list) >= 2 and monthly_list[-2]["debit"] > 0 and today.day >= 20:
        ch = (monthly_list[-1]["debit"] - monthly_list[-2]["debit"]) / monthly_list[-2]["debit"] * 100
        insights.append(f"This month's spending is {abs(ch):.0f}% {'higher' if ch > 0 else 'lower'} than last month.")
    if emi_monthly and c_total:
        months_n = max(1, days / 30)
        share = emi_monthly / (c_total / months_n) * 100
        insights.append(f"Your EMIs are roughly {share:.0f}% of your average monthly income.")
    if any(d["overdue"] for d in due_list):
        insights.append("Some payments look overdue. Check the Upcoming payments list.")
    return {
        "currency": currency, "days": days,
        "totals": {"debit": round(d_total, 2), "credit": round(c_total, 2), "net": round(c_total - d_total, 2),
                   "count": len(money), "avg_daily_spend": round(d_total / span, 2), "emi_monthly": round(emi_monthly, 2)},
        "monthly": monthly_list, "by_category": pack(cats, 12), "income": pack(income, 6),
        "top_merchants": pack(merchants, 8), "by_channel": pack(channels, 6),
        "upcoming": due_list[:12], "loans": loan_list[:10], "accounts": list(accounts.values())[:8],
        "recent": [{"id": r["id"], "date": r["txn_date"][:10], "kind": r["kind"], "amount": r["amount"],
                    "merchant": r["merchant"], "category": r["spend_cat"], "currency": r["currency"]} for r in all_rows[:8]
                   if r["kind"] in ("debit", "credit", "emi")],
        "insights": insights,
    }
