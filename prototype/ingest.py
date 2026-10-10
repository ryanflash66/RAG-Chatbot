"""Build a prototype index offline from documents in the data directory.

    py -m prototype.ingest FILE [FILE ...] --out DIR [--compare]

Documents are read and chunked exactly as the Chainlit app does (rag.loader's
PDF-to-Markdown reader, rag.tables' table-aware splitter, CHUNK_SIZE and
CHUNK_OVERLAP from the environment), embedded with prototype.embedder and saved
with prototype.index_file. FILEs must be under DATA_DIR (default data/).

--compare also embeds a sample of the chunks and a few questions with
sentence-transformers (the Chainlit app's embedder) and prints the cosine
similarity between the two models' vectors.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import List

import numpy as np
from dotenv import load_dotenv

from prototype.embedder import Embedder
from prototype.index_file import IndexFile
from rag import loader
from rag.config import AppConfig, load_config
from rag.tables import TableAwareSplitter

_COMPARE_SAMPLE = 64
_COMPARE_QUESTIONS = [
    "What is the minimum acceleration lane for an interstate entrance ramp in a work zone?",
    "What are the dimensions of the NC-PCB concrete barrier?",
    "How long should a merging taper be?",
]


def build(config: AppConfig, files: List[Path], embedder: Embedder) -> IndexFile:
    documents = loader.load(config.data_dir, only=files)
    if not documents:
        raise SystemExit(f"No loadable documents among {[str(f) for f in files]} under {config.data_dir}")
    splitter = TableAwareSplitter(chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap)
    nodes = [n for n in splitter.get_nodes_from_documents(documents) if n.get_content().strip()]
    chunks = [
        {
            "text": node.get_content().strip(),
            "source": node.metadata.get("source"),
            "page": int(node.metadata["page_label"]) if str(node.metadata.get("page_label", "")).isdigit() else None,
            "section": node.metadata.get("section"),
        }
        for node in nodes
    ]
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
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path, help="directory to write chunks.json and vectors.npy to")
    parser.add_argument("--compare", action="store_true", help="check the vectors against sentence-transformers")
    args = parser.parse_args(argv)

    load_dotenv()
    config = load_config()
    embedder = Embedder()
    started = time.perf_counter()
    index = build(config, args.files, embedder)
    index.save(args.out)
    size = sum(f.stat().st_size for f in args.out.iterdir())
    print(
        f"{len(index.chunks)} chunks from {len({c['source'] for c in index.chunks})} file(s) "
        f"in {time.perf_counter() - started:.0f}s -> {args.out} ({size / 1e6:.1f} MB)"
    )
    if args.compare:
        compare(config, index, embedder)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
