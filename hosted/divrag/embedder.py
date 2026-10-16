"""Question embeddings and reranking, computed locally with no API key.

fastembed runs BAAI/bge-small-en-v1.5 on onnxruntime: the same model the
Chainlit app indexes with (rag/config.py), without torch. Its vectors match the
sentence-transformers ones (cosine 1.0000 on the TMP Design Manual) so either can build
an index the other searches; `python -m prototype.ingest --compare` checks it.

Like the Chainlit app (LlamaIndex's HuggingFaceEmbedding), queries get the BGE
retrieval instruction and passages are embedded as-is.

The reranker is the ONNX port of the cross-encoder the Chainlit app uses
(cross-encoder/ms-marco-MiniLM-L-6-v2): it scores each (question, passage) pair
and re-orders the vector hits. It runs the repo's dynamically quantized (int8)
file rather than the fp32 one fastembed lists: on the 32 questions with known
answer pages it ranked the same (median Spearman 0.994 against fp32 over 20
candidates, the expected page at the same rank for all 32) in half the CPU time,
and it is 23 MB instead of 91 MB.

Model files are read from (and on first use downloaded into) `model_cache_dir()`.
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

import numpy as np

MODEL_NAME = "BAAI/bge-small-en-v1.5"
RERANK_MODEL_NAME = "Xenova/ms-marco-MiniLM-L-6-v2"
RERANK_MODEL_FILE = "onnx/model_quantized.onnx"
QUERY_INSTRUCTION = "Represent this question for searching relevant passages: "

# A deployment can ship the model files here (a fastembed cache directory).
BUNDLED_MODEL_DIR = Path(__file__).resolve().parent.parent / "models"


def model_cache_dir() -> str:
    """Where fastembed looks for (and downloads) model files.

    MODEL_CACHE_DIR when set; else hosted/models/ if a deployment bundled it;
    else a directory under the system temp dir (/tmp on Vercel, the only
    writable place there), downloading the models on the first request.
    """
    configured = os.environ.get("MODEL_CACHE_DIR", "").strip()
    if configured:
        return configured
    if BUNDLED_MODEL_DIR.is_dir():
        return str(BUNDLED_MODEL_DIR)
    return os.path.join(tempfile.gettempdir(), "fastembed_cache")


def onnx_threads() -> Optional[int]:
    """onnxruntime threads per model: ONNX_THREADS when set, else onnxruntime's default (None).

    onnxruntime sizes its thread pool from the cores the machine reports, which
    can be more than a serverless instance's share of CPU.
    """
    configured = os.environ.get("ONNX_THREADS", "").strip()
    return max(1, int(configured)) if configured else None


def cpu_info() -> Dict[str, Union[int, str, None]]:
    """What this instance reports about its CPUs, for /api/health."""
    info: Dict[str, Union[int, str, None]] = {"cpu_count": os.cpu_count(), "onnx_threads": onnx_threads()}
    if hasattr(os, "sched_getaffinity"):
        info["affinity"] = len(os.sched_getaffinity(0))
    for path in ("/sys/fs/cgroup/cpu.max", "/sys/fs/cgroup/cpu/cpu.cfs_quota_us"):
        try:
            info["cgroup_" + Path(path).name] = Path(path).read_text().strip()[:40]
        except OSError:
            pass
    return info


class Embedder:
    """Unit-length float32 embeddings; the model loads on first use.

    `model_dir` loads the ONNX model from a directory instead of downloading it
    from Hugging Face (for a deployment that bundles the model files).
    """

    def __init__(self, model_name: str = MODEL_NAME, cache_dir: Optional[str] = None, model_dir: Optional[str] = None):
        self.model_name = model_name
        self._cache_dir = cache_dir
        self._model_dir = model_dir
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            kwargs = {"specific_model_path": self._model_dir} if self._model_dir else {}
            self._model = TextEmbedding(self.model_name, cache_dir=self._cache_dir, threads=onnx_threads(), **kwargs)
        return self._model

    def passages(self, texts: Iterable[str], batch_size: int = 32) -> np.ndarray:
        vectors = np.array(list(self._load().embed(list(texts), batch_size=batch_size)), dtype=np.float32)
        return _unit(vectors)

    def query(self, question: str) -> np.ndarray:
        vector = np.array(next(iter(self._load().embed([QUERY_INSTRUCTION + question]))), dtype=np.float32)
        return _unit(vector[None, :])[0]


def cross_encoder_name(repo: str = RERANK_MODEL_NAME, model_file: str = RERANK_MODEL_FILE) -> str:
    """The fastembed model name that loads `model_file` from the Hugging Face repo `repo`.

    fastembed lists one file per repo, so another file of the same repo is
    registered once as a custom model. It is read from the same cache folder
    (models--Xenova--ms-marco-MiniLM-L-6-v2), so a bundled copy loads offline.
    """
    from fastembed.common.model_description import ModelSource
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    listed = {m.model: m for m in TextCrossEncoder._list_supported_models()}
    if repo in listed and listed[repo].model_file == model_file:
        return repo
    name = f"{repo}-{Path(model_file).stem}"
    if name not in listed:
        TextCrossEncoder.add_custom_model(name, sources=ModelSource(hf=repo), model_file=model_file, size_in_gb=0.03)
    return name


class Reranker:
    """Cross-encoder relevance scores for (question, passage) pairs; loads on first use."""

    def __init__(self, model_name: str = RERANK_MODEL_NAME, cache_dir: Optional[str] = None,
                 model_file: str = RERANK_MODEL_FILE):
        self.model_name = model_name
        self.model_file = model_file
        self._cache_dir = cache_dir
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(cross_encoder_name(self.model_name, self.model_file), cache_dir=self._cache_dir,
                                           threads=onnx_threads())
        return self._model

    def scores(self, question: str, passages: List[str]) -> List[float]:
        if not passages:
            return []
        return [float(s) for s in self._load().rerank(question, passages, batch_size=32)]


def _unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)
