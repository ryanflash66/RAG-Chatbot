"""Retrieval index: the single ChromaDB-backed vector index over the data directory.

The interface is refresh / retrieve / stats. Refresh only happens when asked.
Retrieve never rebuilds and never writes. LlamaIndex node types stay inside this
module; callers get plain Hit values.

Retrieval is two-stage when a reranker is given: the vector search fetches
`rerank_candidates` hits, a cross-encoder scores each (question, passage) pair,
and the best `k` are returned. The small embedding model alone ranks table
passages poorly (e.g. Table 9-1 came 10th for its own question); the
cross-encoder puts it first.

A refresh builds into a staging collection and swaps it in only once the build
succeeds, so a failed refresh leaves the previous index serving queries.

Several RetrievalIndex instances (the API server, the Chainlit app, the CLI) may
share one store. None of them caches the collection: every call looks it up by
name, so each sees the others' refreshes. A swap briefly removes the name; lookups
that land in that window wait for it to reappear.
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import chromadb
from chromadb.errors import NotFoundError
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from llama_index.vector_stores.chroma import ChromaVectorStore

from rag import loader
from rag.tables import TableAwareSplitter
from rag.config import AppConfig


class EmptyIndexError(RuntimeError):
    """Raised by retrieve() when nothing has been indexed yet."""


class NoDocumentsError(ValueError):
    """Raised by refresh() when the data directory has no loadable Documents."""


# How long a lookup waits for a collection that another instance is swapping in.
_SWAP_WAIT_SECONDS = 5.0
_SWAP_POLL_SECONDS = 0.1


@dataclass(frozen=True)
class Hit:
    text: str
    score: Optional[float]
    source: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexStats:
    collection: str
    documents: int
    vectors: int
    last_refresh_at: Optional[str]


# Scores (question, passage) pairs; higher means more relevant.
Reranker = Callable[[str, Sequence[str]], Sequence[float]]


def make_embed_model(config: AppConfig):
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    return HuggingFaceEmbedding(model_name=config.embedding_model)


def make_reranker(config: AppConfig) -> Optional[Reranker]:
    """A cross-encoder reranker for `config.rerank_model`, or None when reranking is off."""
    if not config.rerank_model:
        return None
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(config.rerank_model, max_length=512)

    def rerank(query: str, passages: Sequence[str]) -> Sequence[float]:
        return [float(s) for s in model.predict([(query, p) for p in passages])]

    return rerank


class RetrievalIndex:
    def __init__(self, config: AppConfig, embed_model: Any, reranker: Optional[Reranker] = None):
        self._config = config
        self._embed_model = embed_model
        self._reranker = reranker
        self._lock = threading.RLock()
        config.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(config.chroma_persist_dir))

    @property
    def _staging_name(self) -> str:
        return f"{self._config.chroma_collection}__staging"

    def _collection(self):
        """The live collection, looked up by name; None if nothing has been built."""
        deadline = time.monotonic() + _SWAP_WAIT_SECONDS
        while True:
            try:
                return self._client.get_collection(self._config.chroma_collection)
            except NotFoundError:
                # A staging collection means another instance is mid-swap.
                if not self._exists(self._staging_name) or time.monotonic() > deadline:
                    return None
                time.sleep(_SWAP_POLL_SECONDS)

    def _exists(self, name: str) -> bool:
        try:
            self._client.get_collection(name)
            return True
        except NotFoundError:
            return False

    @property
    def config(self) -> AppConfig:
        return self._config

    def stats(self) -> IndexStats:
        with self._lock:
            collection = self._collection()
            if collection is None:
                return IndexStats(self._config.chroma_collection, documents=0, vectors=0, last_refresh_at=None)
            meta = collection.metadata or {}
            return IndexStats(
                collection=self._config.chroma_collection,
                documents=int(meta.get("documents", 0)),
                vectors=collection.count(),
                last_refresh_at=meta.get("last_refresh_at"),
            )

    def refresh(self) -> IndexStats:
        """Rebuild the index from every Document currently in the data directory."""
        with self._lock:
            documents = loader.load(self._config.data_dir)
            if not documents:
                raise NoDocumentsError(
                    f"No documents found under data directory: {self._config.data_dir}. "
                    "Add documents before building the index."
                )

            name = self._config.chroma_collection
            staging_name = self._staging_name
            self._delete_collection(staging_name)
            staging = self._client.create_collection(
                staging_name,
                metadata={
                    "documents": len({d.metadata.get("source") for d in documents}),
                    "last_refresh_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            try:
                VectorStoreIndex.from_documents(
                    documents,
                    storage_context=StorageContext.from_defaults(
                        vector_store=ChromaVectorStore(chroma_collection=staging)
                    ),
                    embed_model=self._embed_model,
                    # Tables are never cut mid-row or separated from their headers.
                    transformations=[
                        TableAwareSplitter(
                            chunk_size=self._config.chunk_size,
                            chunk_overlap=self._config.chunk_overlap,
                        )
                    ],
                )
            except Exception:
                self._delete_collection(staging_name)
                raise

            self._delete_collection(name)
            staging.modify(name=name)
            return self.stats()

    def ensure_built(self) -> IndexStats:
        """Build once if the index is empty and there are Documents to index."""
        with self._lock:
            if self.stats().vectors == 0:
                try:
                    return self.refresh()
                except NoDocumentsError:
                    pass
            return self.stats()

    def retrieve(
        self,
        query: str,
        k: int = 4,
        where: Optional[Mapping[str, str]] = None,
    ) -> List[Hit]:
        filters = (
            MetadataFilters(filters=[MetadataFilter(key=key, value=value) for key, value in where.items()])
            if where
            else None
        )
        fetch = max(k, self._config.rerank_candidates) if self._reranker else k
        with self._lock:
            # One retry covers a collection swapped out by another instance mid-query.
            for attempt in range(2):
                collection = self._collection()
                if collection is None or collection.count() == 0:
                    raise EmptyIndexError("The index is empty. Ingest documents first.")
                index = VectorStoreIndex.from_vector_store(
                    vector_store=ChromaVectorStore(chroma_collection=collection),
                    embed_model=self._embed_model,
                )
                try:
                    nodes = index.as_retriever(similarity_top_k=fetch, filters=filters).retrieve(query)
                    break
                except NotFoundError:
                    if attempt:
                        raise

        hits = [
            Hit(
                text=nws.node.get_content().strip(),
                score=nws.score,
                source=nws.node.metadata.get("source"),
                metadata=dict(nws.node.metadata),
            )
            for nws in nodes
        ]
        if not self._reranker or not hits:
            return hits[:k]
        # The reranker's score replaces the vector similarity; the latter is kept
        # in metadata as "vector_score".
        scores = self._reranker(query, [hit.text for hit in hits])
        ranked = sorted(zip(scores, hits), key=lambda pair: pair[0], reverse=True)[:k]
        return [
            Hit(text=hit.text, score=score, source=hit.source, metadata={**hit.metadata, "vector_score": hit.score})
            for score, hit in ranked
        ]

    def _delete_collection(self, name: str) -> None:
        try:
            self._client.delete_collection(name)
        except Exception:
            pass
