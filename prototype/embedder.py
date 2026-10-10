"""Embeddings for the hosted prototype, computed locally with no API key.

fastembed runs BAAI/bge-small-en-v1.5 on onnxruntime: the same model the
Chainlit app indexes with (rag/config.py), without torch. Its vectors match the
sentence-transformers ones (cosine 1.0000 on the TMP Design Manual) so either can build
an index the other searches; `python -m prototype.ingest --compare` checks it.

Like the Chainlit app (LlamaIndex's HuggingFaceEmbedding), queries get the BGE
retrieval instruction and passages are embedded as-is.
"""

from typing import Iterable, Optional

import numpy as np

MODEL_NAME = "BAAI/bge-small-en-v1.5"
QUERY_INSTRUCTION = "Represent this question for searching relevant passages: "


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


def _unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)
