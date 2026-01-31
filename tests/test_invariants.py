from __future__ import annotations

from PIL import Image

from markforge.core import WatermarkSpec, apply_text_watermark

from .utils import count_changed_pixels


def test_invariant_size_and_mode_unchanged():
    im = Image.new("RGB", (128, 64), (255, 255, 255))
    spec = WatermarkSpec(text="X", tile=True, opacity=0.2)
    out = apply_text_watermark(im, spec)
    assert out.size == im.size
    assert out.mode == "RGBA"


def test_invariant_opacity_zero_no_rgb_change():
    """Opacity=0 should not change visible RGB pixels."""
    im = Image.new("RGB", (64, 64), (10, 20, 30))
    out = apply_text_watermark(im, WatermarkSpec(text="TEST", opacity=0.0, tile=True))
    assert out.convert("RGB").tobytes() == im.tobytes()


def test_invariant_some_pixels_change_when_opacity_nonzero():
    im = Image.new("RGB", (128, 128), (255, 255, 255))
    out = apply_text_watermark(im, WatermarkSpec(text="TEST", opacity=0.25, tile=False, center=True, angle_deg=0))
    changed = count_changed_pixels(im, out, threshold=1)
    assert changed > 0
