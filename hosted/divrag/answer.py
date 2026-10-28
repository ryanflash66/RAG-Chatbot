"""Answer a question from one division's documents, with citations.

The flow for one question:

1. retrieve the asked ("target") division's best passages, and only theirs;
2. ask the model to answer from those passages alone, citing them as [n];
3. keep the passages the answer cites, renumbered 1..m in order of first
   mention (one source per document page), with document title, PDF page,
   section and a link to the public PDF at that page.

When the model says the passages don't answer the question, the reply is a
refusal that names the division's documents and shows no sources; if another
division's documents look relevant, it suggests asking that division instead.
An answer that cites none of the passages is kept and marked `uncited`, so the
page can flag it ("No source cited") instead of hiding it (DAR-629).

answer() waits for the model's whole reply; answer_stream() passes the text on
as it is written. Both grade, retry and refuse the same way.

The asker's own division only shapes the wording (who the answer is for); its
documents are never searched.

A follow-up question comes with the conversation so far (the page keeps it):
the search runs on the previous question plus the follow-up, and the prompt
shows the last turns only to explain what the question refers to. Facts and
citations still come from the new passages alone.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from .divisions import BY_ID, DIVISIONS, Division, document_for
from .index_file import Hit
from .llm import Completion, LLMError, OpenRouterClient
from .retrieval import Retriever
from .timing import StepTimer, timed

# emit(event, data): one server-sent event of a streamed answer ("step", "delta", "replace").
Emit = Callable[[str, Dict[str, Any]], None]
# One model call: (messages, models) -> the reply; models None means the configured list.
_Call = Callable[..., Awaitable[Completion]]

NOT_FOUND = "NOT_IN_DOCUMENTS"
# Cross-encoder (ms-marco MiniLM) score above which another division's best
# passage counts as relevant enough to suggest asking that division instead.
SUGGEST_THRESHOLD = 0.0
# Vector hits of another division reranked for the suggestion. Against 20, every
# yes/no decision on 70 question-division pairs was the same from 8 up (with 5,
# the open-cut trench question asked of Work Zone lost its "ask Utilities");
# reranking 20 added about 4.6 s to every refusal on Vercel.
SUGGEST_CANDIDATES = 10
# Time a suggestion check for one more division needs: an embedding plus 10
# reranks, about 2.3 s on Vercel by the figure above. With a third division
# (TMSD, DAR-622) a refusal checks two divisions, and a retry may end only
# RETRY_MARGIN_SECONDS before the deadline, so later checks are skipped rather
# than letting the refusal run past it.
SUGGEST_MIN_SECONDS = 3.0
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
# Follow-ups (DAR-619) are understood without an extra model call: the search
# runs on the previous question plus the follow-up, and the prompt carries the
# last few turns. The page sends at most this many already; the server keeps
# only these too, whatever arrives. Earlier answers are clipped because they
# only say what "it" or "that" refers to; the facts come from the new passages.
HISTORY_TURNS = 3
HISTORY_ANSWER_CHARS = 1500
# The previous question is clipped so a long one can't push the follow-up past
# the 512 tokens bge-small and the reranker read: the follow-up comes after it in
# the search text. 500 characters plus a follow-up of at most MAX_QUESTION_CHARS
# (500 by default) is about 250 tokens of English; a forged 5,000-character
# history question would otherwise fill the window on its own.
HISTORY_QUESTION_CHARS = 500

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

# Added to the rules only when the question comes with earlier turns, so a first
# question gets exactly the prompt the known-page checks were run with.
HISTORY_RULE = """
8. The earlier conversation, when shown, is only there to understand what the question refers to (for example "it" or "that barrier"). It is not a source: take every fact from the numbered passages and cite them, never from the earlier answers. If the passages do not answer the question, reply with exactly {not_found}, even if the earlier conversation did."""

USER_PROMPT = """{history}Passages from the {target_name} division's documents:

{context}

Question: {question}"""

HISTORY_PROMPT = """Earlier conversation, oldest first (only to understand what the question refers to; not a source):

{turns}

"""

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
    first_model: Optional[str] = None  # the model that answered the first call (differs from `model` after a retry)
    uncited: bool = False  # an answer (not a refusal) that cites none of the passages

    def as_dict(self) -> Dict:
        return {
            "answer": self.answer,
            "refused": self.refused,
            "uncited": self.uncited,
            "sources": [s.as_dict() for s in self.sources],
            "model": self.model,
            "first_model": self.first_model,
            "retried": self.retried,
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


def recent_turns(history: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    """The last HISTORY_TURNS turns of the conversation, oldest first."""
    return list(history)[-HISTORY_TURNS:]


def _clip(text: str, limit: int) -> str:
    """The text in at most `limit` characters (plus " …" when cut), never an empty prefix.

    It is cut after the last whole word when one ends near the limit; text with
    no space there (a pasted URL or part number) is cut at the limit itself.
    """
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit * 0.8 else cut) + " …"


def _history_text(history: Sequence[Dict[str, str]]) -> str:
    """The earlier turns for the user message; empty when there are none.

    Their [n] markers are removed: they numbered the earlier answer's passages,
    and left in they would read as citations of this question's passages. A turn
    with an empty answer is a question asked of another division, which the page
    sends when one of its "Ask … instead" buttons is used; only its question is shown.
    """
    turns = []
    for turn in recent_turns(history):
        text = f"Earlier question: {_clip(turn.get('question') or '', HISTORY_QUESTION_CHARS)}"
        answer = _CITATION.sub("", _EMPTY_CITATION.sub("", turn.get("answer") or ""))
        answer = _clip(re.sub(r"[ \t]+([.,;:])", r"\1", answer), HISTORY_ANSWER_CHARS)
        turns.append(f"{text}\nEarlier answer: {answer}" if answer else text)
    return HISTORY_PROMPT.format(turns="\n\n".join(turns)) if turns else ""


def build_messages(question: str, asker: Division, target: Division, hits: List[Hit],
                   history: Sequence[Dict[str, str]] = ()) -> List[Dict[str, str]]:
    """The system and user messages for one question.

    `history` is the conversation so far ([{"question", "answer"}], oldest
    first). Its last HISTORY_TURNS turns go before the passages, with a rule
    that they only explain what the question refers to.
    """
    if asker.id == target.id:
        asker_line = f"The person asking also works in {target.name}."
    else:
        asker_line = (
            f"The person asking works in a different division, {asker.name} ({asker.unit}), and may not know "
            f"{target.name}'s terms; explain them briefly only where the passages do."
        )
    earlier = _history_text(history)
    system = SYSTEM_PROMPT.format(
        target_name=target.name, target_unit=target.unit, asker_line=asker_line, not_found=NOT_FOUND
    )
    if earlier:
        system += HISTORY_RULE.format(not_found=NOT_FOUND)
    context = "\n\n---\n\n".join(f"[{n}] ({_locator(hit)})\n{hit.chunk['text']}" for n, hit in enumerate(hits, 1))
    user = USER_PROMPT.format(history=earlier, target_name=target.name, context=context, question=question)
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


# Up to this many documents, a refusal names them; beyond it, it counts them. With the
# 50-document stress test (DAR-621) a division has up to 20, and listing every title made a
# refusal about 2,000 characters long; the page's document panel lists them anyway.
_REFUSAL_TITLES = 3


def refusal_text(target: Division, suggest: List[str]) -> str:
    if len(target.documents) <= _REFUSAL_TITLES:
        searched = "; ".join(d.title for d in target.documents)
    else:
        searched = f"{len(target.documents)} documents"
    text = f"I couldn't find an answer to that in the {target.name} documents ({searched})."
    if len(suggest) == 1:
        name = BY_ID[suggest[0]].name
        text += f" The {name} documents look more relevant: try asking {name} instead."
    elif suggest:
        # Listed, not joined with "or": "Transportation Mobility and Safety" already has an "and" in it.
        names = "; ".join(BY_ID[d].name for d in suggest)
        text += f" Other divisions' documents look more relevant; try asking one of them instead: {names}."
    else:
        text += " Try rephrasing the question, or ask the division that owns the topic."
    return text


log = logging.getLogger(__name__)


def _grade(raw: str, hits: List[Hit]) -> Tuple[str, List[Source]]:
    """The answer text and its sources.

    Empty text means the model said the documents don't answer the question.
    Text without sources is an answer that cites none of the passages: it is
    kept and flagged, not turned into a refusal (DAR-629). A reply that uses
    NOT_FOUND inside a sentence and cites nothing ("I'm sorry, NOT_IN_DOCUMENTS")
    is a refusal worded around the marker, not an answer.
    """
    if _lead(raw).startswith(NOT_FOUND):
        return "", []
    text, sources = attach_sources(raw.replace(NOT_FOUND, ""), hits)
    if NOT_FOUND in raw and not sources:
        return "", []
    return text, sources


def _lead(text: str) -> str:
    """The text without leading whitespace and Markdown emphasis, where a reply that refuses starts with NOT_FOUND."""
    return text.lstrip(" \t\r\n*_`")


def _marker_start(text: str) -> int:
    """How many characters at the end of `text` could be the beginning of NOT_FOUND."""
    for size in range(min(len(NOT_FOUND) - 1, len(text)), 0, -1):
        if text.endswith(NOT_FOUND[:size]):
            return size
    return 0


# A complete citation marker in streamed text, with the spaces before it ("feet [3]." shows as "feet.").
_STREAMED_CITATION = re.compile(r"[ \t]*[\[【［]\s*(?:\d+(?:\s*[,;\-–]\s*\d+)*|none|n/?a)\s*[\]】］]", re.IGNORECASE)
# What the end of streamed text holds back: trailing spaces, and a bracket not yet closed
# that may be the start of a citation (short, as markers are).
_OPEN_TAIL = re.compile(r"[ \t]*(?:[\[【［][^\]】］\n]{0,20})?$")


class _VisibleText:
    """Which part of a reply that is still being written can be shown yet.

    The start is held back until it can't be NOT_FOUND, so a refusal's marker
    never flashes on the page, and a reply that starts with it shows nothing
    (_grade makes it a refusal). Further in, the marker is cut out as _grade
    cuts it, holding back a tail that could be its beginning.

    Citation markers are left out too: they carry the prompt's passage
    numbers, which the citation check renumbers ([4] may become [1]), so the
    answer's citations appear only with the checked answer.
    """

    def __init__(self) -> None:
        self._held = ""
        self._flowing = False  # the start is not the marker: text is shown as it comes
        self.refusal = False

    def feed(self, piece: str) -> str:
        """The new text to show after `piece` (often "")."""
        if self.refusal:
            return ""
        self._held += piece
        if not self._flowing:
            head = _lead(self._held)
            if head.startswith(NOT_FOUND):
                self.refusal, self._held = True, ""
                return ""
            if NOT_FOUND.startswith(head):  # "", "**" or e.g. "NOT_IN": could still become the marker
                return ""
            # Leading whitespace goes, as the final answer is stripped; emphasis stays.
            self._flowing, self._held = True, self._held.lstrip()
        text = _STREAMED_CITATION.sub("", self._held.replace(NOT_FOUND, ""))
        tail = _OPEN_TAIL.search(text)
        cut = min(tail.start() if tail else len(text), len(text) - _marker_start(text))
        self._held = text[cut:]
        return text[:cut]

    def end(self) -> str:
        """The text still held back once the reply is complete."""
        if self.refusal or not self._flowing:
            rest = "" if self.refusal else self._held.strip()
        else:
            rest = self._held.rstrip()
        self._held = ""
        return _STREAMED_CITATION.sub("", rest.replace(NOT_FOUND, ""))


# The steps the page shows while it answers (DAR-629), in order, with the
# StepTimer steps each is made of. "read" includes loading the models on a cold
# instance, so that wait shows as the first step instead of a pause before it.
LIVE_STEPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("read", ("model_load", "embed")),
    ("search", ("search",)),
    ("rerank", ("rerank",)),
    ("write", ("llm",)),
    ("check", ("citations",)),
    ("retry", ("retry",)),
    ("suggest", ("suggest",)),
)

# Steps that only run after a refusal, so the page isn't told about them in
# advance: most answers never retry or suggest, and a step left "not started"
# at the end would read as if the answer stopped short (DAR-636).
OCCASIONAL_STEPS = ("retry", "suggest")


def live_step_labels(target: Division, passages: int, top_k: int) -> Dict[str, str]:
    """What the page calls each live step; `passages` is how many the search looks through."""
    return {
        "read": "Reading your question",
        "search": f"Searching {target.name} documents ({passages:,} passages)",
        "rerank": f"Picking the {top_k} best passages",
        "write": "Writing the answer",
        "check": "Checking sources",
        "retry": "Double-checking the source…",
        "suggest": "Checking whether another division covers it",
    }


class LiveSteps:
    """A StepTimer listener that turns the timer's steps into the steps the page shows.

    A live step starts with the first of its timer steps and is done after the
    last one, with their times added, so its ms are the ones in timing_ms.
    `done` lists the finished ones, [{"id", "label", "ms"}], for the answer's
    payload; with `emit`, each start and finish is also sent as it happens:
    emit("step", {"id", "label", "status": "start" | "done", "ms"}), after
    announce() has sent the expected ones as "pending".
    """

    def __init__(self, labels: Dict[str, str], emit: Optional[Emit] = None):
        self._labels = labels
        self._emit = emit
        self._live = {part: live for live, parts in LIVE_STEPS for part in parts}
        self._last = {live: parts[-1] for live, parts in LIVE_STEPS}
        self._running: Dict[str, int] = {}
        self.done: List[Dict[str, Any]] = []

    def announce(self, rerank: bool) -> None:
        """Send each step expected to run as pending, in order, before the first one starts.

        The page lists every step from the start as not started (DAR-636: on the
        Oct 22 demo a list that grew one step at a time was confusing). rerank runs
        only with a reranker; retry and suggest (OCCASIONAL_STEPS) appear when they start.
        """
        for live, _ in LIVE_STEPS:
            if live in OCCASIONAL_STEPS or (live == "rerank" and not rerank):
                continue
            self._send(live, "pending", 0)

    def __call__(self, step: str, status: str, ms: int) -> None:
        live = self._live[step]
        if status == "start":
            if live not in self._running:
                self._running[live] = 0
                self._send(live, "start", 0)
            return
        self._running[live] = self._running.get(live, 0) + ms
        if step == self._last[live]:
            ms = self._running.pop(live)
            self.done.append({"id": live, "label": self._labels[live], "ms": ms})
            self._send(live, "done", ms)

    def _send(self, live: str, status: str, ms: int) -> None:
        if self._emit:
            self._emit("step", {"id": live, "label": self._labels[live], "status": status, "ms": ms})


class Answerer:
    def __init__(self, retriever: Retriever, llm: OpenRouterClient, top_k: int = 5,
                 retry_min_score: Optional[float] = RETRY_MIN_SCORE, retry_min_seconds: float = RETRY_MIN_SECONDS):
        self.retriever = retriever
        self.llm = llm
        self.top_k = top_k
        self.retry_min_score = retry_min_score  # None: never retry
        self.retry_min_seconds = retry_min_seconds

    def search_query(self, question: str, history: Sequence[Dict[str, str]] = ()) -> str:
        """The text to search with: the previous question plus this one when there is history.

        A follow-up such as "What if it is more than 6 feet from the edge?" says
        nothing about bridge-deck barrier on its own, so searched alone it finds
        other 6-foot rules. Prefixing only the latest question keeps the topic
        without letting older turns outweigh the new question. No model call
        rewrites the question, which keeps follow-ups as fast as first questions.
        The previous question is clipped to HISTORY_QUESTION_CHARS so the
        follow-up after it always stays inside the models' 512-token window.
        """
        turns = recent_turns(history)
        previous = _clip(turns[-1].get("question") or "", HISTORY_QUESTION_CHARS) if turns else ""
        return f"{previous} {question}" if previous else question

    def retrieve(self, question: str, target: Division, timer: Optional[StepTimer] = None,
                 documents: Optional[Sequence[str]] = None, history: Sequence[Dict[str, str]] = ()) -> List[Hit]:
        """The passages for the question from `target`'s documents (only `documents` when given)."""
        hits = self.retriever.retrieve(self.search_query(question, history), division=target.id, k=self.top_k,
                                       timer=timer, sources=documents)
        return self.retriever.as_passages(self.retriever.with_following(hits, top=FOLLOWING_FOR_TOP))

    def suggest_divisions(self, question: str, target: Division, deadline: Optional[float] = None,
                          refused_by: Sequence[str] = ()) -> List[str]:
        """Other divisions whose best passage clears the reranker's relevance bar.

        `refused_by` are divisions that already refused this question (the page
        sends them after an "Ask … instead"); they are never suggested again.
        Otherwise two divisions whose passages both mention the topic send the
        visitor back and forth: after DAR-621, "lane closure" scored above
        SUGGEST_THRESHOLD in both Work Zone and Utilities, and each refusal
        suggested the other.

        Divisions are checked one after another, and the check stops when less
        than SUGGEST_MIN_SECONDS of the request is left, so a refusal that comes
        late (after a retry) is still returned, without the later suggestions.
        """
        if self.retriever.reranker is None:
            return []
        suggest = []
        for division in DIVISIONS:
            if division.id == target.id or division.id in refused_by:
                continue
            if deadline is not None and deadline - time.monotonic() < SUGGEST_MIN_SECONDS:
                log.info("skipping the remaining division suggestions: too little time left")
                break
            hits = self.retriever.retrieve(question, division=division.id, k=1, candidates=SUGGEST_CANDIDATES)
            if hits and hits[0].score >= SUGGEST_THRESHOLD:
                suggest.append(division.id)
        return suggest

    def _worth_retrying(self, hits: List[Hit], deadline: Optional[float]) -> bool:
        """Retrieval was strong (reranker scores only) and enough of the request's time is left."""
        if self.retry_min_score is None or self.retriever.reranker is None:
            return False
        if max(hit.score for hit in hits) < self.retry_min_score:
            return False
        if deadline is None:
            return True
        left = deadline - time.monotonic()
        # More than the margin must be left, or _retry would give the call no time and report a retry that never ran.
        return left >= self.retry_min_seconds and left > RETRY_MARGIN_SECONDS

    async def _retry(self, messages: List[Dict[str, str]], first: Completion, hits: List[Hit],
                     deadline: Optional[float], call: _Call) -> Optional[Tuple[Completion, str, List[Source]]]:
        """Ask once more with the next model: its reply and that reply graded, or None if the call failed.

        Only a cited answer replaces the refusal (see _answer). An uncited answer
        is kept when it is the first reply, but not in place of a refusal: one
        model saying the documents don't cover it and the next answering
        without pointing to a passage is the case most likely to come from
        outside the documents.
        """
        models = self.llm.retry_models(first.model)
        log.info("refusal despite strong retrieval (top score %.2f): retrying %s with %s",
                 max(hit.score for hit in hits), first.model, models[0])
        timeout = None if deadline is None else deadline - time.monotonic() - RETRY_MARGIN_SECONDS
        try:
            second = await asyncio.wait_for(call(messages, models=models), timeout=timeout)
        except (LLMError, asyncio.TimeoutError) as exc:
            log.warning("retry failed (%s); keeping the refusal", exc.__class__.__name__)
            return None
        text, sources = _grade(second.text, hits)
        log.info("retry by %s: %s", second.model,
                 "cited answer" if sources else "uncited answer, keeping the refusal" if text else "refused again")
        return second, text, sources

    async def answer(self, question: str, asker: Division, target: Division, hits: List[Hit],
                     deadline: Optional[float] = None, timer: Optional[StepTimer] = None,
                     history: Sequence[Dict[str, str]] = (), refused_by: Sequence[str] = ()) -> Answer:
        """Answer from the hits.

        `deadline` is a time.monotonic() value that bounds the optional retry;
        `timer` records the llm, citations, retry and suggest steps; `history`
        is the conversation so far (see build_messages); `refused_by` are
        divisions a refusal must not suggest (see suggest_divisions).
        """
        return await self._answer(question, asker, target, hits, deadline, timer, history, self.llm.complete,
                                  refused_by)

    async def answer_stream(self, question: str, asker: Division, target: Division, hits: List[Hit], emit: Emit,
                            deadline: Optional[float] = None, timer: Optional[StepTimer] = None,
                            history: Sequence[Dict[str, str]] = (), refused_by: Sequence[str] = ()) -> Answer:
        """answer(), passing the model's text on while it is written.

        emit("delta", {"text"}) gets each new piece of text to show, and
        emit("replace", {"text": ""}) clears it when the retry starts over. The
        returned Answer is the one answer() would give: its text is graded and
        renumbered, so it replaces the streamed text once it is complete.
        """
        calls = 0

        async def call(messages: List[Dict[str, str]], models: Optional[Sequence[str]] = None) -> Completion:
            nonlocal calls
            calls += 1
            if calls > 1:
                emit("replace", {"text": ""})
            return await self._streamed(messages, models, emit)

        return await self._answer(question, asker, target, hits, deadline, timer, history, call, refused_by)

    async def _streamed(self, messages: List[Dict[str, str]], models: Optional[Sequence[str]], emit: Emit) -> Completion:
        """One streamed model call, its visible text emitted as "delta" events."""
        visible = _VisibleText()
        stream = self.llm.complete_stream(messages, models=models)
        async for piece in stream:
            text = visible.feed(piece)
            if text:
                emit("delta", {"text": text})
        rest = visible.end()
        if rest:
            emit("delta", {"text": rest})
        return Completion(stream.text, stream.model)

    async def _answer(self, question: str, asker: Division, target: Division, hits: List[Hit],
                      deadline: Optional[float], timer: Optional[StepTimer], history: Sequence[Dict[str, str]],
                      call: _Call, refused_by: Sequence[str] = ()) -> Answer:
        """The answer, with `call` asking the model (complete(), or a streamed call)."""
        if not hits:
            return Answer(refusal_text(target, []), refused=True)
        messages = build_messages(question, asker, target, hits, history)
        with timed(timer, "llm"):
            completion = await call(messages)
        first_model = completion.model
        with timed(timer, "citations"):
            text, sources = _grade(completion.text, hits)
        retried = False
        # Only a "not found" is retried: it is short, so the retry costs little
        # before the visitor sees an answer, while a written-out uncited answer is kept.
        if not text and self._worth_retrying(hits, deadline):
            retried = True
            with timed(timer, "retry"):
                second = await self._retry(messages, completion, hits, deadline, call)
            if second and second[2]:
                completion, text, sources = second
            elif second:
                # Still a refusal, now from the retry's model: name that one, so the
                # page shows which two models refused instead of the first one twice.
                completion = second[0]
        if not text:
            with timed(timer, "suggest"):
                # The same text the question was searched with, so a refused follow-up is matched on its topic.
                suggest = await asyncio.to_thread(self.suggest_divisions, self.search_query(question, history), target,
                                                  deadline, refused_by)
            return Answer(refusal_text(target, suggest), refused=True, model=completion.model, suggest=suggest,
                          retried=retried, first_model=first_model)
        return Answer(text, refused=False, sources=sources, model=completion.model, retried=retried,
                      first_model=first_model, uncited=not sources)
