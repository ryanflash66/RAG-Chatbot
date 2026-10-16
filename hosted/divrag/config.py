"""Settings for the hosted demo, read once from environment variables.

Only OPENROUTER_API_KEY is required. Everything else has a default suitable
for the public demo.

    OPENROUTER_API_KEY          secret; never sent to the browser
    OPENROUTER_MODEL            primary model (must end in ":free")
    OPENROUTER_FALLBACK_MODELS  comma-separated backups, tried in order by OpenRouter (":free" only)
    LLM_TEMPERATURE             default 0.1
    LLM_REASONING               "off" (default), "low", "medium" or "high" for reasoning models
    RERANK                      "on" (default) or "off": rerank vector hits with the cross-encoder
    RERANK_CANDIDATES           vector hits handed to the reranker (default 20)
    TOP_K                       passages given to the model (default 5)
    MODEL_CACHE_DIR             fastembed model directory (see embedder.model_cache_dir)
    ONNX_THREADS                onnxruntime threads per model (default: onnxruntime's own choice; see embedder.onnx_threads)
    INDEX_DIR                   directory with chunks.json and vectors.npy (default hosted/index)
    MAX_QUESTION_CHARS          default 500
    RATE_LIMIT_PER_MINUTE       questions per client IP per minute, per server instance (default 8)
    REQUEST_BUDGET_SECONDS      total time one question may take, kept under Vercel's 60 s maxDuration (default 55)
    RETRY_ON_REFUSAL            "on" (default) or "off": ask once more when the model refuses although retrieval was strong
    RETRY_MIN_SCORE             top reranker score that counts as strong retrieval (default 1.0)
    RETRY_MIN_SECONDS           retry only if at least this much of the request budget is left (default 15)
    ALLOWED_ORIGINS             comma-separated origins allowed to call the API from another site
                                (default none: only the page served by this app can call it)
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple

HOSTED_DIR = Path(__file__).resolve().parent.parent

# Free models only, so the public link cannot spend the account's credits.
# Chosen from https://openrouter.ai/api/v1/models on 2026-10-10: Nemotron 3 Ultra
# answered the grounded test prompt correctly in ~2.5 s; Nemotron 3 Super is a
# smaller model from the same family on a different endpoint; Gemma 4 31B was
# rate-limited upstream at the time but is a strong instruction follower when up.
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
DEFAULT_FALLBACK_MODELS = ("nvidia/nemotron-3-super-120b-a12b:free", "google/gemma-4-31b-it:free")
FREE_SUFFIX = ":free"


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: Optional[str]
    models: Tuple[str, ...]
    temperature: float
    reasoning: str
    rerank: bool
    rerank_candidates: int
    top_k: int
    index_dir: Path
    max_question_chars: int
    rate_limit_per_minute: int
    request_budget_seconds: float
    retry_on_refusal: bool
    retry_min_score: float
    retry_min_seconds: float
    allowed_origins: Tuple[str, ...]


def _csv(value: str) -> Tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    env = os.environ if env is None else env
    primary = env.get("OPENROUTER_MODEL", "").strip() or DEFAULT_MODEL
    fallbacks = _csv(env["OPENROUTER_FALLBACK_MODELS"]) if "OPENROUTER_FALLBACK_MODELS" in env else DEFAULT_FALLBACK_MODELS
    models = tuple(dict.fromkeys((primary,) + fallbacks))
    paid = [m for m in models if not m.endswith(FREE_SUFFIX)]
    if paid:
        raise ValueError(f"Only free OpenRouter models (ending in {FREE_SUFFIX!r}) are allowed; got {paid}")
    rerank = env.get("RERANK", "on").strip().lower()
    if rerank not in ("on", "off", "1", "0", "true", "false"):
        raise ValueError(f"RERANK must be on or off, got {rerank!r}")
    reasoning = env.get("LLM_REASONING", "off").strip().lower()
    if reasoning not in ("off", "low", "medium", "high"):
        raise ValueError(f"LLM_REASONING must be off, low, medium or high, got {reasoning!r}")
    top_k = int(env.get("TOP_K", "5"))
    if not 1 <= top_k <= 10:
        raise ValueError(f"TOP_K must be 1-10, got {top_k}")
    budget = float(env.get("REQUEST_BUDGET_SECONDS", "55"))
    if not 10 <= budget <= 58:
        raise ValueError(f"REQUEST_BUDGET_SECONDS must be 10-58 (Vercel stops the function at 60), got {budget}")
    retry = env.get("RETRY_ON_REFUSAL", "on").strip().lower()
    if retry not in ("on", "off", "1", "0", "true", "false"):
        raise ValueError(f"RETRY_ON_REFUSAL must be on or off, got {retry!r}")
    retry_min_seconds = float(env.get("RETRY_MIN_SECONDS", "15"))
    if retry_min_seconds < 0:
        raise ValueError(f"RETRY_MIN_SECONDS must be 0 or more, got {retry_min_seconds}")
    index_dir = Path(env.get("INDEX_DIR", "").strip() or HOSTED_DIR / "index")
    return Settings(
        openrouter_api_key=env.get("OPENROUTER_API_KEY", "").strip() or None,
        models=models,
        temperature=float(env.get("LLM_TEMPERATURE", "0.1")),
        reasoning=reasoning,
        rerank=rerank in ("on", "1", "true"),
        rerank_candidates=int(env.get("RERANK_CANDIDATES", "20")),
        top_k=top_k,
        index_dir=index_dir if index_dir.is_absolute() else HOSTED_DIR / index_dir,
        max_question_chars=int(env.get("MAX_QUESTION_CHARS", "500")),
        rate_limit_per_minute=int(env.get("RATE_LIMIT_PER_MINUTE", "8")),
        request_budget_seconds=budget,
        retry_on_refusal=retry in ("on", "1", "true"),
        retry_min_score=float(env.get("RETRY_MIN_SCORE", "1.0")),
        retry_min_seconds=retry_min_seconds,
        allowed_origins=_csv(env.get("ALLOWED_ORIGINS", "")),
    )
