"""Tests for the Document loader: the format table and what load() returns."""

import shutil

import pytest

from rag import loader

TEXT_EXTENSIONS = sorted(ext for ext, fmt in loader.FORMATS.items() if fmt.reader == "text")


def test_every_format_has_a_known_reader_and_doc_type():
    for ext, fmt in loader.FORMATS.items():
        assert ext.startswith(".") and ext == ext.lower()
        assert fmt.reader in {"default", "text", "unstructured"}
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
