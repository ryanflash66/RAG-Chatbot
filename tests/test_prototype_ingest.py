"""Tests for the offline index build (prototype.ingest): section tagging, and where it reads documents."""

import pytest

from prototype.ingest import build_division, chunk_sections, document_root, section_headings, text_warning  # noqa: E501  (puts hosted/ on sys.path)
from divrag.divisions import Division, Document  # noqa: I001
from rag.config import load_config

_OWN = Document(file="own.md", title="Own", url="https://connect.ncdot.gov/own.pdf")
_OLD = Document(file="old.md", title="Old", url="https://connect.ncdot.gov/old.pdf")
_DIVISION = Division(id="demo", name="Demo", unit="Demo Unit", documents=(_OWN, _OLD))


def test_numbered_section_and_appendix_headings_are_found():
    text = "\n".join([
        "**Utilities Accommodation Manual**",
        "## **3.6.4.1 Lane and Road Closures**",
        "# Figure 5-2b Example design chart",
        "##### 11.3 Policies ",
        "#### **Appendix B. Figures**",
    ])
    assert section_headings(text) == ["3.6.4.1 Lane and Road Closures", "11.3 Policies", "Appendix B. Figures"]


def test_each_chunk_gets_the_section_in_effect_plus_those_starting_inside_it():
    chunks = [
        "intro\n# 1.1 One\nbody",
        "more of one",
        "# 1.2 Two\nbody",
        "end of two\n# 1.3 Three\nbody",
        "no headings at all",
    ]
    assert chunk_sections(chunks) == ["1.1 One", "1.1 One", "1.2 Two", "1.2 Two; 1.3 Three", "1.3 Three"]


def test_text_before_the_first_heading_has_no_section():
    assert chunk_sections(["cover page", "# 1.1 One\nx"]) == [None, "1.1 One"]


@pytest.fixture
def folders(tmp_path):
    documents, data = tmp_path / "documents", tmp_path / "data"
    (documents / "demo").mkdir(parents=True)
    data.mkdir()
    return documents, data, load_config({"DATA_DIR": str(data)})


def test_a_document_is_read_from_its_divisions_folder_first(folders):
    documents, data, config = folders
    (documents / "demo" / "own.md").write_text("# 1.1 Own\nnew copy", encoding="utf-8")
    (data / "own.md").write_text("# 1.1 Own\nold copy", encoding="utf-8")

    assert document_root(config, _DIVISION, _OWN, documents) == documents / "demo"


def test_a_document_only_in_data_dir_is_still_found(folders):
    documents, data, config = folders
    (data / "old.md").write_text("# 1.1 Old\nbody", encoding="utf-8")

    assert document_root(config, _DIVISION, _OLD, documents) == data
    assert document_root(config, _DIVISION, _OWN, documents) is None


def test_another_divisions_folder_is_not_searched(folders):
    documents, _, config = folders
    (documents / "other").mkdir()
    (documents / "other" / "own.md").write_text("# 1.1 Own\nbody", encoding="utf-8")

    assert document_root(config, _DIVISION, _OWN, documents) is None


def test_chunks_from_both_folders_name_their_source_by_file_name(folders):
    documents, data, config = folders
    (documents / "demo" / "own.md").write_text("# 1.1 Own\nThe own rule.", encoding="utf-8")
    (data / "old.md").write_text("# 2.1 Old\nThe old rule.", encoding="utf-8")
    (data / "unlisted.md").write_text("# 9.9 Unlisted\nNot this division's.", encoding="utf-8")

    chunks = build_division(config, _DIVISION, 512, 64, documents)

    assert sorted(c["source"] for c in chunks) == ["old.md", "own.md"]
    assert {c["division"] for c in chunks} == {"demo"}


def test_the_build_records_each_documents_chunks_and_time_in_division_order(folders):
    documents, data, config = folders
    (documents / "demo" / "own.md").write_text("# 1.1 Own\nThe own rule.", encoding="utf-8")
    (data / "old.md").write_text("# 2.1 Old\nThe old rule.", encoding="utf-8")
    stats = []

    chunks = build_division(config, _DIVISION, 512, 64, documents, stats=stats)

    assert [c["source"] for c in chunks] == ["own.md", "old.md"]
    assert [(s["source"], s["chunks"]) for s in stats] == [("own.md", 1), ("old.md", 1)]
    assert all(s["division"] == "demo" and s["seconds"] >= 0 for s in stats)


def test_a_document_without_text_or_with_many_empty_pages_is_flagged():
    assert "scanned" in text_warning({"chunks": 0, "pages_with_text": 0, "pdf_pages": 5})
    assert "26 of 48 pages" in text_warning({"chunks": 30, "pages_with_text": 26, "pdf_pages": 48})
    assert text_warning({"chunks": 216, "pages_with_text": 172, "pdf_pages": 172}) is None
    assert text_warning({"chunks": 3, "pages_with_text": 1, "pdf_pages": None}) is None


def test_a_missing_document_stops_the_build_and_says_how_to_fetch_it(folders):
    documents, _, config = folders
    (documents / "demo" / "own.md").write_text("# 1.1 Own\nbody", encoding="utf-8")

    with pytest.raises(SystemExit, match=r"missing \['old.md'\].*fetch_documents.py --division demo"):
        build_division(config, _DIVISION, 512, 64, documents)
