"""RAG evaluation of the hosted demo (DAR-637): the RAGAS metrics plus answer time.

    py -m evaluation.build_testset   rebuild evaluation/testset.json from the gold sets
    py -m evaluation.run_ragas       answer, judge, score and chart (resumable)

See evaluation/METRICS.md for what each metric means and how it is measured,
and evaluation/RESULTS.md for the latest results.

Importing this package puts hosted/ on sys.path so the harness runs the hosted
app's own `divrag` pipeline (same index, retrieval, prompt and citation check)
instead of a copy. hosted/ itself never imports from here.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOSTED_DIR = ROOT / "hosted"
EVALUATION_DIR = ROOT / "evaluation"

if str(HOSTED_DIR) not in sys.path:
    sys.path.insert(0, str(HOSTED_DIR))
