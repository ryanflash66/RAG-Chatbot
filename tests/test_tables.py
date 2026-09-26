"""Tests for Markdown table cleanup and table-aware chunking (rag/tables.py)."""

from rag import tables

CURVE_TABLE = "\n".join([
    "###### Table 3-2 Horizontal Curve Adjustments",
    "KCZ (Curve Correction Factor)",
    "|RADIUS [ft]|||DESI |GN SPEED [ |mph] |||",
    "|---|---|---|---|---|---|---|---|",
    "||40|45|50|55|60|65|70|",
    "|1640|1.1|1.2|1.2|1.3|1.3|1.4|1.5|",
    "|1430|1.2|1.2|1.3|1.3|1.4|1.4|--|",
])


def _words(n: int, word: str = "prose") -> str:
    return " ".join(f"{word}{i}." for i in range(n))


def _count(text: str) -> int:
    return len(text.split())


# ---------------------------------------------------------------------------
# clean_markdown_tables
# ---------------------------------------------------------------------------

def test_spanning_header_is_merged_into_one_readable_row():
    cleaned = tables.clean_markdown_tables(CURVE_TABLE).split("\n")

    assert cleaned[2] == r"|RADIUS [ft] \ DESIGN SPEED [mph]|40|45|50|55|60|65|70|"
    assert tables.is_separator(cleaned[3])
    assert cleaned[4] == "|1640|1.1|1.2|1.2|1.3|1.3|1.4|1.5|"
    assert "||40|" not in "\n".join(cleaned)


def test_ordinary_tables_are_left_alone():
    table = "|State|Criteria|\n|---|---|\n|Texas|Drop-off depth > 2 feet|"
    assert tables.clean_markdown_tables(f"intro\n{table}\noutro") == f"intro\n{table}\noutro"


def test_header_not_merged_when_row_below_is_data():
    table = "|Speed|Width||\n|---|---|---|\n|55|23|x|"
    assert tables.clean_markdown_tables(table) == table


# ---------------------------------------------------------------------------
# split_text
# ---------------------------------------------------------------------------

def test_small_table_stays_whole_with_its_caption():
    text = f"{_words(60)}\n\n{CURVE_TABLE}\n\n{_words(60, 'after')}"
    chunks = tables.split_text(text, chunk_size=200, chunk_overlap=0, count=_count)

    table_chunks = [c for c in chunks if "|1640|" in c]
    assert len(table_chunks) == 1
    assert "Table 3-2 Horizontal Curve Adjustments" in table_chunks[0]
    assert "|1430|" in table_chunks[0]
    assert all("|1640|" not in c for c in chunks if "prose0." in c)


def test_large_table_splits_between_rows_repeating_caption_and_header():
    rows = [f"|{r}|{r}.0|{r}.5|" for r in range(100)]
    text = "\n".join(["Table 7 Big numbers", "|Radius|Low|High|", "|---|---|---|", *rows])

    chunks = tables.split_text(text, chunk_size=60, chunk_overlap=0, count=_count)

    assert len(chunks) > 1
    seen = []
    for chunk in chunks:
        lines = chunk.split("\n")
        assert lines[:3] == ["Table 7 Big numbers", "|Radius|Low|High|", "|---|---|---|"]
        body = lines[3:]
        assert body and all(line.startswith("|") and line.count("|") == 4 for line in body)
        seen += body
    assert seen == rows  # every row exactly once, in order


def test_multi_row_headers_after_separator_are_repeated():
    rows = [f"||{v}|{v}-{v + 2}|" for v in range(40)]
    text = "\n".join(["|DESIGN|||", "|---|---|---|", "| SPEED|DESIGN ADT|1V:6H or flatter|", *rows])

    chunks = tables.split_text(text, chunk_size=40, chunk_overlap=0, count=_count)

    assert len(chunks) > 1
    assert all("| SPEED|DESIGN ADT|1V:6H or flatter|" in chunk for chunk in chunks)


def test_all_text_table_repeats_only_its_first_row():
    rows = [f"|State{i}|Drop-off depth > {i} inches located within {i} feet|" for i in range(30)]
    text = "\n".join(["|State|Criteria|", "|---|---|", *rows])

    chunks = tables.split_text(text, chunk_size=60, chunk_overlap=0, count=_count)

    assert len(chunks) > 1
    assert sum(chunk.count("|State0|") for chunk in chunks) == 1


def test_short_lines_above_a_table_become_its_caption():
    text = "Part 2\n\nDesign Manual\n\n|A|B|\n|---|---|\n|1|2|"
    chunks = tables.split_text(text, chunk_size=200, chunk_overlap=0, count=_count)

    assert chunks == ["Part 2\nDesign Manual\n|A|B|\n|---|---|\n|1|2|"]


def test_long_caption_like_paragraph_is_not_pulled_into_the_table():
    paragraph = "x " * 150
    text = f"{paragraph}\n\n|A|B|\n|---|---|\n|1|2|"
    chunks = tables.split_text(text, chunk_size=500, chunk_overlap=0, count=_count)

    assert len(chunks) == 2
    assert chunks[1].startswith("|A|B|")


def test_text_without_tables_matches_sentence_splitting():
    text = _words(500)
    chunks = tables.split_text(text, chunk_size=100, chunk_overlap=10)
    assert len(chunks) > 1
    assert "prose0." in chunks[0] and "prose499." in chunks[-1]


def test_bracketed_values_in_unit_columns_are_unwrapped():
    table = "\n".join([
        "|Speed (km/h)|Widths (m)|Speed [mph]|Widths [ft]|",
        "|---|---|---|---|",
        "|90|7|[55]|[23]|",
        "|50 - 60|4|[30 - 40]|[13]|",
    ])
    assert tables.clean_markdown_tables(table).split("\n")[2:] == ["|90|7|55|23|", "|50 - 60|4|30 - 40|13|"]


def test_brackets_kept_outside_unit_columns_and_when_only_partly_bracketed():
    table = "|Item [ref]|Note|\n|---|---|\n|[a] b|[keep]|"
    assert tables.clean_markdown_tables(table) == table
