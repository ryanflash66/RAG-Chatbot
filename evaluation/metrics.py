"""The metrics, as pure functions (no models, no network), so they can be unit-tested.

The four RAGAS metrics are computed here from the judge's verdicts (see
judge.py for the one call that produces them), following the RAGAS
definitions (Es et al. 2024; docs.ragas.io, "Available metrics"):

    faithfulness       supported answer statements / all answer statements
    answer relevancy   mean cosine similarity between the question and questions
                       generated from the answer; 0 when the answer is noncommittal
    context precision  sum over k of precision@k * v_k / relevant passages in the top K
    context recall     reference statements attributable to the passages / all of them

and the deterministic cross-check from the gold pages, which needs no LLM:

    page hit@k, reciprocal rank, page precision (the same rank-weighted formula
    with v_k = "the chunk is from a gold page") and page recall (gold pages the
    model was shown / gold pages; one of them is enough when they are alternatives).

Every function returns None when the metric is undefined for the question
(an answer with no statements, a question with no gold pages), so averages
are taken over the questions where it applies, with n reported beside them.
"""

import math
import random
from typing import Dict, Iterable, List, Optional, Sequence, Set

import numpy as np


def _share(flags: Sequence[bool]) -> Optional[float]:
    return sum(1 for f in flags if f) / len(flags) if flags else None


def faithfulness(supported: Sequence[bool]) -> Optional[float]:
    """Share of the answer's statements the passages support; None when it makes none."""
    return _share(supported)


def context_recall(attributed: Sequence[bool]) -> Optional[float]:
    """Share of the reference answer's statements the passages support; None without a reference."""
    return _share(attributed)


def context_precision(relevant: Sequence[bool]) -> Optional[float]:
    """RAGAS context precision@K for verdicts in rank order (rank 1 first).

    sum_k precision@k * v_k / (relevant items in the top K): 1.0 when every
    relevant passage ranks above every irrelevant one, 0.0 when none is
    relevant, None when nothing was retrieved.
    """
    if not relevant:
        return None
    total, hits = 0.0, 0
    for k, useful in enumerate(relevant, 1):
        if useful:
            hits += 1
            total += hits / k
    return total / hits if hits else 0.0


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b / norm) if norm else 0.0


def answer_relevancy(question: Sequence[float], generated: Sequence[Sequence[float]], noncommittal: bool) -> Optional[float]:
    """Mean cosine similarity of the generated questions to the asked one, times "not noncommittal".

    As RAGAS's ResponseRelevancy: `cosine_sim.mean() * int(not all_noncommittal)`.
    None when the judge generated no questions.
    """
    if not len(generated):
        return None
    if noncommittal:
        return 0.0
    return float(np.mean([cosine(question, g) for g in generated]))


def page_metrics(ranked_pages: Sequence[Optional[int]], shown_pages: Iterable[Optional[int]],
                 gold: Iterable[int], mode: str = "all") -> Dict[str, Optional[float]]:
    """The deterministic retrieval metrics for one question from its gold pages.

    `ranked_pages`: the page of each reranked hit, best first (the top k the
    model is given). `shown_pages`: every page the model was shown, including
    the following chunks and merged parts. `mode` "all": each gold page is
    needed; "any": the gold pages are alternatives (a key phrase found on
    several pages), so recall is 1 when any of them was shown.
    """
    gold_set: Set[int] = set(gold)
    if not gold_set:
        return {"hit": None, "rr": None, "precision": None, "recall": None}
    on_gold = [p in gold_set for p in ranked_pages]
    first = next((k for k, g in enumerate(on_gold, 1) if g), None)
    shown = set(shown_pages) & gold_set
    if mode == "any":
        recall = 1.0 if shown else 0.0
    else:
        recall = len(shown) / len(gold_set)
    return {
        "hit": 1.0 if first else 0.0,
        "rr": 1.0 / first if first else 0.0,
        "precision": context_precision(on_gold),
        "recall": recall,
    }


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    kept = [v for v in values if v is not None and not math.isnan(v)]
    return sum(kept) / len(kept) if kept else None


def percentile(values: Sequence[float], q: float) -> Optional[float]:
    """The nearest-rank q-th percentile: the smallest value at or above q% of the values.

    For 10 answers the 90th percentile is the 9th slowest, not the slowest.
    """
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[max(0, math.ceil(q / 100 * len(ordered)) - 1)]


def bootstrap_ci(values: Sequence[float], level: float = 0.95, rounds: int = 2000,
                 seed: int = 637) -> Optional[List[float]]:
    """A percentile bootstrap interval for the mean (fixed seed, so charts are reproducible).

    With n around 40 per division, a mean alone hides how much it could move;
    the interval is drawn as the error bar.
    """
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(rounds))
    low = means[int((1 - level) / 2 * rounds)]
    high = means[min(rounds - 1, int((1 + level) / 2 * rounds))]
    return [low, high]
