"""Tests for the ASGI entrypoint in server.py."""

from fastapi.testclient import TestClient

import api
import server


def test_api_routes_are_mounted():
    paths = set(server.app.openapi()["paths"])
    assert {"/api/ingest", "/api/query", "/health"} <= paths


def test_health_reports_index_stats(index):
    index.refresh()
    server.app.dependency_overrides[api.get_index] = lambda: index
    try:
        body = TestClient(server.app).get("/health").json()
    finally:
        server.app.dependency_overrides.clear()

    assert body["status"] == "ok"
    assert body["collection"] == "test_col"
    assert body["documents"] == 1
    assert body["vectors"] >= 1
