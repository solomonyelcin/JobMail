"""Banking workspace: read transaction / EMI / bill emails (rules), categorise spending, build analytics."""
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

SPEND_CATEGORIES = [
    "Food & Dining", "Groceries", "Shopping", "Transport", "Fuel", "Travel", "Bills & Utilities", "Subscriptions",
    "Entertainment", "Health", "Education", "Rent & Housing", "Insurance", "Investments", "EMI & Loans",
    "Transfers", "Cash withdrawal", "Fees & Charges", "Credit card payment", "Other",
]
INCOME_CATEGORIES = ["Salary", "Refund", "Interest", "Transfer in", "Other income"]
ALL_CATEGORIES = SPEND_CATEGORIES + INCOME_CATEGORIES

# (category, keywords found in merchant or message text)
CATEGORY_RULES = [
    ("Credit card payment", ("credit card payment", "credit card bill", "cc payment", "card bill", "cred club", "cred.club",
                             "creditcard payment", "card payment", "cc bill")),
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
BANK_PARSER_VERSION = "2"
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
    all_amounts = find_amounts(text)
    # skip figures that are balances or limits, e.g. "Avl Bal Rs 12,000" or "credit limit Rs 1,00,000"
    amounts = [a for a in all_amounts if not re.search(r"(bal(ance)?|limit|available|avl|outstanding|total due|min(imum)? due)\W{0,12}$",
                                                       low[max(0, a[2] - 28):a[2]])] or all_amounts
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
    failed = re.search(r"\b(failed|declined|unsuccessful|unable to process|could not be processed|not processed|"
                       r"insufficient (funds|balance)|transaction (was )?rejected|cancelled|canceled)\b", low)
    if failed and not re.search(r"\b(reversed|refund(ed)?)\b", low):
        return None
    otp_only = re.search(r"\botp\b|one[- ]time (password|pin)|verification code", low) and not (d_pos or c_pos)
    if otp_only:
        return None

    card_payment = bool(re.search(r"(payment|amount) (of .{0,25})?(received|credited)[^.]{0,60}(credit )?card|"
                                  r"thank you for (your )?(credit )?card payment|payment received (on|towards|for) (your )?(credit )?card", low))
    kind = ""
    if card_payment and direction != "debit":
        kind = "card_payment"
    elif has_emi and upcoming and amounts:
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
    elif kind == "card_payment":
        spend_cat = "Credit card payment"
    mref = re.search(r"(?:ref(?:erence)?|rrn|utr|txn|transaction)\s*(?:no\.?|number|id)?\s*[:#\-]?\s*([A-Za-z0-9]{8,22})", text, re.I)
    ref = mref.group(1).upper() if mref and re.search(r"\d", mref.group(1)) else ""
    return {
        "kind": kind, "amount": amount, "currency": cur, "merchant": merchant, "spend_cat": spend_cat,
        "channel": detect_channel(text), "account": acc, "balance": bal, "min_due": min_due, "due_date": due_date,
        "src": _src_domain(sender_email), "ref": ref,
        "category": {"emi_due": "emi", "due": "bill"}.get(kind, kind),
    }




# ---------- analytics ----------
import calendar
import statistics

NON_SPEND = {"Credit card payment"}  # paying a card bill is not new spending (the card purchases already count)


def _month_key(iso):
    return iso[:7]


def dedupe(rows):
    """Remove double counting. The same payment often triggers two emails (bank + UPI app):
    1) rows sharing a bank reference number are one payment;
    2) otherwise, within one (day, amount, kind) group keep as many as the busiest single sender produced, so real
       repeats from one sender are kept but copies from different senders are not."""
    seen_ref, kept, rest = set(), [], []
    for r in sorted(rows, key=lambda r: r["txn_date"]):
        ref = r.get("ref") or ""
        if ref:
            key = (ref, r["kind"])
            if key in seen_ref:
                continue
            seen_ref.add(key)
            kept.append(r)
        else:
            rest.append(r)
    groups = defaultdict(list)
    for r in rest:
        groups[(r["txn_date"][:10], round(r["amount"], 2), r["kind"])].append(r)
    for g in groups.values():
        by_src = defaultdict(list)
        for r in g:
            by_src[r["src"]].append(r)
        kept += max(by_src.values(), key=len)
    return sorted(kept, key=lambda r: r["txn_date"], reverse=True)


def detect_recurring(debits):
    """Monthly / weekly repeating payments to the same merchant with a similar amount (subscriptions, rent, SIPs)."""
    by = defaultdict(list)
    for r in debits:
        if r["merchant"] and r["kind"] == "debit":
            by[r["merchant"].lower()].append(r)
    out = []
    for key, items in by.items():
        items.sort(key=lambda r: r["txn_date"])
        if len(items) < 3:
            continue
        days = [date.fromisoformat(r["txn_date"][:10]) for r in items]
        gaps = [(b - a).days for a, b in zip(days, days[1:]) if (b - a).days > 0]
        if len(gaps) < 2:
            continue
        gap = statistics.median(gaps)
        amts = [r["amount"] for r in items]
        mean = statistics.mean(amts)
        spread = statistics.pstdev(amts) / mean if mean else 1
        if 25 <= gap <= 35:
            every, per_month = "monthly", 1.0
        elif 6 <= gap <= 8:
            every, per_month = "weekly", 4.33
        else:
            continue
        if spread > 0.2 and items[-1]["spend_cat"] not in ("Subscriptions", "Rent & Housing", "Investments", "Insurance"):
            continue
        last = days[-1]
        out.append({"merchant": items[0]["merchant"], "amount": round(statistics.median(amts), 2), "every": every,
                    "count": len(items), "last_date": last.isoformat(),
                    "next_date": (last + timedelta(days=int(round(gap)))).isoformat(),
                    "monthly_cost": round(statistics.median(amts) * per_month, 2), "currency": items[0]["currency"],
                    "category": items[0]["spend_cat"]})
    return sorted(out, key=lambda x: -x["monthly_cost"])[:12]


def _upcoming(all_rows, today):
    dues = {}
    for r in all_rows:
        if r["kind"] in ("due", "emi_due") and r["due_date"]:
            key = (r["merchant"].lower() or r["src"], r["kind"], r["due_date"][:7])
            if key not in dues or r["txn_date"] > dues[key]["txn_date"]:
                dues[key] = r
    out = []
    for r in dues.values():
        dd = date.fromisoformat(r["due_date"])
        days_left = (dd - today).days
        if days_left < -10:
            continue
        lo, hi = (dd - timedelta(days=12)).isoformat(), (dd + timedelta(days=5)).isoformat()
        paid = any(p["kind"] in ("debit", "emi") and p["currency"] == r["currency"] and lo <= p["txn_date"][:10] <= hi
                   and p["txn_date"] > r["txn_date"] and (abs(p["amount"] - r["amount"]) < 1 or p["src"] == r["src"])
                   for p in all_rows)
        if paid:
            continue
        out.append({"id": r["id"], "title": r["merchant"] or r["src"], "kind": "EMI" if r["kind"] == "emi_due" else "Bill",
                    "amount": r["amount"], "min_due": r["min_due"], "currency": r["currency"], "due_date": r["due_date"],
                    "days_left": days_left, "overdue": days_left < 0})
    return sorted(out, key=lambda x: x["due_date"])


def _totals(money):
    spend = [r for r in money if r["kind"] in ("debit", "emi") and r["spend_cat"] not in NON_SPEND]
    inc = [r for r in money if r["kind"] == "credit"]
    return spend, inc, sum(r["amount"] for r in spend), sum(r["amount"] for r in inc)


def _pct(new, old):
    return None if not old else round((new - old) / old * 100)


def build_summary(rows, days, today=None, start=None, end=None, budgets=None):
    """Aggregate transaction rows (dicts) into the analytics payload for the Banking workspace.

    The window is either the last `days` days or [start, end] (dates). `budgets` is {category: monthly limit}.
    """
    today = today or datetime.now(timezone.utc).date()
    if start and end:
        start_d, end_d = date.fromisoformat(start), min(date.fromisoformat(end), today)
        days = (end_d - start_d).days + 1
    else:
        end_d, start_d = today, today - timedelta(days=days)
    prev_end = start_d - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    all_rows = dedupe(list(rows))
    in_range = lambda r, a, b: a.isoformat() <= r["txn_date"][:10] <= b.isoformat()
    money_all = [r for r in all_rows if r["kind"] in ("debit", "credit", "emi")]
    cur_counts = defaultdict(int)
    for r in money_all:
        if in_range(r, start_d, end_d):
            cur_counts[r["currency"]] += 1
    currency = max(cur_counts, key=cur_counts.get) if cur_counts else "INR"
    money_all = [r for r in money_all if r["currency"] == currency]
    money = [r for r in money_all if in_range(r, start_d, end_d)]
    prev_money = [r for r in money_all if in_range(r, prev_start, prev_end)]
    debits, credits, d_total, c_total = _totals(money)
    _, _, pd_total, pc_total = _totals(prev_money)
    card_paid = sum(r["amount"] for r in money if r["kind"] == "debit" and r["spend_cat"] in NON_SPEND)

    monthly = defaultdict(lambda: {"debit": 0.0, "credit": 0.0})
    for r in money:
        if r["kind"] == "credit":
            monthly[_month_key(r["txn_date"])]["credit"] += r["amount"]
        elif r["spend_cat"] not in NON_SPEND:
            monthly[_month_key(r["txn_date"])]["debit"] += r["amount"]
    months, y, m = [], end_d.year, end_d.month
    for _ in range(max(1, min(12, (end_d.year - start_d.year) * 12 + end_d.month - start_d.month + 1))):
        months.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    monthly_list = [{"month": k, "debit": round(monthly[k]["debit"], 2), "credit": round(monthly[k]["credit"], 2)} for k in months]

    cats = defaultdict(lambda: [0.0, 0])
    merchants = defaultdict(lambda: [0.0, 0])
    channels = defaultdict(lambda: [0.0, 0])
    accounts_spend = defaultdict(lambda: [0.0, 0])
    weekday = [0.0] * 7
    for r in debits:
        c = r["spend_cat"] or "Other"
        cats[c][0] += r["amount"]
        cats[c][1] += 1
        if r["merchant"]:
            merchants[r["merchant"].title()][0] += r["amount"]
            merchants[r["merchant"].title()][1] += 1
        if r["channel"]:
            channels[r["channel"]][0] += r["amount"]
            channels[r["channel"]][1] += 1
        if r["account"]:
            accounts_spend[r["account"]][0] += r["amount"]
            accounts_spend[r["account"]][1] += 1
        weekday[date.fromisoformat(r["txn_date"][:10]).weekday()] += r["amount"]
    pack = lambda d, n=10: [{"name": k, "amount": round(v[0], 2), "count": v[1]}
                            for k, v in sorted(d.items(), key=lambda kv: -kv[1][0])[:n]]
    income = defaultdict(lambda: [0.0, 0])
    for r in credits:
        income[r["spend_cat"] or "Other income"][0] += r["amount"]
        income[r["spend_cat"] or "Other income"][1] += 1

    upcoming = _upcoming(all_rows, today)
    soon = [u for u in upcoming if 0 <= u["days_left"] <= 7]

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

    recurring = detect_recurring([r for r in money_all if r["kind"] == "debit"])
    # unusually large payments: well above the usual size for the category
    by_cat_amounts = defaultdict(list)
    for r in money_all:
        if r["kind"] in ("debit", "emi") and r["spend_cat"] not in NON_SPEND:
            by_cat_amounts[r["spend_cat"] or "Other"].append(r["amount"])
    unusual = []
    for r in debits:
        vals = by_cat_amounts.get(r["spend_cat"] or "Other", [])
        if len(vals) >= 6:
            med = statistics.median(vals)
            if med and r["amount"] >= 3 * med and r["amount"] >= 1000 and r["spend_cat"] not in ("Rent & Housing", "Investments", "Travel", "EMI & Loans"):
                unusual.append({"id": r["id"], "date": r["txn_date"][:10], "merchant": r["merchant"], "amount": r["amount"],
                                "category": r["spend_cat"], "times_usual": round(r["amount"] / med, 1)})
    unusual = sorted(unusual, key=lambda x: -x["amount"])[:5]

    # budgets always cover the current calendar month
    month_start = today.replace(day=1)
    spent_cat = defaultdict(float)
    for r in money_all:
        if r["kind"] in ("debit", "emi") and r["spend_cat"] not in NON_SPEND and r["txn_date"][:10] >= month_start.isoformat():
            spent_cat[r["spend_cat"] or "Other"] += r["amount"]
    budget_list = []
    for cat, limit in sorted((budgets or {}).items()):
        sp = spent_cat.get(cat, 0.0)
        budget_list.append({"category": cat, "limit": limit, "spent": round(sp, 2), "pct": round(sp / limit * 100) if limit else 0,
                            "remaining": round(limit - sp, 2)})
    dim = calendar.monthrange(today.year, today.month)[1]
    mtd_spend = sum(spent_cat.values())
    projection = round(mtd_spend / today.day * dim, 2) if today.day >= 5 and mtd_spend else None

    span = max(1, (end_d - start_d).days + 1)
    insights = []
    if cats and d_total:
        top = max(cats.items(), key=lambda kv: kv[1][0])
        insights.append(f"Your biggest spending category is {top[0]} ({top[1][0] / d_total * 100:.0f}% of spend).")
    ch = _pct(d_total, pd_total)
    if ch is not None and abs(ch) >= 5:
        insights.append(f"Spending is {abs(ch)}% {'higher' if ch > 0 else 'lower'} than the previous {days} days.")
    if c_total:
        rate = (c_total - d_total) / c_total * 100
        insights.append(f"You kept {rate:.0f}% of your income in this period." if rate >= 0 else
                        f"You spent {abs(rate):.0f}% more than you earned in this period.")
    if emi_monthly and c_total:
        share = emi_monthly / (c_total / max(1, days / 30)) * 100
        insights.append(f"Your EMIs are roughly {share:.0f}% of your average monthly income.")
    if recurring:
        insights.append(f"{len(recurring)} recurring payments cost about {sum(x['monthly_cost'] for x in recurring):,.0f} a month.")
    if soon:
        insights.append(f"{len(soon)} payment{'s' if len(soon) != 1 else ''} due in the next 7 days.")
    if any(u["overdue"] for u in upcoming):
        insights.append("Some payments look overdue. Check the Upcoming payments list.")
    if unusual:
        insights.append(f"{unusual[0]['merchant'] or unusual[0]['category']} on {unusual[0]['date']} was {unusual[0]['times_usual']}x your usual size for that category.")
    return {
        "currency": currency, "days": days, "from": start_d.isoformat(), "to": end_d.isoformat(),
        "totals": {"debit": round(d_total, 2), "credit": round(c_total, 2), "net": round(c_total - d_total, 2),
                   "count": len(money), "avg_daily_spend": round(d_total / span, 2), "emi_monthly": round(emi_monthly, 2),
                   "savings_rate": round((c_total - d_total) / c_total * 100) if c_total else None,
                   "card_bills_paid": round(card_paid, 2)},
        "vs_previous": {"debit_pct": _pct(d_total, pd_total), "credit_pct": _pct(c_total, pc_total)},
        "monthly": monthly_list, "by_category": pack(cats, 12), "income": pack(income, 6),
        "top_merchants": pack(merchants, 8), "by_channel": pack(channels, 6), "by_account": pack(accounts_spend, 6),
        "weekday": [round(x, 2) for x in weekday],
        "largest": [{"id": r["id"], "date": r["txn_date"][:10], "merchant": r["merchant"], "amount": r["amount"],
                     "category": r["spend_cat"]} for r in sorted(debits, key=lambda r: -r["amount"])[:5]],
        "recurring": recurring, "unusual": unusual,
        "upcoming": upcoming[:12], "due_soon": {"count": len(soon), "total": round(sum(u["amount"] for u in soon), 2)},
        "loans": loan_list[:10], "accounts": list(accounts.values())[:8],
        "budgets": budget_list, "month": {"spent": round(mtd_spend, 2), "projection": projection, "day": today.day, "days_in_month": dim},
        "recent": [{"id": r["id"], "date": r["txn_date"][:10], "kind": r["kind"], "amount": r["amount"],
                    "merchant": r["merchant"], "category": r["spend_cat"], "currency": r["currency"]} for r in all_rows[:8]
                   if r["kind"] in ("debit", "credit", "emi")],
        "insights": insights,
    }
