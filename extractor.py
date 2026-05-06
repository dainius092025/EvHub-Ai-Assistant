"""
extractor.py — Stage 2: Faithful lossless raw content capture
Reads shared_profile.json written by detector.py.
Writes raw/{start}_{end}.json and images/*.png

Responsibilities (only these):
  - Open PDF once per run
  - Extract all text with bbox (Docling)
  - Extract all tables with raw grid (Docling + TableFormer)
  - Extract all images saved as PNG (pymupdf)
  - Resolve page references per page (footer → header → full scan → sequential)
  - Detect scanned pages per page (not per batch)
  - Stamp document_id from shared_profile on every batch file
  - Update shared_profile.json completion status

Does NOT:
  - Filter any content
  - Interpret element meaning
  - Make semantic decisions
  - Write shared_profile identity fields (detector owns those)
"""

from __future__ import annotations
import gc, json, logging, re, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
from docling.datamodel.base_models import InputFormat
from docling.datamodel.document import TableItem, TextItem
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

try:
    from docling.backend.docling_parse_v2 import DoclingParseV2DocumentBackend
    _BACKEND: Any = DoclingParseV2DocumentBackend
except ImportError:
    _BACKEND = None

import config

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("extractor")

_PAGE_RE    = re.compile(config.NISSAN_PAGE_REF_PATTERN)
_BATCH_RE   = re.compile(r"^\d+_\d+\.json$")


# ── Config dataclass — values come from config.py defaults ───────────────────

@dataclass
class Config:
    batch_size:            int   = config.BATCH_SIZE
    page_render_dpi:       int   = config.PAGE_RENDER_DPI
    min_img_size_px:       int   = config.MIN_IMAGE_SIZE_PX
    footer_height_pct:     float = config.FOOTER_HEIGHT_PCT
    header_height_pct:     float = config.HEADER_HEIGHT_PCT
    ocr_threshold_per_page: int  = config.OCR_THRESHOLD_CHARS


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_region(page: fitz.Page, y_start_pct: float, y_end_pct: float) -> str:
    h      = page.rect.height
    region = fitz.Rect(0, h * y_start_pct, page.rect.width, h * y_end_pct)
    return page.get_text("text", clip=region).strip()


def _load_profile(out: Path) -> dict:
    path = out / "shared_profile.json"
    if not path.exists():
        log.warning("shared_profile.json not found — detector.py should run first")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_profile(profile: dict, out: Path) -> None:
    path = out / "shared_profile.json"
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Page reference resolution ─────────────────────────────────────────────────

def _resolve_page_ref(
    page: fitz.Page, cfg: Config, page_no: int
) -> tuple[str | None, str | None, str, float]:
    """
    Multi-strategy page reference resolution.
    Returns: (page_manual, section_code, source_location, confidence)
    All patterns from config — no magic strings here.
    """
    # Strategy 1 — footer
    text = _read_region(page, 1 - cfg.footer_height_pct, 1.0)
    m    = _PAGE_RE.search(text)
    if m:
        ref = m.group(1)
        return ref, ref.split("-")[0], "footer", 0.97

    # Strategy 2 — header
    text = _read_region(page, 0.0, cfg.header_height_pct)
    m    = _PAGE_RE.search(text)
    if m:
        ref = m.group(1)
        return ref, ref.split("-")[0], "header", 0.85

    # Strategy 3 — full page scan
    text = page.get_text("text") or ""
    m    = _PAGE_RE.search(text)
    if m:
        ref = m.group(1)
        return ref, ref.split("-")[0], "full_page_scan", 0.60

    # Strategy 4 — sequential fallback
    return None, None, "sequential_fallback", 0.0


# ── Docling converter ─────────────────────────────────────────────────────────

def _make_converter(*, ocr: bool) -> DocumentConverter:
    opts = PdfPipelineOptions()
    opts.do_ocr                  = ocr
    opts.do_table_structure      = True
    opts.generate_page_images    = False
    opts.generate_picture_images = False
    kw: dict[str, Any] = {"pipeline_options": opts}
    if _BACKEND:
        kw["backend"] = _BACKEND
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(**kw)})


# ── Image extraction ──────────────────────────────────────────────────────────

def _extract_images(
    doc: fitz.Document,
    page: fitz.Page,
    page_no: int,
    page_manual: str | None,
    section_code: str | None,
    image_dir: Path,
    cfg: Config,
) -> list[dict]:
    """
    Extract all images from a single page.
    Raster: extracted natively, converted to PNG.
    Vector: rendered as PNG via clip rect.
    Both types saved as PNG — format_saved is always "png".
    Images smaller than min_img_size_px discarded.
    """
    image_dir.mkdir(parents=True, exist_ok=True)
    images:     list[dict]      = []
    seen_rects: list[fitz.Rect] = []
    mat = fitz.Matrix(cfg.page_render_dpi / 72, cfg.page_render_dpi / 72)

    # ── Raster ────────────────────────────────────────────────────────────────
    for idx, img in enumerate(page.get_images(full=True)):
        xref = img[0]
        try:
            extracted = doc.extract_image(xref)
        except Exception:
            continue

        w, h = extracted["width"], extracted["height"]
        if w < cfg.min_img_size_px or h < cfg.min_img_size_px:
            continue

        fname = f"page_{page_no:03d}_raster_{idx + 1:02d}.png"
        fpath = image_dir / fname
        if not fpath.exists():
            try:
                pix = fitz.Pixmap(extracted["image"])
                if pix.colorspace and pix.colorspace.name not in ("DeviceRGB", "DeviceGray"):
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                pix.save(str(fpath))
            except Exception as exc:
                log.warning("  page %d raster_%d save failed: %s", page_no, idx + 1, exc)
                continue

        bbox       = None
        bbox_found = False
        for info in page.get_image_info(xrefs=True):
            if info.get("xref") == xref:
                r          = fitz.Rect(info["bbox"])
                bbox       = [r.x0, r.y0, r.x1, r.y1]
                bbox_found = True
                seen_rects.append(r)
                break

        if not bbox_found:
            log.warning("  page %d raster_%d bbox not found", page_no, idx + 1)

        images.append({
            "image_id":               str(uuid.uuid4()),
            "file":                   f"images/{fname}",
            "format_original":        extracted.get("ext", "unknown"),
            "format_saved":           "png",
            "page_pdf":               page_no,
            "page_manual":            page_manual,
            "section_code":           section_code,
            "bbox":                   bbox,
            "bbox_coordinate_system": "pymupdf",
            "bbox_resolved":          bbox_found,
            "width_px":               w,
            "height_px":              h,
            "type":                   "raster",
            "caption_raw":            "",
            "image_ref_code":         None,
        })

    # ── Vector ────────────────────────────────────────────────────────────────
    vec_idx = 0
    for block in page.get_text("dict", flags=fitz.TEXT_PRESERVE_IMAGES).get("blocks", []):
        if block.get("type") != 1:
            continue
        r = fitz.Rect(block["bbox"])
        if r.width < cfg.min_img_size_px or r.height < cfg.min_img_size_px:
            continue
        if any(r.intersects(s) for s in seen_rects):
            continue

        vec_idx += 1
        fname = f"page_{page_no:03d}_vector_{vec_idx:02d}.png"
        fpath = image_dir / fname
        if not fpath.exists():
            try:
                page.get_pixmap(matrix=mat, clip=r).save(str(fpath))
            except Exception as exc:
                log.warning("  page %d vector_%d render failed: %s", page_no, vec_idx, exc)
                continue

        seen_rects.append(r)
        images.append({
            "image_id":               str(uuid.uuid4()),
            "file":                   f"images/{fname}",
            "format_original":        "vector",
            "format_saved":           "png",
            "page_pdf":               page_no,
            "page_manual":            page_manual,
            "section_code":           section_code,
            "bbox":                   [r.x0, r.y0, r.x1, r.y1],
            "bbox_coordinate_system": "pymupdf",
            "bbox_resolved":          True,
            "width_px":               int(r.width),
            "height_px":              int(r.height),
            "type":                   "vector",
            "caption_raw":            "",
            "image_ref_code":         None,
        })

    return images


# ── Text and table extraction from Docling ────────────────────────────────────

def _docling_bbox(prov) -> list | None:
    b = getattr(prov[0], "bbox", None) if prov else None
    return [b.l, b.t, b.r, b.b] if b else None


def _docling_page(prov) -> int | None:
    return getattr(prov[0], "page_no", None) if prov else None


def _extract_text_tables(result, page_map: dict[int, dict]) -> tuple[list, list]:
    """
    Extract text elements and tables from Docling result.
    Stamps every element with page references from page_map.
    Labels bbox coordinate system explicitly.
    No filtering or interpretation here.
    """
    texts:  list[dict] = []
    tables: list[dict] = []

    for item, _ in result.document.iterate_items():
        prov = getattr(item, "prov", [])
        pg   = _docling_page(prov)
        info = page_map.get(pg, {})

        manual = info.get("page_manual")
        code   = info.get("section_code")

        if isinstance(item, TextItem):
            texts.append({
                "element_id":             str(uuid.uuid4()),
                "text":                   item.text or "",
                "page_pdf":               pg,
                "page_manual":            manual,
                "section_code":           code,
                "label":                  item.label.value if item.label else None,
                "bbox":                   _docling_bbox(prov),
                "bbox_coordinate_system": "docling",
                "font_name":              None,
                "font_size":              None,
                "is_bold":                None,
                "is_italic":              None,
                "reading_order":          None,
                "docling_label":          item.label.value if item.label else None,
            })

        elif isinstance(item, TableItem):
            grid = [
                [c.text if c else "" for c in row]
                for row in (item.data.grid if item.data else [])
            ]
            tables.append({
                "table_id":               str(uuid.uuid4()),
                "page_pdf":               pg,
                "page_manual":            manual,
                "section_code":           code,
                "bbox":                   _docling_bbox(prov),
                "bbox_coordinate_system": "docling",
                "num_rows":               len(grid),
                "num_cols":               len(grid[0]) if grid else 0,
                "tableformer_used":       item.data is not None and len(grid) > 0,
                "continues_on_next_page": False,
                "continued_from_prev":    False,
                "data_raw":               grid,
                "markdown_raw":           item.export_to_markdown() if grid else "",
            })

    return texts, tables


# ── Per-page scanned detection ────────────────────────────────────────────────

def _is_scanned(doc: fitz.Document, page_no: int, threshold: int) -> bool:
    """Check single page using pymupdf — much faster than Docling."""
    page = doc[page_no - 1]
    return len((page.get_text("text") or "").strip()) < threshold


# ── Batch processing ──────────────────────────────────────────────────────────

def _process_batch(
    pdf:      Path,
    doc:      fitz.Document,
    s:        int,
    e:        int,
    out:      Path,
    conv_std: DocumentConverter,
    conv_ocr: DocumentConverter | None,
    cfg:      Config,
    profile:  dict,
) -> bool:
    try:
        image_dir = out / "images"
        images:   list[dict]      = []
        page_map: dict[int, dict] = {}

        # pymupdf pass — page refs and images
        for page_no in range(s, e + 1):
            page = doc[page_no - 1]

            manual, code, ref_src, ref_conf = _resolve_page_ref(page, cfg, page_no)

            footer_raw = _read_region(page, 1 - cfg.footer_height_pct, 1.0)
            header_raw = _read_region(page, 0.0, cfg.header_height_pct)

            page_map[page_no] = {
                "page_pdf":               page_no,
                "page_manual":            manual,
                "page_manual_confidence": ref_conf,
                "page_manual_source":     ref_src,
                "section_code":           code,
                "is_scanned":             _is_scanned(doc, page_no, cfg.ocr_threshold_per_page),
                "rotation_degrees":       page.rotation,
                "width_pts":              page.rect.width,
                "height_pts":             page.rect.height,
                "footer_text_raw":        footer_raw,
                "header_text_raw":        header_raw,
            }

            if manual:
                log.info("  page %d → %s (via %s %.2f)", page_no, manual, ref_src, ref_conf)
            else:
                log.warning("  page %d → no ref (sequential fallback)", page_no)

            images.extend(
                _extract_images(doc, page, page_no, manual, code, image_dir, cfg)
            )

        # Docling pass — use OCR if any page in batch is scanned
        any_scanned = any(page_map[pg]["is_scanned"] for pg in range(s, e + 1))
        ran_ocr     = False

        log.info("Docling pages %d-%d (OCR=%s)", s, e, any_scanned)

        if any_scanned and conv_ocr is not None:
            res     = conv_ocr.convert(str(pdf), page_range=(s, e))
            ran_ocr = True
        else:
            res = conv_std.convert(str(pdf), page_range=(s, e))

        texts, tables = _extract_text_tables(res, page_map)
        gc.collect()

        # Write batch JSON
        doc_id    = profile.get("document_id")
        vehicle   = profile.get("vehicle", {})
        section   = profile.get("section", {})

        batch_out = {
            "schema_version": "2.0",
            "schema_type":    "raw_batch",
            "document_id":    doc_id,
            "manufacturer":   vehicle.get("make"),
            "model":          vehicle.get("model"),
            "year":           vehicle.get("year"),
            "section_code":   section.get("code"),
            "batch": {
                "page_start_pdf":    s,
                "page_end_pdf":      e,
                "ocr_used":          ran_ocr,
                "tableformer_used":  True,
                "extracted_at":      _now(),
                "extraction_errors": [],
            },
            "page_map":      {str(pg): info for pg, info in page_map.items()},
            "text_elements": texts,
            "tables":        tables,
            "images":        images,
        }

        batch_path = out / f"{s}_{e}.json"
        batch_path.write_text(
            json.dumps(batch_out, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        log.info("  → text=%d tables=%d images=%d ocr=%s",
                 len(texts), len(tables), len(images), ran_ocr)
        gc.collect()
        return True

    except Exception:
        log.exception("Batch %d-%d failed", s, e)
        profile.setdefault("processing", {}).setdefault("errors", []).append({
            "batch": f"{s}_{e}",
            "error": "extraction_failed",
            "at":    _now(),
        })
        return False


# ── Entry point ───────────────────────────────────────────────────────────────

def run(
    pdf_path:   str | Path,
    output_dir: str | Path = "raw",
    cfg:        Config | None = None,
) -> bool:
    cfg = cfg or Config()
    pdf = Path(pdf_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not pdf.exists():
        log.error("PDF not found: %s", pdf)
        return False

    profile = _load_profile(out)
    doc     = fitz.open(str(pdf))
    total   = doc.page_count
    log.info("%s — %d pages | document_id=%s", pdf.name, total, profile.get("document_id"))

    # Load converters — OCR only if profile says needed
    needs_ocr = profile.get("pdf_profile", {}).get("needs_ocr", True)
    conv_std  = _make_converter(ocr=False)
    conv_ocr  = _make_converter(ocr=True) if needs_ocr else None
    if not needs_ocr:
        log.info("OCR converter skipped (profile: digital)")

    batches = [
        (s, min(s + cfg.batch_size - 1, total))
        for s in range(1, total + 1, cfg.batch_size)
    ]
    pending = [(s, e) for s, e in batches if not (out / f"{s}_{e}.json").exists()]
    if len(pending) < len(batches):
        log.info("Resuming — skipping %d completed batches", len(batches) - len(pending))

    success = all(
        _process_batch(pdf, doc, s, e, out, conv_std, conv_ocr, cfg, profile)
        for s, e in pending
    )

    doc.close()

    # Update shared_profile completion status
    profile.setdefault("processing", {})["procedure_extraction_completed"] = success
    _save_profile(profile, out)

    log.info("Extraction %s", "complete" if success else "completed with errors")
    return success


if __name__ == "__main__":
    run(pdf_path="PDF/ha.pdf", output_dir="raw")