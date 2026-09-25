"""Retrieval index: the single ChromaDB-backed vector index over the data directory.

The interface is refresh / retrieve / stats. Refresh only happens when asked.
Retrieve never rebuilds and never writes. LlamaIndex node types stay inside this
module; callers get plain Hit values.

A refresh builds into a staging collection and swaps it in only once the build
succeeds, so a failed refresh leaves the previous index serving queries.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

import chromadb
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from llama_index.vector_stores.chroma import ChromaVectorStore

from rag import loader
from rag.config import AppConfig


class EmptyIndexError(RuntimeError):
    """Raised by retrieve() when nothing has been indexed yet."""


class NoDocumentsError(ValueError):
    """Raised by refresh() when the data directory has no loadable Documents."""


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


def make_embed_model(config: AppConfig):
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    return HuggingFaceEmbedding(model_name=config.embedding_model)


class RetrievalIndex:
    def __init__(self, config: AppConfig, embed_model: Any):
        self._config = config
        self._embed_model = embed_model
        self._lock = threading.RLock()
        config.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(config.chroma_persist_dir))
        self._collection = self._client.get_or_create_collection(config.chroma_collection)

    @property
    def config(self) -> AppConfig:
        return self._config

    def stats(self) -> IndexStats:
        with self._lock:
            meta = self._collection.metadata or {}
            return IndexStats(
                collection=self._config.chroma_collection,
                documents=int(meta.get("documents", 0)),
                vectors=self._collection.count(),
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
            staging_name = f"{name}__staging"
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
                )
            except Exception:
                self._delete_collection(staging_name)
                raise

            self._delete_collection(name)
            staging.modify(name=name)
            self._collection = self._client.get_collection(name)
            return self.stats()

    def ensure_built(self) -> IndexStats:
        """Build once if the index is empty and there are Documents to index."""
        with self._lock:
            if self._collection.count() == 0:
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
        with self._lock:
            if self._collection.count() == 0:
                raise EmptyIndexError("The index is empty. Ingest documents first.")
            index = VectorStoreIndex.from_vector_store(
                vector_store=ChromaVectorStore(chroma_collection=self._collection),
                embed_model=self._embed_model,
            )
            filters = (
                MetadataFilters(filters=[MetadataFilter(key=key, value=value) for key, value in where.items()])
                if where
                else None
            )
            nodes = index.as_retriever(similarity_top_k=k, filters=filters).retrieve(query)

        return [
            Hit(
                text=nws.node.get_content().strip(),
                score=nws.score,
                source=nws.node.metadata.get("source"),
                metadata=dict(nws.node.metadata),
            )
            for nws in nodes
        ]

    def _delete_collection(self, name: str) -> None:
        try:
            self._client.delete_collection(name)
        except Exception:
            pass
