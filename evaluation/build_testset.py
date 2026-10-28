"""Build evaluation/testset.json: one list of questions with gold pages and reference answers.

    py -m evaluation.build_testset [--sibling R:/_code_/ncdot-agentic-ai] [--out evaluation/testset.json]

The questions come from the gold sets already in the repo, so the evaluation
measures the questions the pipeline was checked against rather than new ones:

  eval/retrieval_pages.json   70 questions with known PDF pages (`pages`) or a
                              phrase of the answer as it appears in the index (`key`)
  eval/table_questions.json   13 table questions with pages and accept/reject
                              strings, plus Q9, which no document answers
  hosted/RESULTS-local.md     the hand-checked expected answers for the B, A and
                              X questions, and four not-in-the-documents questions (N1-N4)

and, when the sibling project folder is there (it is not a git repo):

  ncdot-agentic-ai/evaluation/tmp_manual_test_set_v1.md   15 TMP manual facts with
                              expected answers (chapter-relative page numbers)
  ncdot-agentic-ai/evaluation/demo_questions_v1.md        12 demo questions with
                              expected answers and PDF pages

Most TMP and demo items ask a question that is already in the set (the TMP
items were the source of the A questions), so they add their expected answer
and an origin to that question instead of a duplicate. Two TMP items have no
question yet (9 and 12); their questions are written here and their PDF pages
were checked against the index text (see _TMP_NEW).

Every item records where it came from (`origin`), where its pages came from
(`pages_from`) and where its reference answer came from (`reference_from`).
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from evaluation import HOSTED_DIR, ROOT

EVAL_DIR = ROOT / "eval"
# The sibling folder next to the repo; a git worktree sits deeper, so look up the tree.
DEFAULT_SIBLING = next((p / "ncdot-agentic-ai" for p in ROOT.parents if (p / "ncdot-agentic-ai").is_dir()),
                       ROOT.parent / "ncdot-agentic-ai")
DEFAULT_OUT = ROOT / "evaluation" / "testset.json"
RESULTS_LOCAL = HOSTED_DIR / "RESULTS-local.md"
TMP_FILE = Path("evaluation") / "tmp_manual_test_set_v1.md"
DEMO_FILE = Path("evaluation") / "demo_questions_v1.md"

# The B, A and X questions were asked across divisions (RESULTS-local.md's
# headings): Utilities documents by a Work Zone user and the other way round.
# The asker only changes the answer's wording, but the evaluation asks them the
# way they were checked.
_CROSS_ASKER = {"utilities": "wztc", "wztc": "utilities"}

# The division each not-in-the-documents question in RESULTS-local.md was asked
# of (its expected column: "Not in the TMP manual" is Work Zone, "Not in the UAM" Utilities).
_NEGATIVE_TARGETS = {"N1": "wztc", "N2": "wztc", "N3": "utilities", "N4": "wztc"}
# TMP manual test set item -> the question already in the set that asks it.
_TMP_TO_CASE = {1: "A1", 2: "A2", 3: "A3", 4: "A4", 5: "A5", 6: "A6", 7: "A7", 8: "A8",
                10: "Q7", 11: "X3", 13: "A9", 14: "N1", 15: "N2"}
# TMP items with no question in the set. The test set gives chapter-relative
# pages; the PDF pages were found in the index text on 2026-10-27:
#   9:  the NC-PCB deflection charts, asphalt (35.89 in) on PDF p. 37, concrete (25.37 in) on p. 38
#       (Ch 5 p. 13 is PDF p. 37: Ch 5 p. 8 is p. 32, as question A4's page shows).
#   12: Ch 8 pp. 4, 6, 7 are PDF pp. 77, 79, 80 (p. 80 is printed "Chapter 8 | Page 7");
#       the Section I warrants it depends on are on p. 78, so it is included.
_TMP_NEW = {
    9: {"id": "TMP9", "pages": [37, 38],
        "question": "What impact angle and maximum deflection does the NC-PCB deflection chart give for barrier "
                    "on asphalt at a 20 ft offset and 60 mph, and what is the deflection on concrete?"},
    12: {"id": "TMP12", "pages": [77, 78, 79, 80],
         "question": "A 70 mph interstate work zone is 4 miles long, lasts 8 months, has 20% trucks and a crash rate "
                     "above the statewide rate. Does it qualify for a work zone speed limit reduction, how big a "
                     "reduction can be used, and does the $250 fine apply?"},
}
# Demo question number -> the question already in the set (checked against the question text).
_DEMO_TO_CASE = {1: "A3", 2: "A5", 3: "A6", 4: "A8", 5: "B4", 6: "B6", 7: "B5", 8: "B2", 9: "B1", 10: "A9",
                 11: "N1", 12: "N4"}

_LOCATOR_WORDS = re.compile(r"\b(?:UAM|TMP|PDF|Table|Figure|Fig|Section|Ch|pp|p)\b\.?", re.IGNORECASE)
_PAGE_PAREN = re.compile(r"\s*\([^()]*\b(?:pp?|Ch)\.?\s*\d[^()]*\)")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def clean_reference(text: str) -> str:
    """The expected answer without its locators ("; UAM 3.6.4.1, PDF p. 126", "(Ch 2, 2.2, p.1)").

    The judge splits the reference into statements and checks each against the
    retrieved passages; a page number is not a statement a passage can support,
    so it would count against context recall.
    """
    text = _PAGE_PAREN.sub("", text)
    segments = text.split(";")
    while len(segments) > 1 and _is_locator(segments[-1]):
        segments.pop()
    return ";".join(segments).strip().rstrip(".").strip() + "."


def first_sentence(text: str) -> str:
    """The first sentence of a table question's note: the value itself.

    What follows is grading commentary ("so naming Ohio is fine", "The PDF text
    layer renders '12' as '1 2'"), which no passage states. Decimals ("1.3") don't end it.
    """
    return re.split(r"(?<=\.)\s+(?=[A-Z])", text.strip(), maxsplit=1)[0]


def _is_locator(segment: str) -> bool:
    rest = _LOCATOR_WORDS.sub("", segment)
    return bool(re.search(r"\d", segment)) and not re.sub(r"[\s\d.,\-–]", "", rest)


def _table_rows(markdown: str) -> List[List[str]]:
    rows = []
    for line in markdown.splitlines():
        line = line.strip()
        if line.startswith("|") and line.endswith("|") and not re.fullmatch(r"\|[\s|:\-]+\|", line):
            rows.append([cell.strip() for cell in line[1:-1].split("|")])
    return rows


def parse_results_local(markdown: str) -> Tuple[Dict[str, Dict[str, str]], List[Dict[str, str]]]:
    """(expected answers by question id, the not-in-the-documents rows) from RESULTS-local.md.

    Rows are | id | question | answer | cited | expected | correct | time |.
    """
    expected: Dict[str, Dict[str, str]] = {}
    negatives: List[Dict[str, str]] = []
    for cells in _table_rows(markdown):
        if len(cells) < 6 or not re.fullmatch(r"[A-Z]\d+", cells[0]):
            continue
        row = {"id": cells[0], "question": cells[1], "answer": cells[2], "expected": cells[4]}
        if cells[0].startswith("N"):
            negatives.append(row)
        else:
            expected[cells[0]] = row
    return expected, negatives


def parse_tmp(markdown: str) -> Dict[int, str]:
    """TMP test set items by number: "5. PCB on bridge deck anchored when ... (Ch 5, 5.8.4, p.22)"."""
    return {int(m.group(1)): m.group(2).strip() for m in re.finditer(r"^(\d+)\.\s+(.+)$", markdown, re.MULTILINE)}


def parse_demo(markdown: str) -> Dict[int, Dict[str, str]]:
    """Demo questions by number from Part 1's tables: the question and its expected answer.

    The cross-division rows have "I am in" and "Ask" cells before the question,
    so the question is the first cell that ends in a question mark.
    """
    part1 = markdown.split("## Part 2")[0]
    items = {}
    for cells in _table_rows(part1):
        if not cells[0].isdigit():
            continue
        at = next((i for i, c in enumerate(cells[1:], 1) if c.endswith("?")), None)
        if at is not None and at + 1 < len(cells):
            items[int(cells[0])] = {"question": cells[at], "expected": cells[at + 1]}
    return items


def key_pages_and_sentence(chunks: Sequence[Dict[str, Any]], division: str, key: str) -> Tuple[List[int], str]:
    """The pages of every chunk of `division` holding `key`, and the sentence around its first match.

    The same matching as prototype.rerank_check (case and spacing ignored). A
    key repeated on several pages makes those pages alternatives: any one of
    them holds the answer.
    """
    pages, sentence = set(), ""
    for chunk in chunks:
        if chunk.get("division") != division:
            continue
        flat = " ".join(chunk["text"].split())
        at = flat.lower().find(_norm(key))
        if at < 0:
            continue
        pages.add(chunk["page"])
        if not sentence:
            sentence = _sentence_around(flat, at, at + len(_norm(key)))
    if not pages:
        raise ValueError(f"key not found in {division}: {key!r}")
    return sorted(pages), sentence


def _sentence_around(flat: str, start: int, end: int, reach: int = 250) -> str:
    left = max(flat.rfind(". ", max(0, start - reach), start), flat.rfind("| ", max(0, start - reach), start))
    left = left + 2 if left >= 0 else max(0, start - reach)
    right = flat.find(". ", end, end + reach)
    right = right + 1 if right >= 0 else min(len(flat), end + reach)
    text = re.sub(r"\*\*|__|#{1,6}\s*|<br>", "", flat[left:right])
    return " ".join(text.split())


def build(chunks: Sequence[Dict[str, Any]], sibling: Optional[Path]) -> List[Dict[str, Any]]:
    pages_cases = json.loads((EVAL_DIR / "retrieval_pages.json").read_text(encoding="utf-8"))["cases"]
    table_cases = json.loads((EVAL_DIR / "table_questions.json").read_text(encoding="utf-8"))["cases"]
    local_expected, local_negatives = parse_results_local(RESULTS_LOCAL.read_text(encoding="utf-8"))

    items: Dict[str, Dict[str, Any]] = {}

    for case in pages_cases:
        item = {"id": case["id"], "question": case["question"], "target": case["division"],
                "asker": _CROSS_ASKER[case["division"]] if case["id"][0] in "BAX" else case["division"],
                "answerable": True, "group": "known-page", "origin": [f"eval/retrieval_pages.json#{case['id']}"]}
        if not case.get("key") and not case.get("pages"):
            raise ValueError(f"retrieval_pages.json {case['id']} has neither pages nor a key")
        if case.get("key"):
            pages, sentence = key_pages_and_sentence(chunks, case["division"], case["key"])
            item["key"] = case["key"]
            item["reference"], item["reference_from"] = sentence, "index text holding the key"
        if case.get("pages"):
            # Listed pages are each needed (X1's rules sit on 126 and 127), except
            # beside a key, where they are the places the key's values appear (T27).
            mode = "any" if case.get("key") else "all"
            item["pages"], item["pages_mode"], item["pages_from"] = sorted(case["pages"]), mode, "case"
        else:
            item["pages"], item["pages_mode"], item["pages_from"] = pages, "any", "chunks holding the key"
        items[case["id"]] = item

    for case in table_cases:
        answerable = bool(case.get("pages"))
        items[case["id"]] = {
            "id": case["id"], "question": case["question"], "target": "wztc", "asker": "wztc",
            "answerable": answerable, "group": "table" if answerable else "negative",
            "pages": sorted(int(p) for p in case.get("pages") or []), "pages_mode": "all",
            "pages_from": "case" if answerable else None,
            "reference": clean_reference(first_sentence(case["note"])) if answerable else None,
            "reference_from": "eval/table_questions.json note" if answerable else None,
            "accept": case.get("accept", []), "reject": case.get("reject", []),
            "holdout": bool(case.get("holdout")), "origin": [f"eval/table_questions.json#{case['id']}"],
        }

    for qid, row in local_expected.items():
        item = items.get(qid)
        if item is None or _norm(item["question"]) != _norm(row["question"]):
            raise ValueError(f"RESULTS-local.md {qid} does not match the retrieval_pages question")
        item["reference"], item["reference_from"] = clean_reference(row["expected"]), "hosted/RESULTS-local.md expected"
        item["origin"].append(f"hosted/RESULTS-local.md#{qid}")

    for row in local_negatives:
        target = _NEGATIVE_TARGETS.get(row["id"])
        if target is None:
            raise ValueError(f"RESULTS-local.md {row['id']}: add the division it was asked of to _NEGATIVE_TARGETS")
        items[row["id"]] = {"id": row["id"], "question": row["question"], "target": target, "asker": target,
                            "answerable": False, "group": "negative", "pages": [], "pages_mode": "all",
                            "pages_from": None, "reference": None, "reference_from": None,
                            "expected_behavior": row["expected"], "origin": [f"hosted/RESULTS-local.md#{row['id']}"]}

    if sibling is not None:
        _add_sibling(items, sibling)

    return list(items.values())


def _add_sibling(items: Dict[str, Dict[str, Any]], sibling: Path) -> None:
    origin = f"ncdot-agentic-ai/{TMP_FILE.as_posix()}"
    tmp = parse_tmp((sibling / TMP_FILE).read_text(encoding="utf-8"))
    for number, text in sorted(tmp.items()):
        if number in _TMP_TO_CASE:
            item = items[_TMP_TO_CASE[number]]
            item["origin"].append(f"{origin}#{number}")
            if item["answerable"] and item.get("reference_from") != "hosted/RESULTS-local.md expected":
                item["reference"], item["reference_from"] = clean_reference(text), origin
        elif number in _TMP_NEW:
            new = _TMP_NEW[number]
            items[new["id"]] = {"id": new["id"], "question": new["question"], "target": "wztc", "asker": "wztc",
                                "answerable": True, "group": "tmp", "pages": new["pages"], "pages_mode": "all",
                                "pages_from": "TMP test set, mapped to PDF pages (checked in the index text)",
                                "reference": clean_reference(text), "reference_from": origin,
                                "origin": [f"{origin}#{number}"]}
        else:
            raise ValueError(f"TMP test set item {number} is not mapped; add it to _TMP_TO_CASE or _TMP_NEW")

    origin = f"ncdot-agentic-ai/{DEMO_FILE.as_posix()}"
    demo = parse_demo((sibling / DEMO_FILE).read_text(encoding="utf-8"))
    for number, row in sorted(demo.items()):
        item = items[_DEMO_TO_CASE[number]]
        if _norm(item["question"]) != _norm(row["question"]):
            raise ValueError(f"demo question {number} does not match {item['id']}")
        item["origin"].append(f"{origin}#{number}")
        if item["answerable"] and not item.get("reference"):
            item["reference"], item["reference_from"] = clean_reference(row["expected"]), origin


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.build_testset", description=__doc__.splitlines()[0])
    parser.add_argument("--sibling", default=str(DEFAULT_SIBLING),
                        help="the ncdot-agentic-ai folder with evaluation/*.md (skipped with a warning when missing)")
    parser.add_argument("--index", default=str(HOSTED_DIR / "index"))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    chunks = json.loads((Path(args.index) / "chunks.json").read_text(encoding="utf-8"))["chunks"]
    sibling: Optional[Path] = Path(args.sibling)
    if not (sibling / TMP_FILE).exists():
        print(f"warning: {sibling / TMP_FILE} not found; building without the TMP and demo sets", file=sys.stderr)
        sibling = None
    items = build(chunks, sibling)
    out = {
        "description": "Questions for the RAG evaluation (python -m evaluation.run_ragas), built by "
                       "python -m evaluation.build_testset; see the module docstring for the sources. "
                       "`pages` are PDF pages; pages_mode 'all' means every page is needed, 'any' that "
                       "each page holds the answer on its own.",
        "items": items,
    }
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    answerable = sum(i["answerable"] for i in items)
    print(f"{len(items)} items ({answerable} answerable, {len(items) - answerable} negative) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
