"""Show an email the way Gmail does: its real HTML, cleaned up so it is safe to display.

The result is a complete HTML document that the app serves into a sandboxed <iframe> with its own strict
Content-Security-Policy. Safety comes in layers, so no single one has to be perfect:
  1. this module rebuilds the HTML from an allow-list (no scripts, forms, frames, event handlers, javascript: links)
  2. the document is served with a CSP that forbids scripts and all connections
  3. the iframe is sandboxed without allow-scripts
Remote images are optional (they can be used to track that a mail was opened); inline images are embedded.
"""
import base64
import html
import re
from html.parser import HTMLParser

MAX_HTML = 1_500_000  # characters; bigger than any normal mail, small enough to be safe

ALLOWED_TAGS = {
    "a", "abbr", "address", "article", "aside", "b", "bdi", "bdo", "big", "blockquote", "br", "caption", "center",
    "cite", "code", "col", "colgroup", "dd", "del", "dfn", "div", "dl", "dt", "em", "figcaption", "figure", "font",
    "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "i", "img", "ins", "kbd", "li", "main", "mark",
    "nav", "ol", "p", "pre", "q", "s", "samp", "section", "small", "span", "strike", "strong", "style", "sub",
    "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "tt", "u", "ul", "var", "wbr",
}
VOID = {"br", "hr", "img", "col", "wbr"}
# removed together with everything inside them
DROP_WITH_CONTENT = {
    "script", "iframe", "frame", "frameset", "object", "embed", "applet", "noscript", "template", "svg", "math",
    "audio", "video", "canvas", "title", "select", "textarea", "button", "datalist", "dialog",
}
GLOBAL_ATTRS = {
    "style", "class", "id", "dir", "lang", "title", "align", "valign", "width", "height", "bgcolor", "color", "face",
    "size", "border", "cellpadding", "cellspacing", "colspan", "rowspan", "nowrap", "span", "start", "type",
    "background", "role", "abbr", "scope", "headers",
}
SAFE_IMG_DATA = re.compile(r"^data:image/(png|jpe?g|gif|webp|bmp|x-icon|vnd\.microsoft\.icon);base64,[A-Za-z0-9+/=\s]+$", re.I)
SAFE_LINK = re.compile(r"^(https?:|mailto:|tel:)", re.I)
CSS_BAD = re.compile(r"(?i)@import[^;]*;?|expression\s*\(|javascript\s*:|vbscript\s*:|behaviou?r\s*:|-moz-binding\s*:")
CSS_URL = re.compile(r"(?i)url\(\s*(['\"]?)(.*?)\1\s*\)")
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)


class _Cleaner(HTMLParser):
    def __init__(self, inline, allow_remote):
        super().__init__(convert_charrefs=True)
        self.out, self.stack = [], []
        self.skip = 0
        self.inline = inline          # {content-id: (mime, bytes)}
        self.allow_remote = allow_remote
        self.remote = 0               # remote images found (shown or held back)
        self.in_style = False

    # ----- url / css helpers -----
    def _cid_uri(self, cid):
        key = re.sub(r"^cid:", "", cid.strip(), flags=re.I)
        for k in (key, key.strip("<>")):
            if k in self.inline:
                mime, raw = self.inline[k]
                return f"data:{mime};base64," + base64.b64encode(raw).decode()
        return ""

    def _image_url(self, value):
        """Return a URL that is safe to load, or '' (and count remote images that are held back or shown)."""
        v = (value or "").strip()
        if v.lower().startswith("cid:"):
            return self._cid_uri(v)
        if SAFE_IMG_DATA.match(v):
            return re.sub(r"\s+", "", v)
        if re.match(r"(?i)^https?://", v):
            self.remote += 1
            return v if self.allow_remote else ""
        if v.startswith("//"):
            self.remote += 1
            return "https:" + v if self.allow_remote else ""
        return ""

    def _css(self, text):
        text = CSS_BAD.sub(" ", CSS_COMMENT.sub(" ", text))

        def fix(m):
            url = self._image_url(m.group(2))
            return f"url('{url}')" if url and "'" not in url and "\\" not in url else "none"
        return CSS_URL.sub(fix, text).replace("</", "<\\/")

    # ----- parser callbacks -----
    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in DROP_WITH_CONTENT and tag not in VOID:
                self.skip += 1
            return
        if tag in DROP_WITH_CONTENT:
            self.skip = 1
            return
        if tag == "body":
            tag = "div"
        elif tag not in ALLOWED_TAGS:
            return  # unknown tag (html, head, form, o:p...): drop the tag, keep what is inside
        if tag == "style":
            self.in_style = True
        parts = []
        a = dict((k.lower(), v if v is not None else "") for k, v in attrs)
        for k, v in a.items():
            if k == "style":
                css = self._css(v)
                if css.strip():
                    parts.append(f' style="{html.escape(css, quote=True)}"')
            elif k == "href" and tag == "a":
                if SAFE_LINK.match(v.strip()):
                    parts.append(f' href="{html.escape(v.strip(), quote=True)}"')
            elif k == "src" and tag == "img":
                url = self._image_url(v)
                if url:
                    parts.append(f' src="{html.escape(url, quote=True)}"')
            elif k == "alt" and tag == "img":
                parts.append(f' alt="{html.escape(v, quote=True)}"')
            elif k == "background":
                url = self._image_url(v)
                if url:
                    parts.append(f' background="{html.escape(url, quote=True)}"')
            elif k in GLOBAL_ATTRS and k != "background" and len(v) < 2000:
                parts.append(f' {k}="{html.escape(v, quote=True)}"')
        if tag == "a":
            parts.append(' target="_blank" rel="noopener noreferrer nofollow"')
        self.out.append(f"<{tag}{''.join(parts)}>")
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            return  # a self-closed <svg/> has no content to skip
        self.handle_starttag(tag, attrs)
        if tag not in VOID and tag in ALLOWED_TAGS | {"body"} and not self.skip and self.stack:
            self.handle_endtag("div" if tag == "body" else tag)

    def handle_endtag(self, tag):
        if self.skip:
            if tag in DROP_WITH_CONTENT:
                self.skip -= 1
            return
        if tag == "body":
            tag = "div"
        if tag in VOID or tag not in self.stack:
            return
        while self.stack:  # close anything left open inside it, then the tag itself
            top = self.stack.pop()
            self.out.append(f"</{top}>")
            if top == "style":
                self.in_style = False
            if top == tag:
                break

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_style:
            self.out.append(self._css(data))
        else:
            self.out.append(html.escape(data, quote=False))

    def close_all(self):
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")


def clean_html(raw, inline=None, allow_remote=True):
    """Return (safe_html_fragment, remote_image_count)."""
    p = _Cleaner(inline or {}, allow_remote)
    p.feed((raw or "")[:MAX_HTML])
    p.close()
    p.close_all()
    return "".join(p.out), p.remote


URL_IN_TEXT = re.compile(r"https?://[^\s<>\"')\]]+", re.I)


def text_to_html(text):
    """Plain-text-only mail: keep line breaks, make links clickable."""
    out, last = [], 0
    for m in URL_IN_TEXT.finditer(text or ""):
        url = m.group(0).rstrip(".,;:!?")
        out.append(html.escape(text[last:m.start()], quote=False))
        out.append(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer nofollow">{html.escape(url, quote=False)}</a>')
        last = m.start() + len(url)
    out.append(html.escape((text or "")[last:], quote=False))
    return '<div class="jm-plain">' + "".join(out) + "</div>"


BASE_CSS = (
    "html,body{margin:0;background:#fff;color:#202124}"
    "body{padding:14px 16px;font:14px/1.5 Roboto,'Helvetica Neue',Arial,sans-serif;overflow-wrap:anywhere}"
    "img{max-width:100%}.jm-plain{white-space:pre-wrap;font-family:Roboto,Arial,sans-serif}"
    "a{color:#1a0dab}"
)


def render(original, allow_remote=True):
    """Full HTML document for one message. `original` comes from GmailClient.get_original()."""
    inline = original.get("inline") or {}
    if (original.get("html") or "").strip():
        body, remote = clean_html(original["html"], inline, allow_remote)
    else:
        body, remote = text_to_html(original.get("text") or ""), 0
    return wrap(body, remote)


def wrap(body, remote=0, error=False):
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light"><base target="_blank">'
        f'<meta name="jm-remote" content="{int(remote)}">' + ('<meta name="jm-error" content="1">' if error else "") +
        f"<style>{BASE_CSS}</style></head><body>{body}</body></html>"
    )


def error_page(message):
    return wrap(f'<p style="color:#5f6368">{html.escape(message)}</p>', 0, error=True)


# What the framed document may do: show inline styles and images, nothing else.
def csp(allow_remote):
    img = "data: https:" if allow_remote else "data:"
    return (f"default-src 'none'; img-src {img}; style-src 'unsafe-inline'; font-src data:; "
            "script-src 'none'; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'")
