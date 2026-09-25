"""Answer-accuracy harness: ask the chat app's questions about PDF tables and grade the answers.

    py eval/run_eval.py --provider ollama --model qwen2.5:14b --rebuild
    py eval/run_eval.py --provider openrouter --model gpt-4o --json out.json

Each case in eval/table_questions.json is retrieved, prompted and answered with
the Chainlit app's own helpers (app._build_prompt, app._make_llm), so the score
reflects what users get. The index is private to the harness (eval/.chroma) and
built from DATA_DIR, so the app's chroma_db is never touched.

Two things are reported per question:
  retrieval  -- did any retrieved chunk come from the expected page?
  answer     -- did the answer contain the expected values?
A retrieval miss means the LLM never saw the table; a retrieval hit with a wrong
answer is a reading miss.

Nothing heavy is imported at module level, so grade() can be unit-tested alone.
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

EVAL_DIR = Path(__file__).resolve().parent
ROOT = EVAL_DIR.parent
CASES_FILE = EVAL_DIR / "table_questions.json"
EVAL_CHROMA_DIR = EVAL_DIR / ".chroma"
EVAL_COLLECTION = "eval_docs"
DEFAULT_TOP_K = 4  # app.TOP_K at the time of writing; --top-k overrides
ANSWER_PREVIEW = 120
# Ollama is shared and may queue requests; one retry on a timeout.
LLM_ATTEMPTS = 2

_DASHES = re.compile("[‐-―−]")
_SPACED_HYPHEN = re.compile(r"\s*-\s*")
_MARKUP = re.compile(r"[*_`]")
# A "Sources:" line followed only by list items (or nothing) up to the end of the answer.
_SOURCES_TRAILER = re.compile(
    r"\n[ \t#*_]*sources?[*_]*[ \t]*:[^\n]*"
    r"(?:\n[ \t]*(?:[-*•]|\d+[.)]|\[\d+\])[^\n]*|\n[ \t]*)*\Z",
    re.IGNORECASE,
)


def normalise(text: str) -> str:
    """Lowercase, drop markdown emphasis, unify dashes and quotes, collapse whitespace."""
    text = _MARKUP.sub("", text.lower())
    text = _DASHES.sub("-", text)
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"\s+", " ", text)
    return _SPACED_HYPHEN.sub("-", text).strip()


def answer_text(raw: str) -> str:
    """The answer without a trailing Sources list, so file names and page numbers can't score.

    A "Source:" line in the middle of the answer is kept.
    """
    match = _SOURCES_TRAILER.search(raw)
    return raw[: match.start()] if match else raw


def _contains(haystack: str, needle: str) -> bool:
    """Substring match; a needle starting with a letter or digit must start a word."""
    needle = normalise(needle)
    if not needle:
        return False
    start = 0
    while True:
        at = haystack.find(needle, start)
        if at < 0:
            return False
        if not needle[0].isalnum() or at == 0 or not haystack[at - 1].isalnum():
            return True
        start = at + 1


def _any_group(haystack: str, groups: Iterable[Sequence[str]]) -> bool:
    return any(group and all(_contains(haystack, s) for s in group) for group in groups)


def grade(answer: str, case: Mapping[str, Any]) -> bool:
    """True if any accept group matches in full and no reject group does."""
    text = normalise(answer_text(answer))
    return _any_group(text, case.get("accept", [])) and not _any_group(text, case.get("reject", []))


def retrieval_hit(hits: Sequence[Any], case: Mapping[str, Any]) -> Optional[bool]:
    """Whether a Hit came from the expected source page; None when the case expects no page."""
    pages = {str(p) for p in case.get("pages") or []}
    if not pages:
        return None
    source = (case.get("source") or "").lower()
    return any(
        str(hit.metadata.get("page_label")) in pages and source in (hit.source or "").lower()
        for hit in hits
    )


def load_cases(path: Path = CASES_FILE) -> List[Dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _configure_env(provider: Optional[str], model: Optional[str]) -> None:
    """Point the app's config at the harness's own index and the chosen model.

    With neither flag given, LLM_PROVIDER and MODEL_NAME come from the environment
    or .env, as in the app. --provider alone uses that provider's default model.
    Must run before app is imported: app._config() is lru-cached.
    """
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")  # never overrides what is already set
    os.environ["CHROMA_PERSIST_DIR"] = str(EVAL_CHROMA_DIR)
    os.environ["CHROMA_COLLECTION"] = EVAL_COLLECTION
    if provider:
        os.environ["LLM_PROVIDER"] = provider
        if not model:
            os.environ.pop("MODEL_NAME", None)
    if model:
        os.environ["MODEL_NAME"] = model
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")


async def _ask(llm, prompt: str) -> str:
    """Stream the answer the way the app does, keeping only the answer tokens."""
    stream = await llm.astream_complete(prompt)
    parts = []
    async for chunk in stream:
        parts.append(chunk.delta or "")
    return "".join(parts)


async def _ask_with_retry(llm, prompt: str) -> str:
    for attempt in range(LLM_ATTEMPTS):
        try:
            return await _ask(llm, prompt)
        except Exception as exc:
            if attempt + 1 == LLM_ATTEMPTS:
                raise
            print(f"  LLM call failed ({exc.__class__.__name__}: {exc}); retrying", file=sys.stderr)
    raise AssertionError("unreachable")


def _mark(value: Optional[bool]) -> str:
    return "n/a" if value is None else ("✅" if value else "❌")


def _preview(answer: str) -> str:
    return re.sub(r"\s+", " ", answer).strip()[:ANSWER_PREVIEW]


async def _run_cases(app, index, llm, top_k: int) -> List[Dict[str, Any]]:
    """One event loop for every case: the Ollama client's async session is bound to it."""
    results = []
    for case in load_cases():
        hits = index.retrieve(case["question"], k=top_k)
        prompt = app._build_prompt(case["question"], hits)
        started = time.perf_counter()
        raw = await _ask_with_retry(llm, prompt)
        latency = time.perf_counter() - started
        result = {
            "id": case["id"],
            "question": case["question"],
            "refusal": bool(case.get("refusal")),
            "passed": grade(raw, case),
            "retrieved_expected_page": retrieval_hit(hits, case),
            "retrieved_pages": [
                f"{h.source}#p{h.metadata.get('page_label')}" if h.metadata.get("page_label") else h.source
                for h in hits
            ],
            "latency_s": round(latency, 2),
            "answer": raw,
        }
        results.append(result)
        print(f"{case['id']:<4} {_mark(result['passed'])}  retrieval {_mark(result['retrieved_expected_page']):<3} "
              f"{latency:6.1f}s  {_preview(raw)}", flush=True)

    return results


class HarnessError(RuntimeError):
    """A setup problem reported as a one-line message rather than a traceback."""


def run(provider: Optional[str], model: Optional[str], top_k: int, rebuild: bool) -> Dict[str, Any]:
    _configure_env(provider, model)

    import app
    from rag.config import load_config
    from rag.index import NoDocumentsError, RetrievalIndex, make_embed_model

    try:
        config = load_config()
        if config.llm_provider == "ollama":
            app._check_ollama(config)
        llm = app._make_llm(config)
    except (RuntimeError, ValueError) as exc:  # Ollama down, model not pulled, bad provider, missing key
        raise HarnessError(str(exc)) from exc

    index = RetrievalIndex(config, make_embed_model(config))
    try:
        stats = index.refresh() if rebuild else index.ensure_built()
    except NoDocumentsError as exc:
        raise HarnessError(str(exc)) from exc
    if stats.vectors == 0:
        raise HarnessError(f"The eval index is empty and there are no documents under {config.data_dir}. Set DATA_DIR.")
    print(f"Index {stats.collection} at {config.chroma_persist_dir}: {stats.documents} documents, "
          f"{stats.vectors} vectors (data: {config.data_dir})")
    print(f"Model: {config.model_name} via {config.llm_provider}, top-k {top_k}\n")

    results = asyncio.run(_run_cases(app, index, llm, top_k))
    table = [r for r in results if not r["refusal"]]
    refusals = [r for r in results if r["refusal"]]
    summary = {
        "provider": config.llm_provider,
        "model": config.model_name,
        "top_k": top_k,
        "table_passed": sum(r["passed"] for r in table),
        "table_total": len(table),
        "refusal_passed": sum(r["passed"] for r in refusals),
        "refusal_total": len(refusals),
        "retrieval_hits": sum(bool(r["retrieved_expected_page"]) for r in table),
        "avg_latency_s": round(sum(r["latency_s"] for r in results) / len(results), 2) if results else 0.0,
        "results": results,
    }
    print(
        f"\nTable questions: {summary['table_passed']}/{summary['table_total']}  "
        f"Refusal: {summary['refusal_passed']}/{summary['refusal_total']}  "
        f"Expected page retrieved: {summary['retrieval_hits']}/{summary['table_total']}  "
        f"Avg latency: {summary['avg_latency_s']}s"
    )
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--provider", choices=["ollama", "openrouter"],
                        help="defaults to LLM_PROVIDER, as in the app")
    parser.add_argument("--model", help="defaults to MODEL_NAME, or the provider's default model")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--rebuild", action="store_true", help="rebuild eval/.chroma from DATA_DIR first")
    parser.add_argument("--json", type=Path, help="also write full results (answers included) to this file")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(ROOT))

    try:
        summary = run(args.provider, args.model, args.top_k, args.rebuild)
    except HarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        args.json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
