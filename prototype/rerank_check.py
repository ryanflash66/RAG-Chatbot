"""Check whether the expected pages survive reranking, for several ways of reranking.

    py -m prototype.rerank_check [--settings 512/32 384/32 512/1 512/32/fp32 ...] [--repeat 3] [--only ID ...]

Runs each question in eval/retrieval_pages.json (and the table questions with
pages in eval/table_questions.json) through the hosted app's vector search (top
20 within the asked division), then reranks those 20 once per setting
TOKENS/BATCH[/fp32]: the cross-encoder reads at most TOKENS of each (question,
passage) pair, BATCH pairs per model call, with the int8 file the app uses (or
the fp32 one). For each setting it prints where the first chunk from an
expected page ranks, how many questions keep one in the top 5, the mean
reciprocal rank, and the rerank time (the fastest of --repeat runs per question).

A case with a `key` is "late" when the key ends past what a 384-token reranker
reads in every chunk that holds it, but within what a 512-token one reads in at
least one: those answers are the ones a shorter input could lose.
"""

import argparse
import json
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

from prototype import HOSTED_DIR
from divrag.embedder import RERANK_BATCH_SIZE, Embedder, Reranker, model_cache_dir
from divrag.index_file import IndexFile
from divrag.retrieval import DEFAULT_CANDIDATES

EVAL_DIR = HOSTED_DIR.parent / "eval"
TOP = 5


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def load_cases(only: Optional[List[str]] = None) -> List[Dict]:
    cases = json.loads((EVAL_DIR / "retrieval_pages.json").read_text(encoding="utf-8"))["cases"]
    tables = json.loads((EVAL_DIR / "table_questions.json").read_text(encoding="utf-8"))["cases"]
    cases += [{"id": c["id"], "division": "wztc", "question": c["question"], "pages": [int(p) for p in c["pages"]]}
              for c in tables if c.get("pages")]
    return [c for c in cases if not only or c["id"] in only]


def key_tokens(tokenizer, text: str, key: str) -> Optional[int]:
    """Tokens of `text` up to the end of `key` (None if `key` isn't in it), ignoring case and spacing.

    Spacing doesn't change the tokens: the reranker's tokenizer splits on it.
    """
    flat = " ".join(text.split())
    at = flat.lower().find(_norm(key))
    if at < 0:
        return None
    end = at + len(_norm(key))
    return sum(1 for start, _ in tokenizer.encode(flat, add_special_tokens=False).offsets if start < end)


class Setting:
    """One way of reranking: at most `tokens` per pair, `batch` pairs per model call, the int8 or fp32 file."""

    def __init__(self, spec: str, cache: str, fp32_cache: str):
        parts = spec.split("/")
        self.name = spec
        self.tokens = int(parts[0])
        self.batch = int(parts[1]) if len(parts) > 1 else RERANK_BATCH_SIZE
        fp32 = len(parts) > 2 and parts[2] == "fp32"
        self.reranker = Reranker(cache_dir=fp32_cache, model_file="onnx/model.onnx") if fp32 else Reranker(cache_dir=cache)
        self.model = self.reranker._load()
        self.model.model.tokenizer.enable_truncation(max_length=self.tokens)  # longest_first, as the model's own 512

    def scores(self, question: str, texts: List[str]) -> List[float]:
        return [float(s) for s in self.model.rerank(question, texts, batch_size=self.batch)]


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m prototype.rerank_check", description=__doc__.splitlines()[0])
    parser.add_argument("--settings", nargs="+", default=["512", "384", "256"],
                        help=f"TOKENS[/BATCH[/fp32]] per setting (default batch {RERANK_BATCH_SIZE}, as the hosted app; "
                             "fp32: the unquantized file)")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--index", default=str(HOSTED_DIR / "index"))
    parser.add_argument("--fp32-cache", default=str(Path(tempfile.gettempdir()) / "fastembed_cache"),
                        help="fastembed cache that holds (or will download) the fp32 file")
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args(argv)

    index = IndexFile.load(args.index)
    cache = model_cache_dir()
    embedder = Embedder(index.model, cache_dir=cache)
    settings = [Setting(spec, cache, args.fp32_cache) for spec in args.settings]
    for setting in settings:
        setting.scores("warm up", ["warm up"])
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_str(settings[0].model.model.tokenizer.to_str())  # a copy, for counting
    tokenizer.no_truncation()
    count = lambda text: len(tokenizer.encode(text, add_special_tokens=False).ids)

    cases = load_cases(args.only)
    rows = []
    for case in cases:
        division, question = case["division"], case["question"]
        pages = set(case.get("pages", []))
        late = None
        if case.get("key"):
            holding = [(c, key_tokens(tokenizer, c["text"], case["key"])) for c in index.chunks if c["division"] == division]
            holding = [(c, n) for c, n in holding if n is not None]
            if not holding:
                raise SystemExit(f"{case['id']}: key not found in {division}: {case['key']!r}")
            pages |= {c["page"] for c, _ in holding} if "pages" not in case else set()
            reach = min(n for _, n in holding)
            room = lambda n: n - 3 - count(question)  # [CLS] question [SEP] passage [SEP]
            late = room(512) >= reach > room(384)
        hits = index.search(embedder.query(question), k=DEFAULT_CANDIDATES, division=division)
        vector_rank = next((i for i, h in enumerate(hits, 1) if h.chunk["page"] in pages), None)
        row = {"id": case["id"], "division": division, "pages": sorted(pages), "late": late, "vector": vector_rank}
        texts = [h.chunk["text"] for h in hits]
        for setting in settings:
            seconds = []
            for _ in range(args.repeat):
                started = time.perf_counter()
                scores = setting.scores(question, texts)
                seconds.append(time.perf_counter() - started)
            order = [h for _, h in sorted(zip(scores, hits), key=lambda pair: -pair[0])]
            row[setting.name] = next((i for i, h in enumerate(order, 1) if h.chunk["page"] in pages), None)
            row["ms " + setting.name] = min(seconds) * 1000
        rows.append(row)

    names = [s.name for s in settings]
    fmt = lambda r: "-" if r is None else str(r)
    print("| id | division | pages | late | vector | " + " | ".join(names) + " |")
    print("|---|---|---|---|---|" + "---|" * len(names))
    for row in rows:
        late = "late" if row["late"] else ""
        print(f"| {row['id']} | {row['division']} | {','.join(map(str, row['pages']))} | {late} | {fmt(row['vector'])} | "
              + " | ".join(fmt(row[n]) for n in names) + " |")

    groups = {"all": rows, "late": [r for r in rows if r["late"]]}
    print(f"\n{len(rows)} questions, {len(groups['late'])} late; top {TOP} of {DEFAULT_CANDIDATES} reranked vector hits\n")
    print("| tokens/batch | group | in top 5 | MRR | missed (rank) | rerank ms median | rerank ms total |")
    print("|---|---|---|---|---|---|---|")
    for n in names:
        for name, group in groups.items():
            top = sum(1 for r in group if r[n] is not None and r[n] <= TOP)
            mrr = sum(1 / r[n] for r in group if r[n]) / len(group)
            missed = ", ".join(f"{r['id']} ({fmt(r[n])})" for r in group if r[n] is None or r[n] > TOP) or "none"
            ms = [r["ms " + n] for r in group]
            print(f"| {n} | {name} | {top}/{len(group)} | {mrr:.3f} | {missed} | {statistics.median(ms):.0f} | {sum(ms):.0f} |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
