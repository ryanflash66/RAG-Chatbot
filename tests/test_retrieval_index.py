"""Tests for the Retrieval index, through its interface: refresh / retrieve / stats.

ChromaDB is real (persistent client in tmp_path); only the embedding is a test double.
"""

import dataclasses
import os
from dataclasses import replace

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


# ---------------------------------------------------------------------------
# Several instances sharing one store (API server, Chainlit app, CLI)
# ---------------------------------------------------------------------------

def test_second_instance_sees_refresh(index, seeded_config, hash_embed):
    index.refresh()
    other = RetrievalIndex(seeded_config, hash_embed)
    assert _sources(other.retrieve("ransomware", k=10)) == {"seed_ransomware.md"}

    (seeded_config.data_dir / "phishing_playbook.md").write_text("# Phishing\nReset.", encoding="utf-8")
    index.refresh()

    assert "phishing_playbook.md" in _sources(other.retrieve("phishing", k=10))
    assert other.stats() == index.stats()


def test_instance_created_before_first_build_sees_it(index, seeded_config, hash_embed):
    other = RetrievalIndex(seeded_config, hash_embed)
    assert other.stats().vectors == 0

    index.refresh()

    assert other.stats().vectors > 0
    assert other.retrieve("ransomware")


_REFRESH_IN_SUBPROCESS = """
import sys
sys.path.insert(0, sys.argv[1])
from rag.config import load_config
from rag.index import RetrievalIndex
from tests.conftest import _HashEmbedding
config = load_config({"DATA_DIR": sys.argv[2], "CHROMA_PERSIST_DIR": sys.argv[3], "CHROMA_COLLECTION": sys.argv[4]})
print(RetrievalIndex(config, _HashEmbedding()).refresh().documents)
"""


def test_refresh_in_another_process_is_visible(index, seeded_config):
    import subprocess
    import sys
    from pathlib import Path

    index.refresh()
    assert index.retrieve("ransomware")
    (seeded_config.data_dir / "phishing_playbook.md").write_text("# Phishing\nReset.", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, "-c", _REFRESH_IN_SUBPROCESS,
            str(Path(__file__).resolve().parent.parent),
            str(seeded_config.data_dir), str(seeded_config.chroma_persist_dir), seeded_config.chroma_collection,
        ],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "2"

    assert index.stats().documents == 2
    assert "phishing_playbook.md" in _sources(index.retrieve("phishing", k=10))


# ---------------------------------------------------------------------------
# chunking / top-k
# ---------------------------------------------------------------------------

LONG_TEXT = " ".join(f"Sentence number {i} describes host containment step {i}." for i in range(400))


def _long_index(config, hash_embed, **overrides):
    """An index over one long plain-text Document, with chunking settings overridden."""
    (config.data_dir / "long_runbook.txt").write_text(LONG_TEXT, encoding="utf-8")
    return RetrievalIndex(replace(config, **overrides), hash_embed)


def test_smaller_chunk_size_yields_more_vectors(config, hash_embed):
    big = _long_index(config, hash_embed, chunk_size=1024, chunk_overlap=0).refresh().vectors
    small = _long_index(config, hash_embed, chunk_size=128, chunk_overlap=0).refresh().vectors

    assert big >= 1
    assert small > big


def test_retrieve_honours_k(config, hash_embed):
    index = _long_index(config, hash_embed, chunk_size=128, chunk_overlap=0)
    assert index.refresh().vectors > 5

    assert len(index.retrieve("containment", k=1)) == 1
    assert len(index.retrieve("containment", k=5)) == 5


def test_refresh_keeps_markdown_tables_whole(config, hash_embed):
    rows = "\n".join(f"|{r}|{r}.5|" for r in range(12))
    (config.data_dir / "clearance.md").write_text(
        "# Clearance\n\n" + " ".join(f"Sentence {i}." for i in range(400)) +
        "\n\n###### Table 9-1 Work zone widths\n|Speed|Width|\n|---|---|\n" + rows + "\n",
        encoding="utf-8",
    )
    index = RetrievalIndex(dataclasses.replace(config, chunk_size=128, chunk_overlap=0), hash_embed)
    index.refresh()

    hits = index.retrieve("work zone widths", k=200)
    table_hits = [h for h in hits if "|Speed|Width|" in h.text]
    assert len(table_hits) == 1
    assert "Table 9-1 Work zone widths" in table_hits[0].text
    assert all(f"|{r}|{r}.5|" in table_hits[0].text for r in range(12))


# ---------------------------------------------------------------------------
# Reranking
# ---------------------------------------------------------------------------

def _keyword_reranker(keyword):
    """Fake cross-encoder: passages containing `keyword` score 1, others 0."""
    calls = []

    def rerank(query, passages):
        calls.append(len(passages))
        return [1.0 if keyword in passage else 0.0 for passage in passages]

    rerank.calls = calls
    return rerank


def _many_docs_config(config, n=12, **overrides):
    for i in range(n):
        (config.data_dir / f"doc{i:02d}.md").write_text(f"# Doc {i}\nfiller text number {i}", encoding="utf-8")
    (config.data_dir / "needle.md").write_text("# Needle\nthe answer is 42", encoding="utf-8")
    return replace(config, **overrides)


def test_reranker_reorders_candidates_and_keeps_vector_score(config, hash_embed):
    cfg = _many_docs_config(config, rerank_candidates=50)
    rerank = _keyword_reranker("answer is 42")
    index = RetrievalIndex(cfg, hash_embed, rerank)
    index.refresh()

    hits = index.retrieve("unrelated question", k=3)

    assert len(hits) == 3
    assert hits[0].source == "needle.md"
    assert hits[0].score == 1.0
    assert isinstance(hits[0].metadata["vector_score"], float)
    assert rerank.calls == [13]  # all candidates scored in one call


def test_reranker_fetches_rerank_candidates_not_k(config, hash_embed):
    cfg = _many_docs_config(config, rerank_candidates=5)
    rerank = _keyword_reranker("zzz")
    RetrievalIndex(cfg, hash_embed, rerank).refresh()

    hits = RetrievalIndex(cfg, hash_embed, rerank).retrieve("anything", k=2)

    assert len(hits) == 2
    assert rerank.calls == [5]


def test_k_above_candidates_still_returns_k(config, hash_embed):
    cfg = _many_docs_config(config, rerank_candidates=2)
    rerank = _keyword_reranker("zzz")
    index = RetrievalIndex(cfg, hash_embed, rerank)
    index.refresh()

    assert len(index.retrieve("anything", k=6)) == 6
    assert rerank.calls == [6]


def test_without_reranker_scores_are_vector_similarity(config, hash_embed):
    cfg = _many_docs_config(config)
    index = RetrievalIndex(cfg, hash_embed)
    index.refresh()

    hits = index.retrieve("anything", k=3)

    assert len(hits) == 3
    assert all("vector_score" not in hit.metadata for hit in hits)


def test_make_reranker_off_when_model_unset(config):
    from rag.index import make_reranker

    assert make_reranker(replace(config, rerank_model=None)) is None
