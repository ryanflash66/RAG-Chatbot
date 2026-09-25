"""Tests for the Retrieval index, through its interface: refresh / retrieve / stats.

ChromaDB is real (persistent client in tmp_path); only the embedding is a test double.
"""

import os

import pytest

from rag.index import EmptyIndexError, NoDocumentsError, RetrievalIndex


def _sources(hits):
    return {hit.source for hit in hits}


# ---------------------------------------------------------------------------
# refresh / stats
# ---------------------------------------------------------------------------

def test_new_index_is_empty(index):
    stats = index.stats()
    assert stats.vectors == 0
    assert stats.documents == 0
    assert stats.last_refresh_at is None


def test_refresh_builds_collection(index):
    stats = index.refresh()
    assert stats.collection == "test_col"
    assert stats.documents == 1
    assert stats.vectors >= 1
    assert stats.last_refresh_at


def test_refresh_counts_documents_not_chunks(index, seeded_config):
    (seeded_config.data_dir / "a.md").write_text("# A\n\n## One\nx\n\n## Two\ny", encoding="utf-8")
    (seeded_config.data_dir / "b.txt").write_text("plain", encoding="utf-8")
    assert index.refresh().documents == 3


def test_refresh_empty_data_dir_raises(config, hash_embed):
    with pytest.raises(NoDocumentsError):
        RetrievalIndex(config, hash_embed).refresh()


def test_failed_refresh_keeps_previous_index(index, seeded_config):
    before = index.refresh()
    os.remove(seeded_config.data_dir / "seed_ransomware.md")

    with pytest.raises(NoDocumentsError):
        index.refresh()

    assert index.stats().vectors == before.vectors
    assert index.retrieve("ransomware")


def test_stats_survive_reopen(index, seeded_config, hash_embed):
    built = index.refresh()
    reopened = RetrievalIndex(seeded_config, hash_embed).stats()
    assert reopened == built


def test_ensure_built_builds_only_when_empty(index):
    first = index.ensure_built()
    assert first.vectors >= 1
    assert index.ensure_built().last_refresh_at == first.last_refresh_at


def test_ensure_built_with_no_documents_stays_empty(config, hash_embed):
    stats = RetrievalIndex(config, hash_embed).ensure_built()
    assert stats.vectors == 0


# ---------------------------------------------------------------------------
# retrieve
# ---------------------------------------------------------------------------

def test_retrieve_on_empty_index_raises(index):
    with pytest.raises(EmptyIndexError):
        index.retrieve("anything")


def test_retrieve_returns_hits_with_metadata(index):
    index.refresh()
    hits = index.retrieve("EDR containment isolation", k=2)

    assert 0 < len(hits) <= 2
    hit = hits[0]
    assert hit.text
    assert isinstance(hit.score, float)
    assert hit.source == "seed_ransomware.md"
    assert hit.metadata["incident_type"] == "ransomware"
    assert hit.metadata["doc_domain"] == "ir"
    assert hit.metadata["doc_type"] == "markdown"


def test_retrieve_never_refreshes(index, seeded_config):
    index.refresh()
    (seeded_config.data_dir / "phishing_playbook.md").write_text("# Phishing\nReset.", encoding="utf-8")
    before = index.stats()

    hits = index.retrieve("phishing", k=10)

    assert "phishing_playbook.md" not in _sources(hits)
    assert index.stats() == before


def test_refresh_picks_up_added_and_deleted_documents(index, seeded_config):
    index.refresh()
    (seeded_config.data_dir / "phishing_playbook.md").write_text("# Phishing\nReset.", encoding="utf-8")
    index.refresh()
    assert "phishing_playbook.md" in _sources(index.retrieve("phishing", k=10))

    os.remove(seeded_config.data_dir / "phishing_playbook.md")
    index.refresh()
    assert "phishing_playbook.md" not in _sources(index.retrieve("phishing", k=10))


def test_retrieve_filters_on_classification(index, seeded_config):
    (seeded_config.data_dir / "phishing_playbook.md").write_text("# Phishing\nReset.", encoding="utf-8")
    (seeded_config.data_dir / "cafeteria_menu.md").write_text("# Menu\nSoup.", encoding="utf-8")
    index.refresh()

    hits = index.retrieve("playbook", k=10, where={"incident_type": "phishing"})

    assert _sources(hits) == {"phishing_playbook.md"}


def test_classification_ignores_location_of_data_dir(tmp_path, hash_embed):
    """A data dir under a path like 'rag-chatbot' must not label documents iot_ot."""
    from rag.config import load_config

    cfg = load_config({
        "DATA_DIR": str(tmp_path / "rag-chatbot" / "incident-response" / "data"),
        "CHROMA_PERSIST_DIR": str(tmp_path / "chroma"),
        "CHROMA_COLLECTION": "loc_col",
    })
    cfg.data_dir.mkdir(parents=True)
    (cfg.data_dir / "K-Maps Lecture Notes page.md").write_text("# K-maps\nKarnaugh maps.", encoding="utf-8")

    index = RetrievalIndex(cfg, hash_embed)
    index.refresh()
    hit = index.retrieve("karnaugh", k=1)[0]

    assert hit.source == "K-Maps Lecture Notes page.md"
    assert hit.metadata["incident_type"] == "unknown"
    assert hit.metadata["doc_domain"] == "general"


def test_json_documents_are_indexed(index, seeded_config):
    (seeded_config.data_dir / "asset_inventory.json").write_text(
        '{"hosts": ["dc01", "web01"]}', encoding="utf-8"
    )
    index.refresh()

    hits = index.retrieve("hosts", k=10, where={"doc_domain": "asset_inventory"})

    assert _sources(hits) == {"asset_inventory.json"}
    assert hits[0].metadata["asset_scope"] == "org_inventory"
    assert hits[0].metadata["doc_type"] == "json"


def test_subdirectories_are_indexed_with_relative_source(index, seeded_config):
    sub = seeded_config.data_dir / "playbooks"
    sub.mkdir()
    (sub / "malware.md").write_text("# Malware\nScan.", encoding="utf-8")
    index.refresh()

    hits = index.retrieve("scan", k=10, where={"incident_type": "malware"})

    assert _sources(hits) == {"playbooks/malware.md"}
