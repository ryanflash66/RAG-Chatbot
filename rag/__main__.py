"""Operator commands for the Retrieval index.

    py -m rag refresh   rebuild the index from the data directory
    py -m rag stats     show what is indexed
"""

import sys

from dotenv import load_dotenv

from rag.config import load_config
from rag.index import RetrievalIndex, make_embed_model


def main(argv: list) -> int:
    command = argv[0] if argv else ""
    if command not in ("refresh", "stats"):
        print(__doc__)
        return 2

    load_dotenv()
    config = load_config()
    index = RetrievalIndex(config, make_embed_model(config))
    stats = index.refresh() if command == "refresh" else index.stats()
    print(
        f"collection={stats.collection} documents={stats.documents} "
        f"vectors={stats.vectors} last_refresh_at={stats.last_refresh_at}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
