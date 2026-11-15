"""Every supported file type, read from a real file built in the test."""
import datetime
import json
import shutil
import zipfile

import pytest

from app.services.chunking import split_markdown
from app.services.extractors import ParseError, extract, sniff_problem


def _text(pages):
    return "\n\n".join(p["content"] for p in pages)


def _table_chunks(pages):
    return [c for p in pages for c in split_markdown(p["content"], 1000, 200) if c.kind == "table"]


def test_pdf_tables_keep_headers_across_pages(tmp_path):
    pytest.importorskip("reportlab")
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    rows = [["Region", "Revenue", "Growth"]] + [[f"Region {i}", str(1000 + i), f"{i % 7}%"] for i in range(1, 80)]
    table = Table(rows)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    path = tmp_path / "report.pdf"
    SimpleDocTemplate(str(path)).build([Paragraph("Sales report for the year.", getSampleStyleSheet()["Normal"]), table])

    pages = extract(str(path), "report.pdf")
    assert len(pages) >= 2 and pages[0]["page_number"] == 1
    assert "Sales report for the year." in pages[0]["content"]
    assert "| Region 1 | 1001 | 1% |" in pages[0]["content"]
    # The table continues on page 2 and gets its header back there.
    assert pages[1]["content"].startswith("| Region | Revenue | Growth |")
    assert all(c.text.startswith("| Region | Revenue | Growth |") for c in _table_chunks(pages))


def test_pdf_password_and_fake_pdf(tmp_path):
    pytest.importorskip("reportlab")
    from reportlab.pdfgen import canvas

    locked = tmp_path / "locked.pdf"
    c = canvas.Canvas(str(locked), encrypt="secret")
    c.drawString(100, 750, "hidden")
    c.save()
    with pytest.raises(ParseError, match="password-protected"):
        extract(str(locked), "locked.pdf")

    fake = tmp_path / "fake.pdf"
    fake.write_text("not a pdf")
    with pytest.raises(ParseError, match="not a valid PDF"):
        extract(str(fake), "fake.pdf")


def test_docx_headings_lists_tables_and_pages(tmp_path):
    import docx

    d = docx.Document()
    d.add_heading("Handbook", 0)
    d.add_heading("Leave", 1)
    d.add_paragraph("Staff get 24 days.")
    d.add_paragraph("Carry over 5 days", style="List Bullet")
    t = d.add_table(rows=3, cols=2)
    for r, vals in enumerate([["Grade", "Days"], ["A", "24"], ["B | senior", "28"]]):
        for c, v in enumerate(vals):
            t.cell(r, c).text = v
    d.add_page_break()
    d.add_heading("Benefits", 1)
    d.add_paragraph("Health cover from day one.")
    path = tmp_path / "h.docx"
    d.save(path)

    pages = extract(str(path), "h.docx")
    text = _text(pages)
    assert "# Handbook" in text and "# Leave" in text and "- Carry over 5 days" in text
    assert "| Grade | Days |" in text and "| B \\| senior | 28 |" in text   # pipes escaped, table intact
    assert [p["page_number"] for p in pages] == [1, 2]                     # explicit page break
    assert "Health cover" in pages[1]["content"]
    assert len(_table_chunks(pages)) == 1


def test_old_doc_renamed_to_docx_is_explained(tmp_path):
    path = tmp_path / "old.docx"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600)
    assert "older Office file" in sniff_problem(str(path), ".docx")
    with pytest.raises(ParseError):
        extract(str(path), "old.docx")
    with pytest.raises(ParseError, match="save it as .docx"):
        extract(str(path), "old.doc")


def test_pptx_slides_tables_charts_and_notes(tmp_path):
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[5])
    s1.shapes.title.text = "Pricing"
    tbl = s1.shapes.add_table(3, 2, Inches(1), Inches(2), Inches(6), Inches(1.5)).table
    for r, vals in enumerate([["Plan", "Price"], ["Basic", "$5"], ["Pro", "$20"]]):
        for c, v in enumerate(vals):
            tbl.cell(r, c).text = v
    s1.notes_slide.notes_text_frame.text = "Mention the discount."
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Signups"
    data = CategoryChartData()
    data.categories = ["Jan", "Feb"]
    data.add_series("Users", (120, 150))
    s2.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(2), Inches(6), Inches(4), data)
    path = tmp_path / "d.pptx"
    prs.save(path)

    pages = extract(str(path), "d.pptx")
    assert [p["page_number"] for p in pages] == [1, 2]
    assert pages[0]["content"].startswith("## Slide 1: Pricing")
    assert "| Pro | $20 |" in pages[0]["content"] and "Speaker notes: Mention the discount." in pages[0]["content"]
    assert "| Category | Users |" in pages[1]["content"] and "| Feb | 150 |" in pages[1]["content"]


def test_xlsx_sheets_blocks_formats_and_row_cap(tmp_path, monkeypatch):
    import openpyxl
    from app.core.config import settings

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Metric", "Value"])
    ws.append(["Churn", 0.042])
    ws["B2"].number_format = "0.0%"
    ws.append(["Start", datetime.date(2026, 1, 1)])
    ws.append([])
    ws.append([])
    ws.append(["Product", "Units"])
    ws.append(["Widget", 10.0])
    orders = wb.create_sheet("Orders")
    orders.append(["Order", "Amount"])
    for i in range(1, 301):
        orders.append([f"ORD-{i}", i * 1.5])
    path = tmp_path / "x.xlsx"
    wb.save(path)

    monkeypatch.setattr(settings, "TABLE_MAX_ROWS", 101)
    pages = extract(str(path), "x.xlsx")
    assert [p["metadata"]["sheet"] for p in pages] == ["Summary", "Orders"]
    summary = pages[0]["content"]
    assert "| Churn | 4.2% |" in summary and "| Start | 2026-01-01 |" in summary
    assert "| Product | Units |" in summary and "| Widget | 10 |" in summary   # second table, own header
    assert "## Sheet: Orders" in pages[1]["content"]
    assert "| ORD-100 | 150 |" in pages[1]["content"] and "ORD-101" not in pages[1]["content"]
    assert "Only the first 101 of 301 rows" in pages[1]["content"]


def test_xls(tmp_path):
    xlwt = pytest.importorskip("xlwt")
    book = xlwt.Workbook()
    sh = book.add_sheet("Old")
    for r, vals in enumerate([["Name", "Score"], ["Ann", 91]]):
        for c, v in enumerate(vals):
            sh.write(r, c, v)
    path = tmp_path / "o.xls"
    book.save(str(path))
    assert "| Ann | 91 |" in _text(extract(str(path), "o.xls"))


def test_csv_encoding_and_delimiter_detection(tmp_path):
    path = tmp_path / "eu.csv"
    path.write_bytes("Name;City;Amount\nJosé;Málaga;1.200\nZoë;Köln;950\n".encode("latin-1"))
    text = _text(extract(str(path), "eu.csv"))
    assert "| Name | City | Amount |" in text and "| José | Málaga | 1.200 |" in text

    tsv = tmp_path / "t.tsv"
    tsv.write_text("id\tvalue\n1\talpha\n")
    assert "| 1 | alpha |" in _text(extract(str(tsv), "t.tsv"))


def test_big_csv_splits_into_table_chunks_with_header(tmp_path):
    path = tmp_path / "big.csv"
    path.write_text("id,name,amount\n" + "\n".join(f"{i},n{i},{i * 2}" for i in range(3000)))
    chunks = _table_chunks(extract(str(path), "big.csv"))
    assert len(chunks) > 5
    assert all(c.text.startswith("| id | name | amount |") for c in chunks)


def test_json_records_become_a_table_and_other_json_stays_readable(tmp_path):
    rec = tmp_path / "s.json"
    rec.write_text(json.dumps({"items": [{"sku": "A1", "stock": 5}, {"sku": "B2", "stock": 0}]}))
    assert "| sku | stock |" in _text(extract(str(rec), "s.json"))
    nested = tmp_path / "n.json"
    nested.write_text(json.dumps({"config": {"retries": 3}}))
    assert '"retries": 3' in _text(extract(str(nested), "n.json"))


def test_html_tables(tmp_path):
    path = tmp_path / "p.html"
    path.write_text("<html><head><title>Rates</title></head><body><h1>Rates</h1><table>"
                    "<tr><th>Term</th><th>Rate</th></tr><tr><td>1 year</td><td>4.1%</td></tr>"
                    "<tr><td colspan='2'>Fixed</td></tr></table><script>x()</script></body></html>")
    text = _text(extract(str(path), "p.html"))
    assert "# Rates" in text and "| 1 year | 4.1% |" in text and "| Fixed | Fixed |" in text and "x()" not in text


def test_rtf_eml_markdown_epub(tmp_path):
    rtf = tmp_path / "m.rtf"
    rtf.write_text(r"{\rtf1\ansi{\fonttbl\f0 Helvetica;}\f0\pard Meeting moved to Friday.\par}")
    assert "Meeting moved to Friday." in _text(extract(str(rtf), "m.rtf"))

    eml = tmp_path / "m.eml"
    eml.write_text("Subject: Renewal\nFrom: a@example.com\nContent-Type: text/plain\n\nRenews on 1 March.\n")
    text = _text(extract(str(eml), "m.eml"))
    assert "Subject: Renewal" in text and "Renews on 1 March." in text

    md = tmp_path / "n.md"
    md.write_text("# Notes\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert len(_table_chunks(extract(str(md), "n.md"))) == 1

    epub = tmp_path / "b.epub"
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/c.opf"/></rootfiles></container>')
        z.writestr("OEBPS/c.opf", '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
                   '<item id="a" href="2.xhtml"/><item id="b" href="1.xhtml"/></manifest>'
                   '<spine><itemref idref="b"/><itemref idref="a"/></spine></package>')
        z.writestr("OEBPS/1.xhtml", "<html><body><h1>One</h1><p>Dawn.</p></body></html>")
        z.writestr("OEBPS/2.xhtml", "<html><body><h1>Two</h1><p>Noon.</p></body></html>")
    pages = extract(str(epub), "b.epub")
    assert [p["content"].splitlines()[0] for p in pages] == ["# One", "# Two"]   # spine order


def test_opendocument_spreadsheet(tmp_path):
    ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"')
    row = lambda *cells: "<table:table-row>" + "".join(f"<table:table-cell><text:p>{c}</text:p></table:table-cell>" for c in cells) + "</table:table-row>"  # noqa: E731
    xml = (f'<office:document-content {ns}><office:body><office:spreadsheet><table:table table:name="Stock">'
           + row("Item", "Qty") + row("Bolt", "40")
           + '<table:table-row table:number-rows-repeated="3"><table:table-cell/></table:table-row>'
           + row("Owner", "Site") + row("Ana", "Pune")
           + "</table:table></office:spreadsheet></office:body></office:document-content>")
    path = tmp_path / "s.ods"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", xml)
    text = _text(extract(str(path), "s.ods"))
    assert "## Sheet: Stock" in text and "| Bolt | 40 |" in text
    assert "| Owner | Site |" in text   # separate table, own header


def test_empty_and_unsupported(tmp_path):
    empty = tmp_path / "e.txt"
    empty.write_text("")
    with pytest.raises(ParseError, match="empty"):
        extract(str(empty), "e.txt")
    blank = tmp_path / "b.txt"
    blank.write_text("   \n\n ")
    with pytest.raises(ParseError, match="No text"):
        extract(str(blank), "b.txt")
    with pytest.raises(ParseError, match="Unsupported"):
        extract(str(blank), "b.exe")


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
def test_ocr_image(tmp_path):
    pytest.importorskip("pytesseract")
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1600, 400), "white")
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 64)
    except OSError:
        font = ImageFont.load_default(size=64)
    ImageDraw.Draw(img).text((60, 150), "Invoice total 2350", fill="black", font=font)
    path = tmp_path / "scan.png"
    img.save(path)
    assert "2350" in _text(extract(str(path), "scan.png"))
