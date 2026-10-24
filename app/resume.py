"""Resume upload validation and text extraction."""
import html
import io
import re
import zipfile

MAX_BYTES = 2 * 1024 * 1024
ALLOWED = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/plain",
}


def validate(filename: str, data: bytes):
    """Return (extension, mime) or raise ValueError with a short reason."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED:
        raise ValueError("unsupported_type")
    if not data:
        raise ValueError("empty_file")
    if len(data) > MAX_BYTES:
        raise ValueError("too_large")
    if ext == ".pdf" and not data.startswith(b"%PDF"):
        raise ValueError("not_a_pdf")
    if ext == ".docx" and not data.startswith(b"PK"):
        raise ValueError("not_a_docx")
    return ext, ALLOWED[ext]


def extract_text(ext: str, data: bytes) -> str:
    """Best-effort plain text (used for AI matching). Returns '' if it cannot be read."""
    try:
        if ext in (".txt", ".md"):
            return data.decode("utf-8", "replace")[:20000]
        if ext == ".docx":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                info = z.getinfo("word/document.xml")
                if info.file_size > 20 * 1024 * 1024:
                    return ""
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            xml = re.sub(r"</w:p>|<w:br\s*/>|<w:tab\s*/>", "\n", xml)
            return re.sub(r"\n{3,}", "\n\n", html.unescape(re.sub(r"<[^>]+>", "", xml))).strip()[:20000]
        if ext == ".pdf":
            from pypdf import PdfReader  # optional dependency

            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages[:12]).strip()[:20000]
    except Exception:  # unreadable or optional parser missing: the user can paste a profile instead
        return ""
    return ""
