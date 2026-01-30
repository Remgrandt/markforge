from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__ = version("markforge")
except PackageNotFoundError:  # pragma: no cover - only hits when running without installed metadata.
    __version__ = "0.0.0"
