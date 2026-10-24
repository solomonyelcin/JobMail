"""Build RFC 822 messages (with optional resume attachment) for Gmail drafts."""
import base64
import mimetypes
import re
from email.message import EmailMessage

ADDR = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


def clean_header(v: str, limit: int = 300) -> str:
    return re.sub(r"[\r\n]+", " ", v or "").strip()[:limit]


def first_address(header: str) -> str:
    """Return the first bare address from a From/Reply-To style header, or ''."""
    m = re.search(r"<([^>]+)>", header or "")
    addr = (m.group(1) if m else (header or "").split(",")[0]).strip().lower()
    return addr if ADDR.match(addr) else ""


def build_raw(to: str, subject: str, body: str, in_reply_to: str = "", attachment=None) -> str:
    """attachment: (filename, mime, bytes) or None. Returns base64url string for the Gmail API."""
    if not ADDR.match(to or ""):
        raise ValueError("invalid recipient address")
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = clean_header(subject, 200) or "(no subject)"
    if in_reply_to:
        msg["In-Reply-To"] = clean_header(in_reply_to)
        msg["References"] = clean_header(in_reply_to)
    msg.set_content(body)
    if attachment:
        filename, mime, data = attachment
        maintype, _, subtype = (mime or mimetypes.guess_type(filename)[0] or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream",
                           filename=clean_header(filename, 120) or "resume")
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()
