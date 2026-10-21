"""Division-scoped retrieval: vector search within one division, then rerank.

The division filter is applied inside the vector search (IndexFile.search), so
the reranker and the answer only ever see the asked division's chunks.
"""

from typing import List, Optional, Sequence

from .embedder import Embedder, Reranker
from .index_file import Hit, IndexFile
from .timing import StepTimer, timed

DEFAULT_CANDIDATES = 20


class Retriever:
    def __init__(self, index: IndexFile, embedder: Embedder, reranker: Optional[Reranker] = None,
                 candidates: int = DEFAULT_CANDIDATES):
        self.index = index
        self.embedder = embedder
        self.reranker = reranker
        self.candidates = candidates

    def retrieve(self, question: str, division: Optional[str], k: int = 5,
                 timer: Optional[StepTimer] = None, candidates: Optional[int] = None,
                 sources: Optional[Sequence[str]] = None) -> List[Hit]:
        """The k best chunks of `division` for the question (all divisions when None).

        `sources` (document file names) limits the search to those documents.
        With a reranker, the top `candidates` vector hits (default: the
        retriever's) are re-ordered by the cross-encoder and their scores are
        the cross-encoder's. `timer` records the embed, search and rerank steps.
        """
        pool = max(k, candidates or self.candidates) if self.reranker else k
        with timed(timer, "embed"):
            vector = self.embedder.query(question)
        with timed(timer, "search"):
            hits = self.index.search(vector, k=pool, division=division, sources=sources)
        if self.reranker and len(hits) > 1:
            with timed(timer, "rerank"):
                scores = self.reranker.scores(question, [h.chunk["text"] for h in hits])
            hits = [Hit(s, h.chunk) for s, h in sorted(zip(scores, hits), key=lambda pair: -pair[0])]
        return hits[:k]

    def warm_up(self) -> None:
        """Load the models and run each once on a few words.

        The first inference of an ONNX model is slow, so a cold instance runs one
        before the first question. Short text is enough: reranking 20 real
        passages here took about 4.6 s of a cold start on Vercel's CPU. Two
        full-length passages (the index's longest) added 0.5 s to the warm-up on
        Vercel and changed nothing after it. With all 20 passages in one batch,
        the first two questions still reranked about 0.6 s slower than later
        ones either way; one passage per call (embedder.RERANK_BATCH_SIZE) left
        the first questions 0.06 s slower than the same questions asked again,
        after either warm-up.
        """
        self.embedder.query("warm up")
        if self.reranker:
            self.reranker.scores("warm up", ["warm up"])

    def with_following(self, hits: List[Hit], top: int = 2) -> List[Hit]:
        """The hits, each of the first `top` followed by the next chunk of its document.

        A rule that runs onto the next page is split across two chunks; the
        second half often doesn't match the question on its own (the TMP manual's
        drop-off rule D continues on the next page as "3. Provide a lateral distance...").
        A following chunk comes from the same document, so the same division.
        """
        seen = {id(h.chunk) for h in hits}
        out: List[Hit] = []
        for rank, hit in enumerate(hits):
            out.append(hit)
            after = self.index.following(hit.chunk) if rank < top else None
            if after is not None and id(after) not in seen:
                seen.add(id(after))
                out.append(Hit(hit.score, after))
        return out

    def as_passages(self, hits: List[Hit]) -> List[Hit]:
        """The hits in reading order, with chunks that follow each other merged into one passage.

        A rule split across pages then reaches the model as one passage. With
        the halves as separate passages, the model mixed up the TMP manual's
        drop-off rules C and D (rule D's last item starts the next page). A
        merged passage keeps its first page as `page`, its last as `page_end`
        and the chunks it was made from as `parts` (answer.narrow uses them to
        cite only the pages an answer drew on).
        """
        passages: List[Hit] = []
        last_position = None
        for hit in sorted(hits, key=lambda h: self.index.position(h.chunk)):
            position = self.index.position(hit.chunk)
            previous = passages[-1].chunk if passages else None
            if previous is not None and position == last_position + 1 and previous.get("source") == hit.chunk.get("source"):
                merged = dict(previous, text=previous["text"] + "\n\n" + hit.chunk["text"])
                merged["parts"] = previous.get("parts", [previous]) + [hit.chunk]
                if hit.chunk.get("page") != previous.get("page"):
                    merged["page_end"] = hit.chunk.get("page")
                merged["section"] = _join_sections(previous.get("section"), hit.chunk.get("section"))
                passages[-1] = Hit(max(passages[-1].score, hit.score), merged)
            else:
                passages.append(hit)
            last_position = position
        return passages


def _join_sections(first, second):
    names = [s for part in (first, second) if part for s in part.split("; ")]
    return "; ".join(dict.fromkeys(names)) or None
