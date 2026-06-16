"""Tests for the FastAPI ingest and query endpoints in api.py.

All tests use the `client` fixture from conftest.py, which wires the api router
into a minimal FastAPI app with:
  - temp DATA_DIR and CHROMA_PERSIST_DIR (isolated per test via tmp_path)
  - _HashEmbedding replacing the HuggingFace model (no download, no GPU)

The ChromaDB integration is real -- vectors are written to and read from an
actual chromadb.PersistentClient backed by the temp directory.
"""

import io

import pytest


# ---------------------------------------------------------------------------
# POST /api/ingest
# ---------------------------------------------------------------------------

def test_ingest_markdown_returns_success(client):
    content = (
        "# Phishing Playbook\n\n"
        "## Containment\nReset compromised credentials immediately.\n\n"
        "## Eradication\nBlock sender domains at the email gateway.\n"
    ).encode()

    resp = client.post(
        "/api/ingest",
        files={"files": ("phishing_response.md", io.BytesIO(content), "text/plain")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["indexed_docs"] >= 1
    assert body["vector_count"] >= 1
    assert body["collection"] == "test_col"
    assert "rebuilt" in body["message"]


def test_ingest_multiple_files_returns_correct_count(client, temp_env):
    data_dir, _ = temp_env
    files = [
        ("files", ("ransomware.md", b"# Ransomware\n\nIsolate hosts.", "text/plain")),
        ("files", ("malware.md",    b"# Malware\n\nRun EDR scan.",     "text/plain")),
    ]
    resp = client.post("/api/ingest", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    # seed_ransomware.md (from temp_data) + 2 uploaded files = at least 3
    assert body["indexed_docs"] >= 2


def test_ingest_plain_text_file(client):
    resp = client.post(
        "/api/ingest",
        files={"files": ("notes.txt", b"Incident notes: server unreachable.", "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_ingest_unsupported_extension_returns_400(client):
    resp = client.post(
        "/api/ingest",
        files={"files": ("payload.exe", b"\x4d\x5a\x90\x00", "application/octet-stream")},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert ".exe" in detail
    assert "Unsupported" in detail


def test_ingest_zip_extension_returns_400(client):
    resp = client.post(
        "/api/ingest",
        files={"files": ("archive.zip", b"PK\x03\x04", "application/zip")},
    )
    assert resp.status_code == 400


def test_ingest_docx_extension_is_in_supported_list():
    from api import SUPPORTED_EXTENSIONS
    assert ".docx" in SUPPORTED_EXTENSIONS


def test_ingest_pptx_extension_is_in_supported_list():
    from api import SUPPORTED_EXTENSIONS
    assert ".pptx" in SUPPORTED_EXTENSIONS


def test_ingest_image_extensions_are_in_supported_list():
    from api import SUPPORTED_EXTENSIONS
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".tiff", ".bmp"):
        assert ext in SUPPORTED_EXTENSIONS, f"Expected {ext} in SUPPORTED_EXTENSIONS"


# ---------------------------------------------------------------------------
# POST /api/query
# ---------------------------------------------------------------------------

def test_query_returns_results_after_ingest(client):
    client.post(
        "/api/ingest",
        files={"files": ("incident.md", b"# Incident Response\n\nContain and isolate.", "text/plain")},
    )

    resp = client.post("/api/query", json={"query": "incident response containment"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "incident response containment"
    assert len(body["results"]) > 0


def test_query_results_have_required_fields(client):
    client.post(
        "/api/ingest",
        files={"files": ("playbook.md", b"# IR Playbook\n\nTriage, contain, eradicate.", "text/plain")},
    )

    resp = client.post("/api/query", json={"query": "triage"})
    assert resp.status_code == 200

    for result in resp.json()["results"]:
        assert "text" in result
        assert result["text"]


def test_query_top_k_limits_result_count(client):
    resp = client.post("/api/query", json={"query": "ransomware containment", "top_k": 1})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) <= 1


def test_query_top_k_default_is_four(client):
    resp = client.post("/api/query", json={"query": "ransomware"})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) <= 4


def test_query_seed_document_is_retrievable(client):
    resp = client.post("/api/query", json={"query": "EDR containment isolation"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) > 0
    combined_text = " ".join(r["text"] for r in body["results"]).lower()
    assert any(word in combined_text for word in ("isolat", "edr", "contain", "eradicat", "backup"))


def test_query_includes_score_in_results(client):
    resp = client.post("/api/query", json={"query": "ransomware response"})
    assert resp.status_code == 200
    for result in resp.json()["results"]:
        if result.get("score") is not None:
            assert isinstance(result["score"], float)


def test_query_empty_data_dir_returns_500(tmp_path, monkeypatch):
    """Query endpoint returns 500 when data directory has no documents."""
    from api import SUPPORTED_EXTENSIONS
    import api
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from tests.conftest import _HashEmbedding

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()

    monkeypatch.setenv("DATA_DIR", str(empty_dir))
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(chroma_dir))
    monkeypatch.setenv("CHROMA_COLLECTION", "empty_col")
    monkeypatch.setattr(api, "_embed_model", _HashEmbedding())

    app = FastAPI()
    app.include_router(api.router)
    c = TestClient(app, raise_server_exceptions=False)

    resp = c.post("/api/query", json={"query": "anything"})
    assert resp.status_code == 500
    assert "Index unavailable" in resp.json()["detail"]
