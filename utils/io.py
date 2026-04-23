"""Atomic filesystem helpers.

Atomic writes protect against half-written config files if the process crashes
or the disk fills up mid-write — very important because the Settings UI
rewrites these files on every save.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Write ``content`` to ``path`` atomically (same-directory tmp + rename).

    The rename is POSIX-atomic on the same filesystem, so readers either see
    the old file or the fully-written new one — never a partial state.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the tmp file in the same directory so os.replace() is an atomic rename.
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup; swallow inner errors so the caller sees the original.
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def read_text_or_default(path: Path, default: str, encoding: str = "utf-8") -> str:
    """Read ``path`` as text, or return ``default`` if it doesn't exist yet."""
    try:
        return path.read_text(encoding=encoding)
    except FileNotFoundError:
        return default


__all__ = ["atomic_write_text", "read_text_or_default"]
