"""Charts for the evaluation (matplotlib, PNG): one bar chart per metric plus the answer time.

    py -m evaluation.charts [--scores evaluation/results/scores.json] [--out evaluation/charts]

Every chart is drawn from scores.json, so it can be redrawn without running
anything. Bars are means over the questions the metric applies to, the
error bars are 95% bootstrap intervals, and every bar is labelled with its
value and n. Groups are "All" plus one bar per division in the scores, so a
new division shows up without changes here.

Colours follow the dataviz reference palette: one hue (blue) for a single
series, the fixed categorical order (blue, orange, aqua, ...) when divisions
are the series.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from evaluation import EVALUATION_DIR  # noqa: E402
from evaluation.metrics import bootstrap_ci, mean, percentile  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7"
SURFACE = "#fcfcfb"

RAGAS = (
    ("faithfulness", "Faithfulness", "Share of the answer's statements supported by the retrieved passages"),
    ("answer_relevancy", "Answer relevancy", "Mean cosine similarity of questions generated from the answer to the question"),
    ("context_precision", "Context precision", "Rank-weighted share of retrieved passages useful for the reference answer"),
    ("context_recall", "Context recall", "Share of the reference answer's statements found in the retrieved passages"),
)
PAGE = (
    ("page_hit", "Hit@5"),
    ("page_rr", "Reciprocal rank"),
    ("page_precision", "Page precision"),
    ("page_recall", "Page recall"),
)


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _figure(width: float = 7.5, height: float = 4.2):
    fig, ax = plt.subplots(figsize=(width, height), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    return fig, ax


def _bar_label(ax, bar, value: float, n: int) -> None:
    """The value and n inside the bar's foot, or above a bar too short to hold them."""
    x = bar.get_x() + bar.get_width() / 2
    if value >= 0.2:
        ax.text(x, 0.03, f"{value:.2f}\nn={n}", ha="center", va="bottom", fontsize=9, color="white", fontweight="bold")
    else:
        ax.text(x, value + 0.06, f"{value:.2f}\nn={n}", ha="center", va="bottom", fontsize=9, color=INK)


def _title(fig, ax, title: str, subtitle: str) -> None:
    fig.text(0.02, 0.905, subtitle, fontsize=9, color=MUTED, ha="left", va="top")
    fig.text(0.02, 0.975, title, fontsize=12, color=INK, ha="left", va="top", fontweight="bold")


def division_names(rows: Sequence[Dict[str, Any]], names: Dict[str, str]) -> List[str]:
    """Division ids in divisions.py's order (`names`), then any the index has that it doesn't."""
    present = {r["target"] for r in rows}
    return [d for d in names if d in present] + sorted(present - set(names))


def _groups(rows: Sequence[Dict[str, Any]], key: str, names: Dict[str, str]):
    """(label, values) for All and each division, values being the metric where it applies."""
    out = [("All", [r[key] for r in rows if r.get(key) is not None])]
    for division in division_names(rows, names):
        out.append((names.get(division, division), [r[key] for r in rows if r["target"] == division and r.get(key) is not None]))
    return out


def metric_chart(rows: Sequence[Dict[str, Any]], key: str, title: str, meaning: str, names: Dict[str, str],
                 path: Path, footnote: str) -> bool:
    groups = [(label, values) for label, values in _groups(rows, key, names) if values]
    if not groups:
        return False
    fig, ax = _figure()
    labels = [label for label, _ in groups]
    means = [mean(values) for _, values in groups]
    cis = [bootstrap_ci(values) for _, values in groups]
    low = [m - (ci[0] if ci else m) for m, ci in zip(means, cis)]
    high = [(ci[1] if ci else m) - m for m, ci in zip(means, cis)]
    colours = ["#1c5cab"] + [SERIES[0]] * (len(groups) - 1)
    bars = ax.bar(labels, means, width=0.55, color=colours, edgecolor=SURFACE, linewidth=2)
    ax.errorbar(labels, means, yerr=[low, high], fmt="none", ecolor=INK, elinewidth=1, capsize=4)
    for bar, value, (_, values) in zip(bars, means, groups):
        _bar_label(ax, bar, value, len(values))
    ax.set_ylim(0, 1.05)
    ax.set_ylabel(f"{title} (0 to 1, higher is better)", color=MUTED, fontsize=9)
    ax.set_xlabel("Division asked", color=MUTED, fontsize=9)
    _title(fig, ax, title, meaning)
    fig.text(0.02, 0.01, footnote, fontsize=7.5, color=MUTED, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04, 1, 0.86))
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return True


def overview_chart(rows: Sequence[Dict[str, Any]], path: Path, footnote: str) -> bool:
    """The four RAGAS metrics side by side, over all questions: the headline."""
    present = [(key, title) for key, title, _ in RAGAS if any(r.get(key) is not None for r in rows)]
    if not present:
        return False
    fig, ax = _figure(8, 4.2)
    values = [[r[key] for r in rows if r.get(key) is not None] for key, _ in present]
    means = [mean(v) for v in values]
    cis = [bootstrap_ci(v) for v in values]
    bars = ax.bar([t for _, t in present], means, width=0.55, color=SERIES[0], edgecolor=SURFACE, linewidth=2)
    ax.errorbar([t for _, t in present], means, fmt="none", ecolor=INK, elinewidth=1, capsize=4,
                yerr=[[m - (c[0] if c else m) for m, c in zip(means, cis)], [(c[1] if c else m) - m for m, c in zip(means, cis)]])
    for bar, value, v in zip(bars, means, values):
        _bar_label(ax, bar, value, len(v))
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score (0 to 1, higher is better)", color=MUTED, fontsize=9)
    _title(fig, ax, "RAGAS metrics, all questions", "Mean per metric with 95% bootstrap interval; n = questions the metric applies to")
    fig.text(0.02, 0.01, footnote, fontsize=7.5, color=MUTED, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04, 1, 0.86))
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return True


def page_chart(rows: Sequence[Dict[str, Any]], names: Dict[str, str], path: Path) -> bool:
    """The deterministic gold-page metrics, one group of bars per metric, one bar per division."""
    rows = [r for r in rows if r.get("page_hit") is not None]
    if not rows:
        return False
    divisions = division_names(rows, names)
    fig, ax = _figure(8.5, 4.4)
    width = 0.8 / len(divisions)
    for i, division in enumerate(divisions):
        mine = [r for r in rows if r["target"] == division]
        means = [mean(r[key] for r in mine) for key, _ in PAGE]
        xs = [j + (i - (len(divisions) - 1) / 2) * width for j in range(len(PAGE))]
        bars = ax.bar(xs, means, width=width, color=SERIES[i % len(SERIES)], edgecolor=SURFACE, linewidth=2,
                      label=f"{names.get(division, division)} (n={len(mine)})")
        for bar, value in zip(bars, means):
            ax.text(bar.get_x() + bar.get_width() / 2, value + 0.015, f"{value:.2f}", ha="center", va="bottom",
                    fontsize=8, color=INK)
    ax.set_xticks(range(len(PAGE)), [label for _, label in PAGE])
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("Score (0 to 1, higher is better)", color=MUTED, fontsize=9)
    ax.legend(frameon=False, fontsize=8, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=len(divisions))
    _title(fig, ax, "Retrieval against the gold pages (no LLM)",
           "Top 5 reranked passages vs the PDF pages known to hold each answer")
    fig.tight_layout(rect=(0, 0, 1, 0.80))
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return True


def time_chart(rows: Sequence[Dict[str, Any]], path: Path, footnote: str) -> bool:
    """The distribution of the time to answer one question, with the median and 90th percentile marked."""
    seconds = sorted(r["total_ms"] / 1000 for r in rows if r.get("total_ms") is not None)
    if not seconds:
        return False
    fig, ax = _figure()
    top = max(seconds)
    bins = [i * 0.5 for i in range(int(top / 0.5) + 2)] if top <= 20 else 30
    ax.hist(seconds, bins=bins, color=SERIES[0], edgecolor=SURFACE, linewidth=1)
    median = statistics.median(seconds)
    p90 = percentile(seconds, 90)
    for value, label, style in ((median, "median", "-"), (p90, "90th percentile", "--")):
        ax.axvline(value, color=INK, linewidth=1, linestyle=style)
        ax.text(value, ax.get_ylim()[1] * 0.97, f" {label} {value:.1f} s", color=INK, fontsize=8, va="top")
    ax.set_xlabel("Time to answer one question (seconds)", color=MUTED, fontsize=9)
    ax.set_ylabel("Questions", color=MUTED, fontsize=9)
    _title(fig, ax, "Answer time", f"Question in to checked answer out, n={len(seconds)} answered questions")
    fig.text(0.02, 0.01, footnote, fontsize=7.5, color=MUTED, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04, 1, 0.86))
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return True


def steps_chart(rows: Sequence[Dict[str, Any]], path: Path, footnote: str) -> bool:
    """Median milliseconds per pipeline step, over the questions where the step ran."""
    steps = ("embed", "search", "rerank", "llm", "citations", "retry", "suggest")
    timed = [r["timing_ms"] for r in rows if r.get("timing_ms")]
    if not timed:
        return False
    data = []
    for step in steps:
        ran = [t[step] for t in timed if t.get(step)]
        if ran:
            data.append((step, statistics.median(ran), len(ran)))
    fig, ax = _figure(7.5, 3.8)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.yaxis.grid(False)
    labels = [f"{step} (n={n})" for step, _, n in data][::-1]
    values = [ms for _, ms, _ in data][::-1]
    bars = ax.barh(labels, values, color=SERIES[0], edgecolor=SURFACE, linewidth=2, height=0.6)
    for bar, value in zip(bars, values):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f" {value:,.0f} ms", va="center", fontsize=8, color=INK)
    ax.set_xlabel("Median time when the step ran (milliseconds)", color=MUTED, fontsize=9)
    ax.set_xlim(0, max(values) * 1.18)
    _title(fig, ax, "Where the answer time goes", "Median per step; retry and suggest run only after a refusal")
    fig.text(0.02, 0.01, footnote, fontsize=7.5, color=MUTED, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.05, 1, 0.86))
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return True


def _used(rows: Sequence[Dict[str, Any]], field: str) -> str:
    """The models that actually produced the rows, with counts. The configured fallback lists are too long
    for a footnote, and only the models that answered or judged matter for reading the chart."""
    counts: Dict[str, int] = {}
    for row in rows:
        if row.get(field):
            counts[row[field]] = counts.get(row[field], 0) + 1
    if not counts:
        return "none"
    return ", ".join(f"{model} ({n})" for model, n in sorted(counts.items(), key=lambda kv: -kv[1]))


def make_charts(scores: Dict[str, Any], out_dir: Path) -> List[Path]:
    from divrag.divisions import DIVISIONS

    names = {d.id: d.name for d in DIVISIONS}
    rows = scores["questions"]
    out_dir.mkdir(parents=True, exist_ok=True)
    footnote = f"Answered by {_used(rows, 'model')}.  Judged by {_used(rows, 'judge_model')}."
    made: List[Path] = []

    def keep(ok: bool, path: Path) -> None:
        if ok:
            made.append(path)

    keep(overview_chart(rows, out_dir / "ragas_overview.png", footnote), out_dir / "ragas_overview.png")
    for key, title, meaning in RAGAS:
        path = out_dir / f"{key}.png"
        keep(metric_chart(rows, key, title, meaning, names, path, footnote), path)
    keep(page_chart(rows, names, out_dir / "retrieval_pages.png"), out_dir / "retrieval_pages.png")
    keep(time_chart(rows, out_dir / "answer_time.png", footnote), out_dir / "answer_time.png")
    keep(steps_chart(rows, out_dir / "answer_time_steps.png", footnote), out_dir / "answer_time_steps.png")
    return made


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.charts", description=__doc__.splitlines()[0])
    parser.add_argument("--scores", default=str(EVALUATION_DIR / "results" / "scores.json"))
    parser.add_argument("--out", default=str(EVALUATION_DIR / "charts"))
    args = parser.parse_args(argv)
    scores = json.loads(Path(args.scores).read_text(encoding="utf-8"))
    for path in make_charts(scores, Path(args.out)):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
