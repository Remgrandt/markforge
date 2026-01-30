from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import io
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import unquote, urlparse
import uuid
import webbrowser

import typer
from PIL import Image, ImageFont

app = typer.Typer(add_completion=False, no_args_is_help=True)

_FALLBACK_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Markforge GUI</title>
    <style>
      body{font-family:system-ui,Segoe UI,Arial,sans-serif;background:#0b0d12;color:#fff;padding:24px}
      .card{max-width:720px;margin:0 auto;padding:18px;border-radius:14px;border:1px solid #2a2f3a;background:#121521}
      code{color:#9ac4ff}
    </style>
  </head>
  <body>
    <div class="card">
      <h1>Markforge GUI</h1>
      <p>Missing <code>static/index.html</code>. Pass <code>--html</code> to use another file.</p>
    </div>
  </body>
</html>
"""


@dataclass
class FileItem:
    id: str
    name: str
    path: Path
    size: int
    width: int
    height: int
    is_temp: bool = False
    preview_path: Path | None = None


@dataclass
class GuiState:
    temp_dir: Path
    files: list[FileItem] = field(default_factory=list)
    selected_id: str | None = None
    fonts: dict[str, Path] = field(default_factory=dict)
    system_fonts: list[dict[str, str]] = field(default_factory=list)
    system_font_map: dict[str, Path] = field(default_factory=dict)
    last_output_dir: Path | None = None
    html_bytes: bytes = b""


@dataclass
class _FormFile:
    filename: str
    file: io.BytesIO
    content_type: str | None = None


def _static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


def _load_html(path: Path | None) -> bytes:
    if path is None:
        path = _static_dir() / "index.html"
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return _FALLBACK_HTML.encode("utf-8")


def _font_display_name(path: Path) -> str:
    try:
        font = ImageFont.truetype(str(path))
        family, style = font.getname()
        family = (family or "").strip()
        style = (style or "").strip()
        if family:
            if style and style.lower() not in {"regular", "normal", "roman", "book"}:
                return f"{family} {style}"
            return family
    except Exception:
        pass
    name = path.stem.replace("_", " ").replace("-", " ").strip()
    return name or path.name


def _list_system_fonts() -> list[dict[str, str]]:
    font_dirs: list[Path] = []
    home = Path.home()
    if sys.platform.startswith("win"):
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        font_dirs.extend([windir / "Fonts", home / "AppData/Local/Microsoft/Windows/Fonts"])
    elif sys.platform == "darwin":
        font_dirs.extend(
            [Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library/Fonts"]
        )
    else:
        font_dirs.extend(
            [
                Path("/usr/share/fonts"),
                Path("/usr/local/share/fonts"),
                home / ".local/share/fonts",
                home / ".fonts",
            ]
        )

    exts = {".ttf", ".otf", ".ttc", ".otc"}
    seen: dict[str, Path] = {}
    for root in font_dirs:
        if not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in exts:
                    continue
                seen.setdefault(str(path), path)
        except (OSError, PermissionError):
            continue

    fonts: list[dict[str, str]] = []
    name_counts: dict[str, int] = {}
    for path in seen.values():
        name = _font_display_name(path)
        name_counts[name] = name_counts.get(name, 0) + 1
        font_id = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]
        fonts.append(
            {
                "id": font_id,
                "name": name,
                "path": str(path),
                "css_family": f"mf-font-{font_id}",
            }
        )

    for item in fonts:
        if name_counts.get(item["name"], 0) > 1:
            item["name"] = f"{item['name']} ({Path(item['path']).name})"

    fonts.sort(key=lambda item: item["name"].lower())
    return fonts


def _pick_default_font(fonts: list[dict[str, str]]) -> dict[str, str] | None:
    if not fonts:
        return None
    if sys.platform.startswith("win"):
        preferred = [
            "segoe ui",
            "segoe ui variable",
            "arial",
            "calibri",
            "tahoma",
        ]
    elif sys.platform == "darwin":
        preferred = [
            "sf pro",
            "sf pro display",
            "sf pro text",
            "san francisco",
            "helvetica neue",
            "helvetica",
        ]
    else:
        preferred = [
            "dejavu sans",
            "noto sans",
            "liberation sans",
            "ubuntu",
            "arial",
        ]

    def is_reasonable(name: str) -> bool:
        lowered = name.lower()
        return not any(tag in lowered for tag in ("bold", "italic", "black", "condensed"))

    for pref in preferred:
        for font in fonts:
            name = font.get("name", "").lower()
            if name == pref or name.startswith(pref):
                if is_reasonable(name):
                    return font
        for font in fonts:
            name = font.get("name", "").lower()
            if name == pref or name.startswith(pref):
                return font
    return fonts[0]


def _send_bytes(handler: BaseHTTPRequestHandler, body: bytes, content_type: str) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_json(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


def _format_file_info(item: FileItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "size": item.size,
        "width": item.width,
        "height": item.height,
    }


def _run_cli_watermark(
    input_path: Path,
    output_path: Path,
    settings: dict[str, Any],
    font_path: Path | None,
) -> None:
    args = [
        sys.executable,
        "-m",
        "markforge",
        "watermark",
        str(input_path),
        str(output_path),
        "--text",
        str(settings.get("text") or ""),
        "--opacity",
        str(settings.get("opacity", 0.15)),
        "--angle",
        str(settings.get("angle", -30.0)),
        "--fill",
        str(settings.get("fill", "#0A3D91")),
        "--font-size",
        str(int(settings.get("font_size", 64))),
        "--padding",
        str(int(settings.get("padding", 100))),
        "--blend",
        str(settings.get("blend", "normal")),
        "--offset",
        f"{int(settings.get('offset_x', 0))},{int(settings.get('offset_y', 0))}",
    ]

    scale = settings.get("scale")
    if scale:
        args += ["--scale", str(scale)]
    if font_path:
        args += ["--font", str(font_path)]
    if settings.get("tile", True):
        args += ["--tile"]
    else:
        args += ["--no-tile"]
    if settings.get("center"):
        args += ["--center"]
    if not settings.get("antialias", True):
        args += ["--no-antialias"]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "CLI failed")


def _pick_files() -> list[Path]:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return []
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", 1)
    paths = filedialog.askopenfilenames(
        title="Select images",
        filetypes=[
            ("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"),
            ("All files", "*.*"),
        ],
    )
    root.destroy()
    return [Path(p) for p in paths]


def _pick_font() -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", 1)
    path = filedialog.askopenfilename(
        title="Select font",
        filetypes=[("Fonts", "*.ttf *.otf"), ("All files", "*.*")],
    )
    root.destroy()
    return Path(path) if path else None


def _pick_directory() -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", 1)
    path = filedialog.askdirectory(title="Select output folder")
    root.destroy()
    return Path(path) if path else None


def _make_handler(state: GuiState):
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib method name
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path in {"/", "/index.html"}:
                _send_bytes(self, state.html_bytes, "text/html; charset=utf-8")
                return
            if path.startswith("/preview/"):
                file_id = path.split("/")[-1]
                item = next((f for f in state.files if f.id == file_id), None)
                if item and item.preview_path and item.preview_path.exists():
                    content_type = mimetypes.guess_type(item.preview_path.name)[0] or "image/png"
                    _send_bytes(self, item.preview_path.read_bytes(), content_type)
                    return
                self.send_error(404, "Preview not found")
                return
            if path.startswith("/font/"):
                font_id = path.split("/")[-1]
                font_path = state.system_font_map.get(font_id)
                if font_path and font_path.exists():
                    content_type = (
                        mimetypes.guess_type(font_path.name)[0] or "application/octet-stream"
                    )
                    _send_bytes(self, font_path.read_bytes(), content_type)
                    return
                self.send_error(404, "Font not found")
                return
            if path.startswith("/source/"):
                file_id = path.split("/")[-1]
                item = next((f for f in state.files if f.id == file_id), None)
                if item and item.path.exists():
                    content_type = mimetypes.guess_type(item.path.name)[0] or "application/octet-stream"
                    _send_bytes(self, item.path.read_bytes(), content_type)
                    return
                self.send_error(404, "Source not found")
                return
            self.send_error(404, "Not Found")

        def do_POST(self) -> None:  # noqa: N802 - stdlib method name
            parsed = urlparse(self.path)
            if parsed.path == "/api/queue":
                _send_json(
                    self,
                    {
                        "files": [_format_file_info(f) for f in state.files],
                        "selected_id": state.selected_id,
                    },
                )
                return
            if parsed.path == "/api/select":
                payload = _read_json(self)
                file_id = payload.get("id")
                if file_id and any(f.id == file_id for f in state.files):
                    state.selected_id = file_id
                    _send_json(self, {"ok": True, "selected_id": state.selected_id})
                else:
                    _send_json(self, {"ok": False, "error": "Unknown file id"}, status=400)
                return
            if parsed.path == "/api/upload":
                self._handle_upload()
                return
            if parsed.path == "/api/upload-font":
                self._handle_font_upload()
                return
            if parsed.path == "/api/pick-files":
                self._handle_pick_files()
                return
            if parsed.path == "/api/pick-font":
                self._handle_pick_font()
                return
            if parsed.path == "/api/pick-output":
                self._handle_pick_output()
                return
            if parsed.path == "/api/preview":
                self._handle_preview()
                return
            if parsed.path == "/api/fonts":
                self._handle_fonts()
                return
            if parsed.path == "/api/forge":
                self._handle_forge()
                return
            if parsed.path == "/api/clear":
                self._handle_clear()
                return
            if parsed.path == "/api/clear-selected":
                self._handle_clear_selected()
                return
            if parsed.path == "/api/open-output":
                self._handle_open_output()
                return
            self.send_error(404, "Not Found")

        def _handle_upload(self) -> None:
            form = self._parse_form()
            if "files" not in form:
                _send_json(self, {"ok": False, "error": "No files uploaded"}, status=400)
                return
            items = form["files"]
            if not isinstance(items, list):
                items = [items]
            for item in items:
                if not getattr(item, "filename", None):
                    continue
                dest, name = self._save_upload(item, state.temp_dir)
                try:
                    with Image.open(dest) as im:
                        width, height = im.size
                except Exception:
                    dest.unlink(missing_ok=True)
                    continue
                file_id = uuid.uuid4().hex
                state.files.append(
                    FileItem(
                        id=file_id,
                        name=name,
                        path=dest,
                        size=dest.stat().st_size,
                        width=width,
                        height=height,
                        is_temp=True,
                    )
                )
                if state.selected_id is None:
                    state.selected_id = file_id
            _send_json(
                self,
                {
                    "ok": True,
                    "files": [_format_file_info(f) for f in state.files],
                    "selected_id": state.selected_id,
                },
            )

        def _handle_font_upload(self) -> None:
            form = self._parse_form()
            if "font" not in form:
                _send_json(self, {"ok": False, "error": "No font uploaded"}, status=400)
                return
            item = form["font"]
            if not item or not getattr(item, "filename", None):
                _send_json(self, {"ok": False, "error": "No font uploaded"}, status=400)
                return
            dest, name = self._save_upload(item, state.temp_dir)
            font_id = uuid.uuid4().hex
            state.fonts[font_id] = dest
            _send_json(self, {"ok": True, "font_id": font_id, "name": name})

        def _handle_pick_files(self) -> None:
            paths = _pick_files()
            added = 0
            for path in paths:
                if not path.exists():
                    continue
                try:
                    with Image.open(path) as im:
                        width, height = im.size
                except Exception:
                    continue
                file_id = uuid.uuid4().hex
                state.files.append(
                    FileItem(
                        id=file_id,
                        name=path.name,
                        path=path,
                        size=path.stat().st_size,
                        width=width,
                        height=height,
                        is_temp=False,
                    )
                )
                if state.selected_id is None:
                    state.selected_id = file_id
                added += 1
            _send_json(
                self,
                {
                    "ok": True,
                    "added": added,
                    "files": [_format_file_info(f) for f in state.files],
                    "selected_id": state.selected_id,
                },
            )

        def _handle_pick_font(self) -> None:
            path = _pick_font()
            if not path:
                _send_json(self, {"ok": False, "error": "No font selected"}, status=400)
                return
            font_id = uuid.uuid4().hex
            state.fonts[font_id] = path
            _send_json(self, {"ok": True, "font_id": font_id, "name": path.name})

        def _handle_pick_output(self) -> None:
            path = _pick_directory()
            if not path:
                _send_json(self, {"ok": False, "error": "No folder selected"}, status=400)
                return
            _send_json(self, {"ok": True, "path": str(path)})

        def _handle_preview(self) -> None:
            payload = _read_json(self)
            file_id = payload.get("id") or state.selected_id
            settings = payload.get("settings") or {}
            item = next((f for f in state.files if f.id == file_id), None)
            if not item:
                _send_json(self, {"ok": False, "error": "No file selected"}, status=400)
                return
            preview_path = state.temp_dir / f"preview_{item.id}.png"
            font_path = self._resolve_font_path(settings)
            try:
                _run_cli_watermark(item.path, preview_path, settings, font_path)
            except RuntimeError as exc:
                _send_json(self, {"ok": False, "error": str(exc)}, status=500)
                return
            item.preview_path = preview_path
            _send_json(self, {"ok": True, "preview_url": f"/preview/{item.id}"})

        def _handle_forge(self) -> None:
            payload = _read_json(self)
            settings = payload.get("settings") or {}
            apply_all = bool(payload.get("apply_all"))
            naming = str(payload.get("naming") or "append_wm")
            fmt = str(payload.get("format") or "auto").lower()
            keep_originals = bool(payload.get("keep_originals", True))
            output_dir = str(payload.get("output_dir") or "").strip()
            font_path = self._resolve_font_path(settings)

            if apply_all:
                targets = list(state.files)
            else:
                targets = [f for f in state.files if f.id == state.selected_id]
            if not targets:
                _send_json(self, {"ok": False, "error": "No files to forge"}, status=400)
                return

            outputs: list[str] = []
            for item in targets:
                in_path = item.path
                if output_dir:
                    out_dir = Path(output_dir).expanduser()
                else:
                    out_dir = Path.cwd() / "exports"
                if not out_dir.is_absolute():
                    out_dir = Path.cwd() / out_dir
                if keep_originals or not out_dir.exists():
                    out_dir.mkdir(parents=True, exist_ok=True)
                suffix = in_path.suffix
                if fmt in {"png", "jpg", "jpeg", "webp"}:
                    suffix = f".{fmt.replace('jpeg', 'jpg')}"
                stem = in_path.stem
                if naming == "overwrite" and not keep_originals:
                    out_name = f"{stem}{suffix}"
                elif naming == "append_markforge":
                    out_name = f"{stem}_MARKFORGE{suffix}"
                else:
                    out_name = f"{stem}_wm{suffix}"
                out_path = out_dir / out_name
                try:
                    _run_cli_watermark(in_path, out_path, settings, font_path)
                except RuntimeError as exc:
                    _send_json(self, {"ok": False, "error": str(exc)}, status=500)
                    return
                outputs.append(str(out_path))
                state.last_output_dir = out_dir

            _send_json(
                self,
                {
                    "ok": True,
                    "outputs": outputs,
                    "output_dir": str(state.last_output_dir) if state.last_output_dir else "",
                },
            )

        def _handle_clear(self) -> None:
            for item in state.files:
                if item.is_temp:
                    try:
                        item.path.unlink()
                    except FileNotFoundError:
                        pass
                if item.preview_path and item.preview_path.exists():
                    item.preview_path.unlink(missing_ok=True)
            state.files.clear()
            state.selected_id = None
            _send_json(self, {"ok": True})

        def _handle_clear_selected(self) -> None:
            if not state.selected_id:
                _send_json(self, {"ok": False, "error": "No file selected"}, status=400)
                return
            idx = next((i for i, f in enumerate(state.files) if f.id == state.selected_id), None)
            if idx is None:
                _send_json(self, {"ok": False, "error": "No file selected"}, status=400)
                return
            item = state.files.pop(idx)
            if item.is_temp:
                try:
                    item.path.unlink()
                except FileNotFoundError:
                    pass
            if item.preview_path and item.preview_path.exists():
                item.preview_path.unlink(missing_ok=True)
            if state.files:
                next_idx = min(idx, len(state.files) - 1)
                state.selected_id = state.files[next_idx].id
            else:
                state.selected_id = None
            _send_json(
                self,
                {
                    "ok": True,
                    "files": [_format_file_info(f) for f in state.files],
                    "selected_id": state.selected_id,
                },
            )

        def _handle_open_output(self) -> None:
            if state.last_output_dir and state.last_output_dir.exists():
                try:
                    os.startfile(state.last_output_dir)  # type: ignore[attr-defined]
                except Exception:
                    webbrowser.open(state.last_output_dir.as_uri())
                _send_json(self, {"ok": True})
                return
            _send_json(self, {"ok": False, "error": "No output folder yet"}, status=400)

        def _parse_form(self):  # type: ignore[no-untyped-def]
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                return {}

            boundary = None
            for part in content_type.split(";"):
                part = part.strip()
                if part.startswith("boundary="):
                    boundary = part.split("=", 1)[1].strip()
                    if boundary.startswith('"') and boundary.endswith('"'):
                        boundary = boundary[1:-1]
                    break
            if not boundary:
                return {}

            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return {}
            body = self.rfile.read(length)

            boundary_bytes = b"--" + boundary.encode("utf-8")
            parts = body.split(boundary_bytes)
            form: dict[str, object] = {}

            for part in parts:
                if not part:
                    continue
                if part.startswith(b"--"):
                    continue
                if part.startswith(b"\r\n"):
                    part = part[2:]
                if part.endswith(b"\r\n"):
                    part = part[:-2]
                if not part:
                    continue

                header_block, sep, data = part.partition(b"\r\n\r\n")
                if not sep:
                    continue
                headers: dict[str, str] = {}
                for line in header_block.split(b"\r\n"):
                    if b":" not in line:
                        continue
                    key, value = line.split(b":", 1)
                    headers[key.decode("utf-8").strip().lower()] = value.decode("utf-8").strip()

                disposition = headers.get("content-disposition", "")
                if not disposition:
                    continue
                name = None
                filename = None
                segments = [seg.strip() for seg in disposition.split(";")]
                for segment in segments[1:]:
                    if "=" not in segment:
                        continue
                    key, value = segment.split("=", 1)
                    key = key.strip().lower()
                    value = value.strip()
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    if key == "name":
                        name = value
                    elif key == "filename":
                        filename = value

                if not name:
                    continue

                if filename is not None:
                    item = _FormFile(
                        filename=filename,
                        file=io.BytesIO(data),
                        content_type=headers.get("content-type"),
                    )
                    existing = form.get(name)
                    if existing is None:
                        form[name] = item
                    elif isinstance(existing, list):
                        existing.append(item)
                    else:
                        form[name] = [existing, item]
                else:
                    value = data.decode("utf-8", errors="replace")
                    existing = form.get(name)
                    if existing is None:
                        form[name] = value
                    elif isinstance(existing, list):
                        existing.append(value)
                    else:
                        form[name] = [existing, value]

            return form

        def _save_upload(self, item, dest_dir: Path) -> tuple[Path, str]:  # type: ignore[no-untyped-def]
            name = Path(item.filename).name
            suffix = Path(name).suffix
            dest = dest_dir / f"{uuid.uuid4().hex}{suffix}"
            with dest.open("wb") as fh:
                fh.write(item.file.read())
            return dest, name

        def _resolve_font_path(self, settings: dict[str, Any]) -> Path | None:
            font_id = settings.get("font_id")
            if font_id and font_id in state.fonts:
                return state.fonts[font_id]
            font_path = settings.get("font_path")
            return Path(font_path) if font_path else None

        def _handle_fonts(self) -> None:
            if not state.system_fonts:
                state.system_fonts = _list_system_fonts()
            if not state.system_font_map:
                state.system_font_map = {
                    font["id"]: Path(font["path"]) for font in state.system_fonts
                }
            default_font = _pick_default_font(state.system_fonts)
            _send_json(
                self,
                {
                    "ok": True,
                    "fonts": state.system_fonts,
                    "default_font": default_font,
                },
            )

        def log_message(self, _format: str, *_args: object) -> None:  # noqa: D401
            return

    return _Handler


@app.command()
def run(
    host: str = typer.Option("127.0.0.1", help="Bind host for the GUI server."),
    port: int = typer.Option(0, help="Bind port (0 picks a free port)."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open a browser tab."),
    html: Path | None = typer.Option(None, "--html", help="Path to a custom HTML file."),
) -> None:
    """Launch the GUI by serving the static UI and API endpoints."""
    temp_dir = Path(tempfile.mkdtemp(prefix="markforge_gui_"))
    state = GuiState(temp_dir=temp_dir, html_bytes=_load_html(html))
    handler = _make_handler(state)
    with ThreadingHTTPServer((host, port), handler) as server:
        bind_host, bind_port = server.server_address[:2]
        show_host = "127.0.0.1" if bind_host in {"0.0.0.0", "::"} else bind_host
        url = f"http://{show_host}:{bind_port}/"
        typer.echo(f"Markforge GUI running at {url}")
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main() -> None:
    app()


if __name__ == "__main__":
    main()
