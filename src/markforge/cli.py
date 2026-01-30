from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .core import WatermarkSpec, watermark_file

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="markforge: stamp images with text watermarks (CLI-first, GUI-ready).",
)


@app.command("watermark")
def watermark_cmd(
    input_path: Path = typer.Argument(..., exists=True, readable=True, dir_okay=False, help="Input image file."),
    output_path: Path = typer.Argument(..., writable=True, dir_okay=False, help="Output image file."),
    text: str = typer.Option("markforge", "--text", "-t", help="Watermark text."),
    opacity: float = typer.Option(0.15, min=0.0, max=1.0, help="Text opacity (0..1)."),
    angle: float = typer.Option(-30.0, "--angle", help="Rotation angle in degrees."),
    fill: str = typer.Option("#0A3D91", "--fill", help="Text color (e.g. '#ffffff', 'white')."),
    font_path: Optional[Path] = typer.Option(None, "--font", exists=True, dir_okay=False, help="Path to .ttf/.otf font."),
    font_size: int = typer.Option(64, "--font-size", min=8, max=4096, help="Font size (ignored if --scale is set)."),
    scale: Optional[float] = typer.Option(None, "--scale", min=0.01, max=2.0, help="Auto font sizing as fraction of min(image_dim)."),
    tile: bool = typer.Option(True, "--tile/--no-tile", help="Tile the watermark across the image."),
    padding: int = typer.Option(100, "--padding", min=0, max=10000, help="Padding between tiles (px)."),
    center: bool = typer.Option(False, "--center", help="Center a single watermark (use with --no-tile)."),
    offset: str = typer.Option("0,0", "--offset", help="Offset in pixels as 'x,y'."),
    blend: str = typer.Option("normal", "--blend", help="Blend mode: normal, multiply, overlay, soft_light."),
    antialias: bool = typer.Option(True, "--antialias/--no-antialias", help="Smooth rotated text."),
) -> None:
    """Apply a text watermark to an image."""
    offset_parts = [p for p in offset.replace(" ", ",").split(",") if p]
    if len(offset_parts) != 2:
        raise typer.BadParameter("Offset must be two numbers like '12,-8'.")
    try:
        offset_x = int(float(offset_parts[0]))
        offset_y = int(float(offset_parts[1]))
    except ValueError as exc:
        raise typer.BadParameter("Offset must be numeric like '12,-8'.") from exc

    spec = WatermarkSpec(
        text=text,
        opacity=opacity,
        angle_deg=angle,
        fill=fill,
        font_path=str(font_path) if font_path else None,
        font_size=font_size,
        scale=scale,
        tile=tile,
        padding=padding,
        center=center,
        offset_x=offset_x,
        offset_y=offset_y,
        blend_mode=blend,
        antialias=antialias,
    )
    watermark_file(input_path, output_path, spec)
    typer.echo(str(output_path))


@app.command("version")
def version_cmd() -> None:
    """Print version."""
    from . import __version__

    typer.echo(__version__)


@app.command("gui")
def gui_cmd(
    host: str = typer.Option("127.0.0.1", help="Bind host for the GUI server."),
    port: int = typer.Option(0, help="Bind port (0 picks a free port)."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open a browser tab."),
    html: Optional[Path] = typer.Option(None, "--html", help="Path to a custom HTML file."),
) -> None:
    """Launch the GUI server."""
    from . import gui

    gui.run(host=host, port=port, open_browser=open_browser, html=html)
