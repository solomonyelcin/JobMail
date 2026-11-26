import base64

import requests

from app import htmlview
from app.gmail import _html_to_text
from helpers import sync_all

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def clean(raw, inline=None, remote=True):
    return htmlview.clean_html(raw, inline, remote)


# ---------- sanitizer: things that must never survive ----------
def test_scripts_frames_and_forms_are_removed():
    out, _ = clean('<p>Hi</p><script>alert(1)</script><iframe src="https://evil"></iframe><object data="x"></object>'
                   '<form action="https://evil"><input name=a><button>Go</button></form><svg onload=alert(1)><circle/></svg>after')
    assert "<script" not in out and "alert" not in out and "iframe" not in out and "<object" not in out
    assert "<form" not in out and "<input" not in out and "<svg" not in out
    assert "Hi" in out and "after" in out  # content around the removed parts is kept


def test_event_handlers_and_unsafe_links_are_stripped():
    out, _ = clean('<a href="javascript:alert(1)" onclick="x()">a</a><a href=" JaVaScRiPt:alert(1)">b</a>'
                   '<a href="data:text/html,<script>1</script>">c</a><a href="https://ok.com/x?a=1&b=2">d</a>'
                   '<img src=x onerror="alert(1)"><div onmouseover="x()">e</div>')
    low = out.lower()
    assert "onclick" not in low and "onerror" not in low and "onmouseover" not in low
    assert "javascript:" not in low and "data:text/html" not in low
    assert 'href="https://ok.com/x?a=1&amp;b=2"' in out
    assert 'target="_blank"' in out and "noopener" in out


def test_css_tricks_are_neutralised():
    out, _ = clean('<style>@import url(https://evil/x.css); p{background:url(javascript:alert(1)); width:expression(alert(1))}'
                   'b{-moz-binding:url(x);behavior:url(x)}</style><div style="background:url(https://t.example/p.gif)">x</div>', remote=False)
    low = out.lower()
    assert "@import" not in low and "javascript" not in low and "expression" not in low
    assert "-moz-binding" not in low and "behavior" not in low
    assert "t.example" not in low  # remote css image held back when remote images are off


def test_style_text_cannot_break_out_of_the_style_tag():
    out, _ = clean("<style>p{color:red}</style><script>alert(1)</script><p>x</p>")
    assert "<script" not in out
    out, _ = clean('<style>a{}</style><img src=x onerror=alert(1)><style>b{}</style>')
    assert "onerror" not in out


def test_self_closed_dropped_tag_does_not_swallow_the_mail():
    out, _ = clean("<svg/><p>Still here</p><script src=x /><p>and here</p>")
    assert "Still here" in out and "and here" in out


def test_unclosed_and_misnested_tags_are_balanced():
    out, _ = clean("<div><table><tr><td><b>bold<i>both</td></tr></table>tail")
    for tag in ("div", "table", "tr", "td", "b", "i"):
        assert out.count(f"<{tag}") == out.count(f"</{tag}>"), tag
    assert "tail" in out


# ---------- images ----------
def test_remote_images_can_be_held_back_and_are_counted():
    raw = '<img src="https://track.example/p.gif" alt="pixel"><img src="//cdn.example/a.png">'
    shown, n1 = clean(raw, remote=True)
    held, n2 = clean(raw, remote=False)
    assert n1 == n2 == 2
    assert "track.example" in shown and "cdn.example" in shown
    assert "track.example" not in held and "cdn.example" not in held and 'alt="pixel"' in held


def test_cid_images_are_embedded_and_unknown_cid_dropped():
    out, n = clean('<img src="cid:logo@x"><img src="cid:missing">', {"logo@x": ("image/png", PNG)}, remote=False)
    assert "data:image/png;base64," in out and n == 0
    assert out.count("src=") == 1


def test_only_safe_data_images_allowed():
    out, _ = clean('<img src="data:image/svg+xml;base64,PHN2Zz4="><img src="data:text/html;base64,PHA+"><img src="data:image/png;base64,AAAA">')
    assert out.count("src=") == 1 and "image/png" in out


# ---------- fidelity ----------
def test_formatting_is_kept():
    raw = ('<body bgcolor="#eeeeee" style="margin:0"><table width="600" align="center" bgcolor="#fff" cellpadding="8">'
           '<tr><td style="font-family:Georgia;color:#336699;font-size:20px"><b>Hello</b> <font color="red" face="Arial">there</font>'
           '</td></tr></table><h1>Title</h1><ul><li>one</li></ul><hr></body>')
    out, _ = clean(raw)
    for needle in ('bgcolor="#eeeeee"', 'width="600"', 'align="center"', "font-family:Georgia", "color:#336699", '<font color="red" face="Arial">',
                   "<h1>", "<li>", "<hr>"):
        assert needle in out, needle


def test_entities_survive_once_and_are_not_double_escaped():
    out, _ = clean("<p>Don&#x27;t &amp; won&nbsp;t &lt;b&gt;</p>")
    assert "Don't" in out and "&amp;" in out and "&lt;b&gt;" in out and "&amp;amp;" not in out and "&#x27;" not in out


def test_plain_text_mail_keeps_breaks_and_links():
    doc = htmlview.render({"html": "", "text": "Hi <Solomon>\nApply: https://acme.com/jobs/1."})
    assert "white-space:pre-wrap" in doc and "&lt;Solomon&gt;" in doc
    assert '<a href="https://acme.com/jobs/1"' in doc


def test_text_version_decodes_entities():
    t = _html_to_text("<p>I don&#x27;t want you to miss out.&nbsp;Reply &ldquo;yes&rdquo;</p><p>Next</p>")
    assert "&#x27;" not in t and "&nbsp;" not in t and "don't" in t and "\n" in t


# ---------- route ----------
HTML = ('<html><body style="background:#f4f4f4"><h1 style="color:#c00">Hello</h1><img src="cid:logo">'
        '<img src="https://t.example/p.gif"><script>alert(1)</script></body></html>')


def _setup(app, auth_client):
    sync_all(auth_client)
    from conftest import SAMPLE
    SAMPLE[0]["html"] = HTML
    SAMPLE[0]["inline"] = {"logo": ("image/png", PNG)}
    wanted = SAMPLE[0]["subject"]
    return next(i["id"] for i in auth_client.get("/api/emails").get_json()["items"] if i["subject"] == wanted)


def _cleanup():
    from conftest import SAMPLE
    for m in SAMPLE:
        m.pop("html", None); m.pop("inline", None)


def test_view_route_serves_original_with_strict_headers(app, auth_client):
    try:
        eid = _setup(app, auth_client)
        r = auth_client.get(f"/api/emails/{eid}/view")
        assert r.status_code == 200 and r.mimetype == "text/html"
        body = r.get_data(as_text=True)
        assert "color:#c00" in body and "data:image/png;base64," in body and "t.example/p.gif" in body
        assert "<script" not in body and "alert(1)" not in body
        csp = r.headers["Content-Security-Policy"]
        assert "script-src 'none'" in csp and "default-src 'none'" in csp and "connect-src 'none'" in csp
        assert "img-src data: https:" in csp
        assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
        held = auth_client.get(f"/api/emails/{eid}/view?images=0")
        assert "t.example" not in held.get_data(as_text=True) and "img-src data:;" in held.headers["Content-Security-Policy"]
        assert 'name="jm-remote" content="1"' in held.get_data(as_text=True)
    finally:
        _cleanup()


def test_other_pages_still_cannot_be_framed(auth_client):
    r = auth_client.get("/api/stats")
    assert r.headers["X-Frame-Options"] == "DENY" and "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_view_route_needs_login_and_handles_missing(app, auth_client, client):
    assert client.get("/api/emails/1/view").status_code in (401, 302)
    r = auth_client.get("/api/emails/99999/view")
    assert r.status_code == 404 and 'name="jm-error"' in r.get_data(as_text=True)


def test_view_route_reports_gmail_failure_without_leaking(app, auth_client):
    eid = _setup(app, auth_client)
    try:
        import conftest

        class Boom(conftest.FakeGmail):
            def get_original(self, mid):
                raise RuntimeError("token abc123 secret")
        app.extensions["gmail_factory"] = lambda cfg, r: Boom([])
        r = auth_client.get(f"/api/emails/{eid}/view")
        assert r.status_code == 502 and "abc123" not in r.get_data(as_text=True) and 'name="jm-error"' in r.get_data(as_text=True)
    finally:
        _cleanup()
