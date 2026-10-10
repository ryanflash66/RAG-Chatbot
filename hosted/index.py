"""The hosted demo: one FastAPI app that serves the page and answers questions.

    GET  /                the page (public/index.html)
    GET  /api/divisions   divisions, their documents and example questions
    POST /api/ask         {"question", "asker", "target"} -> answer with cited sources
    GET  /api/health      index and model settings (no secrets)

Vercel loads `app` from this file (a FastAPI entrypoint at the project root,
with hosted/ as the Root Directory). Locally:

    .venv/Scripts/python -m uvicorn index:app --app-dir hosted --env-file .env --port 8000

Models load on the first question (or in the background when the page asks for
/api/divisions), not at import, so a cold start can serve the page quickly.
"""

import asyncio
import logging
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from divrag.answer import Answerer
from divrag.config import Settings, load_settings
from divrag.divisions import BY_ID, DIVISIONS
from divrag.embedder import Embedder, Reranker, model_cache_dir
from divrag.index_file import IndexFile
from divrag.llm import MISCONFIGURED, TOO_SLOW, LLMError, OpenRouterClient
from divrag.retrieval import Retriever

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
                retriever.retrieve("warm up", division=None, k=1)  # loads the models
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


class AskRequest(BaseModel):
    # Generous hard caps; the friendly limit (MAX_QUESTION_CHARS) is checked in ask().
    question: str = Field(max_length=5000)
    asker: str = Field(max_length=40)
    target: str = Field(max_length=40)


def _make_llm() -> OpenRouterClient:
    return OpenRouterClient(settings.openrouter_api_key or "", settings.models, settings.temperature, settings.reasoning)


@app.get("/", include_in_schema=False)
def page() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html", media_type="text/html")


@app.get("/api/divisions")
def divisions() -> Dict:
    # Start loading the models while the visitor reads the page and types.
    threading.Thread(target=_warm, daemon=True).start()
    return {
        "divisions": [
            {
                "id": d.id,
                "name": d.name,
                "unit": d.unit,
                "documents": [{"title": doc.title, "url": doc.url} for doc in d.documents],
                "examples": list(d.examples),
            }
            for d in DIVISIONS
        ],
        "max_question_chars": settings.max_question_chars,
    }


def _warm() -> None:
    try:
        runtime.retriever()
    except Exception:  # noqa: BLE001 - the next question reports the real error
        log.exception("model warm-up failed")


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
    }


@app.post("/api/ask")
async def ask(body: AskRequest, request: Request):
    question = " ".join(body.question.split())
    if len(question) < 3:
        return _error(400, "Please type a question.")
    if len(question) > settings.max_question_chars:
        return _error(400, f"Please keep the question under {settings.max_question_chars} characters.")
    asker, target = BY_ID.get(body.asker), BY_ID.get(body.target)
    if asker is None or target is None:
        return _error(400, "Unknown division.")
    if not limiter.allow(_client_ip(request)):
        return _error(429, "Too many questions in a short time. Please wait a minute and try again.")
    if not settings.openrouter_api_key:
        log.error("OPENROUTER_API_KEY is not set")
        return _error(503, MISCONFIGURED)

    started = time.perf_counter()
    try:
        answerer = await asyncio.to_thread(runtime.answerer, _make_llm())
        hits = await asyncio.to_thread(answerer.retrieve, question, target)
        retrieved = time.perf_counter()
        # httpx's timeout is per phase, so bound the whole call to stay under Vercel's 60 s.
        remaining = max(MIN_ANSWER_SECONDS, settings.request_budget_seconds - (retrieved - started))
        try:
            deadline = time.monotonic() + remaining
            result = await asyncio.wait_for(answerer.answer(question, asker, target, hits, deadline), timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise LLMError(TOO_SLOW, status=504, detail=f"no answer within {remaining:.0f}s") from exc
    except LLMError as exc:
        log.warning("LLM error: %s", exc)
        return _error(exc.status, exc.user_message)
    except Exception:  # noqa: BLE001 - never send internals to the browser
        log.exception("ask failed")
        return _error(500, "Something went wrong answering that question. Please try again.")
    finished = time.perf_counter()
    log.info(
        "ask asker=%s target=%s chars=%d refused=%s retried=%s sources=%d model=%s retrieval=%.2fs total=%.2fs",
        asker.id, target.id, len(question), result.refused, result.retried, len(result.sources), result.model,
        retrieved - started, finished - started,
    )
    payload = result.as_dict()
    payload["asker"] = {"id": asker.id, "name": asker.name}
    payload["target"] = {"id": target.id, "name": target.name}
    payload["timing_ms"] = {"retrieval": round((retrieved - started) * 1000), "total": round((finished - started) * 1000)}
    return payload
