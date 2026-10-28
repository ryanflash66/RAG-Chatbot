"""Measure the hosted app at a given document count, so a bigger index can be compared with a smaller one.

    py -m prototype.stress_test measure --label before --out results/before.json [--index hosted/index]
                                        [--repeat 5] [--answers http://127.0.0.1:8104] [--answer-limit 6]
    py -m prototype.stress_test chart results/before.json results/after.json [--out-dir docs/charts]

`measure` loads an index with the hosted app's own code (divrag) and records:

- retrieval latency: embed, search and rerank milliseconds for a fixed set of
  questions across all three divisions (QUESTIONS), each run --repeat times
  after a warm-up, the median run per question, then median and p95 across them;
- wrong-division hits: every vector candidate, every reranked hit and every
  following chunk of those questions and of the eval questions must be from the
  asked division (the filter is inside IndexFile.search, so this must be 0);
- hit@5 per division on eval/retrieval_pages.json (and the table questions with
  pages): a case passes when one of the app's top 5 reranked hits is an expected
  page *of the division's original manual* (GOLD_SOURCE), so a page 126 of a newly
  added document never counts as the UAM's page 126; and how many of the top 5
  came from documents added since (dilution);
- per-document numbers read from the index (chunks, pages with text, table and
  junk chunks), so scanned pages and broken tables show up by document;
- with --answers, the full answer time of the first --answer-limit ANSWER_QUESTIONS
  through a running server's POST /api/ask (one LLM call each, more on a retry;
  the free models' daily cap is shared, so keep this small), with the documents
  and pages each answer cited.

`chart` draws the before/after comparison PNGs used in docs/stress-test-50-documents.md.
"""

import argparse
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from prototype import HOSTED_DIR
from divrag.divisions import BY_ID, DIVISIONS
from divrag.embedder import Embedder, Reranker, model_cache_dir
from divrag.index_file import IndexFile
from divrag.retrieval import DEFAULT_CANDIDATES, Retriever
from divrag.timing import StepTimer

EVAL_DIR = HOSTED_DIR.parent / "eval"
DATA_DIR = HOSTED_DIR.parent / "data"
TOP = 5

# The manual each division's eval cases were written from. A gold page only
# counts in this document: after the stress test added 18-20 documents per
# division, "page 126" alone would also match page 126 of any of them.
GOLD_SOURCE = {
    "wztc": "TMP Design Manual (Combined, No Links).pdf",
    "utilities": "20220713 NCDOT UAM Ver 2-0.pdf",
}

# Fixed, so a run before and after adding documents times the same questions:
# the divisions' example questions as of the third division (DAR-622), plus a
# few verified eval questions per division (eval/retrieval_pages.json).
QUESTIONS = (
    ("wztc", "What are the dimensions of the NC-PCB concrete barrier?"),
    ("wztc", "What is the minimum acceleration lane for an interstate entrance ramp in a work zone?"),
    ("wztc", "What lane width is used on a freeway or divided highway work zone?"),
    ("wztc", "When must portable concrete barrier on a bridge deck be anchored?"),
    ("wztc", "How long can a work zone speed reduction using portable devices stay in place?"),
    ("wztc", "What is the run-out length at 55 mph with 2,000 to 6,000 vpd?"),
    ("utilities", "At what distance from a travel lane does utility work require a lane closure?"),
    ("utilities", "Who pays for a detour when a utility closes a road?"),
    ("utilities", "What is the minimum cover for a utility installed by bore and jack?"),
    ("utilities", "If utility work blocks a sidewalk for 7 work days or more, what is required?"),
    ("utilities", "How much advance notice does NCDOT need before a utility owner does maintenance work in right of way?"),
    ("utilities", "Can a utility owner work in a median?"),
    ("tmsd", "How many TODS panels can go on one intersection approach?"),
    ("tmsd", "How long does an attraction have to change its operation to qualify for TODS?"),
    ("tmsd", "What fees does an attraction pay for a TODS sign?"),
    ("tmsd", "How long does a regional office have to complete a fatal crash investigation?"),
)

# (asker, target, question, expected document): the answer-time subset, two per
# division plus a third TMSD one. They are also the end-to-end checks: the
# answer should cite the expected document (and, where known, page).
ANSWER_QUESTIONS = (
    ("utilities", "wztc", "What are the dimensions of the NC-PCB concrete barrier?", GOLD_SOURCE["wztc"], (32, 33)),
    ("utilities", "wztc", "When must portable concrete barrier on a bridge deck be anchored?", GOLD_SOURCE["wztc"], (46,)),
    ("wztc", "utilities", "Who pays for a detour when a utility closes a road?", GOLD_SOURCE["utilities"], (127,)),
    ("wztc", "utilities", "What is the minimum cover for a utility installed by bore and jack?", GOLD_SOURCE["utilities"], (101,)),
    ("wztc", "tmsd", "How many TODS panels can go on one intersection approach?", "TODS Manual - September 2024.pdf", ()),
    ("utilities", "tmsd", "How long does a regional office have to complete a fatal crash investigation?",
     "Fatal Investigation Guidelines.pdf", ()),
    ("wztc", "tmsd", "What fees does an attraction pay for a TODS sign?", "TODS Manual - September 2024.pdf", ()),
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    at = (len(ordered) - 1) * q
    low = int(at)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (at - low)


def eval_cases() -> List[Dict]:
    cases = json.loads((EVAL_DIR / "retrieval_pages.json").read_text(encoding="utf-8"))["cases"]
    tables = json.loads((EVAL_DIR / "table_questions.json").read_text(encoding="utf-8"))["cases"]
    cases += [{"id": c["id"], "division": "wztc", "question": c["question"], "pages": [int(p) for p in c["pages"]]}
              for c in tables if c.get("pages")]
    return cases


def gold_pages(case: Dict, index: IndexFile) -> set:
    """The expected pages of the case's gold document: its `pages`, or the pages of the chunks holding its `key`."""
    if "pages" in case:
        return set(case["pages"])
    source = GOLD_SOURCE[case["division"]]
    key = _norm(case["key"])
    pages = {c["page"] for c in index.chunks if c.get("source") == source and key in _norm(c["text"])}
    if not pages:
        raise SystemExit(f"{case['id']}: key not found in {source}: {case['key']!r}")
    return pages


def latency(retriever: Retriever, repeat: int) -> Dict:
    rows = []
    for division, question in QUESTIONS:
        runs = []
        for _ in range(repeat):
            timer = StepTimer()
            started = time.perf_counter()
            retriever.retrieve(question, division, k=TOP, timer=timer)
            ms = timer.as_ms()
            runs.append({"embed": ms["embed"], "search": ms["search"], "rerank": ms["rerank"],
                         "total": (time.perf_counter() - started) * 1000})
        best = sorted(runs, key=lambda r: r["total"])[len(runs) // 2]  # the median run
        rows.append(dict(best, division=division, question=question))
    summary = {}
    for step in ("embed", "search", "rerank", "total"):
        values = [r[step] for r in rows]
        summary[step] = {"median": statistics.median(values), "p95": _percentile(values, 0.95), "max": max(values)}
    return {"questions": rows, "summary": summary}


def wrong_division(retriever: Retriever, questions: Sequence[Sequence[str]]) -> Dict:
    """Hits from another division among the candidates, the top 5 and their following chunks (must be 0)."""
    index = retriever.index
    checked = wrong = 0
    examples = []
    for division, question in questions:
        vector = retriever.embedder.query(question)
        candidates = index.search(vector, k=DEFAULT_CANDIDATES, division=division)
        top = retriever.retrieve(question, division, k=TOP)
        for hit in candidates + retriever.with_following(top):
            checked += 1
            if hit.chunk.get("division") != division:
                wrong += 1
                examples.append({"division": division, "question": question, "hit": hit.chunk.get("source")})
    return {"checked": checked, "wrong": wrong, "examples": examples[:10]}


def hit_at_5(retriever: Retriever, cases: List[Dict]) -> Dict:
    index = retriever.index
    rows = []
    for case in cases:
        division = case["division"]
        pages, source = gold_pages(case, index), GOLD_SOURCE[division]
        hits = retriever.retrieve(case["question"], division, k=TOP)
        rank = next((i for i, h in enumerate(hits, 1) if h.chunk.get("source") == source and h.chunk.get("page") in pages),
                    None)
        rows.append({"id": case["id"], "division": division, "rank": rank,
                     "other_documents_in_top5": sum(1 for h in hits if h.chunk.get("source") != source),
                     "top_sources": [h.chunk.get("source") for h in hits]})
    by_division = {}
    for division in GOLD_SOURCE:
        group = [r for r in rows if r["division"] == division]
        if not group:
            continue
        by_division[division] = {
            "hits": sum(1 for r in group if r["rank"]),
            "cases": len(group),
            "mrr": sum(1 / r["rank"] for r in group if r["rank"]) / len(group),
            "missed": [r["id"] for r in group if not r["rank"]],
            "other_documents_in_top5": sum(r["other_documents_in_top5"] for r in group),
        }
    return {"cases": rows, "by_division": by_division}


_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


def _letters_share(text: str) -> float:
    visible = [ch for ch in text if not ch.isspace()]
    return sum(ch.isalpha() for ch in visible) / len(visible) if visible else 0.0


def documents(index: IndexFile, pdf_pages: Dict[str, int]) -> List[Dict]:
    """Per-document chunk counts and the signs of a PDF that didn't read well.

    table: most of the chunk's lines are Markdown table rows. junk: under 40% of
    its visible characters are letters (rows of numbers, dashes, broken glyphs:
    a drawing's dimension labels or a table read as loose text). tiny: under 80
    characters, usually a page with only a title block or a figure caption.
    """
    rows = []
    by_source: Dict[str, List[Dict]] = defaultdict(list)
    for chunk in index.chunks:
        by_source[chunk["source"]].append(chunk)
    for source, chunks in by_source.items():
        tables = junk = tiny = 0
        for chunk in chunks:
            lines = [line for line in chunk["text"].splitlines() if line.strip()]
            if lines and len(_TABLE_ROW.findall(chunk["text"])) > len(lines) / 2:
                tables += 1
            if _letters_share(chunk["text"]) < 0.4:
                junk += 1
            if len(chunk["text"]) < 80:
                tiny += 1
        pages = {c["page"] for c in chunks if c.get("page")}
        rows.append({
            "source": source, "division": chunks[0]["division"], "chunks": len(chunks),
            "pdf_pages": pdf_pages.get(source), "pages_with_chunks": len(pages),
            "table_chunks": tables, "junk_chunks": junk, "tiny_chunks": tiny,
            "chars": sum(len(c["text"]) for c in chunks),
        })
    # A configured document with no chunks (a scanned PDF) is in the page's list but not in the index.
    for division in DIVISIONS:
        for document in division.documents:
            if document.file in pdf_pages and document.file not in by_source:
                rows.append({"source": document.file, "division": division.id, "chunks": 0,
                             "pdf_pages": pdf_pages[document.file], "pages_with_chunks": 0,
                             "table_chunks": 0, "junk_chunks": 0, "tiny_chunks": 0, "chars": 0})
    return rows


def pdf_page_counts() -> Dict[str, int]:
    """Each configured document's page count, from its PDF in hosted/documents/ when it is there."""
    from divrag.divisions import DOCUMENTS_DIR

    counts = {}
    try:
        import pymupdf
    except ImportError:
        return counts
    for division in DIVISIONS:
        for document in division.documents:
            # Where prototype.ingest reads it: the division's folder, else data/ (older checkouts).
            path = next((p for p in (DOCUMENTS_DIR / division.id / document.file, DATA_DIR / document.file)
                         if p.is_file()), None)
            if path is not None:
                with pymupdf.open(path) as pdf:
                    counts[document.file] = pdf.page_count
    return counts


def _source_file(url: str) -> Optional[str]:
    base = url.split("#", 1)[0]
    for division in DIVISIONS:
        for document in division.documents:
            if document.url == base:
                return document.file
    return None


def _json_or_error(body: bytes) -> Dict:
    try:
        return json.loads(body or b"{}")
    except ValueError:
        return {"error": body[:200].decode("utf-8", "replace")}


def _covers(cited: Dict, pages: Sequence[int]) -> bool:
    """Whether a cited source's page range (page..page_end) includes one of `pages`."""
    first = cited.get("page")
    if first is None:
        return False
    last = cited.get("page_end") or first
    return any(first <= p <= last for p in pages)


def answers(base_url: str, limit: int) -> List[Dict]:
    rows = []
    for asker, target, question, expected, pages in ANSWER_QUESTIONS[:limit]:
        body = json.dumps({"question": question, "asker": asker, "target": target, "history": []}).encode()
        request = urllib.request.Request(urllib.parse.urljoin(base_url, "/api/ask"), data=body,
                                         headers={"Content-Type": "application/json"})
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310 - a local server
                status, payload = response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            status, payload = exc.code, _json_or_error(exc.read())
        except (urllib.error.URLError, OSError, ValueError) as exc:  # server down, timeout, not JSON
            status, payload = None, {"error": f"{type(exc).__name__}: {exc}"}
        wall = (time.perf_counter() - started) * 1000
        cited = [{"file": _source_file(s["url"]), "page": s.get("page"), "page_end": s.get("page_end")}
                 for s in payload.get("sources", [])]
        cites_expected = any(c["file"] == expected for c in cited)
        cites_page = not pages or any(c["file"] == expected and _covers(c, pages) for c in cited)
        rows.append({
            "asker": asker, "target": target, "question": question, "status": status, "wall_ms": wall,
            "timing_ms": payload.get("timing_ms"), "refused": payload.get("refused"), "uncited": payload.get("uncited"),
            "retried": payload.get("retried"), "model": payload.get("model"), "error": payload.get("error"),
            "cited": cited, "expected": expected, "expected_pages": list(pages),
            "cites_expected": cites_expected, "cites_expected_page": cites_expected and cites_page,
            "answer": (payload.get("answer") or "")[:600],
        })
        print(f"  {target}: {status} {wall / 1000:.1f}s refused={payload.get('refused')} "
              f"cites expected={cites_expected} page={cites_expected and cites_page} {question}", flush=True)
    return rows


def measure(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    index = IndexFile.load(args.index)
    load_ms = (time.perf_counter() - started) * 1000
    cache = model_cache_dir()
    retriever = Retriever(index, Embedder(index.model, cache_dir=cache), Reranker(cache_dir=cache))
    retriever.warm_up()
    for division, question in QUESTIONS[:3]:  # the first real-length reranks are slower than later ones
        retriever.retrieve(question, division, k=TOP)

    files = [args.index / f for f in ("chunks.json", "vectors.npy")]
    result: Dict = {
        "label": args.label,
        "index": {
            "chunks": len(index.chunks),
            "by_division": dict(Counter(c["division"] for c in index.chunks)),
            "documents": len({c["source"] for c in index.chunks}),
            "bytes": {f.name: f.stat().st_size for f in files},
            "load_ms": load_ms,
        },
    }
    print(f"{args.label}: {len(index.chunks)} chunks, {result['index']['documents']} documents, "
          f"index loaded in {load_ms:.0f} ms", flush=True)
    result["latency"] = latency(retriever, args.repeat)
    summary = result["latency"]["summary"]
    print("  retrieval ms median/p95: " + ", ".join(
        f"{step} {summary[step]['median']:.0f}/{summary[step]['p95']:.0f}" for step in summary), flush=True)
    cases = eval_cases()
    result["wrong_division"] = wrong_division(retriever, list(QUESTIONS) + [(c["division"], c["question"]) for c in cases])
    print(f"  wrong-division hits: {result['wrong_division']['wrong']} of {result['wrong_division']['checked']}", flush=True)
    result["hit_at_5"] = hit_at_5(retriever, cases)
    for division, row in result["hit_at_5"]["by_division"].items():
        print(f"  hit@5 {division}: {row['hits']}/{row['cases']} (MRR {row['mrr']:.3f}), missed {row['missed'] or 'none'}",
              flush=True)
    result["documents"] = documents(index, pdf_page_counts())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Written before the answers too, so a failed LLM run keeps the minutes of retrieval results.
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    if args.answers:
        result["answers"] = answers(args.answers, args.answer_limit)
        args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


def chart(args: argparse.Namespace) -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    colors = {"before": "#9aa5b1", "after": "#1f5aa6"}

    # Retrieval latency, median and p95 per step.
    steps = ["embed", "search", "rerank", "total"]
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    width = 0.2
    for i, (run, stat) in enumerate([(before, "median"), (before, "p95"), (after, "median"), (after, "p95")]):
        label = "before" if run is before else "after"
        values = [run["latency"]["summary"][s][stat] for s in steps]
        bars = ax.bar([x + (i - 1.5) * width for x in range(len(steps))], values, width,
                      color=colors[label], alpha=1.0 if stat == "median" else 0.55,
                      label=f"{label} ({run['index']['documents']} docs), {stat}")
        ax.bar_label(bars, fmt="%.0f", fontsize=7, padding=1)
    ax.set_xticks(range(len(steps)), steps)
    ax.set_ylabel("milliseconds")
    ax.set_title(f"Retrieval latency per question ({len(before['latency']['questions'])} questions, local CPU)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(args.out_dir / "stress-latency.png", dpi=150)
    plt.close(fig)

    # Chunks per division, before and after.
    divisions = [d.id for d in DIVISIONS]
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    for i, (label, run) in enumerate([("before", before), ("after", after)]):
        values = [run["index"]["by_division"].get(d, 0) for d in divisions]
        bars = ax.bar([x + (i - 0.5) * 0.38 for x in range(len(divisions))], values, 0.38, color=colors[label],
                      label=f"{label}: {run['index']['chunks']} chunks, {run['index']['documents']} documents with text")
        ax.bar_label(bars, fontsize=8, padding=1)
    ax.set_xticks(range(len(divisions)), [BY_ID[d].name for d in divisions], fontsize=8)
    ax.set_ylabel("chunks (passages)")
    ax.set_title("Index size by division")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=8, frameon=False, loc="upper center")
    fig.tight_layout()
    fig.savefig(args.out_dir / "stress-chunks.png", dpi=150)
    plt.close(fig)

    # hit@5 on the known-page questions, per division with eval cases.
    graded = list(before["hit_at_5"]["by_division"])
    fig, ax = plt.subplots(figsize=(6.0, 3.2))
    for i, (label, run) in enumerate([("before", before), ("after", after)]):
        rows = [run["hit_at_5"]["by_division"][d] for d in graded]
        bars = ax.bar([x + (i - 0.5) * 0.38 for x in range(len(graded))], [100 * r["hits"] / r["cases"] for r in rows],
                      0.38, color=colors[label], label=f"{label} ({run['index']['documents']} documents with text)")
        ax.bar_label(bars, labels=[f"{r['hits']}/{r['cases']}" for r in rows], fontsize=8, padding=1)
    ax.set_xticks(range(len(graded)), [BY_ID[d].name for d in graded], fontsize=8)
    ax.set_ylim(0, 130)
    ax.set_ylabel("% with the gold page in the top 5")
    ax.set_title("Known-page questions: gold page of the original manual in the top 5", fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=8, frameon=False, loc="upper center", ncol=2)
    fig.tight_layout()
    fig.savefig(args.out_dir / "stress-hit-at-5.png", dpi=150)
    plt.close(fig)

    # Build time per document (after), the slowest first.
    if args.build:
        build = json.loads(Path(args.build).read_text(encoding="utf-8"))
        rows = sorted(build["documents"], key=lambda r: -r["seconds"])[:15]
        fig, ax = plt.subplots(figsize=(7.5, 4.6))
        names = [r["source"] if len(r["source"]) < 48 else r["source"][:45] + "..." for r in rows]
        bars = ax.barh(names[::-1], [r["seconds"] for r in rows][::-1], color=colors["after"])
        ax.bar_label(bars, fmt="%.0f s", fontsize=7, padding=2)
        ax.set_xlabel("seconds to read and split")
        ax.set_title(f"Slowest 15 of {len(build['documents'])} documents to read "
                     f"(all: {build['read_split']:.0f} s; embedding: {build['embed']:.0f} s)", fontsize=9)
        ax.tick_params(axis="y", labelsize=7)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(args.out_dir / "stress-build-time.png", dpi=150)
        plt.close(fig)
    print(f"charts in {args.out_dir}")
    return 0


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m prototype.stress_test", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("measure", help="time retrieval (and answers) and check hit@5 on one index")
    m.add_argument("--label", required=True)
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--index", type=Path, default=HOSTED_DIR / "index")
    m.add_argument("--repeat", type=int, default=5)
    m.add_argument("--answers", help="base URL of a running server to time full answers against (uses the LLM)")
    m.add_argument("--answer-limit", type=int, default=6, help=f"how many of the {len(ANSWER_QUESTIONS)} answer questions")
    c = sub.add_parser("chart", help="draw before/after PNGs")
    c.add_argument("before")
    c.add_argument("after")
    c.add_argument("--build", help="the after build's --timings JSON from prototype.ingest")
    c.add_argument("--out-dir", type=Path, default=HOSTED_DIR.parent / "docs" / "charts")
    args = parser.parse_args(argv)
    return measure(args) if args.command == "measure" else chart(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
