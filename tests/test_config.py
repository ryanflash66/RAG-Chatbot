"""Tests for AppConfig resolution."""

from pathlib import Path

from rag.config import ROOT, load_config


def test_defaults_resolve_against_repo_root():
    cfg = load_config({})
    assert cfg.data_dir == ROOT / "data"
    assert cfg.chroma_persist_dir == ROOT / "chroma_db"
    assert cfg.chat_storage_dir == ROOT / "chat_history"
    assert cfg.chroma_collection == "irp_docs"
    assert cfg.embedding_model == "BAAI/bge-small-en-v1.5"
    assert cfg.model_name == "gpt-4o"
    assert cfg.temperature == 0.0
    assert cfg.openrouter_api_key is None
    assert cfg.chat_history_enabled is True
    assert cfg.max_chat_history == 50


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
