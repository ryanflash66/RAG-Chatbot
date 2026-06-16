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

@pytest.fixture()
def hash_embed() -> _HashEmbedding:
    """Return a fresh _HashEmbedding instance."""
    return _HashEmbedding()


@pytest.fixture()
def temp_data(tmp_path):
    """Isolated data and ChromaDB directories with one seed document."""
    data_dir = tmp_path / "data"
    chroma_dir = tmp_path / "chroma"
    data_dir.mkdir()
    chroma_dir.mkdir()

    (data_dir / "seed_ransomware.md").write_text(
        "# Ransomware Playbook\n\n"
        "## Identification\nDetect encryption activity via EDR alerts.\n\n"
        "## Containment\nIsolate affected hosts from the network immediately.\n\n"
        "## Eradication\nRemove malicious binaries and restore from clean backups.\n\n"
        "## Recovery\nVerify integrity of restored systems before returning to production.\n",
        encoding="utf-8",
    )
    return data_dir, chroma_dir


@pytest.fixture()
def temp_env(temp_data, monkeypatch):
    """Expose temp data and ChromaDB paths via environment variables."""
    data_dir, chroma_dir = temp_data
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(chroma_dir))
    monkeypatch.setenv("CHROMA_COLLECTION", "test_col")
    monkeypatch.setenv("EMBEDDING_MODEL", "hash-dummy")
    return data_dir, chroma_dir


@pytest.fixture()
def patch_embed(monkeypatch):
    """Replace the lazy embed model singleton in api.py with the test double."""
    import api
    monkeypatch.setattr(api, "_embed_model", _HashEmbedding())


@pytest.fixture()
def client(temp_env, patch_embed):
    """Synchronous TestClient for the api router only.

    Chainlit and the LoRA model are NOT loaded -- this client tests the
    ingestion and query endpoints in isolation.
    """
    import api
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)
