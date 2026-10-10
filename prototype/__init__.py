"""Offline tools for the hosted demo in hosted/.

The hosted app (hosted/) is self-contained so it can be deployed with hosted/
as its root directory: its runtime code (hosted/divrag: embedder, index file,
divisions, answering) needs only hosted/requirements.txt. The tools here run on
a developer machine with the full requirements.txt as well:

    py -m prototype.ingest    build hosted/index/ from the divisions' documents
    py -m prototype.search    try retrieval against an index from the command line

Importing this package puts hosted/ on sys.path so the tools share the hosted
app's `divrag` package (same embedder, same index format) instead of a copy.
"""

import sys
from pathlib import Path

HOSTED_DIR = Path(__file__).resolve().parent.parent / "hosted"

if str(HOSTED_DIR) not in sys.path:
    sys.path.insert(0, str(HOSTED_DIR))
