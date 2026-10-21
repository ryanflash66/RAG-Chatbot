"""Milliseconds spent in each step of answering one question.

The steps, in pipeline order:

    model_load  loading the embedding and reranker models, including the one warm-up
                query that runs their first inference (only on a cold instance; the
                question's own embed, search and rerank are timed separately)
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
from typing import Callable, Dict, Iterator, Optional

STEPS = ("model_load", "embed", "search", "rerank", "llm", "citations", "retry", "suggest")

# listener(step, "start" | "done", ms): ms is 0 at the start, and this run's time when it is done.
Listener = Callable[[str, str, int], None]


class StepTimer:
    def __init__(self, listener: Optional[Listener] = None) -> None:
        """`listener` hears each step start and finish as it happens.

        The streamed answer (DAR-629) shows the steps live from it, so the page
        shows the same steps and times as timing_ms rather than a guess. It is
        called from whichever thread runs the step (retrieval runs in a worker
        thread), and a step that fails reports no "done".
        """
        self._seconds: Dict[str, float] = {}
        self._listener = listener

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        if name not in STEPS:
            raise ValueError(f"unknown step {name!r}")
        if self._listener:
            self._listener(name, "start", 0)
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            self._seconds[name] = self._seconds.get(name, 0.0) + elapsed
        if self._listener:
            self._listener(name, "done", round(elapsed * 1000))

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
