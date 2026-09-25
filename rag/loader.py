"""Document loader: the single table of supported file formats.

Each extension maps to how it is read and the doc_type it is labelled with.
The ingest allowlist, the Retrieval index and the Chainlit UI all derive from
this table.

Readers:
  "default"      -- LlamaIndex's built-in reader for the extension
  "text"         -- read as plain UTF-8 text
  "unstructured" -- UnstructuredReader, for formats with no usable built-in reader
"""

import os
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Dict, FrozenSet, List

from llama_index.core import Document, SimpleDirectoryReader
from llama_index.core.readers.base import BaseReader

from rag.classify import classify


@dataclass(frozen=True)
class FileFormat:
    doc_type: str
    reader: str


FORMATS: Dict[str, FileFormat] = {
    # Documents
    ".pdf": FileFormat("pdf", "default"),
    ".docx": FileFormat("word", "default"),
    ".doc": FileFormat("word", "unstructured"),
    ".md": FileFormat("markdown", "default"),
    ".txt": FileFormat("text", "text"),
    ".rtf": FileFormat("rtf", "unstructured"),
    ".odt": FileFormat("opendocument", "unstructured"),
    ".html": FileFormat("html", "unstructured"),
    ".htm": FileFormat("html", "unstructured"),
    # Presentations
    ".pptx": FileFormat("powerpoint", "default"),
    ".ppt": FileFormat("powerpoint", "unstructured"),
    ".odp": FileFormat("opendocument", "unstructured"),
    # Spreadsheets and data
    ".csv": FileFormat("csv", "default"),
    ".xlsx": FileFormat("spreadsheet", "unstructured"),
    ".xls": FileFormat("spreadsheet", "unstructured"),
    ".ods": FileFormat("opendocument", "unstructured"),
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
    ".png": FileFormat("image", "unstructured"),
    ".jpg": FileFormat("image", "unstructured"),
    ".jpeg": FileFormat("image", "unstructured"),
    ".gif": FileFormat("image", "unstructured"),
    ".bmp": FileFormat("image", "unstructured"),
    ".tiff": FileFormat("image", "unstructured"),
}


def supported_extensions() -> FrozenSet[str]:
    return frozenset(FORMATS)


def doc_type(path: "str | PurePath") -> str:
    fmt = FORMATS.get(PurePath(path).suffix.lower())
    return fmt.doc_type if fmt else "other"


def _relative(data_dir: Path, file_path: str) -> PurePath:
    return PurePath(os.path.relpath(os.path.abspath(file_path), data_dir))


def document_metadata(relative_path: "str | PurePath") -> Dict[str, str]:
    """Metadata stored on every chunk of a Document."""
    rel = PurePath(relative_path)
    return {
        "source": rel.as_posix(),
        "filename": rel.name,
        "doc_type": doc_type(rel),
        "section": "N/A",
        **classify(rel).as_metadata(),
    }


def _supported_files(data_dir: Path) -> List[Path]:
    return [
        p for p in data_dir.rglob("*")
        if p.is_file()
        and p.suffix.lower() in FORMATS
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
    return extractor


class _PlainTextReader(BaseReader):
    def load_data(self, file, extra_info=None, **_kwargs) -> List[Document]:
        text = Path(file).read_text(encoding="utf-8", errors="replace")
        return [Document(text=text, metadata=extra_info or {})]


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
    return [doc for doc in reader.load_data() if doc.text.strip()]
