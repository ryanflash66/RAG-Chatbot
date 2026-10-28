"""Tests for the script that downloads each division's PDFs, and for SOURCES.md (no network)."""

import importlib.util
import sys
from pathlib import Path

import pytest

HOSTED = Path(__file__).resolve().parent.parent / "hosted"
sys.path.insert(0, str(HOSTED))

_spec = importlib.util.spec_from_file_location("fetch_documents", HOSTED / "scripts" / "fetch_documents.py")
fetch_documents = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_documents)

from divrag.divisions import BY_ID, DIVISIONS, DOCUMENTS_DIR, Division, Document  # noqa: E402
from divrag.index_file import IndexFile  # noqa: E402

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nbody"
DOC = Document(file="Guide.pdf", title="A Guide", url="https://connect.ncdot.gov/Guide.pdf")
DIV = Division(id="demo", name="Demo", unit="Demo Unit", documents=(DOC,))

SOURCES = """# Source documents

Intro text with a | pipe that is not a table.

## Demo (`demo`)

| File | Title | Source URL | Pages | Fetched |
|---|---|---|---|---|
| `Guide.pdf` | A Guide | <https://connect.ncdot.gov/Guide.pdf> | 12 | 2026-10-27 |

## Notes

| File | Title | Source URL | Pages | Fetched |
|---|---|---|---|---|
| `Other.pdf` | Not a division's | <https://example.com/x.pdf> | 1 | 2026-01-01 |
"""


def _writer(content):
    calls = []

    def download(url, dest):
        calls.append(url)
        dest.write_bytes(content)
    return download, calls


def test_fetch_saves_a_pdf_under_its_name(tmp_path):
    download, calls = _writer(PDF)
    dest = tmp_path / "demo" / "Guide.pdf"

    assert fetch_documents.fetch(DOC.url, dest, download) is True
    assert dest.read_bytes() == PDF and calls == [DOC.url]
    assert not dest.with_name("Guide.pdf.part").exists()


def test_fetch_skips_a_pdf_that_is_already_there(tmp_path):
    dest = tmp_path / "Guide.pdf"
    dest.write_bytes(PDF)
    download, calls = _writer(PDF)

    assert fetch_documents.fetch(DOC.url, dest, download) is False
    assert calls == []


def test_force_downloads_again_and_a_failure_keeps_the_old_copy(tmp_path):
    dest = tmp_path / "Guide.pdf"
    dest.write_bytes(PDF)
    new_edition, _ = _writer(b"%PDF-1.7 new edition")
    sign_in_page, _ = _writer(b"<html>Sign in</html>")

    assert fetch_documents.fetch(DOC.url, dest, new_edition, force=True) is True
    assert dest.read_bytes() == b"%PDF-1.7 new edition"
    with pytest.raises(fetch_documents.FetchError):
        fetch_documents.fetch(DOC.url, dest, sign_in_page, force=True)
    assert dest.read_bytes() == b"%PDF-1.7 new edition"


def test_fetch_replaces_a_file_that_is_not_a_pdf(tmp_path):
    dest = tmp_path / "Guide.pdf"
    dest.write_bytes(b"<html>half a download</html>")
    download, calls = _writer(PDF)

    assert fetch_documents.fetch(DOC.url, dest, download) is True
    assert dest.read_bytes() == PDF


def test_a_page_that_is_not_a_pdf_is_an_error_and_leaves_nothing_behind(tmp_path):
    # SharePoint answers a moved or protected file with a 200 sign-in page.
    download, _ = _writer(b"<!DOCTYPE html><title>Sign in</title>")
    dest = tmp_path / "Guide.pdf"

    with pytest.raises(fetch_documents.FetchError, match="not return a PDF"):
        fetch_documents.fetch(DOC.url, dest, download)
    assert list(tmp_path.iterdir()) == []


def test_a_failed_download_is_an_error_with_the_reason(tmp_path):
    def download(url, dest):
        dest.write_bytes(b"%PDF-partial")
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(fetch_documents.FetchError, match="404"):
        fetch_documents.fetch(DOC.url, tmp_path / "Guide.pdf", download)
    assert list(tmp_path.iterdir()) == []


def test_main_reports_each_failed_url_and_keeps_going(tmp_path, monkeypatch, capsys):
    good = Document(file="Good.pdf", title="Good", url="https://connect.ncdot.gov/good.pdf")
    bad = Document(file="Bad.pdf", title="Bad", url="https://connect.ncdot.gov/bad.pdf")
    division = Division(id="demo", name="Demo", unit="Demo Unit", documents=(bad, good))
    monkeypatch.setattr(fetch_documents, "BY_ID", {"demo": division})
    monkeypatch.setattr(fetch_documents, "DIVISIONS", (division,))
    monkeypatch.setattr(fetch_documents, "SOURCES_FILE", tmp_path / "missing.md")

    def download(url, dest):
        if url == bad.url:
            raise OSError("HTTP Error 404: Not Found")
        dest.write_bytes(PDF)
    monkeypatch.setattr(fetch_documents, "_download", download)

    assert fetch_documents.main(["--dest", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "FAILED demo/Bad.pdf: download failed: HTTP Error 404" in out and bad.url in out
    assert "fetched demo/Good.pdf" in out
    assert (tmp_path / "demo" / "Good.pdf").read_bytes() == PDF


def test_documents_are_saved_in_their_divisions_folder():
    assert fetch_documents.targets([DIV], Path("root")) == [(DIV, DOC, Path("root") / "demo" / "Guide.pdf")]
    assert all(path.parent == DOCUMENTS_DIR / d.id for d, _, path in fetch_documents.targets(DIVISIONS))


def test_sources_rows_are_read_per_division_and_other_tables_are_ignored():
    rows = fetch_documents.parse_sources(SOURCES)

    assert rows == [fetch_documents.SourceRow("demo", "Guide.pdf", "A Guide", "https://connect.ncdot.gov/Guide.pdf",
                                              "12", "2026-10-27")]
    assert fetch_documents.check_sources(rows, [DIV]) == []


def test_check_sources_names_every_disagreement():
    rows = fetch_documents.parse_sources(SOURCES.replace("A Guide", "Old title").replace("| 12 |", "| ? |"))
    extra = fetch_documents.SourceRow("demo", "Gone.pdf", "Gone", "https://connect.ncdot.gov/gone.pdf", "3", "2026-01-01")
    added = Document(file="New.pdf", title="New", url="https://connect.ncdot.gov/new.pdf")
    division = Division(id="demo", name="Demo", unit="Demo Unit", documents=(DOC, added))

    problems = fetch_documents.check_sources(rows + [extra], [division])

    assert any("title 'Old title'" in p for p in problems)
    assert any("page count '?'" in p for p in problems)
    assert any("Gone.pdf is in SOURCES.md but not in divisions.py" in p for p in problems)
    missing = [p for p in problems if p.startswith("missing row for demo/New.pdf")]
    assert missing and "| `New.pdf` | New | <https://connect.ncdot.gov/new.pdf> | ? |" in missing[0]


def test_a_pasted_row_reads_back_as_the_same_document():
    row = fetch_documents.source_row(DIV, DOC, pages="12", fetched="2026-10-27")
    text = f"## Demo (`demo`)\n\n| File | Title | Source URL | Pages | Fetched |\n|---|---|---|---|---|\n{row}\n"

    assert fetch_documents.check_sources(fetch_documents.parse_sources(text), [DIV]) == []


def test_committed_sources_md_lists_exactly_the_documents_in_divisions_py():
    rows = fetch_documents.parse_sources(fetch_documents.SOURCES_FILE.read_text(encoding="utf-8"))

    assert fetch_documents.check_sources(rows) == []


def test_sources_md_page_counts_cover_every_page_in_the_index():
    rows = {r.file: int(r.pages) for r in fetch_documents.parse_sources(fetch_documents.SOURCES_FILE.read_text(encoding="utf-8"))}
    index = IndexFile.load(HOSTED / "index")

    for chunk in index.chunks:
        assert (chunk["page"] or 0) <= rows[chunk["source"]], chunk["source"]


def test_document_file_names_are_unique_across_divisions():
    # A chunk's `source` is its file name, and divisions.document_for looks a document up by it.
    files = [doc.file for d in DIVISIONS for doc in d.documents]
    assert len(files) == len(set(files))
    assert all(doc.url.startswith("https://") for d in DIVISIONS for doc in d.documents)
    assert set(BY_ID) == {d.id for d in DIVISIONS}
