from __future__ import annotations

from pathlib import Path

from PIL import Image
from typer.testing import CliRunner

from markforge.cli import app
from .utils import asset_path


runner = CliRunner()


def test_cli_watermark_writes_output(tmp_path: Path):
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
