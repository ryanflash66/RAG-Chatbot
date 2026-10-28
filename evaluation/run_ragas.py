"""Evaluate the hosted pipeline on the RAGAS metrics plus answer time, and chart the results.

    py -m evaluation.run_ragas                          # everything: retrieval, answers, judge, report
    py -m evaluation.run_ragas --stage retrieval        # the deterministic page metrics only (no LLM)
    py -m evaluation.run_ragas --stage report           # rescore and redraw from the cache
    py -m evaluation.run_ragas --only B1 A3 --stage all
    py -m evaluation.run_ragas --judge-base-url http://localhost:11434/v1 --judge-models gpt-oss:20b
    py -m evaluation.run_ragas --judge-base-url https://api.openai.com/v1 --judge-models gpt-4o-mini  # JUDGE_API_KEY

For each question in evaluation/testset.json:

1. retrieval (always, no LLM): the hosted Retriever ranks the asked division's
   chunks (vector top 20, cross-encoder, top 5); the page metrics compare the
   ranked pages and every page the model is shown with the gold pages.
2. answer: the hosted Answerer answers the question exactly as /api/ask does
   (same retrieval, prompt, citation check, retry and refusal), timed per step
   with the app's StepTimer, under the same request budget.
3. judge: one LLM call returns the verdicts for faithfulness, answer relevancy,
   context precision and context recall (judge.py), over the full text of the
   passages the answering model was given.
4. report: scores per question and per division, written to
   evaluation/results/scores.json, and the charts in evaluation/charts/.

Answers and verdicts are appended to evaluation/results/cache.jsonl, keyed by
question id and the answering (and judging) models, so a run resumes where the
last one stopped: free OpenRouter models have a daily request cap, and when
it is reached (DAILY_LIMIT) the run stops cleanly, reports how many questions
are covered, and the next run continues. A per-minute limit (BUSY) is waited
out. Questions already cached are never asked again.

Answering defaults to the hosted app's own settings (free OpenRouter models,
read from .env like the app); --answer-base-url points the same Answerer at
another OpenAI-compatible endpoint (for example a local Ollama model when no
OpenRouter key is available). The judge defaults to a free OpenRouter model
from another family than the answering model, so the judge isn't grading its own answers.
"""

import argparse
import asyncio
import functools
import hashlib
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from evaluation import EVALUATION_DIR, ROOT
from evaluation import metrics as m

DEFAULT_TESTSET = EVALUATION_DIR / "testset.json"
RESULTS_DIR = EVALUATION_DIR / "results"
DEFAULT_CACHE = RESULTS_DIR / "cache.jsonl"
DEFAULT_SCORES = RESULTS_DIR / "scores.json"
DEFAULT_CHARTS = EVALUATION_DIR / "charts"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
# Gemma 4 31B: a free model from another family than the app's Nemotron answers,
# and one of the free models that accepts response_format (OpenRouter's model list,
# 2026-10-27). Both free Gemmas were "rate-limited upstream" for long stretches that
# evening, so OpenRouter falls back to dots.llm3 (another family again, structured
# outputs, returned clean JSON in a probe). Each verdict records the model that gave it.
DEFAULT_JUDGE_MODELS = ("google/gemma-4-31b-it:free", "dots-studio/dots-3-note-preview:free")
# Per-minute limits (BUSY) are waited out this long before asking again, doubling each time.
BUSY_WAITS = (20, 40, 80)
# hosted/index.py's minimum: the answer call always gets this long.
MIN_ANSWER_SECONDS = 5.0


def find_env_file() -> Optional[Path]:
    """The repo's .env: in the checkout itself, or above a git worktree of it (never copied into one)."""
    for folder in (ROOT, *ROOT.parents):
        if (folder / ".env").is_file() and (folder / "requirements.txt").is_file():
            return folder / ".env"
    return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _host(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0]


def config_label(base_url: str, models: Sequence[str]) -> str:
    """The cache key for a model setup: endpoint host and the model list, e.g. openrouter.ai:a:free+b:free."""
    return f"{_host(base_url)}:{'+'.join(models)}"


def answer_hash(record: Dict[str, Any]) -> str:
    """Ties a verdict to the exact answer and passages it judged."""
    text = json.dumps([record["answer"].get("answer"), [p["text"] for p in record["passages"]]], ensure_ascii=False)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def reference_hash(item: Dict[str, Any]) -> str:
    """Ties a verdict to the question and reference answer it was judged against, so editing the test set's
    reference (context recall is scored on it) asks the judge again instead of reusing a stale verdict."""
    text = json.dumps([item["question"], item.get("reference")], ensure_ascii=False)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


class Cache:
    """Append-only JSONL of answers and verdicts; the latest record per key wins."""

    def __init__(self, path: Path):
        self.path = path
        self.answers: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.verdicts: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}
        if path.exists():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    self._index(json.loads(line))
                except ValueError:
                    # A run stopped mid-write leaves a cut-off last line; that question is simply asked again.
                    print(f"warning: {path.name} line {number} is not valid JSON; skipped", file=sys.stderr)

    def _index(self, record: Dict[str, Any]) -> None:
        if record["kind"] == "answer":
            self.answers[(record["id"], record["answer_config"])] = record
        elif record["kind"] == "judge":
            key = (record["id"], record["answer_config"], record["answer_hash"], record.get("reference_hash", ""),
                   record["judge_config"])
            self.verdicts[key] = record

    def add(self, record: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._index(record)

    def answer(self, qid: str, answer_config: str) -> Optional[Dict[str, Any]]:
        return self.answers.get((qid, answer_config))

    def verdict(self, item: Dict[str, Any], answer_config: str, answer: Dict[str, Any],
                judge_config: str) -> Optional[Dict[str, Any]]:
        return self.verdicts.get((item["id"], answer_config, answer_hash(answer), reference_hash(item), judge_config))


class Stop(Exception):
    """The run can't go on today (daily cap, bad key); what is cached is kept."""


def passage_pages(chunk: Dict[str, Any]) -> List[int]:
    """Every page a passage shows the model: its merged parts' pages, or its own page(s)."""
    parts = chunk.get("parts") or [chunk]
    pages = {p.get("page") for p in parts if p.get("page")}
    if chunk.get("page_end"):
        pages.add(chunk["page_end"])
    return sorted(pages)


def passage_record(n: int, hit) -> Dict[str, Any]:
    chunk = hit.chunk
    return {"n": n, "score": round(float(hit.score), 4), "source": chunk.get("source"), "page": chunk.get("page"),
            "page_end": chunk.get("page_end"), "section": chunk.get("section"), "pages": passage_pages(chunk),
            "text": chunk["text"]}


class Pipeline:
    """The hosted app's runtime, as hosted/index.py's _Runtime builds it, without the web app."""

    def __init__(self, settings):
        from divrag.embedder import Embedder, Reranker, model_cache_dir
        from divrag.index_file import IndexFile
        from divrag.retrieval import Retriever

        self.settings = settings
        self.index = IndexFile.load(settings.index_dir)
        cache = model_cache_dir()
        self.embedder = Embedder(self.index.model, cache_dir=cache)
        reranker = Reranker(cache_dir=cache) if settings.rerank else None
        self.retriever = Retriever(self.index, self.embedder, reranker, candidates=settings.rerank_candidates)
        self.retriever.warm_up()

    def answerer(self, llm):
        from divrag.answer import Answerer

        s = self.settings
        return Answerer(self.retriever, llm, top_k=s.top_k, retry_min_score=s.retry_min_score if s.retry_on_refusal else None,
                        retry_min_seconds=s.retry_min_seconds)

    def retrieval(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """The deterministic part: ranked top-k pages, every page shown, page metrics and retrieval time."""
        from divrag.answer import FOLLOWING_FOR_TOP
        from divrag.timing import StepTimer

        timer = StepTimer()
        ranked = self.retriever.retrieve(item["question"], division=item["target"], k=self.settings.top_k, timer=timer)
        passages = self.retriever.as_passages(self.retriever.with_following(ranked, top=FOLLOWING_FOR_TOP))
        ranked_pages = [h.chunk.get("page") for h in ranked]
        shown = sorted({p for h in passages for p in passage_pages(h.chunk)})
        ms = timer.as_ms()
        return {"ranked_pages": ranked_pages, "ranked_scores": [round(float(h.score), 3) for h in ranked],
                "shown_pages": shown, "retrieval_ms": ms["embed"] + ms["search"] + ms["rerank"],
                **m.page_metrics(ranked_pages, shown, item.get("pages") or [], item.get("pages_mode", "all"))}


async def _with_busy_waits(call, label: str):
    """`await call()`, waiting out per-minute rate limits; DAILY_LIMIT and a bad key stop the run."""
    from divrag.llm import BUSY, DAILY_LIMIT, MISCONFIGURED, LLMError

    for attempt, wait in enumerate((*BUSY_WAITS, None)):
        try:
            return await call()
        except LLMError as exc:
            if exc.user_message == DAILY_LIMIT:
                raise Stop(f"{label}: daily free-model limit reached ({exc})") from exc
            if exc.user_message == MISCONFIGURED:
                raise Stop(f"{label}: the API key was refused ({exc})") from exc
            if exc.user_message == BUSY and wait is not None:
                print(f"  {label}: rate limited, waiting {wait}s", flush=True)
                await asyncio.sleep(wait)
                continue
            raise


async def answer_one(pipe: Pipeline, llm, item: Dict[str, Any], budget: float) -> Dict[str, Any]:
    """One question through the hosted answering path (hosted/index.py _answer), timed per step."""
    from divrag.divisions import BY_ID
    from divrag.llm import TOO_SLOW, LLMError
    from divrag.timing import StepTimer

    answerer = pipe.answerer(llm)
    target, asker = BY_ID[item["target"]], BY_ID[item.get("asker") or item["target"]]
    timer = StepTimer()
    started = time.perf_counter()
    hits = await asyncio.to_thread(answerer.retrieve, item["question"], target, timer)
    retrieved = time.perf_counter()
    remaining = max(MIN_ANSWER_SECONDS, budget - (retrieved - started))
    deadline = time.monotonic() + remaining
    try:
        result = await asyncio.wait_for(answerer.answer(item["question"], asker, target, hits, deadline, timer),
                                        timeout=remaining)
    except asyncio.TimeoutError as exc:
        raise LLMError(TOO_SLOW, status=504, detail=f"no answer within {remaining:.0f}s") from exc
    ms = timer.as_ms()
    return {"answer": result.as_dict(), "passages": [passage_record(n, h) for n, h in enumerate(hits, 1)],
            "timing_ms": dict(ms, retrieval=ms["embed"] + ms["search"] + ms["rerank"],
                              total=round((time.perf_counter() - started) * 1000))}


async def answer_stage(pipe: Pipeline, llm, answer_config: str, items: Sequence[Dict[str, Any]], cache: Cache,
                       args) -> Tuple[int, Optional[str]]:
    """Answer every uncached question; (new answers, why it stopped early or None)."""
    from divrag.llm import TOO_LONG, TOO_SLOW, LLMError

    todo = [i for i in items if cache.answer(i["id"], answer_config) is None]
    print(f"answers: {len(items) - len(todo)} cached, {len(todo)} to ask ({answer_config})", flush=True)
    done = 0
    for n, item in enumerate(todo, 1):
        # Questions asked, failed ones included: the cap protects a shared quota.
        if args.max_requests is not None and n > args.max_requests:
            return done, f"stopped after --max-requests {args.max_requests}"
        record = {"kind": "answer", "id": item["id"], "answer_config": answer_config, "at": _now()}
        try:
            record.update(await _with_busy_waits(lambda: answer_one(pipe, llm, item, args.budget), item["id"]))
        except Stop as stop:
            return done, str(stop)
        except LLMError as exc:
            if exc.user_message not in (TOO_SLOW, TOO_LONG):
                print(f"  [{n}/{len(todo)}] {item['id']}: {exc.user_message} ({exc}); not cached, retried next run", flush=True)
                await asyncio.sleep(args.pause)
                continue
            # Too slow or too long is what a visitor would get: an outcome, not a glitch.
            record.update({"answer": None, "error": exc.user_message, "passages": [], "timing_ms": None})
        cache.add(record)
        done += 1
        answer = record.get("answer") or {}
        state = record.get("error") or ("refused" if answer.get("refused") else "uncited" if answer.get("uncited") else "answered")
        total = (record.get("timing_ms") or {}).get("total")
        print(f"  [{n}/{len(todo)}] {item['id']}: {state}" + (f" in {total / 1000:.1f}s" if total else ""), flush=True)
        await asyncio.sleep(args.pause)
    return done, None


def needs_judge(item: Dict[str, Any], record: Optional[Dict[str, Any]]) -> bool:
    """Answered questions need verdicts; a question no document answers needs none once it is refused."""
    if not record or not record.get("answer"):
        return False
    return item["answerable"] or not record["answer"]["refused"]


def find_verdict(cache: Cache, item: Dict[str, Any], answer_config: str, record: Optional[Dict[str, Any]],
                 judge_configs: Sequence[str]) -> Optional[Dict[str, Any]]:
    """The first judge's verdict on this answer, else the fallback judge's."""
    if not record or not record.get("answer"):
        return None
    return next((v for c in judge_configs if (v := cache.verdict(item, answer_config, record, c))), None)


async def judge_stage(judge, judge_config: str, answer_config: str, items: Sequence[Dict[str, Any]], cache: Cache,
                      args, earlier: Sequence[str] = ()) -> Tuple[int, Optional[str]]:
    """Judge every answer that has no verdict from this judge or the `earlier` ones."""
    from divrag.llm import LLMError
    from evaluation.judge import JudgeError, judge_messages, parse_verdicts

    todo = []
    for item in items:
        record = cache.answer(item["id"], answer_config)
        if needs_judge(item, record) and find_verdict(cache, item, answer_config, record, [*earlier, judge_config]) is None:
            todo.append((item, record))
    print(f"judge: {len(todo)} to judge ({judge_config})", flush=True)
    done = 0
    for n, (item, record) in enumerate(todo, 1):
        if args.max_requests is not None and n > args.max_requests:
            return done, f"stopped after --max-requests {args.max_requests}"
        texts = [p["text"] for p in record["passages"]]
        messages = judge_messages(item["question"], texts, record["answer"]["answer"], item.get("reference"))
        started = time.perf_counter()
        verdicts, raw, error = None, "", None
        for _ in range(2):  # one more try when the reply isn't the JSON asked for
            try:
                completion = await _with_busy_waits(lambda: judge.complete(messages), f"judge {item['id']}")
            except Stop as stop:
                return done, str(stop)
            except LLMError as exc:
                error = f"{exc.user_message} ({exc})"
                break
            raw = completion.text
            try:
                verdicts = parse_verdicts(raw, len(texts), has_reference=bool(item.get("reference")))
                break
            except JudgeError as exc:
                error = str(exc)
                await asyncio.sleep(args.pause)
        if verdicts is None:
            print(f"  [{n}/{len(todo)}] {item['id']}: judge failed: {error}; not cached, retried next run", flush=True)
            await asyncio.sleep(args.pause)
            continue
        cache.add({"kind": "judge", "id": item["id"], "answer_config": answer_config, "answer_hash": answer_hash(record),
                   "reference_hash": reference_hash(item), "judge_config": judge_config, "model": completion.model, "at": _now(),
                   "ms": round((time.perf_counter() - started) * 1000), "verdicts": verdicts})
        done += 1
        print(f"  [{n}/{len(todo)}] {item['id']}: judged by {completion.model} in {time.perf_counter() - started:.1f}s",
              flush=True)
        await asyncio.sleep(args.pause)
    return done, None


def _ranked_useful(useful: Sequence[bool], passages: Sequence[Dict[str, Any]]) -> List[bool]:
    """The judge's verdicts in rank order.

    The model reads the passages in document order (Retriever.as_passages);
    context precision is about rank, so they are put back in reranker-score
    order (a merged passage or a following chunk carries its best hit's score).
    """
    order = sorted(range(len(passages)), key=lambda i: -passages[i]["score"])
    return [useful[i] for i in order]


def score_question(item: Dict[str, Any], retrieval: Dict[str, Any], record: Optional[Dict[str, Any]],
                   verdict: Optional[Dict[str, Any]], embed=None) -> Dict[str, Any]:
    """One row of scores.json: everything the summary and the charts need for one question."""
    row: Dict[str, Any] = {
        "id": item["id"], "target": item["target"], "asker": item.get("asker"), "group": item["group"],
        "answerable": item["answerable"], "holdout": item.get("holdout", False), "pages": item.get("pages"),
        "page_hit": retrieval.get("hit"), "page_rr": retrieval.get("rr"), "page_precision": retrieval.get("precision"),
        "page_recall": retrieval.get("recall"), "ranked_pages": retrieval.get("ranked_pages"),
        "retrieval_ms": retrieval.get("retrieval_ms"),
        "answered": None, "outcome": "not run", "answer": None, "model": None, "timing_ms": None, "total_ms": None,
        "faithfulness": None, "answer_relevancy": None, "context_precision": None, "context_recall": None,
        "judge_model": None, "table_pass": None, "correct_refusal": None,
    }
    if record is None:
        return row
    answer = record.get("answer")
    if answer is None:
        row.update(outcome=record.get("error") or "error", answered=False)
        return row
    refused = answer["refused"]
    row.update(answered=not refused, answer=answer["answer"], model=answer.get("model"),
               outcome="refused" if refused else "uncited" if answer.get("uncited") else "answered",
               timing_ms=record["timing_ms"], total_ms=record["timing_ms"]["total"],
               # The answered run's own retrieval time, so it adds up with total_ms (the
               # report's fresh retrieval pass shares the CPU with whatever else runs then).
               retrieval_ms=record["timing_ms"].get("retrieval", row["retrieval_ms"]),
               cited_pages=sorted({p for s in answer["sources"] for p in (s["page"], s.get("page_end")) if p}))
    if not item["answerable"]:
        row["correct_refusal"] = 1.0 if refused else 0.0
    if item.get("accept") and item["answerable"]:
        row["table_pass"] = 1.0 if _grade(answer["answer"], item) else 0.0
    if verdict is None:
        return row
    v = verdict["verdicts"]
    row["judge_model"] = verdict.get("model")
    if not refused:
        row["faithfulness"] = m.faithfulness([s["supported"] for s in v["answer_statements"]])
    if refused:
        # A refusal of a question the documents answer is noncommittal by definition: RAGAS scores it 0.
        row["answer_relevancy"] = 0.0 if item["answerable"] else None
    elif embed is not None and v["generated_questions"]:
        vectors = embed([item["question"]] + v["generated_questions"])
        row["answer_relevancy"] = m.answer_relevancy(vectors[0], vectors[1:], v["noncommittal"])
    if item["answerable"] and item.get("reference"):
        row["context_precision"] = m.context_precision(_ranked_useful(v["useful"], record["passages"]))
        row["context_recall"] = m.context_recall([s["attributed"] for s in v["reference_statements"]])
    row["unsupported"] = [s["statement"] for s in v["answer_statements"] if not s["supported"]]
    row["missed"] = [s["statement"] for s in v["reference_statements"] if not s["attributed"]]
    return row


@functools.lru_cache(maxsize=1)
def _run_eval():
    """eval/run_eval.py (not a package; it imports nothing heavy at module level)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _grade(answer: str, item: Dict[str, Any]) -> bool:
    """eval/run_eval.py's substring grader for the table questions' accept/reject strings."""
    return _run_eval().grade(answer, item)


METRIC_KEYS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall",
               "page_hit", "page_rr", "page_precision", "page_recall", "table_pass", "correct_refusal")


def summarise(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Means, intervals and n per metric for all questions and per division, plus outcomes and times."""
    def block(group: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"questions": len(group)}
        for key in METRIC_KEYS:
            values = [r[key] for r in group if r.get(key) is not None]
            out[key] = {"mean": m.mean(values), "ci95": m.bootstrap_ci(values), "n": len(values)}
        outcomes: Dict[str, int] = {}
        for r in group:
            outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
        out["outcomes"] = outcomes
        answerable = [r for r in group if r["answerable"] and r["outcome"] != "not run"]
        out["answerable_refused"] = sum(1 for r in answerable if r["outcome"] == "refused")
        out["answerable_run"] = len(answerable)
        seconds = sorted(r["total_ms"] / 1000 for r in group if r.get("total_ms") is not None)
        retrieval = sorted(r["retrieval_ms"] for r in group if r.get("retrieval_ms") is not None)
        out["answer_seconds"] = {"n": len(seconds), "median": statistics.median(seconds) if seconds else None,
                                 "p90": m.percentile(seconds, 90),
                                 "max": seconds[-1] if seconds else None}
        out["retrieval_ms"] = {"n": len(retrieval), "median": statistics.median(retrieval) if retrieval else None}
        return out

    from divrag.divisions import DIVISIONS
    from evaluation.charts import division_names

    summary = {"all": block(rows)}
    for division in division_names(rows, {d.id: d.name for d in DIVISIONS}):
        summary[division] = block([r for r in rows if r["target"] == division])
    return summary


def report(items, retrievals, cache: Cache, answer_config: str, judge_configs: Sequence[str], pipe: Pipeline,
           scores_path: Path, charts_dir: Path, stopped: Optional[str]) -> Dict[str, Any]:
    from evaluation.charts import make_charts

    def embed(texts: List[str]):
        return pipe.embedder.passages(texts)

    rows = []
    for item in items:
        record = cache.answer(item["id"], answer_config)
        verdict = find_verdict(cache, item, answer_config, record, judge_configs)
        row = score_question(item, retrievals[item["id"]], record, verdict, embed)
        row["judge_config"] = verdict["judge_config"] if verdict else None
        rows.append(row)
    judged = sum(1 for r in rows if r["judge_model"])
    to_judge = sum(1 for item in items if needs_judge(item, cache.answer(item["id"], answer_config)))
    judge_label = judge_configs[0] + "".join(f" (fallback: {c})" for c in judge_configs[1:])
    scores = {
        "generated_at": _now(), "answer_config": answer_config, "judge_config": judge_label,
        "index": {"chunks": len(pipe.index.chunks), "divisions": pipe.index.divisions()},
        "coverage": {"questions": len(items), "answered_or_refused": sum(1 for r in rows if r["outcome"] != "not run"),
                     "judged": judged, "needing_judge": to_judge, "stopped": stopped},
        "summary": summarise(rows), "questions": rows,
    }
    scores_path.parent.mkdir(parents=True, exist_ok=True)
    scores_path.write_text(json.dumps(scores, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    made = make_charts(scores, charts_dir)
    print_summary(scores)
    print(f"\nscores -> {scores_path}\ncharts -> " + ", ".join(p.name for p in made))
    return scores


def _fmt(stat: Dict[str, Any]) -> str:
    if stat["mean"] is None:
        return "-"
    ci = stat["ci95"]
    return f"{stat['mean']:.2f}" + (f" [{ci[0]:.2f}-{ci[1]:.2f}]" if ci else "") + f" (n={stat['n']})"


def print_summary(scores: Dict[str, Any]) -> None:
    summary = scores["summary"]
    groups = list(summary)
    print("\n| metric | " + " | ".join(groups) + " |")
    print("|---|" + "---|" * len(groups))
    for key in METRIC_KEYS:
        print(f"| {key} | " + " | ".join(_fmt(summary[g][key]) for g in groups) + " |")
    for g in groups:
        s = summary[g]
        t = s["answer_seconds"]
        timing = f"median {t['median']:.1f}s, p90 {t['p90']:.1f}s, max {t['max']:.1f}s (n={t['n']})" if t["n"] else "-"
        print(f"{g}: outcomes {s['outcomes']}; answer time {timing}; retrieval median {s['retrieval_ms']['median']} ms")
    c = scores["coverage"]
    print(f"coverage: {c['answered_or_refused']}/{c['questions']} answered or refused, {c['judged']}/{c['needing_judge']} judged"
          + (f"; stopped early: {c['stopped']}" if c["stopped"] else ""))


def load_items(path: Path, only: Optional[Sequence[str]], limit: Optional[int]) -> List[Dict[str, Any]]:
    items = json.loads(path.read_text(encoding="utf-8"))["items"]
    if only:
        items = [i for i in items if i["id"] in set(only)]
    return items[:limit] if limit else items


def _models(value: Optional[str]) -> Optional[List[str]]:
    return [part.strip() for part in value.split(",") if part.strip()] if value else None


def _answer_client(args, settings) -> Tuple[Any, str]:
    """The answering client and its cache label: the hosted app's OpenRouterClient, or ChatClient elsewhere."""
    from divrag.llm import OpenRouterClient
    from evaluation.judge import ChatClient, is_openrouter

    base = args.answer_base_url or OPENROUTER_URL
    if is_openrouter(base):
        llm = OpenRouterClient(settings.openrouter_api_key or "", settings.models, settings.temperature, settings.reasoning)
        return llm, config_label(base, settings.models)
    models = _models(args.answer_models)
    if not models:
        raise SystemExit("--answer-models is required with --answer-base-url")
    key = os.environ.get("ANSWER_API_KEY", "none")
    return ChatClient(base, key, models, temperature=settings.temperature), config_label(base, models)


def _judge_client(base: str, models: Sequence[str], reasoning: Optional[str]) -> Tuple[Any, str]:
    from evaluation.judge import JUDGE_MAX_TOKENS, ChatClient, is_openrouter

    # OpenRouter takes the app's key; JUDGE_API_KEY is for any other endpoint (OpenAI), and is never sent to OpenRouter.
    key = (os.environ.get("OPENROUTER_API_KEY") if is_openrouter(base) else os.environ.get("JUDGE_API_KEY")) or "none"
    client = ChatClient(base, key, models, temperature=0.0, max_tokens=JUDGE_MAX_TOKENS, json_mode=True, reasoning=reasoning)
    return client, config_label(base, models)


def _judges(args) -> List[Tuple[Any, str]]:
    """The judge, then the fallback judge if one is set: it scores what the first couldn't.

    The fallback is for a free judge that hits its daily cap or keeps failing on
    a question (dots.llm3's provider returned 400 for U21 every time); each
    question's verdict records which judge gave it.
    """
    env = os.environ.get
    judges = [_judge_client(args.judge_base_url or env("JUDGE_BASE_URL") or OPENROUTER_URL,
                            _models(args.judge_models) or _models(env("JUDGE_MODELS")) or list(DEFAULT_JUDGE_MODELS),
                            args.judge_reasoning or env("JUDGE_REASONING") or None)]
    fallback_models = _models(args.fallback_judge_models) or _models(env("FALLBACK_JUDGE_MODELS"))
    if fallback_models:
        judges.append(_judge_client(args.fallback_judge_base_url or env("FALLBACK_JUDGE_BASE_URL") or OPENROUTER_URL,
                                    fallback_models, args.fallback_judge_reasoning or env("FALLBACK_JUDGE_REASONING") or None))
    return judges


async def warm_up(client, label: str) -> None:
    """Load a local model before the first question, so its load time isn't counted as answer time.

    Ollama loads a model on its first request (qwen2.5:14b's first answer took
    48 s against 2-4 s after) and swaps models between the answer and judge
    stages. Hosted endpoints are never warmed: the call would spend a request of a capped quota.
    """
    from evaluation.judge import is_openrouter

    base = getattr(client, "base_url", OPENROUTER_URL)
    if is_openrouter(base) or "api.openai.com" in base:
        return
    started = time.perf_counter()
    await client.complete([{"role": "user", "content": 'Reply with the JSON object {"ok": true}.'}])
    print(f"{label}: warmed up in {time.perf_counter() - started:.1f}s", flush=True)


async def run(args) -> int:
    from divrag.config import load_settings

    env_file = Path(args.env_file) if args.env_file else find_env_file()
    if env_file and env_file.is_file():
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)  # hosted/ never loads .env itself
    from evaluation.judge import is_openrouter

    answer_models = _models(args.answer_models)
    if answer_models and is_openrouter(args.answer_base_url or OPENROUTER_URL):
        # The hosted settings check that these are free models.
        os.environ["OPENROUTER_MODEL"] = answer_models[0]
        os.environ["OPENROUTER_FALLBACK_MODELS"] = ",".join(answer_models[1:])
    settings = load_settings()
    args.budget = args.budget or settings.request_budget_seconds

    items = load_items(Path(args.testset), args.only, args.limit)
    print(f"{len(items)} questions from {args.testset}; loading the models", flush=True)
    pipe = Pipeline(settings)
    retrievals = {item["id"]: pipe.retrieval(item) for item in items}
    hits = [r["hit"] for r in retrievals.values() if r["hit"] is not None]
    print(f"retrieval: gold page in the top {settings.top_k} for {int(sum(hits))}/{len(hits)} questions", flush=True)

    cache = Cache(Path(args.cache))
    llm, answer_config = _answer_client(args, settings)
    judges = _judges(args)
    judge_configs = [label for _, label in judges]
    stopped = None
    if args.stage in ("answer", "all"):
        if not args.answer_base_url and not settings.openrouter_api_key:
            stopped = "no OPENROUTER_API_KEY: answers skipped"
        else:
            if any(cache.answer(i["id"], answer_config) is None for i in items):
                await warm_up(llm, "answer model")
            _, stopped = await answer_stage(pipe, llm, answer_config, items, cache, args)
    if args.stage in ("judge", "all"):
        stops = [stopped] if stopped else []
        from divrag.llm import LLMError

        for n, (judge, judge_config) in enumerate(judges):
            # A judge on another endpoint (a local fallback) can go on after the first one's daily cap.
            try:
                await warm_up(judge, "judge model")
            except LLMError as exc:
                stops.append(f"{judge_config} unavailable ({exc})")
                continue
            _, judge_stopped = await judge_stage(judge, judge_config, answer_config, items, cache, args,
                                                 earlier=judge_configs[:n])
            stops += [judge_stopped] if judge_stopped else []
        stopped = "; ".join(stops) or None
    if stopped:
        print(f"stopped early: {stopped}", flush=True)
    report(items, retrievals, cache, answer_config, judge_configs, pipe, Path(args.scores), Path(args.charts), stopped)
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.run_ragas", description=__doc__.splitlines()[0])
    parser.add_argument("--stage", choices=("all", "retrieval", "answer", "judge", "report"), default="all",
                        help="all: answer and judge what isn't cached, then report; retrieval/report: no LLM calls")
    parser.add_argument("--testset", default=str(DEFAULT_TESTSET))
    parser.add_argument("--only", nargs="*", help="question ids")
    parser.add_argument("--limit", type=int, help="only the first N questions")
    parser.add_argument("--answer-base-url", help="OpenAI-compatible endpoint for answering (default: the hosted "
                        "app's OpenRouter client and settings)")
    parser.add_argument("--answer-models", help="comma-separated; on OpenRouter these must be :free models")
    parser.add_argument("--judge-base-url", help=f"default JUDGE_BASE_URL or {OPENROUTER_URL}")
    parser.add_argument("--judge-models", help=f"comma-separated (default JUDGE_MODELS or {','.join(DEFAULT_JUDGE_MODELS)}); "
                        "the key is JUDGE_API_KEY, or OPENROUTER_API_KEY on OpenRouter")
    parser.add_argument("--judge-reasoning", choices=("low", "medium", "high"),
                        help="reasoning effort for a reasoning judge model (default JUDGE_REASONING or the model's own)")
    parser.add_argument("--fallback-judge-base-url", help=f"default FALLBACK_JUDGE_BASE_URL or {OPENROUTER_URL}")
    parser.add_argument("--fallback-judge-models", help="comma-separated (default FALLBACK_JUDGE_MODELS); judges what the "
                        "first judge couldn't, e.g. a local gpt-oss:20b at http://localhost:11434/v1")
    parser.add_argument("--fallback-judge-reasoning", choices=("low", "medium", "high"))
    parser.add_argument("--budget", type=float, help="seconds per question (default: REQUEST_BUDGET_SECONDS, 55)")
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between model calls, to pace a shared free quota")
    parser.add_argument("--max-requests", type=int, help="stop each stage after this many new questions")
    parser.add_argument("--env-file", help="default: the repo's .env (found above a git worktree too)")
    parser.add_argument("--cache", default=str(DEFAULT_CACHE))
    parser.add_argument("--scores", default=str(DEFAULT_SCORES))
    parser.add_argument("--charts", default=str(DEFAULT_CHARTS))
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.stage in ("retrieval", "report"):
        args.stage = "report"
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
