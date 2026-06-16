"""Tests for rag_index -- metadata inference, index creation, and staleness detection.

All tests use _HashEmbedding from conftest (via the hash_embed fixture) and a
temporary ChromaDB directory to avoid touching the production chroma_db/ store.
"""

import os
import time

import pytest

from rag_index import (
    RAGIndexConfig,
    _file_metadata,
    _needs_rebuild,
    create_or_load_index,
    read_index_metadata,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(data_dir, chroma_dir, collection="test_col") -> RAGIndexConfig:
    return RAGIndexConfig(
        data_dir=str(data_dir),
        chroma_persist_dir=str(chroma_dir),
        chroma_collection=collection,
        metadata_path=os.path.join(str(chroma_dir), "index_meta.json"),
    )


# ---------------------------------------------------------------------------
# _file_metadata
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,expected_doc_type,expected_domain", [
    ("seed_ransomware_playbook.md", "markdown", "ir"),
    ("report.docx",                "word",       "general"),
    ("slides.pptx",                "powerpoint", "general"),
    ("diagram.png",                "other",      "general"),
    # threat_intel.pdf contains "threat" which is in IR_KEYWORDS -> domain is "ir"
    ("threat_intel.pdf",           "pdf",        "ir"),
    ("asset_inventory.md",         "markdown",   "asset_inventory"),
    ("asset_inventory.json",       "json",       "asset_inventory"),
])
def test_file_metadata_doc_type_and_domain(filename, expected_doc_type, expected_domain):
    meta = _file_metadata(f"/data/{filename}")
    assert meta["doc_type"] == expected_doc_type
    assert meta["doc_domain"] == expected_domain


def test_file_metadata_asset_inventory_fields():
    meta = _file_metadata("/data/asset_inventory.md")
    assert meta["doc_domain"] == "asset_inventory"
    assert meta["asset_scope"] == "org_inventory"
    assert "asset" in meta["tags"]
    assert meta["incident_type"] == "general"


def test_file_metadata_incident_type_ransomware():
    meta = _file_metadata("/data/seed_ransomware_playbook.md")
    assert meta["incident_type"] == "ransomware"


def test_file_metadata_incident_type_phishing():
    meta = _file_metadata("/data/seed_phishing_playbook.md")
    assert meta["incident_type"] == "phishing"


def test_file_metadata_incident_type_malware():
    meta = _file_metadata("/data/seed_malware_playbook.md")
    assert meta["incident_type"] == "malware"


def test_file_metadata_unknown_incident_type():
    # "summary.md" has no substrings matching any INCIDENT_KEYWORDS entry
    meta = _file_metadata("/data/general_security_summary.md")
    assert meta["incident_type"] == "unknown"


def test_file_metadata_source_contains_filename():
    import os
    meta = _file_metadata(os.path.join("some", "path", "playbook.md"))
    assert "playbook.md" in meta["source"]


# ---------------------------------------------------------------------------
# create_or_load_index
# ---------------------------------------------------------------------------

def test_create_index_builds_chroma_collection(tmp_path, hash_embed):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    (data_dir / "playbook.md").write_text(
        "# Phishing Playbook\n\nContain the incident and reset credentials.",
        encoding="utf-8",
    )

    config = _make_config(data_dir, chroma_dir)
    _, meta = create_or_load_index(config=config, embed_model=hash_embed, force_rebuild=True)

    assert meta["index_backend"] == "chroma"
    assert int(meta["indexed_docs"]) >= 1
    assert int(meta["vector_count"]) >= 1
    assert meta["collection"] == "test_col"
    assert "last_refresh_at" in meta


def test_create_index_raises_on_empty_data_dir(tmp_path, hash_embed):
    data_dir = tmp_path / "empty"
    data_dir.mkdir()
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()

    config = _make_config(data_dir, chroma_dir)
    with pytest.raises((ValueError, RuntimeError)):
        create_or_load_index(config=config, embed_model=hash_embed, force_rebuild=True)


def test_load_existing_index_without_rebuild(tmp_path, hash_embed):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    (data_dir / "doc.md").write_text(
        "# Malware Playbook\n\nRun EDR scan across all endpoints.",
        encoding="utf-8",
    )

    config = _make_config(data_dir, chroma_dir)
    _, meta_first = create_or_load_index(config=config, embed_model=hash_embed, force_rebuild=True)
    _, meta_second = create_or_load_index(config=config, embed_model=hash_embed, force_rebuild=False)

    assert meta_second["index_source"] == "loaded"
    assert int(meta_second["vector_count"]) == int(meta_first["vector_count"])


def test_force_rebuild_replaces_collection(tmp_path, hash_embed):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    (data_dir / "doc.md").write_text(
        "# Data Breach Playbook\n\nNotify affected parties within 72 hours.",
        encoding="utf-8",
    )

    config = _make_config(data_dir, chroma_dir)
    _, meta_first = create_or_load_index(config=config, embed_model=hash_embed, force_rebuild=True)
    _, meta_second = create_or_load_index(config=config, embed_model=hash_embed, force_rebuild=True)

    assert meta_second["index_source"] == "rebuilt"
    assert int(meta_second["vector_count"]) == int(meta_first["vector_count"])


# ---------------------------------------------------------------------------
# _needs_rebuild and read_index_metadata
# ---------------------------------------------------------------------------

def test_needs_rebuild_true_when_no_metadata(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    config = _make_config(data_dir, chroma_dir)
    assert _needs_rebuild(config) is True


def test_needs_rebuild_false_after_build(tmp_path, hash_embed):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    (data_dir / "doc.md").write_text("# Doc\nContent.", encoding="utf-8")

    config = _make_config(data_dir, chroma_dir)
    create_or_load_index(config=config, embed_model=hash_embed, force_rebuild=True)
    assert _needs_rebuild(config) is False


def test_needs_rebuild_true_after_new_file(tmp_path, hash_embed):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    (data_dir / "doc.md").write_text("# Doc\nContent.", encoding="utf-8")

    config = _make_config(data_dir, chroma_dir)
    create_or_load_index(config=config, embed_model=hash_embed, force_rebuild=True)

    new_file = data_dir / "new_doc.md"
    new_file.write_text("# New Doc\nNew content.", encoding="utf-8")
    future_ts = time.time() + 2
    os.utime(str(new_file), (future_ts, future_ts))

    assert _needs_rebuild(config) is True


def test_read_index_metadata_returns_empty_dict_for_missing_file(tmp_path):
    result = read_index_metadata(str(tmp_path / "nonexistent.json"))
    assert result == {}


def test_read_index_metadata_round_trips(tmp_path, hash_embed):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    (data_dir / "doc.md").write_text("# Doc\nContent.", encoding="utf-8")

    config = _make_config(data_dir, chroma_dir)
    _, written_meta = create_or_load_index(
        config=config, embed_model=hash_embed, force_rebuild=True
    )
    read_meta = read_index_metadata(config.metadata_path)

    assert read_meta["index_backend"] == written_meta["index_backend"]
    assert read_meta["collection"] == written_meta["collection"]
    assert read_meta["vector_count"] == written_meta["vector_count"]
