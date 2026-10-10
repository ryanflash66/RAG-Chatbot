"""Question embeddings and reranking, computed locally with no API key.

fastembed runs BAAI/bge-small-en-v1.5 on onnxruntime: the same model the
Chainlit app indexes with (rag/config.py), without torch. Its vectors match the
sentence-transformers ones (cosine 1.0000 on the TMP Design Manual) so either can build
an index the other searches; `python -m prototype.ingest --compare` checks it.

Like the Chainlit app (LlamaIndex's HuggingFaceEmbedding), queries get the BGE
retrieval instruction and passages are embedded as-is.

The reranker is fastembed's ONNX port of the cross-encoder the Chainlit app
uses (cross-encoder/ms-marco-MiniLM-L-6-v2): it scores each (question, passage)
pair and re-orders the vector hits.

Model files are read from (and on first use downloaded into) `model_cache_dir()`.
"""

import os
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional

import numpy as np

MODEL_NAME = "BAAI/bge-small-en-v1.5"
RERANK_MODEL_NAME = "Xenova/ms-marco-MiniLM-L-6-v2"
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
            self._model = TextEmbedding(self.model_name, cache_dir=self._cache_dir, **kwargs)
        return self._model

    def passages(self, texts: Iterable[str], batch_size: int = 32) -> np.ndarray:
        vectors = np.array(list(self._load().embed(list(texts), batch_size=batch_size)), dtype=np.float32)
        return _unit(vectors)

    def query(self, question: str) -> np.ndarray:
        vector = np.array(next(iter(self._load().embed([QUERY_INSTRUCTION + question]))), dtype=np.float32)
        return _unit(vector[None, :])[0]


class Reranker:
    """Cross-encoder relevance scores for (question, passage) pairs; loads on first use."""

    def __init__(self, model_name: str = RERANK_MODEL_NAME, cache_dir: Optional[str] = None):
        self.model_name = model_name
        self._cache_dir = cache_dir
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(self.model_name, cache_dir=self._cache_dir)
        return self._model

    def scores(self, question: str, passages: List[str]) -> List[float]:
        if not passages:
            return []
        return [float(s) for s in self._load().rerank(question, passages, batch_size=32)]


def _unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)
