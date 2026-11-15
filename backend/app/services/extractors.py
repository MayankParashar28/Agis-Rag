"""Local text extraction for every supported file type.

Each extractor returns a list of pages, ``{"content": str, "page_number":
int, "metadata": {...}}``, with headings as Markdown headings and tables as
Markdown tables. The chunker keeps those tables whole (or splits them between
rows, repeating the header), so answers can quote a row and its column names.

What a "page" means depends on the format: a PDF page, a slide, a spreadsheet
sheet, or the page Word last laid the text out on.

Everything here is blocking and CPU-bound; call it through ``extract()``,
which the parser runs in a worker thread so the server keeps answering.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import zipfile
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.core.logging import logger
from app.services.tables import cell_text, md_table, split_blocks

Page = Dict[str, Any]


class ParseError(Exception):
    """A reason, written for the user, that a file could not be read."""


# Extensions the upload accepts, grouped by reader.
TEXT_EXTS = {".txt", ".md", ".markdown", ".rst", ".log", ".xml", ".yaml", ".yml", ".tex", ".ini", ".cfg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
SUPPORTED_EXTS = sorted(
    {".pdf", ".docx", ".pptx", ".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".json", ".html", ".htm",
     ".rtf", ".odt", ".ods", ".odp", ".epub", ".eml"} | TEXT_EXTS | IMAGE_EXTS
)
LEGACY_HINTS = {
    ".doc": "Older Word .doc files are not supported. Open it in Word and save it as .docx, then upload that.",
    ".ppt": "Older PowerPoint .ppt files are not supported. Save it as .pptx and upload that.",
    ".pages": "Apple Pages files are not supported. Export it as .docx or PDF.",
    ".numbers": "Apple Numbers files are not supported. Export it as .xlsx or CSV.",
    ".key": "Keynote files are not supported. Export it as .pptx or PDF.",
}


def _page(content: str, n: int, filename: str, **meta) -> Page:
    return {"content": content, "page_number": n,
            "metadata": {"filename": filename, "page": n, "source": filename, **meta}}


def _max_rows() -> int:
    return max(100, int(getattr(settings, "TABLE_MAX_ROWS", 20000)))


def _rows_note(shown: int, total: int) -> str:
    return f"\n\n_(Only the first {shown:,} of {total:,} rows were indexed.)_" if total > shown else ""


# ---------------------------------------------------------------------------
# File signatures: catch a renamed or corrupt file before parsing it.
# ---------------------------------------------------------------------------
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MEMBERS = {".docx": "word/document.xml", ".pptx": "ppt/presentation.xml",
                ".xlsx": "xl/workbook.xml", ".xlsm": "xl/workbook.xml"}


def sniff_problem(path: str, ext: str) -> Optional[str]:
    """Return a user-facing reason the file is not what its extension says,
    or None if it looks fine."""
    try:
        with open(path, "rb") as f:
            head = f.read(2048)
    except OSError:
        return "The file could not be read."
    if not head:
        return "The file is empty."
    if ext == ".pdf":
        return None if b"%PDF" in head[:1024] else "This file is not a valid PDF (it may be renamed or damaged)."
    if ext in _ZIP_MEMBERS:
        if head.startswith(_OLE):
            # Office stores both password-protected files and the old binary
            # formats in this container.
            return (f"This file is password-protected, or it is an older Office file renamed to {ext}. "
                    f"Remove the password, or open it and save it as {ext}, then upload again.")
        try:
            with zipfile.ZipFile(path) as z:
                if _ZIP_MEMBERS[ext] not in z.namelist():
                    return f"This file is not a valid {ext} document (it may be renamed or damaged)."
                if "EncryptedPackage" in z.namelist():
                    return "This file is password-protected. Remove the password and upload again."
        except zipfile.BadZipFile:
            return f"This file is not a valid {ext} document (it may be renamed or damaged)."
        return None
    if ext in (".odt", ".ods", ".odp", ".epub") and not zipfile.is_zipfile(path):
        return f"This file is not a valid {ext} document (it may be renamed or damaged)."
    if ext == ".xls" and not head.startswith(_OLE) and not head.lstrip().startswith(b"<"):
        return "This file is not a valid Excel .xls file (it may be renamed or damaged)."
    return None


# ---------------------------------------------------------------------------
# Text decoding
# ---------------------------------------------------------------------------
def read_text(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read()
    return decode_bytes(raw)


def decode_bytes(raw: bytes) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # Mostly-ASCII text with a few accented letters is almost always Windows
    # Western (Excel's CSV export). Detectors guess wildly on such files, so
    # settle it first; CJK and Cyrillic text has far more high bytes.
    sample = raw[:1_000_000]
    high = sum(1 for b in sample if b >= 0x80)
    if high / max(len(sample), 1) < 0.15:
        try:
            return raw.decode("cp1252")
        except UnicodeDecodeError:
            pass
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw[:2_000_000]).best()
        if best and best.encoding:
            return raw.decode(best.encoding, errors="replace")
    except Exception:
        pass
    return raw.decode("latin-1", errors="replace")


# ---------------------------------------------------------------------------
# OCR (scanned PDFs and images). Needs the tesseract binary + pytesseract.
# ---------------------------------------------------------------------------
def ocr_available() -> bool:
    if not getattr(settings, "OCR_ENABLED", True) or not shutil.which("tesseract"):
        return False
    try:
        import pytesseract  # noqa: F401
        return True
    except ImportError:
        return False


def _ocr_image(img) -> str:
    import pytesseract
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    # Upscale small images: tesseract wants roughly 300 dpi text.
    if max(img.size) < 1500:
        scale = 1500 / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    try:
        return pytesseract.image_to_string(img, lang=getattr(settings, "OCR_LANG", "eng"), timeout=120) or ""
    except RuntimeError as e:  # tesseract timeout
        logger.warning(f"OCR timed out on one page: {e}")
        return ""


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _norm_row(row) -> List[str]:
    return [cell_text(c) for c in (row or [])]


def _pdf_page_markdown(page, carry: Optional[List[str]] = None) -> Tuple[str, int, Optional[List[str]]]:
    """Text and tables of one pdfplumber page, in reading order.

    `carry` is the header row of the table that ended the previous page. When
    this page opens with a table of the same width and no header of its own,
    that table is a continuation and gets the header back, so its rows keep
    their column names. Returns (markdown, table count, header to carry on).
    """
    tables = []
    raw = []
    try:
        found = sorted(page.find_tables(), key=lambda t: t.bbox[1])
        for t in found:
            data = [r for r in (t.extract() or []) if any(c for c in (r or []))]
            if len(data) >= 2 and max((len(r) for r in data), default=0) >= 2:
                raw.append((t.bbox, data))
    except Exception as e:
        logger.debug(f"PDF table detection failed on page {page.page_number}: {e}")
        raw = []

    try:
        first_text_top = min((float(w["top"]) for w in page.extract_words()[:200]), default=None)
    except Exception:
        first_text_top = None
    next_carry: Optional[List[str]] = None
    for i, (bbox, data) in enumerate(raw):
        header = _norm_row(data[0])
        at_top = first_text_top is None or bbox[1] <= first_text_top + 2
        if (i == 0 and carry and at_top and len(header) == len(carry) and header != carry
                and not all(h and not re.search(r"\d", h) for h in header)):
            data = [carry] + data
            header = carry
        rendered = md_table(data)
        if rendered:
            tables.append((bbox, rendered))
            next_carry = header

    rest = page
    for bbox, _ in tables:
        try:
            rest = rest.outside_bbox(bbox, strict=False)
        except Exception:
            pass
    items: List[Tuple[float, str]] = [(bbox[1], "\n" + md + "\n") for bbox, md in tables]
    try:
        lines = rest.extract_text_lines(return_chars=False, strip=True)
    except Exception:
        lines = []
    prev_bottom, prev_height = None, None
    for ln in lines:
        text = (ln.get("text") or "").strip()
        if not text:
            continue
        top, bottom = float(ln.get("top", 0)), float(ln.get("bottom", 0))
        height = max(bottom - top, 1.0)
        # A gap bigger than a line height starts a new paragraph.
        if prev_bottom is not None and top - prev_bottom > 0.9 * (prev_height or height):
            text = "\n" + text
        items.append((top, text))
        prev_bottom, prev_height = bottom, height
    items.sort(key=lambda x: x[0])
    # Only a table that ends the page can continue on the next one.
    if tables and items and items[-1][1].strip() != tables[-1][1].strip():
        next_carry = None
    return "\n".join(t for _, t in items).strip(), len(tables), next_carry


def extract_pdf(path: str, filename: str) -> List[Page]:
    pages: List[Page] = []
    try:
        import pdfplumber
        from pdfminer.pdfdocument import PDFPasswordIncorrect
    except ImportError:
        pdfplumber = None
    if pdfplumber is not None:
        try:
            with pdfplumber.open(path) as pdf:
                carry = None
                for i, page in enumerate(pdf.pages, start=1):
                    try:
                        text, n_tables, carry = _pdf_page_markdown(page, carry)
                    except Exception as e:
                        logger.warning(f"{filename} page {i}: layout read failed ({e}); using plain text.")
                        text, n_tables, carry = (page.extract_text() or ""), 0, None
                    pages.append(_page(text, i, filename, tables=n_tables))
                    page.close()  # frees the page's parsed objects; big PDFs otherwise hold them all
        except PDFPasswordIncorrect:
            raise ParseError("This PDF is password-protected. Remove the password and upload again.")
        except ParseError:
            raise
        except Exception as e:
            logger.warning(f"pdfplumber could not read {filename} ({e}); falling back to pypdf.")
            pages = []
    if not pages:
        pages = _extract_pdf_pypdf(path, filename)

    _ocr_blank_pdf_pages(path, filename, pages)
    return pages


def _extract_pdf_pypdf(path: str, filename: str) -> List[Page]:
    import pypdf
    try:
        reader = pypdf.PdfReader(path)
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    raise ParseError("This PDF is password-protected. Remove the password and upload again.")
            except ParseError:
                raise
            except Exception:
                raise ParseError("This PDF is password-protected. Remove the password and upload again.")
        out = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            out.append(_page(text, i, filename))
        return out
    except ParseError:
        raise
    except Exception as e:
        raise ParseError(f"This PDF could not be read; it may be damaged ({type(e).__name__}).")


def _ocr_blank_pdf_pages(path: str, filename: str, pages: List[Page]) -> None:
    """Scanned pages have no text layer: read them with OCR, in place."""
    blank = [p for p in pages if len((p["content"] or "").strip()) < 20]
    if not blank:
        return
    if not ocr_available():
        logger.warning(f"{filename}: {len(blank)} page(s) have no text layer and OCR is not installed.")
        return
    limit = int(getattr(settings, "OCR_MAX_PAGES", 200))
    try:
        import pypdfium2 as pdfium
    except ImportError:
        logger.warning("pypdfium2 is missing; cannot OCR scanned PDF pages.")
        return
    pdf = pdfium.PdfDocument(path)
    try:
        for p in blank[:limit]:
            idx = p["page_number"] - 1
            try:
                img = pdf[idx].render(scale=300 / 72).to_pil()
                text = _ocr_image(img).strip()
            except Exception as e:
                logger.warning(f"{filename} page {idx + 1}: OCR failed ({e}).")
                continue
            if text:
                p["content"] = text
                p["metadata"]["ocr"] = True
    finally:
        pdf.close()
    if len(blank) > limit:
        logger.warning(f"{filename}: OCR limited to the first {limit} of {len(blank)} scanned pages.")


# ---------------------------------------------------------------------------
# Word (.docx)
# ---------------------------------------------------------------------------
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_table(table) -> str:
    rows = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            text = " ".join(p.text for p in cell.paragraphs)
            for nested in cell.tables:  # flatten nested tables into the cell
                text += " " + " ; ".join(" ".join(c.text for c in r.cells) for r in nested.rows)
            cells.append(text)
        rows.append(cells)
    return md_table(rows)


def _docx_paragraph(p) -> str:
    text = p.text.strip()
    if not text:
        return ""
    style = (p.style.name if p.style is not None else "") or ""
    m = re.match(r"Heading (\d)", style)
    if m:
        return "#" * min(int(m.group(1)), 6) + " " + text
    if style == "Title":
        return "# " + text
    if style.startswith("List") or p._p.find(f"{_W}pPr/{_W}numPr") is not None:
        return "- " + text
    return text


def extract_docx(path: str, filename: str) -> List[Page]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    try:
        document = docx.Document(path)
    except Exception as e:
        raise ParseError(f"This Word document could not be opened; it may be damaged ({type(e).__name__}).")

    body = document.element.body
    # Word records where it last broke pages; use them for page numbers when
    # present, otherwise explicit page breaks.
    rendered = bool(body.findall(f".//{_W}lastRenderedPageBreak"))
    page_breaks = f"{_W}lastRenderedPageBreak" if rendered else f"{_W}br"

    def breaks_in(el) -> int:
        if rendered:
            return len(el.findall(f".//{page_breaks}"))
        return sum(1 for br in el.iter(page_breaks) if br.get(f"{_W}type") == "page")

    def walk(parent) -> Iterable:
        for child in parent.iterchildren():
            if child.tag == f"{_W}p":
                yield Paragraph(child, document)
            elif child.tag == f"{_W}tbl":
                yield Table(child, document)
            elif child.tag == f"{_W}sdt":  # content controls wrap ordinary content
                content = child.find(f"{_W}sdtContent")
                if content is not None:
                    yield from walk(content)

    pages: Dict[int, List[str]] = {}
    page_no = 1
    for block in walk(body):
        if isinstance(block, Table):
            text = _docx_table(block)
            if text:
                pages.setdefault(page_no, []).append("\n" + text + "\n")
            page_no += breaks_in(block._tbl)
        else:
            text = _docx_paragraph(block)
            if text:
                pages.setdefault(page_no, []).append(text)
            page_no += breaks_in(block._p)

    out = [_page("\n\n".join(parts), n, filename) for n, parts in sorted(pages.items())]
    return out


# ---------------------------------------------------------------------------
# PowerPoint (.pptx)
# ---------------------------------------------------------------------------
def extract_pptx(path: str, filename: str) -> List[Page]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    try:
        prs = Presentation(path)
    except Exception as e:
        raise ParseError(f"This PowerPoint file could not be opened; it may be damaged ({type(e).__name__}).")

    def shape_parts(shapes) -> List[str]:
        parts: List[str] = []
        ordered = sorted(shapes, key=lambda s: ((s.top or 0), (s.left or 0)))
        for shape in ordered:
            try:
                if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                    parts += shape_parts(shape.shapes)
                elif getattr(shape, "has_table", False) and shape.has_table:
                    rows = [[c.text for c in r.cells] for r in shape.table.rows]
                    t = md_table(rows)
                    if t:
                        parts.append("\n" + t + "\n")
                elif getattr(shape, "has_chart", False) and shape.has_chart:
                    parts.append(_pptx_chart(shape.chart))
                elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        text = (para.text or "").strip()
                        if text:
                            parts.append(("  " * para.level + "- " + text) if para.level else text)
            except Exception as e:
                logger.debug(f"{filename}: skipped a shape ({e})")
        return [p for p in parts if p]

    out: List[Page] = []
    for i, slide in enumerate(prs.slides, start=1):
        title = ""
        try:
            if slide.shapes.title is not None:
                title = slide.shapes.title.text.strip()
        except Exception:
            pass
        parts = [f"## Slide {i}" + (f": {title}" if title else "")]
        parts += [p for p in shape_parts(slide.shapes) if p.strip() != title]
        try:
            if slide.has_notes_slide:
                notes = slide.notes_slide.notes_text_frame.text.strip()
                if notes:
                    parts.append("Speaker notes: " + notes)
        except Exception:
            pass
        if len(parts) > 1 or title:
            out.append(_page("\n\n".join(parts), i, filename))
    return out


def _pptx_chart(chart) -> str:
    """A chart's data as a table: categories down, series across."""
    try:
        plot = chart.plots[0]
        cats = [cell_text(c) for c in plot.categories]
        series = list(plot.series)
        rows = [["Category"] + [s.name or f"Series {i + 1}" for i, s in enumerate(series)]]
        values = [list(s.values) for s in series]
        for r, cat in enumerate(cats):
            rows.append([cat] + [v[r] if r < len(v) else "" for v in values])
        title = chart.chart_title.text_frame.text if chart.has_title else "Chart"
        t = md_table(rows)
        return f"Chart: {title}\n\n{t}" if t else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Spreadsheets
# ---------------------------------------------------------------------------
def _sheet_markdown(name: str, rows: Iterable[Sequence[Any]], total_rows: Optional[int] = None) -> str:
    limit = _max_rows()
    kept: List[List[Any]] = []
    seen = 0
    for r in rows:
        seen += 1
        if len(kept) < limit:
            kept.append(list(r))
    parts = [f"## Sheet: {name}"]
    for block in split_blocks(kept):
        t = md_table(block)
        if t:
            parts.append(t)
    if len(parts) == 1:
        return ""
    return "\n\n".join(parts) + _rows_note(min(seen, limit), total_rows or seen)


def extract_xlsx(path: str, filename: str) -> List[Page]:
    import openpyxl
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        raise ParseError(f"This Excel file could not be opened; it may be damaged or password-protected ({type(e).__name__}).")
    out: List[Page] = []
    try:
        for i, ws in enumerate(wb.worksheets, start=1):
            if getattr(ws, "sheet_state", "visible") == "veryHidden":
                continue

            def rows(ws=ws):
                for row in ws.iter_rows():
                    yield [cell_text(c.value, getattr(c, "number_format", None)) for c in row]

            text = _sheet_markdown(ws.title, rows())
            if text:
                out.append(_page(text, i, filename, sheet=ws.title))
    finally:
        wb.close()
    return out


def extract_xls(path: str, filename: str) -> List[Page]:
    try:
        import xlrd
    except ImportError:
        raise ParseError("Older Excel .xls files need the xlrd package on the server. Save it as .xlsx and upload again.")
    try:
        book = xlrd.open_workbook(path, on_demand=True)
    except Exception as e:
        raise ParseError(f"This Excel .xls file could not be opened ({type(e).__name__}). Save it as .xlsx and try again.")
    out: List[Page] = []
    try:
        for i in range(book.nsheets):
            sh = book.sheet_by_index(i)

            def rows(sh=sh):
                for r in range(sh.nrows):
                    vals = []
                    for c in sh.row(r):
                        if c.ctype == xlrd.XL_CELL_DATE:
                            try:
                                vals.append(xlrd.xldate_as_datetime(c.value, book.datemode))
                                continue
                            except Exception:
                                pass
                        vals.append(None if c.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK) else c.value)
                    yield vals

            text = _sheet_markdown(sh.name, rows(), sh.nrows)
            if text:
                out.append(_page(text, i + 1, filename, sheet=sh.name))
    finally:
        book.release_resources()
    return out


def extract_delimited(path: str, filename: str, ext: str) -> List[Page]:
    text = read_text(path)
    sample = text[:65536]
    delimiter = "\t" if ext == ".tsv" else ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        pass
    csv.field_size_limit(10 * 1024 * 1024)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        body = _sheet_markdown(os.path.splitext(filename)[0], reader)
    except csv.Error as e:
        raise ParseError(f"This file is not valid CSV ({e}).")
    return [_page(body, 1, filename)] if body else []


# ---------------------------------------------------------------------------
# JSON, HTML, plain text, RTF, e-mail
# ---------------------------------------------------------------------------
def extract_json(path: str, filename: str) -> List[Page]:
    raw = read_text(path)
    try:
        data = json.loads(raw)
    except ValueError:
        # JSON Lines: one object per line.
        try:
            data = [json.loads(line) for line in raw.splitlines() if line.strip()]
        except ValueError:
            return [_page(raw, 1, filename)]
    # Records (a list of flat objects, or {"key": [records]}) read best as a table.
    records = data
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list) and v and all(isinstance(x, dict) for x in v)]
        records = lists[0] if len(lists) == 1 else None
    if isinstance(records, list) and records and all(isinstance(x, dict) for x in records):
        keys: List[str] = []
        for rec in records[:1000]:
            for k in rec:
                if k not in keys:
                    keys.append(k)
        flat = all(not isinstance(rec.get(k), (dict, list)) for rec in records[:200] for k in keys)
        if flat and len(keys) <= 60:
            rows = [keys] + [[rec.get(k) for k in keys] for rec in records]
            body = _sheet_markdown(os.path.splitext(filename)[0], rows)
            if body:
                return [_page(body, 1, filename)]
    return [_page(json.dumps(data, indent=2, ensure_ascii=False, default=str), 1, filename)]


def extract_html(path: str, filename: str) -> List[Page]:
    from app.services.url_import import html_to_text
    title, text = html_to_text(read_text(path), skip_chrome=False)
    return [_page((f"# {title}\n\n" if title and title not in text[:200] else "") + text, 1, filename)]


def extract_rtf(path: str, filename: str) -> List[Page]:
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError:
        raise ParseError("RTF files need the striprtf package on the server. Save it as .docx and upload again.")
    return [_page(rtf_to_text(read_text(path), errors="ignore"), 1, filename)]


def extract_eml(path: str, filename: str) -> List[Page]:
    from email import policy
    from email.parser import BytesParser
    with open(path, "rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)
    head = [f"{h}: {msg[h]}" for h in ("Subject", "From", "To", "Cc", "Date") if msg[h]]
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        content = body_part.get_content()
        if body_part.get_content_subtype() == "html":
            from app.services.url_import import html_to_text
            content = html_to_text(content, skip_chrome=False)[1]
        body = content
    attachments = [a.get_filename() for a in msg.iter_attachments() if a.get_filename()]
    text = "\n".join(head) + "\n\n" + body
    if attachments:
        text += "\n\nAttachments (not indexed): " + ", ".join(attachments)
    return [_page(text, 1, filename)]


def extract_image(path: str, filename: str) -> List[Page]:
    if not ocr_available():
        raise ParseError("Reading text from images needs OCR, which is not installed on this server. "
                         "Upload a PDF or Word version instead.")
    from PIL import Image, ImageSequence
    out: List[Page] = []
    try:
        with Image.open(path) as im:
            for i, frame in enumerate(ImageSequence.Iterator(im), start=1):
                if i > int(getattr(settings, "OCR_MAX_PAGES", 200)):
                    break
                text = _ocr_image(frame.copy()).strip()
                if text:
                    out.append(_page(text, i, filename, ocr=True))
                if filename.lower().endswith(".gif"):
                    break  # animated GIF frames repeat the same text
    except ParseError:
        raise
    except Exception as e:
        raise ParseError(f"This image could not be opened ({type(e).__name__}).")
    return out


# ---------------------------------------------------------------------------
# OpenDocument (.odt, .ods, .odp) and EPUB, read straight from their XML
# ---------------------------------------------------------------------------
_ODF = {
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
}


def _odf_text(el) -> str:
    """All text inside an element, honouring <text:s/>, tabs and line breaks."""
    out = [el.text or ""]
    for child in el:
        tag = child.tag.split("}")[-1]
        if tag == "s":
            out.append(" " * int(child.get(f"{{{_ODF['text']}}}c", "1") or 1))
        elif tag in ("tab", "line-break"):
            out.append(" ")
        else:
            out.append(_odf_text(child))
        out.append(child.tail or "")
    return "".join(out)


def _odf_rows(tbl) -> List[List[str]]:
    T = _ODF["table"]
    rows: List[List[str]] = []
    for row in tbl.iter(f"{{{T}}}table-row"):
        rep_rows = min(int(row.get(f"{{{T}}}number-rows-repeated", "1") or 1), 50)
        cells: List[str] = []
        for cell in row:
            if cell.tag not in (f"{{{T}}}table-cell", f"{{{T}}}covered-table-cell"):
                continue
            text = " ".join(_odf_text(p) for p in cell if p.tag.endswith("}p") or p.tag.endswith("}h")).strip()
            reps = int(cell.get(f"{{{T}}}number-columns-repeated", "1") or 1)
            cells.extend([text] * (min(reps, 50) if text else min(reps, 1)))
        # Blank rows are kept (a few) so split_blocks can tell tables apart.
        rows.extend([cells] * (rep_rows if any(cells) else min(rep_rows, 2)))
        if len(rows) > _max_rows():
            break
    return rows


def _odf_table(tbl) -> str:
    return md_table(_odf_rows(tbl))


def extract_odf(path: str, filename: str, ext: str) -> List[Page]:
    from xml.etree import ElementTree as ET
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("content.xml"))
    except (KeyError, zipfile.BadZipFile, ET.ParseError):
        raise ParseError(f"This {ext} file could not be read; it may be damaged.")
    O, T, D, X = _ODF["office"], _ODF["table"], _ODF["draw"], _ODF["text"]
    body = root.find(f"{{{O}}}body")
    if body is None:
        return []
    out: List[Page] = []

    def blocks(parent) -> List[str]:
        parts: List[str] = []
        for el in parent:
            tag = el.tag
            if tag == f"{{{X}}}h":
                level = int(el.get(f"{{{X}}}outline-level", "1") or 1)
                t = _odf_text(el).strip()
                if t:
                    parts.append("#" * min(level, 6) + " " + t)
            elif tag == f"{{{X}}}p":
                t = _odf_text(el).strip()
                if t:
                    parts.append(t)
            elif tag == f"{{{X}}}list":
                for item in el.iter(f"{{{X}}}p"):
                    t = _odf_text(item).strip()
                    if t:
                        parts.append("- " + t)
            elif tag == f"{{{T}}}table":
                t = _odf_table(el)
                if t:
                    name = el.get(f"{{{T}}}name")
                    parts.append((f"## Sheet: {name}\n\n" if ext == ".ods" and name else "") + t)
            elif tag in (f"{{{X}}}section", f"{{{D}}}frame", f"{{{D}}}text-box", f"{{{D}}}custom-shape"):
                parts += blocks(el)
        return parts

    for kind in body:
        if ext == ".odp":
            for i, page in enumerate(kind.iter(f"{{{D}}}page"), start=1):
                name = page.get(f"{{{D}}}name") or ""
                parts = blocks(page)
                if parts:
                    out.append(_page(f"## Slide {i}" + (f": {name}" if name and not name.startswith("page") else "") +
                                     "\n\n" + "\n\n".join(parts), i, filename))
        elif ext == ".ods":
            for i, tbl in enumerate(kind.iter(f"{{{T}}}table"), start=1):
                name = tbl.get(f"{{{T}}}name") or f"Sheet {i}"
                t = _sheet_markdown(name, _odf_rows(tbl))
                if t:
                    out.append(_page(t, i, filename, sheet=name))
        else:
            parts = blocks(kind)
            if parts:
                out.append(_page("\n\n".join(parts), 1, filename))
    return out


def extract_epub(path: str, filename: str) -> List[Page]:
    from xml.etree import ElementTree as ET
    from app.services.url_import import html_to_text
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ParseError("This EPUB file could not be read; it may be damaged.")
    with z:
        names = z.namelist()
        order: List[str] = []
        try:
            container = ET.fromstring(z.read("META-INF/container.xml"))
            opf_path = next(el.get("full-path") for el in container.iter() if el.tag.endswith("rootfile"))
            opf = ET.fromstring(z.read(opf_path))
            base = os.path.dirname(opf_path)
            manifest = {el.get("id"): el.get("href") for el in opf.iter() if el.tag.endswith("}item")}
            for ref in (el for el in opf.iter() if el.tag.endswith("}itemref")):
                href = manifest.get(ref.get("idref"))
                if href:
                    order.append(os.path.normpath(os.path.join(base, href)).replace("\\", "/"))
        except Exception:
            order = sorted(n for n in names if n.lower().endswith((".xhtml", ".html", ".htm")))
        out: List[Page] = []
        for item in order:
            if item not in names:
                continue
            title, text = html_to_text(decode_bytes(z.read(item)), skip_chrome=False)
            if text.strip():
                out.append(_page(text, len(out) + 1, filename, chapter=title or item))
        return out


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def _text_file(path: str, filename: str) -> List[Page]:
    return [_page(read_text(path), 1, filename)]


_EXTRACTORS: Dict[str, Callable[[str, str], List[Page]]] = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".pptx": extract_pptx,
    ".xlsx": extract_xlsx,
    ".xlsm": extract_xlsx,
    ".xls": extract_xls,
    ".csv": lambda p, f: extract_delimited(p, f, ".csv"),
    ".tsv": lambda p, f: extract_delimited(p, f, ".tsv"),
    ".json": extract_json,
    ".html": extract_html,
    ".htm": extract_html,
    ".rtf": extract_rtf,
    ".eml": extract_eml,
    ".odt": lambda p, f: extract_odf(p, f, ".odt"),
    ".ods": lambda p, f: extract_odf(p, f, ".ods"),
    ".odp": lambda p, f: extract_odf(p, f, ".odp"),
    ".epub": extract_epub,
    **{e: _text_file for e in TEXT_EXTS},
    **{e: extract_image for e in IMAGE_EXTS},
}


def extract(path: str, filename: str, ext: Optional[str] = None) -> List[Page]:
    """Read any supported file into pages. Raises ParseError with a message
    meant for the user when the file cannot be read or holds no text."""
    ext = (ext or os.path.splitext(filename)[1]).lower()
    if ext in LEGACY_HINTS:
        raise ParseError(LEGACY_HINTS[ext])
    fn = _EXTRACTORS.get(ext)
    if fn is None:
        raise ParseError(f"Unsupported file type '{ext or 'none'}'. Supported: {', '.join(SUPPORTED_EXTS)}.")
    problem = sniff_problem(path, ext)
    if problem:
        raise ParseError(problem)
    pages = fn(path, filename)
    pages = [p for p in pages if (p.get("content") or "").strip()]
    if not pages:
        if ext == ".pdf" or ext in IMAGE_EXTS:
            hint = ("It looks like a scanned document. " +
                    ("OCR found no readable text." if ocr_available()
                     else "OCR is not installed on this server, so scanned pages cannot be read."))
        else:
            hint = "The file appears to be empty."
        raise ParseError(f"No text could be read from this file. {hint}")
    return pages
