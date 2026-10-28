"""Download every division's source documents into hosted/documents/<division id>/.

The documents and their public URLs are the rows of hosted/divrag/divisions.py,
the one list the app, the index build and this script share. The PDFs are not
committed (they are gitignored and left out of Vercel uploads), so anyone who
needs to rebuild the index runs this first, then `python -m prototype.ingest`:

    python hosted/scripts/fetch_documents.py [--division ID ...] [--dest DIR] [--force]
    python hosted/scripts/fetch_documents.py --check-sources

A file that is already there and is a PDF is skipped (--force downloads it
again, for a new edition published at the same URL). Each download goes to a
.part file and only replaces the real name once it starts with the PDF header,
so a login page or an error page served with status 200 never passes for a
document. A failed URL is reported and the rest still download; the exit code
is 1 if any failed.

docs/source-documents/SOURCES.md lists the same documents for people, with each
file's page count and the date it was fetched. --check-sources compares it with
divisions.py (tests/test_fetch_documents.py does too) and prints a ready-to-paste
row for any document it is missing.

It uses the standard library only.
"""

import argparse
import datetime
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

HOSTED_DIR = Path(__file__).resolve().parent.parent
if str(HOSTED_DIR) not in sys.path:
    sys.path.insert(0, str(HOSTED_DIR))

from divrag.divisions import BY_ID, DIVISIONS, DOCUMENTS_DIR, Division, Document  # noqa: E402

SOURCES_FILE = HOSTED_DIR.parent / "docs" / "source-documents" / "SOURCES.md"
PDF_HEADER = b"%PDF-"
# connect.ncdot.gov is SharePoint; send a browser-like agent rather than urllib's default.
_USER_AGENT = "Mozilla/5.0 (compatible; ncdot-division-assistant document fetch)"


class FetchError(Exception):
    """A document that could not be downloaded, with a reason fit to print."""


@dataclass(frozen=True)
class SourceRow:
    """One document row of SOURCES.md."""

    division: str
    file: str
    title: str
    url: str
    pages: str
    fetched: str


def is_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(PDF_HEADER)) == PDF_HEADER
    except OSError:
        return False


def _download(url: str, dest: Path, timeout: float = 120) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response, open(dest, "wb") as out:  # noqa: S310 - URLs from divisions.py
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            out.write(block)


def fetch(url: str, dest: Path, download: Optional[Callable[[str, Path], None]] = None, force: bool = False) -> bool:
    """Download url to dest unless a PDF is already there (or `force`). True if it downloaded.

    Raises FetchError when the download fails or what arrives is not a PDF; a
    copy already at dest is kept then.
    """
    if is_pdf(dest) and not force:
        return False
    download = download or _download
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        download(url, part)
    except Exception as exc:  # noqa: BLE001 - every network or HTTP error becomes one line of output
        part.unlink(missing_ok=True)
        raise FetchError(f"download failed: {exc}") from exc
    if not is_pdf(part):
        part.unlink(missing_ok=True)
        raise FetchError("the URL did not return a PDF (moved, or behind a login?)")
    part.replace(dest)
    return True


def targets(divisions: Iterable[Division], dest: Path = DOCUMENTS_DIR) -> List[Tuple[Division, Document, Path]]:
    """Each document of these divisions with the path it is saved at."""
    return [(d, doc, dest / d.id / doc.file) for d in divisions for doc in d.documents]


# "## Transportation Mobility and Safety (`tmsd`)" starts a division's table.
_DIVISION_HEADING = re.compile(r"^##\s+.*\(`([a-z0-9_-]+)`\)\s*$")
_SOURCE_COLUMNS = ("file", "title", "url", "pages", "fetched")


def parse_sources(text: str) -> List[SourceRow]:
    """The document rows of SOURCES.md, each under its division's heading."""
    rows: List[SourceRow] = []
    division: Optional[str] = None
    for line in text.splitlines():
        heading = _DIVISION_HEADING.match(line)
        if heading:
            division = heading.group(1)
            continue
        if line.startswith("## "):
            division = None
            continue
        if division is None or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != len(_SOURCE_COLUMNS) or cells[0].lower() == "file" or set(cells[0]) <= set("-: "):
            continue  # the header and separator rows
        values = dict(zip(_SOURCE_COLUMNS, cells))
        values["file"] = values["file"].strip("`")
        values["url"] = values["url"].strip("<>")
        rows.append(SourceRow(division=division, **values))
    return rows


def source_row(division: Division, document: Document, pages: str = "?", fetched: Optional[str] = None) -> str:
    """A SOURCES.md table row for a document (paste it under its division's heading)."""
    fetched = fetched or datetime.date.today().isoformat()
    return f"| `{document.file}` | {document.title} | <{document.url}> | {pages} | {fetched} |"


def check_sources(rows: Sequence[SourceRow], divisions: Sequence[Division] = DIVISIONS) -> List[str]:
    """How SOURCES.md disagrees with divisions.py, one line per problem (empty when they agree)."""
    problems: List[str] = []
    listed: Dict[Tuple[str, str], SourceRow] = {}
    for row in rows:
        key = (row.division, row.file)
        if key in listed:
            problems.append(f"{row.division}/{row.file} is listed twice")
        listed[key] = row
    wanted = {(d.id, doc.file): (d, doc) for d in divisions for doc in d.documents}
    for key, (division, document) in wanted.items():
        row = listed.get(key)
        if row is None:
            problems.append(f"missing row for {division.id}/{document.file}:\n  {source_row(division, document)}")
            continue
        if row.title != document.title:
            problems.append(f"{division.id}/{document.file}: title {row.title!r}, divisions.py says {document.title!r}")
        if row.url != document.url:
            problems.append(f"{division.id}/{document.file}: URL {row.url}, divisions.py says {document.url}")
        if not row.pages.isdigit():
            problems.append(f"{division.id}/{document.file}: page count {row.pages!r} is not a number")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row.fetched):
            problems.append(f"{division.id}/{document.file}: fetched date {row.fetched!r} is not YYYY-MM-DD")
    for key in listed.keys() - wanted.keys():
        problems.append(f"{key[0]}/{key[1]} is in SOURCES.md but not in divisions.py")
    return problems


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python hosted/scripts/fetch_documents.py", description=__doc__.splitlines()[0])
    parser.add_argument("--division", action="append", choices=sorted(BY_ID), help="only these divisions (default: all)")
    parser.add_argument("--dest", type=Path, default=DOCUMENTS_DIR, help=f"root folder (default {DOCUMENTS_DIR})")
    parser.add_argument("--force", action="store_true",
                        help="download again even when a PDF is there (NCDOT replaced a document at the same URL)")
    parser.add_argument("--check-sources", action="store_true", help=f"only compare {SOURCES_FILE.name} with divisions.py")
    args = parser.parse_args(argv)

    problems = check_sources(parse_sources(SOURCES_FILE.read_text(encoding="utf-8"))) if SOURCES_FILE.is_file() \
        else [f"{SOURCES_FILE} not found"]
    if args.check_sources:
        for problem in problems:
            print(f"SOURCES.md: {problem}")
        print("SOURCES.md agrees with divisions.py" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0

    divisions = [BY_ID[d] for d in args.division] if args.division else list(DIVISIONS)
    failed = 0
    for division, document, dest in targets(divisions, args.dest):
        name = f"{division.id}/{document.file}"
        try:
            downloaded = fetch(document.url, dest, force=args.force)
        except FetchError as exc:
            failed += 1
            print(f"FAILED {name}: {exc}\n  {document.url}", flush=True)
            continue
        size = dest.stat().st_size / 1e6
        print(f"{'fetched' if downloaded else 'present'} {name} ({size:.1f} MB)", flush=True)
    for problem in problems:
        print(f"SOURCES.md: {problem}")
    total = len(targets(divisions, args.dest))
    print(f"{total - failed} of {total} document(s) ready in {args.dest}" + (f"; {failed} failed" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
