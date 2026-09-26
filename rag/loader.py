"""Document loader: the single table of supported file formats.

Each extension maps to how it is read and the doc_type it is labelled with.
The ingest allowlist, the Retrieval index and the Chainlit UI all derive from
this table.

A format with `requires` set is only supported when that program is on PATH
(Tesseract for image OCR, LibreOffice for .doc/.ppt, pandoc for .rtf/.odt).

Readers:
  "default"      -- LlamaIndex's built-in reader for the extension
  "text"         -- read as plain UTF-8 text
  "unstructured" -- UnstructuredReader, for formats with no usable built-in reader
  "markdown"     -- split into one Document per heading section
  "sheets"       -- UnstructuredReader, one Document per worksheet

Documents carry a `section` naming where in the file they came from, when the
format has one: the heading path for Markdown, "Slide N" for .pptx, the sheet
name for spreadsheets and "Page N" for PDFs.
"""

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Dict, FrozenSet, List, Optional, Tuple

from llama_index.core import Document, SimpleDirectoryReader
from llama_index.core.readers.base import BaseReader

from rag.classify import classify


@dataclass(frozen=True)
class FileFormat:
    doc_type: str
    reader: str
    # External program the reader shells out to; the format is only supported
    # on hosts where it is on PATH.
    requires: Optional[str] = None


FORMATS: Dict[str, FileFormat] = {
    # Documents
    ".pdf": FileFormat("pdf", "default"),
    ".docx": FileFormat("word", "default"),
    ".doc": FileFormat("word", "unstructured", requires="soffice"),
    ".md": FileFormat("markdown", "markdown"),
    ".txt": FileFormat("text", "text"),
    ".rtf": FileFormat("rtf", "unstructured", requires="pandoc"),
    ".odt": FileFormat("opendocument", "unstructured", requires="pandoc"),
    ".html": FileFormat("html", "unstructured"),
    ".htm": FileFormat("html", "unstructured"),
    # Presentations
    ".pptx": FileFormat("powerpoint", "default"),
    ".ppt": FileFormat("powerpoint", "unstructured", requires="soffice"),
    # Spreadsheets and data
    ".csv": FileFormat("csv", "default"),
    ".xlsx": FileFormat("spreadsheet", "sheets"),
    ".xls": FileFormat("spreadsheet", "sheets"),
    ".json": FileFormat("json", "text"),
    ".jsonl": FileFormat("jsonl", "text"),
    # Configuration, scripts and logs
    ".xml": FileFormat("xml", "text"),
    ".yaml": FileFormat("yaml", "text"),
    ".yml": FileFormat("yaml", "text"),
    ".conf": FileFormat("config", "text"),
    ".config": FileFormat("config", "text"),
    ".ini": FileFormat("config", "text"),
    ".ps1": FileFormat("script", "text"),
    ".sh": FileFormat("script", "text"),
    ".bat": FileFormat("script", "text"),
    ".cmd": FileFormat("script", "text"),
    ".py": FileFormat("script", "text"),
    ".log": FileFormat("log", "text"),
    # Email
    ".eml": FileFormat("email", "unstructured"),
    ".msg": FileFormat("email", "unstructured"),
    # Images (OCR)
    ".png": FileFormat("image", "unstructured", requires="tesseract"),
    ".jpg": FileFormat("image", "unstructured", requires="tesseract"),
    ".jpeg": FileFormat("image", "unstructured", requires="tesseract"),
    ".gif": FileFormat("image", "unstructured", requires="tesseract"),
    ".bmp": FileFormat("image", "unstructured", requires="tesseract"),
    ".tiff": FileFormat("image", "unstructured", requires="tesseract"),
}


def is_available(fmt: FileFormat) -> bool:
    return fmt.requires is None or shutil.which(fmt.requires) is not None


def supported_extensions() -> FrozenSet[str]:
    """Extensions this host can actually read (formats whose tool is missing are left out)."""
    return frozenset(ext for ext, fmt in FORMATS.items() if is_available(fmt))


def doc_type(path: "str | PurePath") -> str:
    fmt = FORMATS.get(PurePath(path).suffix.lower())
    return fmt.doc_type if fmt else "other"


def _relative(data_dir: Path, file_path: str) -> PurePath:
    return PurePath(os.path.relpath(os.path.abspath(file_path), data_dir))


def document_metadata(relative_path: "str | PurePath", section: Optional[str] = None) -> Dict[str, str]:
    """Metadata stored on every chunk of a Document.

    `section` is left out entirely when the format has no meaningful one.
    """
    rel = PurePath(relative_path)
    metadata = {
        "source": rel.as_posix(),
        "filename": rel.name,
        "doc_type": doc_type(rel),
        **classify(rel).as_metadata(),
    }
    if section:
        metadata["section"] = section
    return metadata


def section_for(relative_path: "str | PurePath", reader_metadata: Dict) -> Optional[str]:
    """The section a Document came from, from the metadata its reader produced.

    Readers that know the section (Markdown, spreadsheets) set it directly;
    paged formats get it from the reader's `page_label`.
    """
    if reader_metadata.get("section"):
        return str(reader_metadata["section"])
    label = reader_metadata.get("page_label")
    if label in (None, ""):
        return None
    suffix = PurePath(relative_path).suffix.lower()
    if suffix == ".pdf":
        return f"Page {label}"
    if suffix == ".pptx":
        return f"Slide {label}"
    return None


def _supported_files(data_dir: Path) -> List[Path]:
    supported = supported_extensions()
    return [
        p for p in data_dir.rglob("*")
        if p.is_file()
        and p.suffix.lower() in supported
        and not any(part.startswith(".") for part in p.relative_to(data_dir).parts)
    ]


def _file_extractor(files: List[Path]) -> Dict[str, object]:
    extractor: Dict[str, object] = {}
    unstructured_exts = {p.suffix.lower() for p in files if FORMATS[p.suffix.lower()].reader == "unstructured"}
    if unstructured_exts:
        from llama_index.readers.file import UnstructuredReader

        reader = UnstructuredReader()
        extractor.update({ext: reader for ext in unstructured_exts})
    # Keep "text" formats away from any built-in reader keyed on the same extension.
    text_exts = {ext for ext, fmt in FORMATS.items() if fmt.reader == "text"}
    extractor.update({ext: _PlainTextReader() for ext in text_exts})
    extractor.update({ext: _MarkdownReader() for ext, fmt in FORMATS.items() if fmt.reader == "markdown"})
    sheet_exts = {p.suffix.lower() for p in files if FORMATS[p.suffix.lower()].reader == "sheets"}
    if sheet_exts:
        extractor.update({ext: _SheetReader() for ext in sheet_exts})
    return extractor


class _PlainTextReader(BaseReader):
    def load_data(self, file, extra_info=None, **_kwargs) -> List[Document]:
        text = Path(file).read_text(encoding="utf-8", errors="replace")
        return [Document(text=text, metadata=extra_info or {})]


_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def markdown_sections(text: str) -> List[Tuple[Optional[str], str]]:
    """Split Markdown into (heading path, text) pairs, one per heading.

    The heading path joins the enclosing headings with " > ", e.g.
    "Ransomware Playbook > Containment". Text before the first heading has no
    path. Headings inside fenced code blocks are ignored; text is kept verbatim.
    """
    sections: List[Tuple[Optional[str], str]] = []
    path: List[Tuple[int, str]] = []
    heading_line = ""
    lines: List[str] = []
    fence: Optional[str] = None

    def flush() -> None:
        # A heading directly followed by a subheading has no text of its own.
        body = "\n".join(lines).strip()
        if body:
            text = f"{heading_line.strip()}\n{body}" if heading_line else body
            sections.append((" > ".join(title for _, title in path) or None, text))

    for line in text.splitlines():
        fence_match = _FENCE.match(line)
        if fence is not None:
            # A fence closes on a bare run of its own character, at least as long.
            run = fence_match.group(1) if fence_match else ""
            if run[:1] == fence[:1] and len(run) >= len(fence) and not line[fence_match.end():].strip():
                fence = None
            lines.append(line)
            continue
        if fence_match:
            fence = fence_match.group(1)
            lines.append(line)
            continue
        heading = _HEADING.match(line)
        if heading and heading.group(2):
            flush()
            lines = []
            heading_line = line
            level = len(heading.group(1))
            path = [(lvl, title) for lvl, title in path if lvl < level] + [(level, heading.group(2))]
            continue
        lines.append(line)
    flush()
    return sections


class _MarkdownReader(BaseReader):
    def load_data(self, file, extra_info=None, **_kwargs) -> List[Document]:
        text = Path(file).read_text(encoding="utf-8", errors="replace")
        docs = []
        for section, body in markdown_sections(text):
            metadata = dict(extra_info or {})
            if section:
                metadata["section"] = section
            docs.append(Document(text=body, metadata=metadata))
        return docs


class _SheetReader(BaseReader):
    """One Document per worksheet, with the sheet name as its section."""

    def load_data(self, file, extra_info=None, **_kwargs) -> List[Document]:
        from unstructured.partition.auto import partition

        sheets: Dict[str, List[str]] = {}
        for element in partition(filename=str(file)):
            name = getattr(element.metadata, "page_name", None) or ""
            sheets.setdefault(name, []).append(" ".join(str(element).split()))
        docs = []
        for name, chunks in sheets.items():
            metadata = dict(extra_info or {})
            if name:
                metadata["section"] = name
            docs.append(Document(text="\n\n".join(chunks), metadata=metadata))
        return docs


def load(data_dir: "str | Path") -> List[Document]:
    """Load every supported Document under data_dir, with its metadata attached.

    Files with unsupported extensions and hidden files or directories are skipped.
    Documents that produce no text are dropped.
    """
    data_dir = Path(data_dir).resolve()
    files = _supported_files(data_dir)
    if not files:
        return []

    reader = SimpleDirectoryReader(
        input_files=[str(p) for p in files],
        file_extractor=_file_extractor(files),
        file_metadata=lambda path: document_metadata(_relative(data_dir, path)),
    )
    docs = [doc for doc in reader.load_data() if doc.text.strip()]
    for doc in docs:
        section = section_for(doc.metadata["source"], doc.metadata)
        if section:
            doc.metadata["section"] = section
    return docs
