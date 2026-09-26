"""Tests for AppConfig resolution."""

from pathlib import Path

import pytest

from rag.config import ROOT, load_config


def test_defaults_resolve_against_repo_root():
    cfg = load_config({})
    assert cfg.data_dir == ROOT / "data"
    assert cfg.chroma_persist_dir == ROOT / "chroma_db"
    assert cfg.chat_storage_dir == ROOT / "chat_history"
    assert cfg.chroma_collection == "irp_docs"
    assert cfg.embedding_model == "BAAI/bge-small-en-v1.5"
    assert cfg.llm_provider == "ollama"
    assert cfg.model_name == "qwen2.5:14b"
    assert cfg.ollama_base_url == "http://localhost:11434"
    assert cfg.temperature == 0.0
    assert cfg.openrouter_api_key is None
    assert cfg.chat_history_enabled is True
    assert cfg.max_chat_history == 50
    assert cfg.auth_username is None
    assert cfg.auth_password is None
    assert cfg.retrieval_top_k == 5
    assert cfg.chunk_size == 1024
    assert cfg.chunk_overlap == 128
    assert cfg.rerank_model == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    assert cfg.rerank_candidates == 20


def test_relative_paths_ignore_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_config({"DATA_DIR": "./docs"}).data_dir == ROOT / "docs"


def test_absolute_paths_kept(tmp_path):
    assert load_config({"DATA_DIR": str(tmp_path)}).data_dir == Path(tmp_path)


def test_config_is_hashable():
    assert hash(load_config({})) == hash(load_config({}))


def test_reads_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("CHROMA_COLLECTION", "from_env")
    assert load_config().chroma_collection == "from_env"


def test_openrouter_provider_defaults_to_gpt4o():
    cfg = load_config({"LLM_PROVIDER": "OpenRouter"})
    assert cfg.llm_provider == "openrouter"
    assert cfg.model_name == "gpt-4o"


def test_explicit_model_name_wins():
    assert load_config({"MODEL_NAME": "llama3.1:8b"}).model_name == "llama3.1:8b"


def test_invalid_provider_rejected():
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        load_config({"LLM_PROVIDER": "chatgpt"})


def test_ollama_base_url_trailing_slash_dropped():
    assert load_config({"OLLAMA_BASE_URL": "http://gpu-box:11434/"}).ollama_base_url == "http://gpu-box:11434"


def test_retrieval_settings_overridden():
    cfg = load_config({"RETRIEVAL_TOP_K": "3", "CHUNK_SIZE": "512", "CHUNK_OVERLAP": "64"})
    assert (cfg.retrieval_top_k, cfg.chunk_size, cfg.chunk_overlap) == (3, 512, 64)


@pytest.mark.parametrize(
    "env, match",
    [
        ({"RETRIEVAL_TOP_K": "0"}, "RETRIEVAL_TOP_K"),
        ({"CHUNK_SIZE": "16"}, "CHUNK_SIZE"),
        ({"CHUNK_OVERLAP": "-1"}, "CHUNK_OVERLAP"),
        ({"CHUNK_SIZE": "256", "CHUNK_OVERLAP": "256"}, "CHUNK_OVERLAP"),
        ({"RETRIEVAL_TOP_K": "12", "CHUNK_SIZE": "1024"}, "context window"),
    ],
)
def test_invalid_retrieval_settings_rejected(env, match):
    with pytest.raises(ValueError, match=match):
        load_config(env)


def test_default_retrieved_context_fits_ollama_window():
    """5 chunks x 1024 tokens leaves over 3k of the 8192-token window for template, question, answer."""
    cfg = load_config({})
    assert 8192 - cfg.retrieval_top_k * cfg.chunk_size >= 2048


@pytest.mark.parametrize("value", ["", "none", "OFF"])
def test_reranking_can_be_turned_off(value):
    assert load_config({"RERANK_MODEL": value}).rerank_model is None


def test_rerank_candidates_must_be_positive():
    with pytest.raises(ValueError, match="RERANK_CANDIDATES"):
        load_config({"RERANK_CANDIDATES": "0"})
