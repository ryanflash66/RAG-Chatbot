"""Tests for Upload staging: validation before writing, commit, and rollback."""

import pytest

from rag.staging import UploadRejected, stage

ALLOWED = {".md", ".txt"}


def test_valid_batch_is_committed(tmp_path):
    staged = stage(tmp_path, [("a.md", b"A"), ("b.txt", b"B")], ALLOWED)
    with staged:
        pass
    assert (tmp_path / "a.md").read_bytes() == b"A"
    assert (tmp_path / "b.txt").read_bytes() == b"B"


def test_rejected_batch_writes_nothing(tmp_path):
    with pytest.raises(UploadRejected, match=r"\.exe"):
        stage(tmp_path, [("a.md", b"A"), ("x.exe", b"MZ")], ALLOWED)
    assert list(tmp_path.iterdir()) == []


def test_nothing_is_written_until_entered(tmp_path):
    stage(tmp_path, [("a.md", b"A")], ALLOWED)
    assert not (tmp_path / "a.md").exists()


@pytest.mark.parametrize("name,expected", [
    ("../escape.md", "escape.md"),
    ("..\\..\\escape.md", "escape.md"),
    ("/abs/path/escape.md", "escape.md"),
    ("C:\\Windows\\escape.md", "escape.md"),
])
def test_filenames_cannot_escape_data_dir(tmp_path, name, expected):
    data = tmp_path / "data"
    with stage(data, [(name, b"x")], ALLOWED):
        pass
    assert [p.name for p in data.iterdir()] == [expected]
    assert not (tmp_path / "escape.md").exists()


@pytest.mark.parametrize("name", [None, "", "..", "dir/"])
def test_invalid_filenames_rejected(tmp_path, name):
    with pytest.raises(UploadRejected):
        stage(tmp_path, [(name, b"x")], ALLOWED)


def test_duplicate_names_rejected(tmp_path):
    with pytest.raises(UploadRejected, match="Duplicate"):
        stage(tmp_path, [("a.md", b"1"), ("A.md", b"2")], ALLOWED)


def test_empty_batch_rejected(tmp_path):
    with pytest.raises(UploadRejected):
        stage(tmp_path, [], ALLOWED)


def test_failure_removes_new_files(tmp_path):
    with pytest.raises(RuntimeError):
        with stage(tmp_path, [("new.md", b"new")], ALLOWED):
            assert (tmp_path / "new.md").exists()
            raise RuntimeError("refresh failed")
    assert not (tmp_path / "new.md").exists()


def test_failure_restores_overwritten_files(tmp_path):
    (tmp_path / "notes.md").write_bytes(b"original")

    with pytest.raises(RuntimeError):
        with stage(tmp_path, [("notes.md", b"replacement")], ALLOWED):
            assert (tmp_path / "notes.md").read_bytes() == b"replacement"
            raise RuntimeError("refresh failed")

    assert (tmp_path / "notes.md").read_bytes() == b"original"


def test_success_replaces_overwritten_files(tmp_path):
    (tmp_path / "notes.md").write_bytes(b"original")
    with stage(tmp_path, [("notes.md", b"replacement")], ALLOWED):
        pass
    assert (tmp_path / "notes.md").read_bytes() == b"replacement"
