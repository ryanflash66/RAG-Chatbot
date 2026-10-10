"""A precomputed search index as two plain files in one directory.

    chunks.json   {"model": ..., "dim": ..., "chunks": [{"text", "source", "page", "section"}, ...]}
    vectors.npy   float16 array, one unit-length row per chunk, in the same order

Search is a dot product (cosine similarity, as rows and queries are unit length).
Only numpy is needed to load and search it.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

import numpy as np

CHUNKS_FILE = "chunks.json"
VECTORS_FILE = "vectors.npy"


@dataclass(frozen=True)
class Hit:
    score: float
    chunk: Dict[str, Any]


class IndexFile:
    def __init__(self, model: str, chunks: List[Dict[str, Any]], vectors: np.ndarray):
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        self.model = model
        self.chunks = chunks
        self.vectors = vectors

    @classmethod
    def load(cls, directory: "str | Path") -> "IndexFile":
        directory = Path(directory)
        meta = json.loads((directory / CHUNKS_FILE).read_text(encoding="utf-8"))
        vectors = np.load(directory / VECTORS_FILE).astype(np.float32)
        if vectors.shape[1] != meta["dim"]:
            raise ValueError(f"vectors have {vectors.shape[1]} dimensions, chunks.json says {meta['dim']}")
        return cls(meta["model"], meta["chunks"], vectors)

    def save(self, directory: "str | Path") -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        meta = {"model": self.model, "dim": int(self.vectors.shape[1]), "chunks": self.chunks}
        (directory / CHUNKS_FILE).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        np.save(directory / VECTORS_FILE, self.vectors.astype(np.float16))

    def search(self, query_vector: Sequence[float], k: int = 3) -> List[Hit]:
        scores = self.vectors @ np.asarray(query_vector, dtype=np.float32)
        top = np.argsort(-scores)[:k]
        return [Hit(float(scores[i]), self.chunks[i]) for i in top]
