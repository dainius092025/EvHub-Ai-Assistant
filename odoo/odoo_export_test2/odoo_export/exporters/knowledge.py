import re
import logging
from .base import BaseExporter
from ..utils import safe_filename, strip_html, format_html

log = logging.getLogger(__name__)

ARTICLE_FIELDS = [
    "name", "body", "parent_id", "child_ids",
    "write_date", "create_date", "is_published",
    "tag_ids", "category_id", "sequence",
]

_DATE_TITLE_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$")


def _should_skip(title: str, body_text: str, child_ids: list) -> bool:
    t = title.strip()
    if t.lower().startswith("welcome"):
        return True
    if _DATE_TITLE_RE.match(t):
        return True
    # Skip if body is one line or less and no children
    lines = [l for l in body_text.splitlines() if l.strip()]
    if len(lines) <= 1 and not child_ids:
        return True
    return False


class KnowledgeBaseExporter(BaseExporter):
    """
    Exports knowledge base articles as formatted HTML.
    Each article gets a single body.html file; empty/personal articles are skipped.
    """

    def __init__(self, client, adapter, export_dir: str | Path = "odoo_knowledge_export", published_only: bool = False):
        super().__init__(client, adapter, export_dir)
        self.published_only = published_only

    def fetch(self) -> None:
        self.export_dir.mkdir(exist_ok=True)
        log.info("Fetching Knowledge Base articles...")

        domain = [("parent_id", "=", False)]
        if self.published_only:
            domain.append(("is_published", "=", True))

        fields = self.client.valid_fields("knowledge.article", ARTICLE_FIELDS)
        articles = self.client.execute(
            "knowledge.article", "search_read",
            domain=domain,
            fields=fields,
        )

        if not articles:
            log.info("No articles found.")
            return

        log.info(f"Found {len(articles)} root articles.")
        for article in articles:
            self._export_article(article, depth=0)

        log.info(f"Knowledge base export complete → {self.export_dir}")

    def _export_article(self, article: dict, depth: int) -> None:
        article_id = article["id"]
        title = article.get("name") or f"Article_{article_id}"
        indent = "  " * depth

        raw_html = article.get("body") or ""
        body_text = strip_html(raw_html)
        child_ids = article.get("child_ids") or []

        if _should_skip(title, body_text, child_ids):
            log.info(f"{indent}Skipping {title!r} — filtered")
            # Still recurse into children
            if child_ids:
                self._fetch_children(child_ids, depth)
            return

        article_dir = self.export_dir / f"{article_id}_{safe_filename(title)}"
        if article_dir.exists():
            log.debug(f"{indent}Skipping {title} — already exported")
            return

        log.info(f"{indent}Processing: {title} (ID: {article_id})")
        article_dir.mkdir(exist_ok=True)

        formatted = format_html(raw_html) if raw_html else ""
        (article_dir / "body.html").write_text(formatted, encoding="utf-8")

        if child_ids:
            self._fetch_children(child_ids, depth)

    def _fetch_children(self, child_ids: list, depth: int) -> None:
        fields = self.client.valid_fields("knowledge.article", ARTICLE_FIELDS)
        children = self.client.execute(
            "knowledge.article", "read",
            ids=child_ids,
            fields=fields,
        )
        for child in children:
            self._export_article(child, depth=depth + 1)
