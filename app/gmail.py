"""Minimal Gmail / Google OAuth client using plain HTTPS (no Google SDK needed)."""
import base64
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = ("openid email https://www.googleapis.com/auth/gmail.readonly "
          "https://www.googleapis.com/auth/gmail.compose")
TIMEOUT = 20

JOB_KEYWORDS = (
    'application OR applied OR "your application" OR interview OR candidate OR candidacy OR recruiter OR '
    'recruitment OR hiring OR "job alert" OR job OR jobs OR opening OR openings OR position OR vacancy OR '
    'vacancies OR "offer letter" OR assessment OR "coding challenge" OR career OR careers OR resume OR cv OR '
    'shortlisted OR opportunity OR "walk-in"'
)
JOB_SENDERS = (
    "linkedin.com OR naukri.com OR indeed.com OR glassdoor.com OR instahyre.com OR wellfound.com OR foundit.in OR "
    "monsterindia.com OR shine.com OR cutshort.io OR hirist.tech OR iimjobs.com OR ambitionbox.com OR greenhouse.io OR "
    "lever.co OR myworkday.com OR workable.com OR smartrecruiters.com OR ashbyhq.com OR icims.com OR jobvite.com OR "
    "hackerrank.com OR hirevue.com OR bamboohr.com"
)


def build_auth_url(client_id, redirect_uri, state):
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(client_id, client_secret, redirect_uri, code):
    r = requests.post(TOKEN_URL, data={
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def refresh_access_token(client_id, client_secret, refresh_token):
    r = requests.post(TOKEN_URL, data={
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    }, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["access_token"]


def get_userinfo(access_token):
    r = requests.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def build_query(days):
    return f"newer_than:{int(days)}d -in:spam -in:trash (({JOB_KEYWORDS}) OR from:({JOB_SENDERS}))"


class GmailClient:
    def __init__(self, access_token):
        self.h = {"Authorization": f"Bearer {access_token}"}
        self.s = requests.Session()
        retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503], allowed_methods=["GET"])
        self.s.mount("https://", HTTPAdapter(pool_connections=16, pool_maxsize=16, max_retries=retry))

    def list_message_ids(self, query, max_total=1000):
        ids, token = [], None
        while len(ids) < max_total:
            params = {"q": query, "maxResults": 100}
            if token:
                params["pageToken"] = token
            r = self.s.get(f"{GMAIL_API}/messages", headers=self.h, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            ids += [m["id"] for m in data.get("messages", [])]
            token = data.get("nextPageToken")
            if not token:
                break
        return ids[:max_total]

    def list_unread_ids(self, days, max_total=1000):
        return self.list_message_ids(build_query(days) + " is:unread", max_total)

    def create_draft(self, raw_b64url, thread_id=None):
        """Create a Gmail draft from a base64url RFC 822 message. Returns the API response."""
        message = {"raw": raw_b64url}
        if thread_id:
            message["threadId"] = thread_id
        r = self.s.post(f"{GMAIL_API}/drafts", headers=self.h, json={"message": message}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    def get_message(self, msg_id):
        r = self.s.get(f"{GMAIL_API}/messages/{msg_id}", headers=self.h,
                       params={"format": "full"}, timeout=TIMEOUT)
        r.raise_for_status()
        return parse_message(r.json())

    def get_messages(self, ids, workers=8):
        """Fetch many messages in parallel. Returns {id: message or None (if deleted)}."""
        def one(mid):
            try:
                return mid, self.get_message(mid)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    return mid, None
                raise

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return dict(pool.map(one, ids))


def _decode(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _walk(part, out):
    mime = part.get("mimeType", "")
    body = part.get("body", {}).get("data")
    if body and mime in ("text/plain", "text/html"):
        out.setdefault(mime, []).append(_decode(body))
    for p in part.get("parts", []) or []:
        _walk(p, out)


def _html_to_text(html):
    html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def parse_message(msg):
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    out = {}
    _walk(msg.get("payload", {}), out)
    if out.get("text/plain"):
        text = "\n".join(out["text/plain"])
    else:
        text = _html_to_text(" ".join(out.get("text/html", [])))
    received = datetime.fromtimestamp(int(msg.get("internalDate", "0")) / 1000, tz=timezone.utc)
    return {
        "gmail_id": msg["id"],
        "thread_id": msg.get("threadId", ""),
        "subject": headers.get("subject", ""),
        "sender": headers.get("from", ""),
        "snippet": msg.get("snippet", ""),
        "is_unread": 1 if "UNREAD" in (msg.get("labelIds") or []) else 0,
        "message_id": headers.get("message-id", "")[:300],
        "reply_to": headers.get("reply-to", "")[:300],
        "body_text": re.sub(r"\n{3,}", "\n\n", text).strip()[:4000],
        "received_at": received.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
