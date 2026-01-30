from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageStat


@dataclass(frozen=True)
class ImageDiffStats:
    rms: float
    mean_abs: float
    max_abs: int


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def asset_path(*parts: str) -> Path:
    return repo_root() / "tests" / "assets" / Path(*parts)


def diff_stats(a: Image.Image, b: Image.Image) -> ImageDiffStats:
    """Compute numeric diff stats between two images (RGBA)."""
    a_rgba = a.convert("RGBA")
    b_rgba = b.convert("RGBA")
    if a_rgba.size != b_rgba.size:
        raise ValueError(f"Image sizes differ: {a_rgba.size} vs {b_rgba.size}")

    diff = ImageChops.difference(a_rgba, b_rgba)
    stat = ImageStat.Stat(diff)

    rms_channels = stat.rms  # per-channel
    rms = (sum(c * c for c in rms_channels) / len(rms_channels)) ** 0.5

    mean_channels = stat.mean
    mean_abs = sum(mean_channels) / len(mean_channels)

    extrema = diff.getextrema()  # (min,max) per channel
    max_abs = max(mx for (_mn, mx) in extrema)

    return ImageDiffStats(rms=rms, mean_abs=mean_abs, max_abs=max_abs)


def assert_images_fuzzy_equal(
    a: Image.Image,
    b: Image.Image,
    *,
    max_abs: int,
    rms: float,
    mean_abs: float,
) -> None:
    stats = diff_stats(a, b)
    if stats.max_abs > max_abs or stats.rms > rms or stats.mean_abs > mean_abs:
        raise AssertionError(
            "Images differ beyond tolerance. "
            f"Got max_abs={stats.max_abs}, rms={stats.rms:.3f}, mean_abs={stats.mean_abs:.3f}; "
            f"limits max_abs<={max_abs}, rms<={rms}, mean_abs<={mean_abs}"
        )


def count_changed_pixels(a: Image.Image, b: Image.Image, *, threshold: int = 1) -> int:
    """Count pixels where any channel differs by at least threshold."""
    a_rgba = a.convert("RGBA")
    b_rgba = b.convert("RGBA")
    diff = ImageChops.difference(a_rgba, b_rgba)
    gray = diff.convert("L")
    hist = gray.histogram()
    return sum(hist[threshold:])
