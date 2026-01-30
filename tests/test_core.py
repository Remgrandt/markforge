from __future__ import annotations

from PIL import Image

from markforge.core import WatermarkSpec, apply_text_watermark


def test_apply_text_watermark_smoke():
    im = Image.new("RGB", (256, 256), (255, 255, 255))
    spec = WatermarkSpec(text="TEST", opacity=0.2, tile=False, center=True, angle_deg=0)
    out = apply_text_watermark(im, spec)
    assert out.size == (256, 256)
    assert out.mode == "RGBA"
