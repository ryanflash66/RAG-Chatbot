"""Tests for the FastAPI ingest and query endpoints in api.py.

The `client` fixture wires the api router into a minimal FastAPI app and injects
a Retrieval index (via dependency_overrides) that uses:
  - tmp_path data and ChromaDB directories, seeded with one ransomware playbook
  - _HashEmbedding instead of the HuggingFace model (no download, no GPU)

ChromaDB is real -- vectors are written to and read from a persistent client.
"""

import io

from tests.conftest import make_client


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
    assert body["indexed_docs"] == 2
    assert body["vector_count"] >= 2
    assert body["collection"] == "test_col"
    assert "rebuilt" in body["message"]


def test_ingest_multiple_files_returns_correct_count(client):
    files = [
        ("files", ("ransomware.md", b"# Ransomware\n\nIsolate hosts.", "text/plain")),
        ("files", ("malware.md",    b"# Malware\n\nRun EDR scan.",     "text/plain")),
    ]
    resp = client.post("/api/ingest", files=files)

    assert resp.status_code == 200
    # seed_ransomware.md + 2 uploaded files
    assert resp.json()["indexed_docs"] == 3


def test_ingest_plain_text_file(client):
    resp = client.post(
        "/api/ingest",
        files={"files": ("notes.txt", b"Incident notes: server unreachable.", "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_ingest_json_file(client):
    resp = client.post(
        "/api/ingest",
        files={"files": ("asset_inventory.json", b'{"hosts": ["dc01"]}', "application/json")},
    )
    assert resp.status_code == 200
    results = client.post(
        "/api/query", json={"query": "hosts", "top_k": 10, "where": {"doc_domain": "asset_inventory"}}
    ).json()["results"]
    assert [r["source"] for r in results] == ["asset_inventory.json"]


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


def test_ingest_mixed_batch_writes_nothing(client, index):
    before = sorted(p.name for p in index.config.data_dir.iterdir())
    files = [
        ("files", ("good.md", b"# Good", "text/plain")),
        ("files", ("bad.exe", b"MZ", "application/octet-stream")),
    ]

    resp = client.post("/api/ingest", files=files)

    assert resp.status_code == 400
    assert sorted(p.name for p in index.config.data_dir.iterdir()) == before


def test_ingest_path_traversal_is_contained(client, index):
    resp = client.post(
        "/api/ingest",
        files={"files": ("../escape.md", b"# Escape", "text/plain")},
    )
    assert resp.status_code == 200
    assert (index.config.data_dir / "escape.md").exists()
    assert not (index.config.data_dir.parent / "escape.md").exists()


def test_ingest_failure_restores_overwritten_file(client, index, monkeypatch):
    seed = index.config.data_dir / "seed_ransomware.md"
    original = seed.read_bytes()

    def failing_refresh():
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(index, "refresh", failing_refresh)
    resp = client.post(
        "/api/ingest",
        files=[
            ("files", ("seed_ransomware.md", b"replacement", "text/plain")),
            ("files", ("new.md", b"# New", "text/plain")),
        ],
    )

    assert resp.status_code == 500
    assert "embedding service down" in resp.json()["detail"]
    assert seed.read_bytes() == original
    assert not (index.config.data_dir / "new.md").exists()


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
    resp = client.post("/api/query", json={"query": "triage"})
    assert resp.status_code == 200

    results = resp.json()["results"]
    assert results
    for result in results:
        assert result["text"]
        assert isinstance(result["score"], float)
        assert result["source"] == "seed_ransomware.md"
        assert result["incident_type"] == "ransomware"
        assert result["doc_domain"] == "ir"


def test_query_top_k_limits_result_count(client):
    resp = client.post("/api/query", json={"query": "ransomware containment", "top_k": 1})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 1


def test_query_top_k_default_is_four(client):
    resp = client.post("/api/query", json={"query": "ransomware"})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) <= 4


def test_query_seed_document_is_retrievable(client):
    resp = client.post("/api/query", json={"query": "EDR containment isolation"})
    assert resp.status_code == 200
    combined_text = " ".join(r["text"] for r in resp.json()["results"]).lower()
    assert any(word in combined_text for word in ("isolat", "edr", "contain", "eradicat", "backup"))


def test_query_where_filters_results(client):
    client.post(
        "/api/ingest",
        files={"files": ("phishing_playbook.md", b"# Phishing\n\nReset credentials.", "text/plain")},
    )
    resp = client.post(
        "/api/query", json={"query": "playbook", "top_k": 10, "where": {"incident_type": "phishing"}}
    )
    assert {r["source"] for r in resp.json()["results"]} == {"phishing_playbook.md"}


def test_query_does_not_pick_up_unrefreshed_files(client, index):
    (index.config.data_dir / "dropped_in.md").write_text("# Dropped in by hand", encoding="utf-8")
    resp = client.post("/api/query", json={"query": "dropped", "top_k": 10})
    assert "dropped_in.md" not in {r["source"] for r in resp.json()["results"]}


def test_query_empty_index_returns_503(config, hash_embed):
    from rag.index import RetrievalIndex

    c = make_client(RetrievalIndex(config, hash_embed))

    resp = c.post("/api/query", json={"query": "anything"})

    assert resp.status_code == 503
    assert "Index unavailable" in resp.json()["detail"]


def test_ingest_rejects_formats_whose_tool_is_missing(client, monkeypatch):
    from rag import loader

    monkeypatch.setattr(loader.shutil, "which", lambda name: None)
    resp = client.post("/api/ingest", files={"files": ("scan.png", b"not really a png", "image/png")})

    assert resp.status_code == 400
    assert ".png" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Page and section on /api/query results
# ---------------------------------------------------------------------------

def _pdf(page_texts) -> bytes:
    """A minimal valid PDF with one line of Helvetica text per page."""
    n = len(page_texts)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    font_id = 3 + 2 * n
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode(),
    ]
    for i, text in enumerate(page_texts):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {4 + 2 * i} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def test_query_markdown_results_have_no_page(client):
    resp = client.post("/api/query", json={"query": "ransomware containment", "top_k": 10})

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results
    for result in results:
        assert result["page"] is None
        # Either no section is known or a real heading -- never the "N/A" placeholder.
        assert result["section"] is None or result["section"].strip() not in ("", "N/A")


def test_query_pdf_results_report_their_page(client):
    pdf = _pdf(["Clear zone width is 30 feet.", "Taper length depends on speed."])
    ingest = client.post("/api/ingest", files={"files": ("work_zone_manual.pdf", pdf, "application/pdf")})
    assert ingest.status_code == 200, ingest.text

    resp = client.post("/api/query", json={"query": "clear zone", "top_k": 10})

    assert resp.status_code == 200
    by_page = {r["page"]: r["text"] for r in resp.json()["results"] if r["source"] == "work_zone_manual.pdf"}
    assert set(by_page) == {"1", "2"}
    assert "Clear zone width" in by_page["1"]
    assert "Taper length" in by_page["2"]


def test_query_maps_placeholder_section_to_null(index, monkeypatch):
    from rag.index import Hit

    index.ensure_built()
    hits = [
        Hit(text="a", score=0.9, source="a.md", metadata={"section": "N/A"}),
        Hit(text="b", score=0.8, source="b.pdf", metadata={"section": "Table 6H-3", "page_label": 12}),
    ]
    monkeypatch.setattr(index, "retrieve", lambda *args, **kwargs: hits)

    results = make_client(index).post("/api/query", json={"query": "x"}).json()["results"]

    assert [(r["page"], r["section"]) for r in results] == [(None, None), ("12", "Table 6H-3")]
