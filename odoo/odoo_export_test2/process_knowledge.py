#!/usr/bin/env python3
"""
process_knowledge.py

Post-processes exported Odoo knowledge base HTML files for RAG LLM import.
For each article in the knowledge export directory:
  - Downloads or decodes all images and saves them to an images/ subfolder
  - Replaces Odoo embedded file spans with plain-text references
  - Converts HTML to clean Markdown
  - Prepends a YAML metadata block
  - Skips low-content articles below a configurable word count threshold

Run from the project root (or odoo_export_test2/) after the main Odoo export.

Usage:
    python odoo_export_test2/process_knowledge.py [options]

Options:
    --knowledge-dir PATH    Path to knowledge export directory
                            (default: <this script's dir>/Export/knowledge)
    --min-words N           Minimum word count to keep an article (default: 50)
    --overwrite             Re-process and overwrite existing body.md files
    --no-images             Skip image download (faster, offline-safe)
    -v, --verbose           Enable debug logging
"""

import json
import re
import base64
import logging
import argparse
from pathlib import Path
from datetime import date

import requests
from bs4 import BeautifulSoup

try:
    import markdownify as _md
    _HEADING_STYLE = _md.ATX
except ImportError:
    _md = None  # type: ignore
    _HEADING_STYLE = None

ODOO_BASE_URL = "https://evhub.odoo.com"
DEFAULT_KNOWLEDGE_DIR = Path(__file__).parent / "Export" / "knowledge"
MIN_WORD_COUNT = 50

# Odoo data attributes that add noise without semantic value
_ODOO_DATA_ATTRS = {
    "data-oe-version", "data-last-history-steps", "data-oe-id",
    "data-oe-model", "data-oe-field", "data-oe-xpath", "data-oe-expression",
    "data-embedded-props", "data-embedded", "data-file-name",
}

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _article_id_from_folder(name: str) -> int | None:
    m = re.match(r"^(\d+)_", name)
    return int(m.group(1)) if m else None


_DATA_MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
}


def _image_ext(src: str, file_hint: str) -> str:
    """Best-effort extension from data-file-name, MIME type, or URL path."""
    if file_hint:
        suffix = Path(file_hint).suffix
        if suffix:
            return suffix
    if src.startswith("data:"):
        # data:image/png;base64,... — extract MIME without touching the payload
        try:
            mime = src[5 : src.index(";")]
            return _DATA_MIME_TO_EXT.get(mime, ".bin")
        except ValueError:
            return ".jpg"
    suffix = Path(src.split("?")[0]).suffix
    return suffix if suffix else ".jpg"


def _save_base64(data_url: str, dest: Path) -> bool:
    try:
        _, encoded = data_url.split(",", 1)
        dest.write_bytes(base64.b64decode(encoded))
        return True
    except Exception as exc:
        log.warning("base64 decode failed: %s", exc)
        return False


def _download(url: str, dest: Path, session: requests.Session) -> bool:
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except Exception as exc:
        log.warning("download failed %s: %s", url, exc)
        return False


# ---------------------------------------------------------------------------
# HTML processing steps
# ---------------------------------------------------------------------------

def process_images(
    soup: BeautifulSoup,
    article_dir: Path,
    session: requests.Session,
    download: bool,
) -> int:
    """
    Find all <img> tags, resolve each image (base64 / Odoo-relative / absolute),
    save to article_dir/images/, and rewrite the src to the local relative path.
    Returns the number of images successfully saved.
    """
    img_tags = soup.find_all("img")
    if not img_tags:
        return 0

    images_dir = article_dir / "images"
    images_dir.mkdir(exist_ok=True)
    saved = 0

    for idx, img in enumerate(img_tags, start=1):
        src = img.get("src", "").strip()
        if not src:
            continue

        file_hint = img.get("data-file-name", "")
        ext = _image_ext(src, file_hint)
        stem = Path(file_hint).stem if file_hint else "image"
        local_name = f"{idx}_{stem}{ext}"
        dest = images_dir / local_name

        if src.startswith("data:"):
            # Base64-encoded image
            if not dest.exists():
                _save_base64(src, dest)
            if dest.exists():
                img["src"] = f"images/{local_name}"
                saved += 1

        elif src.startswith("/"):
            # Odoo-relative URL — access token already embedded in query string
            full_url = ODOO_BASE_URL + src
            if download:
                if not dest.exists():
                    _download(full_url, dest, session)
                if dest.exists():
                    img["src"] = f"images/{local_name}"
                    saved += 1
                else:
                    img["src"] = full_url  # fall back to absolute URL
            else:
                img["src"] = full_url

        elif src.startswith("http"):
            # Absolute external URL
            if download:
                if not dest.exists():
                    _download(src, dest, session)
                if dest.exists():
                    img["src"] = f"images/{local_name}"
                    saved += 1

    return saved


def process_embedded_files(soup: BeautifulSoup) -> None:
    """
    Replace <span data-embedded="file"> elements with a plain-text
    attachment reference that survives Markdown conversion.
    """
    for span in soup.find_all("span", attrs={"data-embedded": "file"}):
        try:
            props = json.loads(span.get("data-embedded-props") or "{}")
            name = props.get("fileData", {}).get("name", "attachment")
        except (json.JSONDecodeError, AttributeError):
            name = "attachment"
        span.replace_with(f"[Attachment: {name}]")


def clean_soup(soup: BeautifulSoup) -> None:
    """
    Strip Odoo-specific data attributes, remove empty paragraphs,
    and normalize whitespace characters.
    """
    for tag in soup.find_all(True):
        for attr in list(tag.attrs.keys()):
            if attr in _ODOO_DATA_ATTRS:
                del tag[attr]

    # Remove paragraphs that contain only whitespace / <br> (no real content, no images)
    for p in soup.find_all("p"):
        if p.find("img"):
            continue
        text = p.get_text().replace("\xa0", "").replace("​", "").strip()
        if not text:
            p.decompose()

    # Normalize non-breaking spaces and zero-width characters in text nodes
    _INVISIBLE = re.compile(r"[​‌‍­﻿⁠]+")
    for node in soup.find_all(string=True):
        cleaned = node.replace("\xa0", " ")
        cleaned = _INVISIBLE.sub("", cleaned)
        if cleaned != node:
            node.replace_with(cleaned)


# ---------------------------------------------------------------------------
# Markdown conversion
# ---------------------------------------------------------------------------

def html_to_markdown(html: str) -> str:
    if _md is not None:
        text = _md.markdownify(
            html,
            heading_style=_HEADING_STYLE,
            bullets="-",
            newline_style=_md.BACKSLASH,
        )
    else:
        import html as _html_module
        text = re.sub(r"<[^>]+>", "", html)
        text = _html_module.unescape(text)

    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _word_count(text: str) -> int:
    return len(text.split())


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def _yaml_value(v: str) -> str:
    """Quote a YAML scalar value if it contains special characters."""
    if any(c in v for c in (':', '#', '[', ']', '{', '}', '"', "'")):
        v = v.replace('"', '\\"')
        return f'"{v}"'
    return v


def build_frontmatter(
    title: str,
    article_id: int | None,
    folder: str,
    word_count: int,
    image_count: int,
) -> str:
    lines = [
        "---",
        f"title: {_yaml_value(title)}",
        f"article_id: {article_id if article_id is not None else ''}",
        f"folder: {folder}",
        "source: evhub_knowledge_base",
        f"processed_date: {date.today().isoformat()}",
        f"word_count: {word_count}",
        f"image_count: {image_count}",
        "---",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-article processing
# ---------------------------------------------------------------------------

_Result = str  # "ok" | "skipped" | "exists" | "error"


def process_article(
    article_dir: Path,
    session: requests.Session,
    min_words: int,
    overwrite: bool,
    download_images: bool,
) -> _Result:
    html_path = article_dir / "body.html"
    md_path = article_dir / "body.md"

    if not html_path.exists():
        log.debug("No body.html in %s, skipping", article_dir.name)
        return "error"

    if md_path.exists() and not overwrite:
        return "exists"

    html = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    # Title: prefer <h1> text, fall back to folder name
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else article_dir.name

    # 1. Quick word count on raw text to skip low-content articles before downloading
    raw_text = soup.get_text(" ", strip=True)
    if _word_count(raw_text) < min_words:
        log.info("Skipping %-60s  (below threshold)", article_dir.name)
        return "skipped"

    # 2. Replace embedded file spans
    process_embedded_files(soup)

    # Count images found in the article regardless of whether they are downloaded
    image_count = len(soup.find_all("img"))

    # 3. Download / decode images
    process_images(soup, article_dir, session, download=download_images)

    # 4. Strip Odoo noise
    clean_soup(soup)

    # 5. Render to Markdown
    markdown = html_to_markdown(str(soup))

    # 6. Final word count on the rendered Markdown
    wc = _word_count(markdown)
    if wc < min_words:
        log.info("Skipping %-60s  %d words (below threshold)", article_dir.name, wc)
        return "skipped"

    # 6. Prepend metadata and write
    article_id = _article_id_from_folder(article_dir.name)
    frontmatter = build_frontmatter(title, article_id, article_dir.name, wc, image_count)
    md_path.write_text(frontmatter + "\n" + markdown, encoding="utf-8")

    log.info("OK  %-60s  %d words, %d images", article_dir.name, wc, image_count)
    return "ok"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--knowledge-dir", type=Path, default=DEFAULT_KNOWLEDGE_DIR,
        metavar="PATH",
        help="Path to knowledge export directory",
    )
    parser.add_argument(
        "--min-words", type=int, default=MIN_WORD_COUNT,
        metavar="N",
        help=f"Minimum word count to include an article (default: {MIN_WORD_COUNT})",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Re-process and overwrite existing body.md files",
    )
    parser.add_argument(
        "--no-images", action="store_true",
        help="Skip image download (articles are still converted to Markdown)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(message)s",
    )

    knowledge_dir: Path = args.knowledge_dir
    if not knowledge_dir.exists():
        log.error("Knowledge directory not found: %s", knowledge_dir)
        return

    article_dirs = sorted(d for d in knowledge_dir.iterdir() if d.is_dir())
    log.info("Found %d article directories in %s", len(article_dirs), knowledge_dir)

    if _md is None:
        log.warning(
            "markdownify is not installed — falling back to basic HTML stripping. "
            "Run: pip install markdownify"
        )

    session = requests.Session()
    session.headers["User-Agent"] = "EV-Hub-RAG-Processor/1.0"

    stats: dict[str, int] = {"ok": 0, "skipped": 0, "exists": 0, "error": 0}
    for article_dir in article_dirs:
        result = process_article(
            article_dir,
            session=session,
            min_words=args.min_words,
            overwrite=args.overwrite,
            download_images=not args.no_images,
        )
        stats[result] = stats.get(result, 0) + 1

    print(
        f"\nSummary: {stats['ok']} converted, "
        f"{stats['skipped']} skipped (too short), "
        f"{stats['exists']} already exist, "
        f"{stats['error']} errors"
    )


if __name__ == "__main__":
    main()
