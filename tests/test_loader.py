"""Tests for the Document loader: the format table and what load() returns."""

import shutil

import pytest

from rag import loader

TEXT_EXTENSIONS = sorted(ext for ext, fmt in loader.FORMATS.items() if fmt.reader == "text")


def test_every_format_has_a_known_reader_and_doc_type():
    for ext, fmt in loader.FORMATS.items():
        assert ext.startswith(".") and ext == ext.lower()
        assert fmt.reader in {"default", "pdf", "text", "unstructured"}
        assert fmt.doc_type and fmt.doc_type != "other"
        assert fmt.requires in {None, "tesseract", "soffice", "pandoc"}


def test_supported_extensions_follow_tool_availability(monkeypatch):
    monkeypatch.setattr(loader.shutil, "which", lambda name: None)
    without_tools = loader.supported_extensions()
    monkeypatch.setattr(loader.shutil, "which", lambda name: f"/usr/bin/{name}")
    with_tools = loader.supported_extensions()

    assert with_tools == frozenset(loader.FORMATS)
    assert without_tools == frozenset(ext for ext, fmt in loader.FORMATS.items() if fmt.requires is None)
    assert ".png" not in without_tools and ".doc" not in without_tools
    assert ".md" in without_tools and ".html" in without_tools


def test_files_needing_a_missing_tool_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(loader.shutil, "which", lambda name: None)
    (tmp_path / "keep.md").write_text("keep", encoding="utf-8")
    (tmp_path / "scan.png").write_bytes(b"not really a png")

    assert {d.metadata["source"] for d in loader.load(tmp_path)} == {"keep.md"}


@pytest.mark.parametrize("ext", TEXT_EXTENSIONS + [".md"])
def test_text_formats_yield_text(tmp_path, ext):
    (tmp_path / f"sample{ext}").write_text("hello incident responders", encoding="utf-8")

    docs = loader.load(tmp_path)

    assert docs
    assert "hello incident responders" in " ".join(d.text for d in docs)
    assert docs[0].metadata["doc_type"] == loader.FORMATS[ext].doc_type


def test_unsupported_and_hidden_files_are_skipped(tmp_path):
    (tmp_path / "keep.md").write_text("keep", encoding="utf-8")
    (tmp_path / "payload.exe").write_bytes(b"MZ")
    (tmp_path / ".secret.md").write_text("hidden", encoding="utf-8")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "x.md").write_text("hidden", encoding="utf-8")

    docs = loader.load(tmp_path)

    assert {d.metadata["source"] for d in docs} == {"keep.md"}


def test_empty_documents_are_dropped(tmp_path):
    (tmp_path / "blank.txt").write_text("   \n", encoding="utf-8")
    assert loader.load(tmp_path) == []


def test_metadata_uses_relative_posix_source(tmp_path):
    (tmp_path / "ir").mkdir()
    (tmp_path / "ir" / "phishing.md").write_text("reset credentials", encoding="utf-8")

    meta = loader.load(tmp_path)[0].metadata

    assert meta["source"] == "ir/phishing.md"
    assert meta["filename"] == "phishing.md"
    assert meta["incident_type"] == "phishing"


def test_docx_uses_default_reader(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Isolate the domain controller.")
    document.save(tmp_path / "containment.docx")

    docs = loader.load(tmp_path)

    assert "Isolate the domain controller." in docs[0].text
    assert docs[0].metadata["doc_type"] == "word"


def test_pptx_uses_default_reader(tmp_path):
    pptx = pytest.importorskip("pptx")
    deck = pptx.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "Tabletop exercise"
    deck.save(tmp_path / "tabletop.pptx")

    docs = loader.load(tmp_path)

    assert "Tabletop exercise" in " ".join(d.text for d in docs)
    assert docs[0].metadata["doc_type"] == "powerpoint"


CURVE_TABLE = [
    ["RADIUS", "40", "45", "50"],
    ["2860", "1.1", "1.1", "1.1"],
    ["1430", "1.2", "1.2", "--"],
    ["380", "1.5", "--", ""],
]


def _write_pdf(path, pages):
    """Write a PDF with one page per entry; an entry is a heading plus an optional ruled table."""
    pymupdf = pytest.importorskip("pymupdf")
    pdf = pymupdf.open()
    for heading, rows in pages:
        page = pdf.new_page()
        page.insert_text((72, 72), heading, fontsize=12)
        left, top, col_w, row_h = 72, 100, 80, 20
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                rect = pymupdf.Rect(left + c * col_w, top + r * row_h, left + (c + 1) * col_w, top + (r + 1) * row_h)
                page.draw_rect(rect, color=(0, 0, 0), width=0.8)
                if cell:
                    page.insert_text((rect.x0 + 4, rect.y1 - 6), cell, fontsize=10)
    pdf.save(path)


def _table_rows(markdown):
    rows = [line.strip() for line in markdown.splitlines() if line.strip().startswith("|")]
    # Drop only the outer pipes: a trailing empty cell renders as "||".
    return [[cell.strip() for cell in row[1:-1].split("|")] for row in rows if not set(row) <= set("|-: ")]


def test_pdf_tables_become_aligned_markdown_tables(tmp_path):
    _write_pdf(tmp_path / "manual.pdf", [("Table 3-2 Horizontal Curve Adjustments", CURVE_TABLE)])

    docs = loader.load(tmp_path)

    assert len(docs) == 1
    assert "Table 3-2 Horizontal Curve Adjustments" in docs[0].text
    assert _table_rows(docs[0].text) == CURVE_TABLE
    assert docs[0].metadata["doc_type"] == "pdf"
    assert docs[0].metadata["source"] == "manual.pdf"


def test_pdf_yields_one_document_per_page_with_page_label(tmp_path):
    _write_pdf(tmp_path / "manual.pdf", [("Chapter one intro", []), ("Chapter two table", CURVE_TABLE), ("Chapter three end", [])])

    docs = loader.load(tmp_path)

    assert [d.metadata["page_label"] for d in docs] == ["1", "2", "3"]
    assert "Chapter one intro" in docs[0].text
    assert "Chapter two table" in docs[1].text and _table_rows(docs[1].text) == CURVE_TABLE
    assert "Chapter three end" in docs[2].text
    assert all(d.metadata["file_name"] == "manual.pdf" for d in docs)


def test_pdf_reader_strips_inline_markup_and_accepts_legacy_page_key(tmp_path, monkeypatch):
    pymupdf4llm = pytest.importorskip("pymupdf4llm")
    chunks = [{"text": "<mark>Part 2</mark> �\n|Iowa|10 inches<br>(informal)|", "metadata": {"page": 7}}]
    monkeypatch.setattr(pymupdf4llm, "to_markdown", lambda *_args, **_kwargs: chunks)
    (tmp_path / "manual.pdf").write_bytes(b"%PDF-1.7")

    docs = loader.load(tmp_path)

    assert docs[0].text == "Part 2 \n|Iowa|10 inches (informal)|"
    assert docs[0].metadata["page_label"] == "7"


def test_html_uses_unstructured(tmp_path):
    (tmp_path / "runbook.html").write_text(
        "<html><body><h1>Runbook</h1><p>Rotate the TLS certificates quarterly.</p></body></html>",
        encoding="utf-8",
    )
    docs = loader.load(tmp_path)
    assert "Rotate the TLS certificates quarterly." in " ".join(d.text for d in docs)
    assert docs[0].metadata["doc_type"] == "html"


def test_eml_uses_unstructured(tmp_path):
    (tmp_path / "alert.eml").write_text(
        "From: soc@example.com\r\nTo: it@example.com\r\nSubject: Alert\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\nDisable the compromised account now.\r\n",
        encoding="utf-8",
        newline="",
    )
    docs = loader.load(tmp_path)
    assert "Disable the compromised account now." in " ".join(d.text for d in docs)
    assert docs[0].metadata["doc_type"] == "email"


def test_xlsx_uses_unstructured(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.active.append(["hostname", "owner"])
    book.active.append(["dc01", "infra-team"])
    book.save(tmp_path / "assets.xlsx")

    docs = loader.load(tmp_path)

    assert "infra-team" in " ".join(d.text for d in docs)
    assert docs[0].metadata["doc_type"] == "spreadsheet"


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed")
def test_image_ocr(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (600, 120), "white")
    ImageDraw.Draw(image).text((10, 30), "FIREWALL RULE 42", fill="black", font=ImageFont.load_default(size=40))
    image.save(tmp_path / "screenshot.png")

    docs = loader.load(tmp_path)

    assert "FIREWALL" in " ".join(d.text for d in docs).upper()


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")
def test_legacy_doc_via_libreoffice(tmp_path):
    docx = pytest.importorskip("docx")
    import subprocess

    document = docx.Document()
    document.add_paragraph("Legacy procedure text.")
    document.save(tmp_path / "src.docx")
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "doc", "--outdir", str(tmp_path / "out"), str(tmp_path / "src.docx")],
        check=True,
    )

    docs = loader.load(tmp_path / "out")

    assert "Legacy procedure text." in " ".join(d.text for d in docs)
