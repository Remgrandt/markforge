from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from markforge.core import MarkforgeError, WatermarkSpec, apply_text_watermark, watermark_file

from .utils import asset_path, count_changed_pixels


def _font_path() -> str | None:
    font_path = asset_path("fonts", "DejaVuSans.ttf")
    return str(font_path) if font_path.exists() else None


def test_apply_text_watermark_smoke() -> None:
    im = Image.new("RGB", (256, 256), (255, 255, 255))
    spec = WatermarkSpec(text="TEST", opacity=0.2, tile=False, center=True, angle_deg=0)
    out = apply_text_watermark(im, spec)
    assert out.size == (256, 256)
    assert out.mode == "RGBA"


def test_apply_text_watermark_rejects_empty_text() -> None:
    im = Image.new("RGB", (64, 64), (255, 255, 255))
    with pytest.raises(MarkforgeError, match="cannot be empty"):
        apply_text_watermark(im, WatermarkSpec(text=""))


def test_apply_text_watermark_single_top_left_branch_changes_pixels() -> None:
    im = Image.new("RGB", (128, 128), (255, 255, 255))
    spec = WatermarkSpec(
        text="TEST",
        opacity=0.25,
        tile=False,
        center=False,
        angle_deg=0,
        font_path=_font_path(),
    )
    out = apply_text_watermark(im, spec)
    changed = count_changed_pixels(im, out, threshold=1)
    assert changed > 0


@pytest.mark.parametrize("blend_mode", ["multiply", "overlay", "soft_light"])
def test_apply_text_watermark_blend_modes_change_pixels(blend_mode: str) -> None:
    im = Image.new("RGB", (160, 160), (180, 180, 180))
    spec = WatermarkSpec(
        text="TEST",
        opacity=0.8,
        tile=False,
        center=True,
        angle_deg=0,
        fill="#ff0000",
        blend_mode=blend_mode,
        font_path=_font_path(),
    )
    out = apply_text_watermark(im, spec)
    changed = count_changed_pixels(im, out, threshold=1)
    assert changed > 0


def test_apply_text_watermark_rejects_invalid_blend_mode() -> None:
    im = Image.new("RGB", (64, 64), (255, 255, 255))
    with pytest.raises(MarkforgeError, match="Unsupported blend mode"):
        apply_text_watermark(im, WatermarkSpec(text="TEST", blend_mode="bogus"))  # type: ignore[arg-type]


def test_watermark_file_saves_jpeg_and_defaults_unknown_suffix_to_png(tmp_path: Path) -> None:
    source = tmp_path / "input.png"
    Image.new("RGBA", (80, 80), (255, 255, 255, 255)).save(source, format="PNG")

    jpg_output = tmp_path / "output.jpg"
    watermark_file(
        source,
        jpg_output,
        WatermarkSpec(text="JPEG", tile=False, center=True, angle_deg=0, font_path=_font_path()),
    )
    with Image.open(jpg_output) as im:
        assert im.format == "JPEG"
        assert im.mode == "RGB"

    unknown_output = tmp_path / "output.unknown"
    watermark_file(
        source,
        unknown_output,
        WatermarkSpec(text="PNG", tile=False, center=True, angle_deg=0, font_path=_font_path()),
    )
    with Image.open(unknown_output) as im:
        assert im.format == "PNG"
