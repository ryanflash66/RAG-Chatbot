"""Answer a question from one division's documents, with citations.

The flow for one question:

1. retrieve the asked ("target") division's best passages, and only theirs;
2. ask the model to answer from those passages alone, citing them as [n];
3. keep the passages the answer cites, renumbered 1..m in order of first
   mention (one source per document page), with document title, PDF page,
   section and a link to the public PDF at that page.

When the model says the passages don't answer the question, or its answer
cites none of them, the reply is a refusal that names the division's documents
and shows no sources; if another division's documents look relevant, it
suggests asking that division instead.

The asker's own division only shapes the wording (who the answer is for); its
documents are never searched.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .divisions import BY_ID, DIVISIONS, Division, document_for
from .index_file import Hit
from .llm import Completion, LLMError, OpenRouterClient
from .retrieval import Retriever

NOT_FOUND = "NOT_IN_DOCUMENTS"
# Cross-encoder (ms-marco MiniLM) score above which another division's best
# passage counts as relevant enough to suggest asking that division instead.
SUGGEST_THRESHOLD = 0.0
# A refusal is retried once when the best passage's reranker score is at least
# this. Scores of questions the documents answer were 0.9-7.8 (bore-and-jack
# cover, which the free model sometimes refused: 3.5); questions they don't
# answer scored -9.4 to -3.5, and the HAWKS question, whose topic the manual
# mentions without the criteria, 0.5. 1.0 keeps all of those refusals fast.
RETRY_MIN_SCORE = 1.0
RETRY_MIN_SECONDS = 15.0
# The retry stops this long before the request's deadline so the refusal can still be returned.
RETRY_MARGIN_SECONDS = 1.0
EXCERPT_CHARS = 700
# The best hits also bring the next chunk of their document (see Retriever.with_following).
FOLLOWING_FOR_TOP = 2

SYSTEM_PROMPT = """You answer questions for North Carolina Department of Transportation (NCDOT) staff.
You are answering on behalf of the {target_name} division ({target_unit}), using only numbered passages from its documents.
{asker_line}

Rules:
1. Use only the numbered passages. Do not use outside knowledge, and do not guess or fill gaps.
2. Cite the passage that supports each sentence inline, like [1] or [2][3]. Every sentence that states a fact, number or requirement needs a citation.
3. If the passages do not answer the question, reply with exactly {not_found} and nothing else.
4. If the passages answer only part of the question, answer that part with citations and say plainly which part the documents don't cover.
5. When reading a table, find the row and the column that match the question, and take the unit from that column's header. Answer in the units the question uses, and always state the unit.
6. Start with the direct answer. Keep it short: one to four sentences, or a short list when there are several requirements. Use plain language.
7. Don't mention "passages" or "context"; refer to the document by name if needed."""

USER_PROMPT = """Passages from the {target_name} division's documents:

{context}

Question: {question}"""

# One bracketed citation: "[1]", "[1, 2]", "[1; 2]", "[1-3]", "[1–3]", and the
# lenticular/full-width brackets some models use: "【2】", "［2］".
_CITATION = re.compile(r"[\[【［]\s*(\d+(?:\s*[,;\-–]\s*\d+)*)\s*[\]】］]")
_EMPTY_CITATION = re.compile(r"\s*[\[【［]\s*(?:none|n/?a)\s*[\]】］]", re.IGNORECASE)
_RANGE = re.compile(r"(\d+)\s*[\-–]\s*(\d+)")
_MARKDOWN_NOISE = re.compile(r"<!--.*?-->|\*\*|__|^#{1,6}\s*|<br>|</?(?:mark|u|sup|sub)>", re.MULTILINE | re.DOTALL)


@dataclass(frozen=True)
class Source:
    n: int
    division: str
    title: str
    page: Optional[int]
    page_end: Optional[int]
    section: Optional[str]
    url: str
    excerpt: str

    def as_dict(self) -> Dict:
        return {
            "n": self.n, "division": self.division, "title": self.title, "page": self.page,
            "page_end": self.page_end, "section": self.section, "url": self.url, "excerpt": self.excerpt,
        }


@dataclass
class Answer:
    answer: str
    refused: bool
    sources: List[Source] = field(default_factory=list)
    model: Optional[str] = None
    suggest: List[str] = field(default_factory=list)  # division ids worth asking instead
    retried: bool = False  # a refusal was followed by a second model call

    def as_dict(self) -> Dict:
        return {
            "answer": self.answer,
            "refused": self.refused,
            "sources": [s.as_dict() for s in self.sources],
            "model": self.model,
            "suggest": [{"id": d, "name": BY_ID[d].name} for d in self.suggest],
        }


def _locator(hit: Hit) -> str:
    chunk = hit.chunk
    document = document_for(chunk.get("source") or "")
    parts = [document.title if document else (chunk.get("source") or "unknown document")]
    if chunk.get("page"):
        parts.append(_pages(chunk))
    if chunk.get("section"):
        parts.append(f"section {chunk['section']}")
    return ", ".join(parts)


def _pages(chunk: Dict) -> str:
    if chunk.get("page_end") and chunk["page_end"] != chunk.get("page"):
        return f"PDF pages {chunk['page']}–{chunk['page_end']}"
    return f"PDF page {chunk['page']}"


def build_messages(question: str, asker: Division, target: Division, hits: List[Hit]) -> List[Dict[str, str]]:
    if asker.id == target.id:
        asker_line = f"The person asking also works in {target.name}."
    else:
        asker_line = (
            f"The person asking works in a different division, {asker.name} ({asker.unit}), and may not know "
            f"{target.name}'s terms; explain them briefly only where the passages do."
        )
    system = SYSTEM_PROMPT.format(
        target_name=target.name, target_unit=target.unit, asker_line=asker_line, not_found=NOT_FOUND
    )
    context = "\n\n---\n\n".join(f"[{n}] ({_locator(hit)})\n{hit.chunk['text']}" for n, hit in enumerate(hits, 1))
    user = USER_PROMPT.format(target_name=target.name, context=context, question=question)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _marker_numbers(marker: "re.Match[str]", n_hits: int) -> List[int]:
    """Valid passage numbers in one citation marker; out-of-range and malformed parts are dropped."""
    numbers: List[int] = []
    for part in re.split(r"\s*[,;]\s*", marker.group(1)):
        span = _RANGE.fullmatch(part)
        if span:
            low, high = int(span.group(1)), int(span.group(2))
            candidates = range(low, high + 1) if low <= high <= n_hits else []
        else:
            candidates = [int(part)] if part.isdigit() else []
        numbers += [n for n in candidates if 1 <= n <= n_hits and n not in numbers]
    return numbers


def cited_numbers(text: str, n_hits: int) -> List[int]:
    """1-based passage numbers cited in the text, in order of first mention."""
    cited: List[int] = []
    for marker in _CITATION.finditer(text):
        cited += [n for n in _marker_numbers(marker, n_hits) if n not in cited]
    return cited


def _excerpt(text: str) -> str:
    clean = " ".join(_MARKDOWN_NOISE.sub(" ", text).split())
    return clean if len(clean) <= EXCERPT_CHARS else clean[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"


def _source_for(hit: Hit, n: int) -> Source:
    chunk = hit.chunk
    document = document_for(chunk.get("source") or "")
    page = chunk.get("page")
    url = document.url if document else ""
    if url and page:
        url = f"{url}#page={page}"
    return Source(
        n=n,
        division=chunk.get("division") or "",
        title=document.title if document else (chunk.get("source") or "Unknown document"),
        page=page,
        page_end=chunk.get("page_end"),
        section=chunk.get("section"),
        url=url,
        excerpt=_excerpt(chunk.get("text") or ""),
    )


_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)*")
_STOPWORDS = frozenset(
    "the and for with that this from are any all not may must shall should will within than then into "
    "per its has have been was were when where which who what how can each other such only also".split()
)
# A part of a merged passage is cited when it holds at least half of the
# best part's overlap with the citing sentences.
_PART_SHARE = 0.5


def _words(text: str) -> set:
    return {w for w in _WORD.findall(text.lower()) if (len(w) > 2 or w[0].isdigit()) and w not in _STOPWORDS}


def _citing_sentences(text: str, n: int, n_hits: int) -> str:
    sentences = re.split(r"(?<=[.!?\]])\s+(?=[A-Z0-9])", text)
    return " ".join(s for s in sentences if any(n in _marker_numbers(m, n_hits) for m in _CITATION.finditer(s)))


def narrow(chunk: Dict, sentences: str) -> Dict:
    """The part of a merged passage (Retriever.as_passages) that the citing sentences draw on.

    Merged passages help the model read a rule that runs across pages, but a
    citation should name the page(s) the answer came from, not the whole run.
    Parts are scored by how many of the sentences' words they contain; the
    pages of the parts close to the best score are kept.
    """
    parts = chunk.get("parts") or []
    if len(parts) < 2:
        return chunk
    words = _words(_CITATION.sub(" ", sentences))
    scores = [len(words & _words(part["text"])) for part in parts]
    best = max(scores)
    if best == 0:
        return chunk
    kept = [part for part, score in zip(parts, scores) if score >= _PART_SHARE * best]
    pages = [part["page"] for part in kept if part.get("page")]
    sections = [s for part in kept if part.get("section") for s in part["section"].split("; ")]
    narrowed = dict(kept[0], text="\n\n".join(part["text"] for part in kept), section="; ".join(dict.fromkeys(sections)) or None)
    narrowed.pop("page_end", None)
    if pages:
        narrowed["page"] = min(pages)
        if max(pages) != min(pages):
            narrowed["page_end"] = max(pages)
    return narrowed


def attach_sources(text: str, hits: List[Hit]) -> Tuple[str, List[Source]]:
    """Renumber the answer's citations 1..m and build one Source per cited document page.

    Passages from the same page of the same document share one number.
    Citations of passages that don't exist are removed.
    """
    text = _EMPTY_CITATION.sub("", text)
    new_number: Dict[int, int] = {}
    by_page: Dict[Tuple[str, Optional[int], Optional[int]], int] = {}
    sources: List[Source] = []
    for old in cited_numbers(text, len(hits)):
        chunk = narrow(hits[old - 1].chunk, _citing_sentences(text, old, len(hits)))
        key = (chunk.get("source") or "", chunk.get("page"), chunk.get("page_end"))
        if key not in by_page:
            by_page[key] = len(sources) + 1
            sources.append(_source_for(Hit(hits[old - 1].score, chunk), by_page[key]))
        new_number[old] = by_page[key]

    def rewrite(marker: "re.Match[str]") -> str:
        numbers = list(dict.fromkeys(new_number[n] for n in _marker_numbers(marker, len(hits)) if n in new_number))
        return "".join(f"[{n}]" for n in numbers)

    text = _CITATION.sub(rewrite, text)
    text = re.sub(r"(\[\d+\])(?:\s*\1)+", r"\1", text)  # "[1][1]" when two passages share a page
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text)  # "word [9]." with [9] removed -> "word."
    return text.strip(), sources


def refusal_text(target: Division, suggest: List[str]) -> str:
    titles = "; ".join(d.title for d in target.documents)
    text = f"I couldn't find an answer to that in the {target.name} documents ({titles})."
    if suggest:
        names = " or ".join(BY_ID[d].name for d in suggest)
        text += f" The {names} documents look more relevant: try asking {names} instead."
    else:
        text += " Try rephrasing the question, or ask the division that owns the topic."
    return text


log = logging.getLogger(__name__)


def _grade(raw: str, hits: List[Hit]) -> Tuple[str, List[Source]]:
    """The answer text and its sources; no sources means the reply is a refusal."""
    if raw.lstrip().startswith(NOT_FOUND):
        return "", []
    return attach_sources(raw.replace(NOT_FOUND, ""), hits)


class Answerer:
    def __init__(self, retriever: Retriever, llm: OpenRouterClient, top_k: int = 5,
                 retry_min_score: Optional[float] = RETRY_MIN_SCORE, retry_min_seconds: float = RETRY_MIN_SECONDS):
        self.retriever = retriever
        self.llm = llm
        self.top_k = top_k
        self.retry_min_score = retry_min_score  # None: never retry
        self.retry_min_seconds = retry_min_seconds

    def retrieve(self, question: str, target: Division) -> List[Hit]:
        hits = self.retriever.retrieve(question, division=target.id, k=self.top_k)
        return self.retriever.as_passages(self.retriever.with_following(hits, top=FOLLOWING_FOR_TOP))

    def suggest_divisions(self, question: str, target: Division) -> List[str]:
        """Other divisions whose best passage clears the reranker's relevance bar."""
        if self.retriever.reranker is None:
            return []
        suggest = []
        for division in DIVISIONS:
            if division.id == target.id:
                continue
            hits = self.retriever.retrieve(question, division=division.id, k=1)
            if hits and hits[0].score >= SUGGEST_THRESHOLD:
                suggest.append(division.id)
        return suggest

    def _worth_retrying(self, hits: List[Hit], deadline: Optional[float]) -> bool:
        """Retrieval was strong (reranker scores only) and enough of the request's time is left."""
        if self.retry_min_score is None or self.retriever.reranker is None:
            return False
        if max(hit.score for hit in hits) < self.retry_min_score:
            return False
        return deadline is None or deadline - time.monotonic() >= self.retry_min_seconds

    async def _retry(self, messages: List[Dict[str, str]], first: Completion, hits: List[Hit],
                     deadline: Optional[float]) -> Optional[Tuple[Completion, str, List[Source]]]:
        """Ask once more with the next model; the new answer if it is cited, else None."""
        models = self.llm.retry_models(first.model)
        log.info("refusal despite strong retrieval (top score %.2f): retrying %s with %s",
                 max(hit.score for hit in hits), first.model, models[0])
        timeout = None if deadline is None else deadline - time.monotonic() - RETRY_MARGIN_SECONDS
        try:
            second = await asyncio.wait_for(self.llm.complete(messages, models=models), timeout=timeout)
        except (LLMError, asyncio.TimeoutError) as exc:
            log.warning("retry failed (%s); keeping the refusal", exc.__class__.__name__)
            return None
        text, sources = _grade(second.text, hits)
        log.info("retry by %s: %s", second.model, "cited answer" if sources else "refused again")
        return (second, text, sources) if sources else None

    async def answer(self, question: str, asker: Division, target: Division, hits: List[Hit],
                     deadline: Optional[float] = None) -> Answer:
        """Answer from the hits. `deadline` is a time.monotonic() value that bounds the optional retry."""
        if not hits:
            return Answer(refusal_text(target, []), refused=True)
        messages = build_messages(question, asker, target, hits)
        completion = await self.llm.complete(messages)
        text, sources = _grade(completion.text, hits)
        retried = False
        if not sources and self._worth_retrying(hits, deadline):
            retried = True
            second = await self._retry(messages, completion, hits, deadline)
            if second:
                completion, text, sources = second
        if not sources:
            suggest = await asyncio.to_thread(self.suggest_divisions, question, target)
            return Answer(refusal_text(target, suggest), refused=True, model=completion.model, suggest=suggest, retried=retried)
        return Answer(text, refused=False, sources=sources, model=completion.model, retried=retried)
