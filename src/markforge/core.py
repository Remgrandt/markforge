from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFont


@dataclass(frozen=True)
class WatermarkSpec:
    text: str
    opacity: float = 0.15  # 0..1
    angle_deg: float = -30.0
    fill: str = "#0A3D91"  # supports hex or CSS-like colors (Pillow ImageColor)
    font_path: str | None = None
    font_size: int = 64
    tile: bool = True
    padding: int = 100
    offset_x: int = 0
    offset_y: int = 0
    center: bool = False
    scale: float | None = None  # if set, overrides font_size based on image min dimension
    blend_mode: Literal["normal", "multiply", "overlay", "soft_light"] = "normal"
    antialias: bool = True


class MarkforgeError(RuntimeError):
    pass


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _load_font(font_path: str | None, font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path:
        return ImageFont.truetype(font_path, font_size)
    # Pillow's default font is tiny; use a basic fallback if truetype not provided.
    # Many environments have DejaVuSans available; try it, else fallback.
    try:
        return ImageFont.truetype("DejaVuSans.ttf", font_size)
    except Exception:
        return ImageFont.load_default()


def apply_text_watermark(
    img: Image.Image,
    spec: WatermarkSpec,
) -> Image.Image:
    if not spec.text:
        raise MarkforgeError("Text watermark cannot be empty.")

    opacity = _clamp01(spec.opacity)

    base = img.convert("RGBA")
    w, h = base.size

    # Determine font size from scale if requested.
    font_size = spec.font_size
    if spec.scale is not None:
        # scale is fraction of min dimension that text height roughly occupies
        # we approximate by mapping to font size directly and then adjust in loop.
        target = int(min(w, h) * float(spec.scale))
        font_size = max(8, target)

    font = _load_font(spec.font_path, font_size)
    color = ImageColor.getrgb(spec.fill)

    # Render text to its own transparent layer so we can rotate with alpha.
    # Use a generous canvas around the text to avoid clipping after rotation.
    dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    ddraw = ImageDraw.Draw(dummy)
    bbox = ddraw.textbbox((0, 0), spec.text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pad = max(10, int(min(w, h) * 0.02))
    canvas_w = text_w + pad * 2
    canvas_h = text_h + pad * 2

    text_layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(text_layer)
    draw.text((pad, pad), spec.text, font=font, fill=(color[0], color[1], color[2], int(255 * opacity)))

    resample = Image.BICUBIC if spec.antialias else Image.NEAREST
    rotated = text_layer.rotate(spec.angle_deg, expand=True, resample=resample)

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    offset_x = int(spec.offset_x)
    offset_y = int(spec.offset_y)

    if spec.center and not spec.tile:
        # Center single watermark
        rx, ry = rotated.size
        x = (w - rx) // 2 + offset_x
        y = (h - ry) // 2 + offset_y
        overlay.alpha_composite(rotated, dest=(x, y))
    else:
        # Tile or single at 0,0 with padding
        rx, ry = rotated.size
        step_x = max(1, rx + spec.padding)
        step_y = max(1, ry + spec.padding)

        # Start slightly negative to cover edges after rotation
        start_x = -rx + offset_x
        start_y = -ry + offset_y
        end_x = w + rx
        end_y = h + ry

        if spec.tile:
            y = start_y
            while y < end_y:
                x = start_x
                while x < end_x:
                    overlay.alpha_composite(rotated, dest=(x, y))
                    x += step_x
                y += step_y
        else:
            overlay.alpha_composite(rotated, dest=(0 + offset_x, 0 + offset_y))

    if spec.blend_mode == "normal":
        return Image.alpha_composite(base, overlay)

    base_rgb = base.convert("RGB")
    overlay_rgb = overlay.convert("RGB")
    if spec.blend_mode == "multiply":
        blended = ImageChops.multiply(base_rgb, overlay_rgb)
    elif spec.blend_mode == "overlay":
        blended = ImageChops.overlay(base_rgb, overlay_rgb)
    elif spec.blend_mode == "soft_light":
        blended = ImageChops.soft_light(base_rgb, overlay_rgb)
    else:
        blended = base_rgb

    mask = overlay.split()[-1]
    mixed = Image.composite(blended, base_rgb, mask)
    alpha = base.split()[-1]
    return Image.merge("RGBA", (*mixed.split(), alpha))


def watermark_file(
    input_path: str | Path,
    output_path: str | Path,
    spec: WatermarkSpec,
) -> None:
    input_path = Path(input_path)
    output_path = Path(output_path)

    with Image.open(input_path) as im:
        result = apply_text_watermark(im, spec)
        # Preserve original format if possible; default to PNG if output suffix unknown
        fmt = (output_path.suffix or input_path.suffix).lstrip(".").upper()
        if fmt in {"JPG"}:
            fmt = "JPEG"
        if fmt not in {"PNG", "JPEG", "WEBP", "TIFF", "BMP"}:
            fmt = "PNG"

        # If saving to JPEG, must flatten alpha
        if fmt == "JPEG":
            flattened = Image.new("RGB", result.size, (255, 255, 255))
            flattened.paste(result, mask=result.split()[-1])
            flattened.save(output_path, format=fmt, quality=95)
        else:
            result.save(output_path, format=fmt)
