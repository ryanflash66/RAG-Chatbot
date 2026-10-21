"""The hosted demo: one FastAPI app that serves the page and answers questions.

    GET  /                the page (public/index.html; public/css and public/js beside it)
    GET  /api/divisions   divisions, their documents and example questions
    POST /api/warm        load the models now, returning once they are ready
    POST /api/ask         {"question", "asker", "target", "history"?, "documents"?}
                          -> answer with cited sources and timing_ms per step
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
import logging
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, List, NamedTuple, Optional, Union

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from divrag.answer import Answerer
from divrag.config import Settings, load_settings
from divrag.divisions import BY_ID, DIVISIONS, Division
from divrag.embedder import Embedder, Reranker, cpu_info, model_cache_dir
from divrag.index_file import IndexFile
from divrag.llm import MISCONFIGURED, TOO_SLOW, LLMError, OpenRouterClient
from divrag.retrieval import Retriever
from divrag.timing import StepTimer

PUBLIC_DIR = Path(__file__).resolve().parent / "public"
# The answer call always gets at least this long, even if retrieval ate the budget.
MIN_ANSWER_SECONDS = 5.0

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
    documents: Optional[List[str]] = Field(default=None, max_length=20)


class Question(NamedTuple):
    """A request that passed the checks every answering endpoint shares."""
    text: str
    asker: Division
    target: Division
    documents: Optional[List[str]]
    history: List[Dict[str, str]]


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
    return Question(question, asker, target, documents, [t.model_dump() for t in body.history])


def _make_llm() -> OpenRouterClient:
    return OpenRouterClient(settings.openrouter_api_key or "", settings.models, settings.temperature, settings.reasoning)


@app.get("/", include_in_schema=False)
def page() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html", media_type="text/html")


@app.get("/api/divisions")
def divisions() -> Dict:
    return {
        "divisions": [
            {
                "id": d.id,
                "name": d.name,
                "unit": d.unit,
                "documents": [{"file": doc.file, "title": doc.title, "url": doc.url} for doc in d.documents],
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
    question, asker, target = checked.text, checked.asker, checked.target

    started = time.perf_counter()
    timer = StepTimer()
    try:
        with timer.step("model_load"):  # waits for the models on a cold instance, near 0 once loaded
            answerer = await asyncio.to_thread(runtime.answerer, _make_llm())
        hits = await asyncio.to_thread(answerer.retrieve, question, target, timer, checked.documents, checked.history)
        retrieved = time.perf_counter()
        # httpx's timeout is per phase, so bound the whole call to stay under Vercel's 60 s.
        remaining = max(MIN_ANSWER_SECONDS, settings.request_budget_seconds - (retrieved - started))
        try:
            deadline = time.monotonic() + remaining
            result = await asyncio.wait_for(answerer.answer(question, asker, target, hits, deadline, timer,
                                                            checked.history), timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise LLMError(TOO_SLOW, status=504, detail=f"no answer within {remaining:.0f}s") from exc
    except LLMError as exc:
        log.warning("LLM error: %s ms %s", exc, _ms_text(dict(timer.as_ms(), total=_ms_since(started))))
        return _error(exc.status, exc.user_message)
    except Exception:  # noqa: BLE001 - never send internals to the browser
        log.exception("ask failed ms %s", _ms_text(dict(timer.as_ms(), total=_ms_since(started))))
        return _error(500, "Something went wrong answering that question. Please try again.")
    timing = dict(timer.as_ms(), retrieval=round((retrieved - started) * 1000), total=_ms_since(started))
    log.info(
        "ask asker=%s target=%s chars=%d refused=%s retried=%s sources=%d model=%s first_model=%s ms %s",
        asker.id, target.id, len(question), result.refused, result.retried, len(result.sources), result.model,
        result.first_model, _ms_text(timing),
    )
    payload = result.as_dict()
    payload["asker"] = {"id": asker.id, "name": asker.name}
    payload["target"] = {"id": target.id, "name": target.name}
    payload["timing_ms"] = timing
    return payload


def _ms_since(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _ms_text(timing: Dict[str, int]) -> str:
    """The timings as "embed=12 search=3 ..." for the log line."""
    return " ".join(f"{step}={ms}" for step, ms in timing.items())


# Keep this last: routes registered after a mount at "/" would never be reached.
# Locally it serves public/css and public/js beside the page; on Vercel the CDN
# serves public/ before a request reaches this function.
app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="public")
