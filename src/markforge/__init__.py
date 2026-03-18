from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

__all__ = ["__version__"]


def _read_local_version() -> str | None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        content = pyproject.read_text(encoding="utf-8")
    except OSError:
        return None

    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', content, flags=re.MULTILINE)
    return match.group(1) if match else None


def _resolve_version() -> str:
    try:
        return version("markforge")
    except PackageNotFoundError:  # pragma: no cover - only hits when running without installed metadata.
        return _read_local_version() or "0.0.0"


try:
    __version__ = _resolve_version()
except Exception:  # pragma: no cover - version lookup must never break imports.
    __version__ = _read_local_version() or "0.0.0"
