from __future__ import annotations

import pytest
from PIL import Image

from markforge.core import WatermarkSpec, apply_text_watermark

from .utils import assert_images_fuzzy_equal, asset_path


@pytest.mark.parametrize(
    ("input_name", "expected_name", "spec"),
    [
        (
            "input_white_128.bmp",
            "expected_golden_white_128.bmp",
            WatermarkSpec(
                text="MARKFORGE",
                opacity=0.18,
                angle_deg=-30.0,
                fill="#0A3D91",
                font_path=None,
                font_size=64,
                tile=True,
                padding=20,
                center=False,
                scale=0.25,
            ),
        ),
        (
            "input_magenta_256.png",
            "expected_golden_magenta_256.png",
            WatermarkSpec(
                text="MARKFORGE",
                opacity=0.18,
                angle_deg=-30.0,
                fill="#0A3D91",
                font_path=None,
                font_size=56,
                tile=True,
                padding=110,
                center=False,
                scale=None,
            ),
        ),
        (
            "input_black_512.jpg",
            "expected_golden_black_512.jpg",
            WatermarkSpec(
                text="MARKFORGE",
                opacity=0.18,
                angle_deg=-30.0,
                fill="#0A3D91",
                font_path=None,
                font_size=56,
                tile=True,
                padding=110,
                center=False,
                scale=None,
            ),
        ),
    ],
)
def test_golden_fuzzy(input_name: str, expected_name: str, spec: WatermarkSpec):
    input_path = asset_path(input_name)
    expected_path = asset_path(expected_name)
    font_path = asset_path("fonts", "DejaVuSans.ttf")

    im = Image.open(input_path)
    expected = Image.open(expected_path)

    if font_path.exists():
        spec = WatermarkSpec(**{**spec.__dict__, "font_path": str(font_path)})

    out = apply_text_watermark(im, spec)

    # Fuzzy tolerances to absorb minor Pillow/platform drift.
    assert_images_fuzzy_equal(out, expected, max_abs=40, rms=2.5, mean_abs=0.8)
