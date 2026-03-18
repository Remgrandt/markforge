from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from markforge.cli import app

from .utils import asset_path, repo_root

runner = CliRunner()


def _project_version() -> str:
    content = (repo_root() / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', content, flags=re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_cli_watermark_writes_output(tmp_path: Path) -> None:
    inp = asset_path("input_magenta_256.png")
    outp = tmp_path / "out.png"

    result = runner.invoke(
        app,
        [
            "watermark",
            str(inp),
            str(outp),
            "--text",
            "CLI TEST",
            "--opacity",
            "0.2",
            "--angle",
            "0",
            "--no-tile",
            "--center",
            "--font",
            str(asset_path("fonts", "DejaVuSans.ttf")),
            "--font-size",
            "48",
        ],
    )
    assert result.exit_code == 0, (result.stdout or "") + (result.stderr or "")
    assert outp.exists()
    with Image.open(outp) as im:
        assert im.size == (256, 256)


def test_cli_rejects_invalid_blend(tmp_path: Path) -> None:
    inp = asset_path("input_magenta_256.png")
    outp = tmp_path / "out.png"

    result = runner.invoke(
        app,
        [
            "watermark",
            str(inp),
            str(outp),
            "--blend",
            "bogus",
        ],
    )

    assert result.exit_code != 0
    assert "Unsupported blend mode" in (result.stderr or result.output)
    assert not outp.exists()


def test_cli_version_matches_project_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == _project_version()


def test_source_version_fallback_matches_project_version(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata as metadata

    def fake_version(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(metadata, "version", fake_version)

    module_path = repo_root() / "src" / "markforge" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_markforge_version_fallback", module_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.__version__ == _project_version()


def test_python_m_markforge_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "markforge", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Usage: python -m markforge" in result.stdout
