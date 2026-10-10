"""Tests for the offline index build's section tagging (prototype.ingest)."""

from prototype.ingest import chunk_sections, section_headings


def test_numbered_section_and_appendix_headings_are_found():
    text = "\n".join([
        "**Utilities Accommodation Manual**",
        "## **3.6.4.1 Lane and Road Closures**",
        "# Figure 5-2b Example design chart",
        "##### 11.3 Policies ",
        "#### **Appendix B. Figures**",
    ])
    assert section_headings(text) == ["3.6.4.1 Lane and Road Closures", "11.3 Policies", "Appendix B. Figures"]


def test_each_chunk_gets_the_section_in_effect_plus_those_starting_inside_it():
    chunks = [
        "intro\n# 1.1 One\nbody",
        "more of one",
        "# 1.2 Two\nbody",
        "end of two\n# 1.3 Three\nbody",
        "no headings at all",
    ]
    assert chunk_sections(chunks) == ["1.1 One", "1.1 One", "1.2 Two", "1.2 Two; 1.3 Three", "1.3 Three"]


def test_text_before_the_first_heading_has_no_section():
    assert chunk_sections(["cover page", "# 1.1 One\nx"]) == [None, "1.1 One"]
