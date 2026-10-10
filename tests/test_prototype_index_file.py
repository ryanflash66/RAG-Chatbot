"""Tests for the hosted prototype's index files: save, load and cosine search."""

import numpy as np
import pytest

from prototype.index_file import IndexFile


def _unit(rows):
    rows = np.array(rows, dtype=np.float32)
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


def test_saved_index_loads_and_ranks_by_cosine(tmp_path):
    chunks = [{"text": t, "source": "a.pdf", "page": p, "section": f"Page {p}"} for t, p in [("x", 1), ("y", 2), ("xy", 3)]]
    IndexFile("test-model", chunks, _unit([[1, 0, 0], [0, 1, 0], [1, 1, 0]])).save(tmp_path)

    index = IndexFile.load(tmp_path)
    hits = index.search(_unit([[1, 0.2, 0]])[0], k=2)

    assert index.model == "test-model"
    assert np.load(tmp_path / "vectors.npy").dtype == np.float16
    assert [h.chunk["page"] for h in hits] == [1, 3]
    assert hits[0].score == pytest.approx(0.98, abs=0.01)


def test_mismatched_chunks_and_vectors_are_rejected():
    with pytest.raises(ValueError):
        IndexFile("m", [{"text": "only one"}], _unit([[1, 0], [0, 1]]))
