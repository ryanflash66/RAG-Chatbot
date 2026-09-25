"""Tests for the Document loader: the format table and what load() returns."""

import pytest

from rag import loader

TEXT_EXTENSIONS = sorted(ext for ext, fmt in loader.FORMATS.items() if fmt.reader == "text")


def test_every_format_has_a_known_reader_and_doc_type():
    for ext, fmt in loader.FORMATS.items():
        assert ext.startswith(".") and ext == ext.lower()
        assert fmt.reader in {"default", "text", "unstructured"}
        assert fmt.doc_type and fmt.doc_type != "other"


def test_ingest_allowlist_is_the_format_table():
    import api

    assert api.SUPPORTED_EXTENSIONS == loader.supported_extensions() == frozenset(loader.FORMATS)


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
