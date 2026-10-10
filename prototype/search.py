"""Search the hosted demo's index from the command line.

    py -m prototype.search "question" ["question" ...] [--division ID] [--index DIR] [-k 5] [--no-rerank]

Runs the hosted app's retrieval (vector search within one division, then the
cross-encoder reranker unless --no-rerank) and prints the top hits with their
page, section and the start of their text.
"""

import argparse
import sys
import time
from typing import List

from prototype import HOSTED_DIR
from divrag.divisions import BY_ID
from divrag.embedder import Embedder, Reranker, model_cache_dir
from divrag.index_file import IndexFile
from divrag.retrieval import Retriever


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m prototype.search", description=__doc__.splitlines()[0])
    parser.add_argument("questions", nargs="+")
    parser.add_argument("--division", choices=sorted(BY_ID), help="search only this division (default: all)")
    parser.add_argument("--index", default=str(HOSTED_DIR / "index"))
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--no-rerank", action="store_true")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    index = IndexFile.load(args.index)
    cache = model_cache_dir()
    retriever = Retriever(index, Embedder(index.model, cache_dir=cache), None if args.no_rerank else Reranker(cache_dir=cache))
    retriever.retrieve("warm up", division=args.division, k=1)
    print(f"loaded {len(index.chunks)} chunks and the models in {time.perf_counter() - started:.2f}s")

    for question in args.questions:
        started = time.perf_counter()
        hits = retriever.retrieve(question, division=args.division, k=args.k)
        print(f"\nQ: {question}  ({(time.perf_counter() - started) * 1000:.0f} ms)")
        for rank, hit in enumerate(hits, 1):
            preview = " ".join(hit.chunk["text"].split())[:70]
            print(f"  {rank}. {hit.chunk['division']} p.{hit.chunk['page']} {hit.score:.3f} [{hit.chunk.get('section') or ''}] {preview}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
