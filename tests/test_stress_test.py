"""Tests for the stress test's scoring (prototype.stress_test): gold pages count only in the division's own manual."""

import numpy as np

from prototype import stress_test  # puts hosted/ on sys.path
from divrag.index_file import IndexFile  # noqa: I001
from divrag.retrieval import Retriever

UAM = stress_test.GOLD_SOURCE["utilities"]


class _Embedder:
    def query(self, question):
        return np.array([1.0, 0.0], dtype=np.float32)


def _index():
    chunks = [
        {"text": "Detour costs are paid by the utility owner.", "source": "Other.pdf", "page": 127, "division": "utilities"},
        {"text": "The utility owner pays for the detour.", "source": UAM, "page": 127, "division": "utilities"},
        {"text": "Barrier dimensions.", "source": "TMP.pdf", "page": 32, "division": "wztc"},
    ]
    vectors = np.array([[1.0, 0.0], [0.9, 0.1], [1.0, 0.0]], dtype=np.float32)
    return IndexFile("test", chunks, vectors)


def test_a_gold_page_of_another_document_does_not_count():
    retriever = Retriever(_index(), _Embedder())
    case = {"id": "B3", "division": "utilities", "pages": [127], "question": "Who pays for a detour?"}

    result = stress_test.hit_at_5(retriever, [case])

    row = result["cases"][0]
    assert row["rank"] == 2  # page 127 of Other.pdf ranks first but is not the UAM's page 127
    assert row["other_documents_in_top5"] == 1


def test_key_cases_take_their_pages_from_the_gold_document_only():
    case = {"id": "U1", "division": "utilities", "key": "pays for the detour"}

    assert stress_test.gold_pages(case, _index()) == {127}


def test_no_hit_ever_comes_from_another_division():
    retriever = Retriever(_index(), _Embedder())

    result = stress_test.wrong_division(retriever, [("utilities", "Who pays for a detour?")])

    assert result["wrong"] == 0 and result["checked"] > 0


def test_a_cited_page_range_covers_an_expected_page_in_its_middle():
    assert stress_test._covers({"page": 31, "page_end": 34}, (32, 33))
    assert stress_test._covers({"page": 46, "page_end": None}, (46,))
    assert not stress_test._covers({"page": 47, "page_end": None}, (46,))
    assert not stress_test._covers({"page": None}, (46,))


def test_percentile_interpolates_between_ranks():
    assert stress_test._percentile([10, 20, 30, 40, 50], 0.95) == 48
    assert stress_test._percentile([], 0.95) == 0.0
