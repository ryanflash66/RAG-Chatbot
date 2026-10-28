"""The hosted demo: one FastAPI app that serves the page and answers questions.

    GET  /                the page (public/index.html; public/css and public/js beside it)
    GET  /api/divisions   divisions, their documents (with passage counts) and example questions
    POST /api/warm        load the models now, returning once they are ready
    POST /api/ask         {"question", "asker", "target", "history"?, "documents"?, "refused_by"?}
                          -> answer with cited sources, timing_ms per step and
                             searched {documents, passages}
    POST /api/ask/stream  the same question; the steps, the answer's text as it is
                          written, then the same answer, as server-sent events
    GET  /api/health      index and model settings (no secrets)

Vercel loads `app` from this file (a FastAPI entrypoint at the project root,
with hosted/ as the Root Directory). Locally:

    .venv/Scripts/python -m uvicorn index:app --app-dir hosted --env-file .env --port 8000

Models load when the page calls /api/warm (on load, and again when the visitor
picks a division or starts typing) or on the first question, not at import, so a
cold start can serve the page quickly. /api/warm holds its request open until the
models are ready: a background thread started by a request that already returned
can be frozen by Vercel, which left the Oct 16 first question 14 s of retrieval
despite a warm-up.
"""

import asyncio
import json
import logging
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import AsyncIterator, Deque, Dict, List, NamedTuple, Optional, Tuple, Union

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from divrag.answer import Answer, Answerer, Emit, LiveSteps, live_step_labels
from divrag.config import Settings, load_settings
from divrag.divisions import BY_ID, DIVISIONS, Division
from divrag.embedder import Embedder, Reranker, cpu_info, model_cache_dir
from divrag.index_file import IndexFile
from divrag.llm import MISCONFIGURED, TOO_SLOW, LLMError, OpenRouterClient, tls_context
from divrag.retrieval import Retriever
from divrag.timing import StepTimer

PUBLIC_DIR = Path(__file__).resolve().parent / "public"
# The answer call always gets at least this long, even if retrieval ate the budget.
MIN_ANSWER_SECONDS = 5.0
# Vercel stops the function at 60 s (vercel.json maxDuration), and a stream it
# stops just ends, with no done or error event. So the stream ends itself with
# an error first: STREAM_MARGIN_SECONDS after the request budget (whose deadline
# normally ends the answer, refusal included), and never later than
# STREAM_LIMIT_SECONDS. It only matters when loading the models ate the budget
# and MIN_ANSWER_SECONDS runs past it.
STREAM_MARGIN_SECONDS = 2.0
STREAM_LIMIT_SECONDS = 59.0
GENERIC_ERROR = "Something went wrong answering that question. Please try again."

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hosted")

settings: Settings = load_settings()
app = FastAPI(title="NCDOT cross-division Q&A demo", docs_url=None, redoc_url=None, openapi_url=None)

if settings.allowed_origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


class _Runtime:
    """The index, models and LLM client, built once per server instance."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._retriever: Optional[Retriever] = None
        self.index = IndexFile.load(settings.index_dir)

    def retriever(self) -> Retriever:
        with self._lock:
            if self._retriever is None:
                started = time.perf_counter()
                cache = model_cache_dir()
                embedder = Embedder(self.index.model, cache_dir=cache)
                reranker = Reranker(cache_dir=cache) if self.settings.rerank else None
                retriever = Retriever(self.index, embedder, reranker, candidates=self.settings.rerank_candidates)
                retriever.warm_up()
                tls_context()  # for the model calls, off the event loop
                log.info("models loaded from %s in %.1fs", cache, time.perf_counter() - started)
                self._retriever = retriever
            return self._retriever

    def answerer(self, llm: OpenRouterClient) -> Answerer:
        s = self.settings
        return Answerer(self.retriever(), llm, top_k=s.top_k, retry_min_score=s.retry_min_score if s.retry_on_refusal else None,
                        retry_min_seconds=s.retry_min_seconds)


runtime = _Runtime(settings)


class _RateLimiter:
    """At most `limit` requests per client per minute (per server instance; best effort)."""

    def __init__(self, limit: int, window: float = 60.0):
        self.limit = limit
        self.window = window
        self._seen: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client: str) -> bool:
        now = time.monotonic()
        with self._lock:
            seen = self._seen[client]
            while seen and now - seen[0] > self.window:
                seen.popleft()
            if len(seen) >= self.limit:
                return False
            seen.append(now)
            return True


limiter = _RateLimiter(settings.rate_limit_per_minute)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class Turn(BaseModel):
    """One earlier exchange of the conversation, as the page sends it back."""
    question: str = Field(max_length=5000)
    answer: str = Field(max_length=4000)


class AskRequest(BaseModel):
    # Generous hard caps; the friendly limit (MAX_QUESTION_CHARS) is checked in _check().
    question: str = Field(max_length=5000)
    asker: str = Field(max_length=40)
    target: str = Field(max_length=40)
    # The conversation so far, oldest first (DAR-619); the page keeps it, the server stores nothing.
    history: List[Turn] = Field(default_factory=list, max_length=6)
    # Document files (divisions.py `file`) to search; None searches all of the target's documents (DAR-620).
    # The page sends every ticked file when only some are ticked, so the cap is well above any
    # division's document count today (20 at most, after DAR-621); a selection over it would get a 422.
    documents: Optional[List[str]] = Field(default=None, max_length=200)
    # Divisions that already refused this question, sent by an "Ask … instead": a refusal never suggests them again.
    refused_by: List[str] = Field(default_factory=list, max_length=20)


class Question(NamedTuple):
    """A request that passed the checks every answering endpoint shares."""
    text: str
    asker: Division
    target: Division
    documents: Optional[List[str]]
    history: List[Dict[str, str]]
    refused_by: Tuple[str, ...] = ()


def _check(body: AskRequest, request: Request) -> Union[Question, JSONResponse]:
    """The cleaned-up question, or the error reply to send instead."""
    question = " ".join(body.question.split())
    if len(question) < 3:
        return _error(400, "Please type a question.")
    if len(question) > settings.max_question_chars:
        return _error(400, f"Please keep the question under {settings.max_question_chars} characters.")
    asker, target = BY_ID.get(body.asker), BY_ID.get(body.target)
    if asker is None or target is None:
        return _error(400, "Unknown division.")
    documents = None
    if body.documents is not None:
        # Only the target's own documents can be searched; anything else is dropped, never searched.
        owned = {doc.file for doc in target.documents}
        documents = [d for d in dict.fromkeys(body.documents) if d in owned]
        if not documents:
            return _error(400, "Pick at least one document to search.")
    if not limiter.allow(_client_ip(request)):
        return _error(429, "Too many questions in a short time. Please wait a minute and try again.")
    if not settings.openrouter_api_key:
        log.error("OPENROUTER_API_KEY is not set")
        return _error(503, MISCONFIGURED)
    # Unknown ids are dropped: they could only ever skip a division that doesn't exist.
    refused_by = tuple(d for d in dict.fromkeys(body.refused_by) if d in BY_ID)
    return Question(question, asker, target, documents, [t.model_dump() for t in body.history], refused_by)


def _make_llm() -> OpenRouterClient:
    return OpenRouterClient(settings.openrouter_api_key or "", settings.models, settings.temperature, settings.reasoning)


def _searched(target: Division, documents: Optional[List[str]]) -> Dict[str, int]:
    """What a question to `target` looked through, for the page's "Searched N passages in M documents".

    The vector search scores every passage the division and document filters
    let through, so the count of those rows is the number searched, not the
    handful that reached the reranker. `documents` None means all of the target's.
    """
    searched = len(documents) if documents is not None else len(target.documents)
    return {"documents": searched, "passages": runtime.index.count(target.id, documents)}


@app.get("/", include_in_schema=False)
def page() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html", media_type="text/html")


@app.get("/api/divisions")
def divisions() -> Dict:
    # passages: how many chunks a search of that document, or of the whole division, looks through.
    # They come from the index loaded at import, so listing them never waits for the models.
    count = runtime.index.count
    return {
        "divisions": [
            {
                "id": d.id,
                "name": d.name,
                "unit": d.unit,
                "passages": count(d.id),
                "documents": [{"file": doc.file, "title": doc.title, "url": doc.url, "passages": count(d.id, [doc.file])}
                              for doc in d.documents],
                "examples": list(d.examples),
            }
            for d in DIVISIONS
        ],
        "max_question_chars": settings.max_question_chars,
    }


@app.post("/api/warm")
def warm():
    """Load the models while the visitor picks divisions and types; instant once loaded."""
    started = time.perf_counter()
    try:
        runtime.retriever()
    except Exception:  # noqa: BLE001 - the next question reports the real error
        log.exception("model warm-up failed")
        return JSONResponse({"ready": False}, status_code=503)
    return {"ready": True, "ms": _ms_since(started)}


@app.get("/api/health")
def health() -> Dict:
    counts: Dict[str, int] = defaultdict(int)
    for chunk in runtime.index.chunks:
        counts[chunk.get("division") or ""] += 1
    return {
        "ok": True,
        "chunks": dict(counts),
        "embedding_model": runtime.index.model,
        "rerank": settings.rerank,
        "llm_models": list(settings.models),
        "llm_configured": bool(settings.openrouter_api_key),
        "cpus": cpu_info(),
    }


@app.post("/api/ask")
async def ask(body: AskRequest, request: Request):
    checked = _check(body, request)
    if isinstance(checked, JSONResponse):
        return checked
    status, reply = await _answer(checked)
    return JSONResponse(reply, status_code=status)


@app.post("/api/ask/stream")
async def ask_stream(body: AskRequest, request: Request):
    """/api/ask as server-sent events, so the page can show the steps and the text as they happen (DAR-629).

        step     {"id", "label", "status": "pending" | "start" | "done", "ms"}  (answer.LIVE_STEPS):
                 first each step expected to run, as "pending" with ms 0, then each
                 start and done as it happens (retry and suggest only when they start)
        delta    {"text"}    more of the answer, as the model writes it
        replace  {"text"}    the text shown so far is replaced (the retry starts over)
        done     the JSON /api/ask returns
        error    {"error", "status"}

    The stream always ends with done or error. A request that fails the checks
    gets the same JSON error reply as /api/ask, not a stream.
    """
    received = time.monotonic()
    checked = _check(body, request)
    if isinstance(checked, JSONResponse):
        return checked
    # X-Accel-Buffering: no keeps a proxy from holding the events back until the end.
    return StreamingResponse(_events(checked, received), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _step_labels(checked: Question) -> Dict[str, str]:
    """The live steps' labels; the passage count is the same cached row filter the search uses."""
    passages = runtime.index.count(checked.target.id, checked.documents)
    return live_step_labels(checked.target, passages, settings.top_k)


async def _answer(checked: Question, emit: Optional[Emit] = None) -> Tuple[int, Dict]:
    """The status and body of the reply to one question: the answer payload, or {"error": message}.

    With `emit`, the steps and the model's text are streamed through it as they
    happen (LiveSteps, Answerer.answer_stream).
    """
    question, asker, target = checked.text, checked.asker, checked.target
    started = time.perf_counter()
    steps = LiveSteps(_step_labels(checked), emit)
    if emit is not None:
        # The setting the runtime builds the reranker from, not the retriever: on a cold instance
        # the models are still to load, and the page should list the steps before that wait.
        steps.announce(rerank=runtime.settings.rerank)
    timer = StepTimer(steps)
    try:
        with timer.step("model_load"):  # waits for the models on a cold instance, near 0 once loaded
            answerer = await asyncio.to_thread(runtime.answerer, _make_llm())
        hits = await asyncio.to_thread(answerer.retrieve, question, target, timer, checked.documents, checked.history)
        retrieved = time.perf_counter()
        # httpx's timeout is per phase, so bound the whole call to stay under Vercel's 60 s.
        remaining = max(MIN_ANSWER_SECONDS, settings.request_budget_seconds - (retrieved - started))
        deadline = time.monotonic() + remaining
        if emit is None:
            answering = answerer.answer(question, asker, target, hits, deadline, timer, checked.history,
                                        checked.refused_by)
        else:
            answering = answerer.answer_stream(question, asker, target, hits, emit, deadline, timer, checked.history,
                                               checked.refused_by)
        try:
            result = await asyncio.wait_for(answering, timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise LLMError(TOO_SLOW, status=504, detail=f"no answer within {remaining:.0f}s") from exc
    except LLMError as exc:
        log.warning("LLM error: %s ms %s", exc, _ms_text(dict(timer.as_ms(), total=_ms_since(started))))
        return exc.status, {"error": exc.user_message}
    except Exception:  # noqa: BLE001 - never send internals to the browser
        log.exception("ask failed ms %s", _ms_text(dict(timer.as_ms(), total=_ms_since(started))))
        return 500, {"error": GENERIC_ERROR}
    return 200, _payload(checked, result, timer, steps, started, retrieved, streamed=emit is not None)


def _payload(checked: Question, result: Answer, timer: StepTimer, steps: LiveSteps, started: float,
             retrieved: float, streamed: bool) -> Dict:
    """The answer as /api/ask returns it (also the stream's done event); logs the one line per question.

    `steps` are the steps the page shows, [{"id", "label", "ms"}]: the stream
    sends them live, and the page builds them from here when it had to fall
    back to /api/ask.
    """
    asker, target = checked.asker, checked.target
    timing = dict(timer.as_ms(), retrieval=round((retrieved - started) * 1000), total=_ms_since(started))
    log.info(
        "ask asker=%s target=%s chars=%d refused=%s uncited=%s retried=%s sources=%d model=%s first_model=%s "
        "stream=%s ms %s",
        asker.id, target.id, len(checked.text), result.refused, result.uncited, result.retried, len(result.sources),
        result.model, result.first_model, streamed, _ms_text(timing),
    )
    payload = result.as_dict()
    payload["asker"] = {"id": asker.id, "name": asker.name}
    payload["target"] = {"id": target.id, "name": target.name}
    # Every field of the answer is added here, so /api/ask and the stream's done event stay the same.
    payload["steps"] = steps.done
    payload["timing_ms"] = timing
    payload["searched"] = _searched(target, checked.documents)
    return payload


async def _events(checked: Question, received: float) -> AsyncIterator[str]:
    """The server-sent events of one streamed answer; see ask_stream()."""
    stop_at = received + min(STREAM_LIMIT_SECONDS, settings.request_budget_seconds + STREAM_MARGIN_SECONDS)
    loop = asyncio.get_running_loop()
    queue: "asyncio.Queue[Tuple[str, Dict]]" = asyncio.Queue()

    def emit(event: str, data: Dict) -> None:
        # Thread-safe because the retrieval's steps arrive from its worker thread;
        # everything goes through the loop in the order it happened.
        loop.call_soon_threadsafe(queue.put_nowait, (event, data))

    async def run() -> None:
        try:
            status, reply = await _answer(checked, emit)
        except Exception:  # noqa: BLE001 - _answer reports its own errors; this keeps the stream from hanging
            log.exception("stream failed")
            status, reply = 500, {"error": GENERIC_ERROR}
        if status == 200:
            emit("done", reply)
        else:
            emit("error", {"error": reply["error"], "status": status})

    task = asyncio.create_task(run())
    try:
        while True:
            try:
                event, data = await asyncio.wait_for(queue.get(), timeout=max(stop_at - time.monotonic(), 0.0))
            except asyncio.TimeoutError:
                log.warning("stream stopped at %.1f s without an answer", time.monotonic() - received)
                event, data = "error", {"error": TOO_SLOW, "status": 504}
            # ASCII escapes: a character the model split into two halves (an emoji's
            # surrogate pair) can't be encoded as UTF-8 on its own, but escaped it can.
            yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
            if event in ("done", "error"):
                return
    finally:
        task.cancel()  # the visitor left, or the hard stop: stop the model call too


def _ms_since(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _ms_text(timing: Dict[str, int]) -> str:
    """The timings as "embed=12 search=3 ..." for the log line."""
    return " ".join(f"{step}={ms}" for step, ms in timing.items())


# Keep this last: routes registered after a mount at "/" would never be reached.
# Locally it serves public/css and public/js beside the page. On Vercel the CDN
# serves public/ and leaves it out of the function bundle, so the mount is skipped
# there: StaticFiles raises at import for a missing directory, which took down every
# /api route on the first preview of this layout.
if PUBLIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="public")
