"""Shared pytest fixtures and test utilities.

The _HashEmbedding class provides a deterministic, dependency-free embedding
model for tests. It produces a unique 32-dimensional vector for each input
string using SHA-256, so similarity comparisons in ChromaDB are meaningful
without needing a GPU or a downloaded sentence-transformer model.
"""

import hashlib
from typing import List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from llama_index.core.embeddings import BaseEmbedding

from rag.config import load_config
from rag.index import RetrievalIndex


# ---------------------------------------------------------------------------
# Test double: deterministic embedding
# ---------------------------------------------------------------------------

def _hash32(text: str) -> List[float]:
    digest = hashlib.sha256(text.encode()).digest()
    return [b / 127.5 - 1.0 for b in digest[:32]]


class _HashEmbedding(BaseEmbedding):
    """32-dim deterministic embedding backed by SHA-256 -- no model download required."""

    model_name: str = "hash-dummy"

    def _get_text_embedding(self, text: str) -> List[float]:
        return _hash32(text)

    def _get_query_embedding(self, query: str) -> List[float]:
        return _hash32(query)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return _hash32(query)

    async def _aget_text_embedding(self, text: str) -> List[float]:
        return _hash32(text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SEED_PLAYBOOK = (
    "# Ransomware Playbook\n\n"
    "## Identification\nDetect encryption activity via EDR alerts.\n\n"
    "## Containment\nIsolate affected hosts from the network immediately.\n\n"
    "## Eradication\nRemove malicious binaries and restore from clean backups.\n\n"
    "## Recovery\nVerify integrity of restored systems before returning to production.\n"
)


@pytest.fixture()
def hash_embed() -> _HashEmbedding:
    return _HashEmbedding()


@pytest.fixture()
def config(tmp_path):
    """AppConfig pointing at isolated data and ChromaDB directories (both empty)."""
    cfg = load_config({
        "DATA_DIR": str(tmp_path / "data"),
        "CHROMA_PERSIST_DIR": str(tmp_path / "chroma"),
        "CHROMA_COLLECTION": "test_col",
        "CHAT_STORAGE_DIR": str(tmp_path / "chat_history"),
    })
    cfg.data_dir.mkdir()
    return cfg


@pytest.fixture()
def seeded_config(config):
    """config with one seed Document in the data directory."""
    (config.data_dir / "seed_ransomware.md").write_text(SEED_PLAYBOOK, encoding="utf-8")
    return config


@pytest.fixture()
def index(seeded_config, hash_embed) -> RetrievalIndex:
    """A Retrieval index over the seeded data directory, not yet refreshed."""
    return RetrievalIndex(seeded_config, hash_embed)


def make_client(index: RetrievalIndex) -> TestClient:
    """TestClient for the api router with the Retrieval index injected."""
    import api

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_config] = lambda: index.config
    app.dependency_overrides[api.get_index] = lambda: index
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def client(index) -> TestClient:
    """API client whose index was built from the seed Document, as at app startup."""
    index.ensure_built()
    return make_client(index)
