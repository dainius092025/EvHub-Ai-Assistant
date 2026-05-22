import re
import json
import logging
from pathlib import Path
from html.parser import HTMLParser
from typing import Any

log = logging.getLogger(__name__)


class _HTMLTextExtractor(HTMLParser):
    SKIP_TAGS = {"script", "style"}

    def __init__(self):
        super().__init__()
        self._parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip += 1
        if tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "tr"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self):
        text = "".join(self._parts)
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def strip_html(html: str) -> str:
    """Convert HTML to plain text, preserving paragraph breaks."""
    if not html:
        return ""
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html)
        return parser.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html).strip()


def safe_filename(name: str, max_len: int = 60) -> str:
    """Sanitize a string for safe use as a filename."""
    # Replace slashes and backslashes with underscores before sanitizing
    name = name.replace("/", "_").replace("\\", "_")
    name = re.sub(r"[^\w\-\.]", "_", name)  # Replace remaining unsafe characters
    return name[:max_len]

def write_json(path: Path, data: Any) -> None:
    """Write data to a JSON file with proper encoding and formatting."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# Inline email images auto-named by Outlook/mail clients: image001.png etc.
_SIGNATURE_IMAGE_RE = re.compile(r"^image\d+\.(png|jpg|jpeg|gif|bmp)$", re.IGNORECASE)


def is_signature_image(filename: str, mimetype: str, file_size: int) -> bool:
    """Return True if an attachment is likely an inline email signature image."""
    if not (mimetype or "").startswith("image/"):
        return False
    fname = filename or ""
    return bool(_SIGNATURE_IMAGE_RE.match(fname)) or fname.lower().startswith("outlook")


def format_html(html: str) -> str:
    """Add newlines after block-level HTML tags so the file is human-readable."""
    if not html:
        return html
    result = re.sub(
        r'(</(?:p|h[1-6]|div|ul|ol|li|table|tr|td|th|section|blockquote|pre)>)',
        r'\1\n',
        html,
        flags=re.IGNORECASE,
    )
    result = re.sub(r'<br\s*/?>', '<br/>\n', result, flags=re.IGNORECASE)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


def clean_chatter(messages: list) -> list:
    """
    Filter and simplify raw Odoo mail.message records.
    - Drops messages with no text content
    - Returns a compact structure: author, date, type, body (+ from/internal where set)
    """
    result = []
    for m in messages:
        body_text = strip_html(m.get("body") or "").strip()
        if not body_text:
            continue

        author_raw = m.get("author_id")
        if isinstance(author_raw, (list, tuple)) and len(author_raw) == 2:
            author = author_raw[1]
        elif isinstance(author_raw, dict):
            author = author_raw.get("name", "")
        else:
            author = str(author_raw) if author_raw else ""

        entry = {
            "author": author,
            "date": m.get("date"),
            "type": m.get("message_type"),
            "body": body_text,
        }
        if m.get("is_internal"):
            entry["internal"] = True
        if m.get("message_type") == "email" and m.get("email_from"):
            entry["from"] = m["email_from"]

        result.append(entry)
    return result
