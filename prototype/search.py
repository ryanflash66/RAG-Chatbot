"""Search a prototype index from the command line.

    py -m prototype.search DIR "question" ["question" ...] [-k 3]

Embeds each question with prototype.embedder and prints the top hits by cosine
similarity, with their page and the start of their text.
"""

import argparse
import sys
import time
from typing import List

from prototype.embedder import Embedder
from prototype.index_file import IndexFile


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m prototype.search", description=__doc__.splitlines()[0])
    parser.add_argument("index_dir")
    parser.add_argument("questions", nargs="+")
    parser.add_argument("-k", type=int, default=3)
    args = parser.parse_args(argv)

    started = time.perf_counter()
    index = IndexFile.load(args.index_dir)
    embedder = Embedder(index.model)
    embedder.query("warm up")
    print(f"loaded {len(index.chunks)} chunks and {index.model} in {time.perf_counter() - started:.2f}s")

    for question in args.questions:
        started = time.perf_counter()
        hits = index.search(embedder.query(question), k=args.k)
        print(f"\nQ: {question}  ({(time.perf_counter() - started) * 1000:.0f} ms)")
        for rank, hit in enumerate(hits, 1):
            preview = " ".join(hit.chunk["text"].split())[:80]
            print(f"  {rank}. p.{hit.chunk['page']}  {hit.score:.3f}  {preview}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
