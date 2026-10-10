"""Tests for the build step that ships the fastembed models in the Vercel bundle (no network)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HOSTED = Path(__file__).resolve().parent.parent / "hosted"
sys.path.insert(0, str(HOSTED))

_spec = importlib.util.spec_from_file_location("fetch_models", HOSTED / "scripts" / "fetch_models.py")
fetch_models = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_models)

from divrag.embedder import MODEL_NAME, RERANK_MODEL_NAME  # noqa: E402


def test_models_match_what_fastembed_loads():
    from fastembed import TextEmbedding
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    wanted = {}
    for desc in TextEmbedding._list_supported_models():
        if desc.model == MODEL_NAME:
            wanted[desc.sources.hf] = desc.model_file
    for desc in TextCrossEncoder._list_supported_models():
        if desc.model == RERANK_MODEL_NAME:
            wanted[desc.sources.hf] = desc.model_file
    assert {m["repo"]: m["model_file"] for m in fetch_models.MODELS} == wanted


def _fake_hub(files):
    """get() and download() doubles serving `files` ({name: bytes}) for any repo."""
    calls = []

    def get(url):
        siblings = [{"rfilename": name, "size": len(data)} for name, data in files.items()]
        siblings.append({"rfilename": "README.md", "size": 3})
        return json.dumps({"siblings": siblings}).encode()

    def download(url, dest, size):
        calls.append(url)
        dest.write_bytes(files[url.rsplit("/resolve/", 1)[1].split("/", 1)[1]])

    return get, download, calls


def test_fetch_writes_the_hub_cache_layout(tmp_path):
    model = {"repo": "Org/model-onnx", "revision": "abc123", "model_file": "onnx/model.onnx"}
    files = {"onnx/model.onnx": b"weights", "tokenizer.json": b"{}", "config.json": b"{}"}
    get, download, calls = _fake_hub(files)

    snapshot = fetch_models.fetch_model(model, tmp_path, get=get, download=download)

    root = tmp_path / "models--Org--model-onnx"
    assert snapshot == root / "snapshots" / "abc123"
    assert (root / "refs" / "main").read_text() == "abc123"
    assert (snapshot / "onnx" / "model.onnx").read_bytes() == b"weights"
    assert not (snapshot / "README.md").exists()  # only what fastembed reads
    assert len(calls) == 3

    # A second run finds the files and downloads nothing.
    fetch_models.fetch_model(model, tmp_path, get=get, download=download)
    assert len(calls) == 3


def test_fetch_fails_when_the_model_file_is_missing(tmp_path):
    model = {"repo": "Org/model-onnx", "revision": "abc123", "model_file": "model.onnx"}
    get, download, _ = _fake_hub({"tokenizer.json": b"{}"})
    with pytest.raises(ValueError, match="has no model.onnx"):
        fetch_models.fetch_model(model, tmp_path, get=get, download=download)
