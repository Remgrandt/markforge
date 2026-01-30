![Markforge banner](https://raw.githubusercontent.com/remgrandt/markforge/main/assets/logo.webp)

[![CI](https://github.com/remgrandt/markforge/actions/workflows/ci.yml/badge.svg)](https://github.com/remgrandt/markforge/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/markforge.svg)](https://pypi.org/project/markforge/)
[![Python](https://img.shields.io/pypi/pyversions/markforge.svg)](https://pypi.org/project/markforge/)

# Markforge

Markforge is a small, sharp tool for stamping images with text watermarks. It is CLI-first
and ships with a local GUI for batch workflows.

## Features

- Tiled or centered marks
- Opacity, angle, padding, offset, and blend modes
- Auto-scale text to the image or set a fixed font size
- Local GUI with live preview, system fonts, and batch export
- Output format inferred from extension (PNG/JPEG/WEBP/TIFF/BMP)

## Requirements

- Python 3.10+ (tested on 3.10-3.13)

## Install

```bash
pip install markforge
```

For development:

```bash
pip install -e ".[dev]"
```

## Quickstart (CLI)

Stamp a tiled watermark:

```bash
markforge watermark input.jpg output.jpg --text "DRAFT" --opacity 0.15 --angle -30 --tile
```

Or a single centered mark:

```bash
markforge watermark input.jpg output.jpg --text "DRAFT" --center --no-tile --scale 0.35
```

Show full help:

```bash
markforge --help
markforge watermark --help
```

Common options:

- `--text/-t` watermark text (required for useful output)
- `--opacity` in the 0..1 range
- `--angle` rotation in degrees
- `--fill` color (hex or named, via Pillow ImageColor)
- `--font` path to a .ttf/.otf font
- `--font-size` fixed point size
- `--scale` auto size as a fraction of the smaller image dimension (overrides `--font-size`)
- `--tile/--no-tile` and `--padding` spacing between tiles
- `--center` center a single watermark (use with `--no-tile`)
- `--offset` pixel offset as `x,y`
- `--blend` one of `normal`, `multiply`, `overlay`, `soft_light`
- `--antialias/--no-antialias` for rotated text smoothing

Notes:

- Output format is inferred from the output extension. Unknown extensions default to PNG.
- JPEG output is flattened to white because JPEG does not support alpha.
- If no font is provided, Markforge tries `DejaVuSans.ttf` and falls back to Pillow's default.

## GUI

Launch the local GUI (opens a browser tab by default):

```bash
markforge gui
```

Details:

- Binds to `127.0.0.1` by default and chooses a free port.
- Exports default to `./exports` unless you pick a folder or type a path.
- You can serve a custom UI with `--html path/to/index.html`.
- The "Pick" buttons use Tkinter; on minimal Linux installs you may need to add it, or
  use the built-in file picker and manual paths instead.

## Development

```bash
pytest
ruff check .
```

## License

Markforge is free to use and redistribute in unmodified form only. Modification, forking,
and derivative works are not permitted. This is a source-available license. See `LICENSE`
for full terms.
