"""Markdown tables in Document text: cleanup, and chunking that keeps them whole.

PDF pages arrive as Markdown with tables as pipe tables (see rag/loader.py).
Plain sentence splitting cuts those tables anywhere, so a chunk can hold rows
whose column headers are in another chunk. `split_text` instead cuts prose with
a sentence splitter and cuts tables only between rows, repeating the table's
caption and header rows in every piece.
"""

import re
from typing import Callable, List, Optional, Tuple

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.node_parser.interface import TextSplitter
from llama_index.core.utils import get_tokenizer
from pydantic import Field, PrivateAttr

_SEPARATOR_CELL = re.compile(r"^\s*:?-{3,}:?\s*$")
# A data cell: numbers, ranges and placeholders such as "12 - 14", "1.3", "--", "**".
_NUMERIC_CELL = re.compile(r"^[\s\d.,\-–*~<>≥≤%$/\[\]]+$")
# Caption lines kept with a table: short lines just above it (title, units line).
_MAX_CAPTION_LINES = 2
_MAX_CAPTION_CHARS = 200
# Header rows after the separator that are still headers (e.g. Table 3-1's
# "DESIGN SPEED | DESIGN ADT | 1V:6H or flatter ..." rows).
_MAX_EXTRA_HEADER_ROWS = 3
# Prose shorter than this (page headers/footers) is kept with the next table
# instead of becoming a chunk of its own.
_MIN_PROSE_TOKENS = 25


def is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def cells(line: str) -> List[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return inner.split("|")


def is_separator(line: str) -> bool:
    row = cells(line)
    return bool(row) and all(_SEPARATOR_CELL.match(cell) for cell in row)


def _row(values: List[str]) -> str:
    return "|" + "|".join(values) + "|"


def _merge_spanning_header(rows: List[str]) -> List[str]:
    """Fold a spanning column title into the real header row.

    pymupdf4llm renders a grid such as

        |RADIUS [ft]|||DESI |GN SPEED [ |mph] |||
        |---|---|---|---|---|---|---|---|
        ||40|45|50|55|60|65|70|

    where "DESIGN SPEED [mph]" spans the speed columns and is broken across
    cells. This becomes one header row, "|RADIUS [ft] \\ DESIGN SPEED [mph]|40|...|70|",
    so each value sits under a single, readable column name.
    """
    if len(rows) < 3 or not is_separator(rows[1]):
        return rows
    header, below = cells(rows[0]), cells(rows[2])
    fragments = [cell.strip() for cell in header[1:] if cell.strip()]
    spans = header[0].strip() and fragments and len(fragments) < len(header) - 1
    real_header_below = (
        len(below) == len(header) and not below[0].strip() and all(cell.strip() for cell in below[1:])
    )
    if not (spans and real_header_below):
        return rows
    title = re.sub(r"\s+", " ", "".join(fragments)).strip()
    merged = [f"{header[0].strip()} \\ {title}"] + [cell.strip() for cell in below[1:]]
    return [_row(merged), rows[1]] + rows[3:]


def clean_markdown_tables(text: str) -> str:
    """Tidy every pipe table in `text` (see `_merge_spanning_header`)."""
    lines = text.split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        if is_table_line(lines[i]):
            j = i
            while j < len(lines) and is_table_line(lines[j]):
                j += 1
            out.extend(_merge_spanning_header(lines[i:j]))
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def _header_row_count(rows: List[str]) -> int:
    """Rows that label columns: through the separator, plus header-like rows after it.

    Rows after the separator count as headers only when the table has numeric
    data further down, so all-text tables (e.g. state criteria) aren't mistaken
    for having a multi-row header.
    """
    if len(rows) < 2 or not is_separator(rows[1]):
        return 1 if rows else 0

    def numeric(row: str) -> bool:
        return any(cell.strip() and _NUMERIC_CELL.match(cell) for cell in cells(row)[1:])

    count = 2
    if any(numeric(row) for row in rows[2:]):
        while count < len(rows) and count - 2 < _MAX_EXTRA_HEADER_ROWS and not numeric(rows[count]):
            count += 1
    return count


def _segments(text: str) -> List[Tuple[str, str]]:
    """Split text into ("prose", text) and ("table", caption + table) segments."""
    lines = text.split("\n")
    segments: List[Tuple[str, str]] = []
    prose: List[str] = []
    i = 0
    while i < len(lines):
        if not is_table_line(lines[i]):
            prose.append(lines[i])
            i += 1
            continue
        j = i
        while j < len(lines) and is_table_line(lines[j]):
            j += 1
        # Pull the caption (short lines right above the table) out of the prose.
        caption: List[str] = []
        while prose and len(caption) < _MAX_CAPTION_LINES:
            if not prose[-1].strip():
                prose.pop()
                continue
            if len(prose[-1]) > _MAX_CAPTION_CHARS or is_table_line(prose[-1]):
                break
            caption.insert(0, prose.pop())
        if "\n".join(prose).strip():
            segments.append(("prose", "\n".join(prose)))
        segments.append(("table", "\n".join(caption + lines[i:j])))
        prose = []
        i = j
    if "\n".join(prose).strip():
        segments.append(("prose", "\n".join(prose)))
    return segments


def _split_table(block: str, chunk_size: int, count: Callable[[str], int]) -> List[str]:
    """One chunk if the table fits; otherwise row groups that each repeat caption and header."""
    if count(block) <= chunk_size:
        return [block]
    lines = block.split("\n")
    first_row = next(i for i, line in enumerate(lines) if is_table_line(line))
    caption, rows = lines[:first_row], lines[first_row:]
    n_header = _header_row_count(rows)
    preamble = "\n".join(caption + rows[:n_header])
    budget = max(chunk_size - count(preamble), 1)
    pieces: List[str] = []
    group: List[str] = []
    used = 0
    for row in rows[n_header:]:
        size = count(row) + 1
        if group and used + size > budget:
            pieces.append("\n".join([preamble] + group))
            group, used = [], 0
        group.append(row)
        used += size
    if group:
        pieces.append("\n".join([preamble] + group))
    return pieces


def split_text(text: str, chunk_size: int, chunk_overlap: int, count: Optional[Callable[[str], int]] = None) -> List[str]:
    """Chunk text so that no Markdown table is cut mid-row or separated from its headers."""
    tokenizer = get_tokenizer()
    count = count or (lambda s: len(tokenizer(s)))
    prose_splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    chunks: List[str] = []
    carry = ""  # short prose (page headers) waiting to join the next table
    for kind, segment in _segments(text):
        if kind == "prose":
            if count(segment) < _MIN_PROSE_TOKENS:
                carry = f"{carry}\n{segment}".strip()
                continue
            if carry:
                segment, carry = f"{carry}\n{segment}", ""
            chunks.extend(prose_splitter.split_text(segment))
        else:
            if carry:
                segment, carry = f"{carry}\n{segment}", ""
            chunks.extend(_split_table(segment, chunk_size, count))
    if carry:
        if chunks:
            chunks[-1] = f"{chunks[-1]}\n{carry}"
        else:
            chunks.append(carry)
    return [chunk for chunk in (c.strip() for c in chunks) if chunk]


class TableAwareSplitter(TextSplitter):
    """LlamaIndex node parser wrapping `split_text`."""

    chunk_size: int = Field(description="Target tokens per chunk.")
    chunk_overlap: int = Field(description="Token overlap between prose chunks.")
    _count: Callable[[str], int] = PrivateAttr()

    def __init__(self, chunk_size: int, chunk_overlap: int, **kwargs):
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap, **kwargs)
        tokenizer = get_tokenizer()
        self._count = lambda s: len(tokenizer(s))

    def split_text(self, text: str) -> List[str]:
        return split_text(text, self.chunk_size, self.chunk_overlap, self._count)
