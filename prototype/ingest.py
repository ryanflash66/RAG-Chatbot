"""Build the hosted demo's index offline from each division's documents.

    py -m prototype.ingest [--division ID ...] [--out hosted/index] [--compare]

The divisions and their documents come from hosted/divrag/divisions.py; each
document is read from DATA_DIR (default data/) by its `file` name. Documents are
read and chunked as the Chainlit app does (rag.loader's PDF-to-Markdown reader,
rag.tables' table-aware splitter) but into 512-token chunks, tagged with their division and the numbered section heading in
effect, embedded with the hosted app's embedder and saved as one index
(chunks.json + vectors.npy) that the hosted app loads. Building the index needs
requirements.txt (llama-index, pymupdf4llm) as well as hosted/requirements.txt;
the hosted app needs only the latter.

--compare also embeds a sample of the chunks and a few questions with
sentence-transformers (the Chainlit app's embedder) and prints the cosine
similarity between the two models' vectors.
"""

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from dotenv import load_dotenv

from prototype import HOSTED_DIR  # noqa: F401  (puts hosted/ on sys.path)
from divrag.divisions import BY_ID, DIVISIONS, Division
from divrag.embedder import Embedder
from divrag.index_file import IndexFile
from rag import loader
from rag.config import AppConfig, load_config
from rag.tables import TableAwareSplitter

DEFAULT_OUT = HOSTED_DIR / "index"
# Smaller than the Chainlit app's 1024-token chunks: bge-small (and the
# reranker) read only the first 512 tokens of a passage, so with 1024-token
# chunks a rule near the end of a page was never embedded (UAM 3.6.4.1, the lane
# closure distances, ranked below 40th). Tables still get chunks of their own.
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
_COMPARE_SAMPLE = 64
_COMPARE_QUESTIONS = [
    "What is the minimum acceleration lane for an interstate entrance ramp in a work zone?",
    "What are the dimensions of the NC-PCB concrete barrier?",
    "How long should a merging taper be?",
]
# A Markdown heading for a numbered section or an appendix, as pymupdf4llm
# renders the manuals' headings: "## **3.6.4.1 Lane and Road Closures**",
# "# 5.6.3 Assessing ...", "#### **Appendix B. Figures**".
_SECTION_HEADING = re.compile(
    r"^#{1,6}\s+\**\s*((?:\d+(?:\.\d+)+\.?|Appendix\s+[A-Z]\.?)\s+[^*\n]+?)\s*\**\s*$", re.MULTILINE
)
_MAX_SECTIONS = 3


def section_headings(text: str) -> List[str]:
    """Numbered section headings in a chunk, in order."""
    return [" ".join(m.group(1).split()) for m in _SECTION_HEADING.finditer(text)]


def chunk_sections(texts: List[str]) -> List[Optional[str]]:
    """The section(s) each chunk of one document covers, in document order.

    A chunk belongs to the section in effect where it starts (carried over from
    earlier chunks) plus any sections that start inside it.
    """
    current: Optional[str] = None
    sections: List[Optional[str]] = []
    for text in texts:
        inside = section_headings(text)
        starts_with_heading = bool(_SECTION_HEADING.match(text.lstrip()))
        names = ([] if starts_with_heading or current is None else [current]) + inside
        names = list(dict.fromkeys(names))[:_MAX_SECTIONS]
        sections.append("; ".join(names) or None)
        if inside:
            current = inside[-1]
    return sections


def _page(metadata: Dict) -> Optional[int]:
    label = str(metadata.get("page_label", ""))
    return int(label) if label.isdigit() else None


def build_division(config: AppConfig, division: Division, chunk_size: int, chunk_overlap: int) -> List[Dict]:
    files = [config.data_dir / document.file for document in division.documents]
    missing = [str(f) for f in files if not f.is_file()]
    if missing:
        raise SystemExit(f"Division {division.id}: missing {missing} (download them from the URLs in divisions.py)")
    documents = loader.load(config.data_dir, only=files)
    splitter = TableAwareSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    nodes = [n for n in splitter.get_nodes_from_documents(documents) if n.get_content().strip()]
    chunks: List[Dict] = []
    for source in dict.fromkeys(n.metadata.get("source") for n in nodes):
        of_source = [n for n in nodes if n.metadata.get("source") == source]
        texts = [n.get_content().strip() for n in of_source]
        for node, text, section in zip(of_source, texts, chunk_sections(texts)):
            chunks.append({
                "text": text,
                "source": source,
                "page": _page(node.metadata),
                "section": section,
                "division": division.id,
            })
    return chunks


def build(config: AppConfig, divisions: List[Division], embedder: Embedder,
          chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP) -> IndexFile:
    chunks: List[Dict] = []
    for division in divisions:
        started = time.perf_counter()
        division_chunks = build_division(config, division, chunk_size, chunk_overlap)
        print(f"{division.id}: {len(division_chunks)} chunks ({time.perf_counter() - started:.0f}s to read and split)")
        chunks += division_chunks
    vectors = embedder.passages(chunk["text"] for chunk in chunks)
    return IndexFile(embedder.model_name, chunks, vectors)


def compare(config: AppConfig, index: IndexFile, embedder: Embedder) -> None:
    from rag.index import make_embed_model

    reference = make_embed_model(config)
    rng = np.random.default_rng(0)
    sample = rng.choice(len(index.chunks), size=min(_COMPARE_SAMPLE, len(index.chunks)), replace=False)
    texts = [index.chunks[i]["text"] for i in sample]
    ours = embedder.passages(texts)
    theirs = np.array(reference.get_text_embedding_batch(texts), dtype=np.float32)
    passage_cos = np.sum(ours * theirs, axis=1) / np.linalg.norm(theirs, axis=1)
    query_cos = []
    for question in _COMPARE_QUESTIONS:
        theirs_q = np.array(reference.get_query_embedding(question), dtype=np.float32)
        query_cos.append(float(embedder.query(question) @ theirs_q / np.linalg.norm(theirs_q)))
    print(
        f"fastembed vs sentence-transformers ({config.embedding_model}): "
        f"{len(texts)} passages cosine min={passage_cos.min():.4f} mean={passage_cos.mean():.4f}; "
        f"{len(query_cos)} queries cosine min={min(query_cos):.4f}"
    )


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m prototype.ingest", description=__doc__.splitlines()[0])
    parser.add_argument("--division", action="append", choices=sorted(BY_ID), help="only these divisions (default: all)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"directory for chunks.json and vectors.npy (default {DEFAULT_OUT})")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE, help=f"tokens per chunk (default {CHUNK_SIZE})")
    parser.add_argument("--chunk-overlap", type=int, default=CHUNK_OVERLAP, help=f"token overlap (default {CHUNK_OVERLAP})")
    parser.add_argument("--compare", action="store_true", help="check the vectors against sentence-transformers")
    args = parser.parse_args(argv)

    load_dotenv()
    config = load_config()
    divisions = [BY_ID[d] for d in args.division] if args.division else list(DIVISIONS)
    embedder = Embedder()
    started = time.perf_counter()
    index = build(config, divisions, embedder, args.chunk_size, args.chunk_overlap)
    index.save(args.out)
    size = sum(f.stat().st_size for f in args.out.iterdir() if f.is_file())
    print(
        f"{len(index.chunks)} chunks from {len({c['source'] for c in index.chunks})} file(s) "
        f"in {time.perf_counter() - started:.0f}s -> {args.out} ({size / 1e6:.1f} MB)"
    )
    if args.compare:
        compare(config, index, embedder)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
