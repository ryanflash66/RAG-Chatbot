"""Milliseconds spent in each step of answering one question.

The steps, in pipeline order:

    model_load  loading the embedding and reranker models (only on a cold instance)
    embed       turning the question into a vector
    search      the vector search within the asked division
    rerank      the cross-encoder re-reading the search's candidates
    llm         the first model call
    citations   checking and renumbering the answer's citations
    retry       the second model call (and its citation check) after a refusal
    suggest     searching the other divisions for a "try asking X" suggestion

A step that runs more than once in a question adds up; a step that didn't run
reports 0, so every answer has the same keys.
"""

import time
from contextlib import contextmanager
from typing import Dict, Iterator

STEPS = ("model_load", "embed", "search", "rerank", "llm", "citations", "retry", "suggest")


class StepTimer:
    def __init__(self) -> None:
        self._seconds: Dict[str, float] = {}

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        if name not in STEPS:
            raise ValueError(f"unknown step {name!r}")
        started = time.perf_counter()
        try:
            yield
        finally:
            self._seconds[name] = self._seconds.get(name, 0.0) + time.perf_counter() - started

    def as_ms(self) -> Dict[str, int]:
        return {name: round(self._seconds.get(name, 0.0) * 1000) for name in STEPS}


@contextmanager
def timed(timer: "StepTimer | None", name: str) -> Iterator[None]:
    """`timer.step(name)`, or nothing when there is no timer."""
    if timer is None:
        yield
    else:
        with timer.step(name):
            yield
