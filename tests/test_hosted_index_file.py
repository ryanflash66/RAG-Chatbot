"""Tests for the hosted demo's index files: save, load, cosine search and the division filter."""

import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hosted"))

from divrag.index_file import Hit, IndexFile  # noqa: E402
from divrag.retrieval import Retriever  # noqa: E402
from divrag.timing import STEPS, StepTimer  # noqa: E402


def _unit(rows):
    rows = np.array(rows, dtype=np.float32)
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


def _chunk(text, page, division="a"):
    return {"text": text, "source": f"{division}.pdf", "page": page, "section": None, "division": division}


def test_saved_index_loads_and_ranks_by_cosine(tmp_path):
    chunks = [_chunk(t, p) for t, p in [("x", 1), ("y", 2), ("xy", 3)]]
    IndexFile("test-model", chunks, _unit([[1, 0, 0], [0, 1, 0], [1, 1, 0]])).save(tmp_path)

    index = IndexFile.load(tmp_path)
    hits = index.search(_unit([[1, 0.2, 0]])[0], k=2)

    assert index.model == "test-model"
    assert np.load(tmp_path / "vectors.npy").dtype == np.float16
    assert [h.chunk["page"] for h in hits] == [1, 3]
    assert hits[0].score == pytest.approx(0.98, abs=0.01)
    assert index.chunks[0]["division"] == "a"


def test_mismatched_chunks_and_vectors_are_rejected():
    with pytest.raises(ValueError):
        IndexFile("m", [{"text": "only one"}], _unit([[1, 0], [0, 1]]))


def _two_division_index():
    # Division b's chunks match the query better than any of division a's.
    chunks = [_chunk("a1", 1, "a"), _chunk("b1", 1, "b"), _chunk("a2", 2, "a"), _chunk("b2", 2, "b"), _chunk("b3", 3, "b")]
    vectors = _unit([[0.2, 1, 0], [1, 0, 0], [0.1, 1, 0.3], [0.99, 0.1, 0], [0.98, 0, 0.1]])
    return IndexFile("m", chunks, vectors)


def test_division_filter_never_returns_another_divisions_chunks():
    index = _two_division_index()
    query = _unit([[1, 0, 0]])[0]

    hits_a = index.search(query, k=10, division="a")
    hits_b = index.search(query, k=10, division="b")

    assert [h.chunk["text"] for h in hits_a] == ["a1", "a2"]  # all of a's, though b's score higher
    assert {h.chunk["division"] for h in hits_b} == {"b"}
    assert len(hits_b) == 3
    assert index.search(query, k=10, division="unknown") == []
    assert len(index.search(query, k=10)) == 5  # no filter: every division


class _FakeEmbedder:
    def query(self, question):
        return _unit([[1, 0, 0]])[0]


class _RecordingReranker:
    """Scores passages by reversed position, and records what it was shown."""

    def __init__(self):
        self.seen = []

    def scores(self, question, passages):
        self.seen.extend(passages)
        return [float(i) for i in range(len(passages))]


def test_retriever_reranks_only_the_asked_divisions_chunks():
    reranker = _RecordingReranker()
    retriever = Retriever(_two_division_index(), _FakeEmbedder(), reranker, candidates=20)

    hits = retriever.retrieve("q", division="a", k=5)

    assert set(reranker.seen) == {"a1", "a2"}
    assert [h.chunk["text"] for h in hits] == ["a2", "a1"]  # reranker order, not vector order
    assert all(h.chunk["division"] == "a" for h in hits)


class _SlowReranker(_RecordingReranker):
    def scores(self, question, passages):
        time.sleep(0.03)
        return super().scores(question, passages)


def test_retriever_times_embed_search_and_rerank_separately():
    timer = StepTimer()
    Retriever(_two_division_index(), _FakeEmbedder(), _SlowReranker()).retrieve("q", division="a", k=5, timer=timer)

    ms = timer.as_ms()
    assert ms["rerank"] >= 25
    assert ms["embed"] < 25 and ms["search"] < 25
    assert ms["llm"] == 0  # not a retrieval step


def test_step_timer_adds_up_repeats_and_reports_every_step():
    timer = StepTimer()
    for _ in range(2):
        with timer.step("embed"):
            time.sleep(0.02)

    ms = timer.as_ms()
    assert list(ms) == list(STEPS)
    assert ms["embed"] >= 35
    assert ms["retry"] == 0
    with pytest.raises(ValueError):
        with timer.step("typo"):
            pass


def test_retriever_can_rerank_fewer_candidates_for_one_call():
    reranker = _RecordingReranker()
    retriever = Retriever(_two_division_index(), _FakeEmbedder(), reranker, candidates=20)

    retriever.retrieve("q", division="b", k=1, candidates=2)

    assert len(reranker.seen) == 2  # not all 3 of b's chunks


class _RecordingEmbedder(_FakeEmbedder):
    def __init__(self):
        self.questions = []

    def query(self, question):
        self.questions.append(question)
        return super().query(question)


def test_warm_up_runs_each_model_once_on_short_text():
    embedder, reranker = _RecordingEmbedder(), _RecordingReranker()

    Retriever(_two_division_index(), embedder, reranker).warm_up()

    assert embedder.questions == ["warm up"]
    assert reranker.seen == ["warm up"]  # one short passage, not 20 real ones
    Retriever(_two_division_index(), _RecordingEmbedder(), None).warm_up()  # no reranker: nothing to warm


def test_retriever_without_reranker_keeps_vector_order():
    retriever = Retriever(_two_division_index(), _FakeEmbedder(), None)
    assert [h.chunk["text"] for h in retriever.retrieve("q", division="b", k=2)] == ["b1", "b2"]


def test_following_chunk_stays_in_the_same_document():
    retriever = Retriever(_two_division_index(), _FakeEmbedder(), None)
    index = retriever.index
    a1, b1, a2, b2, b3 = index.chunks
    b2["source"] = b1["source"] = b3["source"] = "b.pdf"

    hits = retriever.with_following(retriever.retrieve("q", division="b", k=2), top=1)

    assert [h.chunk["text"] for h in hits] == ["b1", "b2"]  # b1's follower (a2) is another document
    assert index.following(b2) is b3
    assert index.following(b3) is None


def test_passages_are_in_reading_order_with_consecutive_chunks_merged():
    chunks = [_chunk(t, p, "b") for t, p in [("p1", 1), ("p2a", 2), ("p2b", 2), ("p3", 3), ("p4", 4)]]
    chunks[3]["section"] = "1.2 Two"
    index = IndexFile("m", chunks, _unit([[1, 0, 0]] * 5))
    retriever = Retriever(index, _FakeEmbedder(), None)

    passages = retriever.as_passages([Hit(0.9, chunks[4]), Hit(0.8, chunks[3]), Hit(0.7, chunks[1]), Hit(0.5, chunks[2])])
    apart = retriever.as_passages([Hit(0.9, chunks[3]), Hit(0.8, chunks[0])])

    assert [p.chunk["text"] for p in passages] == ["\n\n".join(["p2a", "p2b", "p3", "p4"])]
    assert (passages[0].chunk["page"], passages[0].chunk["page_end"]) == (2, 4)
    assert passages[0].chunk["section"] == "1.2 Two"
    assert passages[0].score == 0.9
    assert [p["text"] for p in passages[0].chunk["parts"]] == ["p2a", "p2b", "p3", "p4"]
    assert [p.chunk["text"] for p in apart] == ["p1", "p3"]  # not adjacent: kept apart, in reading order
    assert "page_end" not in chunks[1]  # the index's own chunks are not changed


def test_committed_index_tags_every_chunk_with_a_configured_division():
    from divrag.config import HOSTED_DIR
    from divrag.divisions import BY_ID, document_for

    index = IndexFile.load(HOSTED_DIR / "index")

    assert set(index.divisions()) == set(BY_ID)
    for chunk in index.chunks:
        document = document_for(chunk["source"])
        assert document is not None, chunk["source"]
        assert document in BY_ID[chunk["division"]].documents
        assert isinstance(chunk["page"], int) and chunk["page"] >= 1


def test_search_and_count_can_be_limited_to_some_documents():
    chunks = [_chunk("a1", 1, "a"), _chunk("b1", 1, "b"), _chunk("b2", 2, "b"), _chunk("b3", 3, "b")]
    chunks[3]["source"] = "b-other.pdf"
    index = IndexFile("m", chunks, _unit([[1, 0, 0], [1, 0.1, 0], [1, 0.2, 0], [1, 0, 0]]))
    query = _unit([[1, 0, 0]])[0]

    hits = index.search(query, k=10, division="b", sources=["b-other.pdf"])

    assert [h.chunk["text"] for h in hits] == ["b3"]
    assert index.count("b") == 3 and index.count("b", ["b.pdf"]) == 2 and index.count() == 4
    assert index.count("a", ["b.pdf"]) == 0  # a document of another division never widens the search
    assert index.search(query, k=10, division="b", sources=[]) == []
