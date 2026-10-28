"""A precomputed search index as two plain files in one directory.

    chunks.json   {"model": ..., "dim": ..., "chunks": [{"text", "source", "page", "section", "division"}, ...]}
    vectors.npy   float16 array, one unit-length row per chunk, in the same order

`division` is the id of the division (divisions.py) whose documents the chunk
came from. Search is a dot product (cosine similarity, as rows and queries are
unit length); a division filter restricts it to that division's rows before
ranking, so another division's chunk can never be returned. A `sources` filter
(document file names) narrows it further to the documents the visitor ticked.
Only numpy is needed to load and search it.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

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
        self._rows_cache: Dict[Optional[str], np.ndarray] = {}
        self._position = {id(chunk): i for i, chunk in enumerate(chunks)}

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

    def divisions(self) -> List[str]:
        return sorted({c.get("division") for c in self.chunks if c.get("division")})

    def _rows(self, division: Optional[str], sources: Optional[Sequence[str]] = None) -> np.ndarray:
        """Row numbers of `division`'s chunks (every division when None), only from `sources` when given.

        Only whole divisions are cached. The visitor picks the `sources` subset, and
        with 20 documents a division (DAR-621) there are about a million subsets, so
        caching each would grow without bound on a warm instance; filtering a cached
        division's rows takes about a millisecond.
        """
        if division not in self._rows_cache:
            rows = [i for i, c in enumerate(self.chunks) if division is None or c.get("division") == division]
            self._rows_cache[division] = np.array(rows, dtype=int)
        rows = self._rows_cache[division]
        if sources is None:
            return rows
        wanted = set(sources)
        return np.array([i for i in rows if self.chunks[i].get("source") in wanted], dtype=int)

    def count(self, division: Optional[str] = None, sources: Optional[Sequence[str]] = None) -> int:
        """How many chunks a search with the same filters would look through."""
        return len(self._rows(division, sources))

    def position(self, chunk: Dict[str, Any]) -> int:
        """Where the chunk sits in the index: documents in order, each in reading order."""
        return self._position.get(id(chunk), len(self.chunks))

    def following(self, chunk: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The chunk after this one in the same document (chunks are saved in reading order)."""
        i = self._position.get(id(chunk))
        if i is None or i + 1 >= len(self.chunks):
            return None
        after = self.chunks[i + 1]
        return after if after.get("source") == chunk.get("source") else None

    def search(self, query_vector: Sequence[float], k: int = 3, division: Optional[str] = None,
               sources: Optional[Sequence[str]] = None) -> List[Hit]:
        """Top k chunks by cosine similarity; only `division`'s chunks (and `sources`' documents) when given."""
        rows = self._rows(division, sources)
        if not len(rows):
            return []
        scores = self.vectors[rows] @ np.asarray(query_vector, dtype=np.float32)
        top = np.argsort(-scores)[:k]
        return [Hit(float(scores[i]), self.chunks[rows[i]]) for i in top]
