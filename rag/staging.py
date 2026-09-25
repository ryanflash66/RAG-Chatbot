"""Upload staging: place uploads into the data directory, then commit or roll back.

    staged = stage(data_dir, [("notes.md", b"...")], allowed_extensions)
    with staged:          # uploads are now in data_dir
        index.refresh()   # an exception here rolls back
    # on success: uploads stay, overwritten originals are discarded
    # on failure: uploads are removed, overwritten originals are restored

stage() validates the whole batch before anything touches data_dir. Filenames
are reduced to their final component, so "../x.md" becomes "x.md".
"""

import shutil
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Iterable, List, Optional, Sequence, Tuple


class UploadRejected(ValueError):
    """The batch was refused; nothing was written to the data directory."""


def safe_filename(name: Optional[str]) -> str:
    # PureWindowsPath splits on both "/" and "\\", whichever OS we run on.
    base = PureWindowsPath(name or "").name.strip()
    if base in ("", ".", ".."):
        raise UploadRejected(f"Invalid filename: {name!r}")
    return base


class StagedUploads:
    def __init__(self, data_dir: Path, files: Sequence[Tuple[str, bytes]]):
        self._data_dir = data_dir
        self._files = files
        self._placed: List[Path] = []
        self._backup_dir: Optional[Path] = None
        self._backups: List[Tuple[Path, Path]] = []

    @property
    def filenames(self) -> List[str]:
        return [name for name, _ in self._files]

    def __enter__(self) -> "StagedUploads":
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._backup_dir = Path(tempfile.mkdtemp(prefix="rag-upload-backup-"))
        try:
            for name, content in self._files:
                dest = self._data_dir / name
                if dest.exists():
                    backup = self._backup_dir / name
                    shutil.move(str(dest), str(backup))
                    self._backups.append((dest, backup))
                dest.write_bytes(content)
                self._placed.append(dest)
        except Exception:
            self._rollback()
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._cleanup()
        else:
            self._rollback()
        return False

    def _rollback(self) -> None:
        for path in self._placed:
            path.unlink(missing_ok=True)
        for dest, backup in self._backups:
            shutil.move(str(backup), str(dest))
        self._cleanup()

    def _cleanup(self) -> None:
        if self._backup_dir is not None:
            shutil.rmtree(self._backup_dir, ignore_errors=True)
            self._backup_dir = None


def stage(
    data_dir: "str | Path",
    uploads: Iterable[Tuple[Optional[str], bytes]],
    allowed_extensions: Iterable[str],
) -> StagedUploads:
    allowed = frozenset(allowed_extensions)
    files: List[Tuple[str, bytes]] = []
    seen = set()
    for raw_name, content in uploads:
        name = safe_filename(raw_name)
        suffix = Path(name).suffix.lower()
        if suffix not in allowed:
            raise UploadRejected(
                f"Unsupported file type '{suffix}'. Accepted extensions: {sorted(allowed)}"
            )
        if name.lower() in seen:
            raise UploadRejected(f"Duplicate filename in upload: {name}")
        seen.add(name.lower())
        files.append((name, content))
    if not files:
        raise UploadRejected("No files uploaded.")
    return StagedUploads(Path(data_dir), files)
