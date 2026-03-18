from __future__ import annotations

import io
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError

import pytest
from PIL import Image

from markforge import gui

from .utils import asset_path


def _start_server(state: gui.GuiState) -> tuple[ThreadingHTTPServer, str]:
    handler = gui._make_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


def _stop_server(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()


def _make_png_bytes(color: tuple[int, int, int, int]) -> bytes:
    img = Image.new("RGBA", (2, 2), color)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _write_png(path: Path, color: tuple[int, int, int, int]) -> Path:
    path.write_bytes(_make_png_bytes(color))
    return path


def _file_item(path: Path, *, file_id: str) -> gui.FileItem:
    with Image.open(path) as im:
        width, height = im.size
    return gui.FileItem(
        id=file_id,
        name=path.name,
        path=path,
        size=path.stat().st_size,
        width=width,
        height=height,
        is_temp=False,
    )


def _post_json(url: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _post_multipart(
    url: str,
    files: list[tuple[str, str, bytes, str]],
) -> tuple[int, dict[str, object]]:
    boundary = "----markforgeboundary"
    parts: list[bytes] = []
    for name, filename, content, content_type in files:
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        parts.append(content)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _get_bytes(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url) as response:
        return response.status, response.read()


def test_gui_upload_and_source(tmp_path: Path) -> None:
    state = gui.GuiState(temp_dir=tmp_path, html_bytes=b"")
    server, base = _start_server(state)
    try:
        png = _make_png_bytes((255, 0, 0, 255))
        status, payload = _post_multipart(
            f"{base}/api/upload",
            [("files", "test.png", png, "image/png")],
        )
        assert status == 200
        assert payload["ok"] is True
        files = payload["files"]
        assert isinstance(files, list) and len(files) == 1
        file_id = files[0]["id"]

        status, body = _get_bytes(f"{base}/source/{file_id}")
        assert status == 200
        assert body == png
    finally:
        _stop_server(server)


def test_gui_queue_and_select(tmp_path: Path) -> None:
    state = gui.GuiState(temp_dir=tmp_path, html_bytes=b"")
    server, base = _start_server(state)
    try:
        png1 = _make_png_bytes((255, 0, 0, 255))
        png2 = _make_png_bytes((0, 0, 255, 255))
        _status, uploaded = _post_multipart(
            f"{base}/api/upload",
            [
                ("files", "one.png", png1, "image/png"),
                ("files", "two.png", png2, "image/png"),
            ],
        )
        assert uploaded["ok"] is True
        second_id = uploaded["files"][1]["id"]

        _status, queued = _post_json(f"{base}/api/queue", {})
        assert len(queued["files"]) == 2
        assert queued["selected_id"] == uploaded["selected_id"]

        _status, selected = _post_json(f"{base}/api/select", {"id": second_id})
        assert selected["ok"] is True
        assert selected["selected_id"] == second_id

        with pytest.raises(HTTPError) as excinfo:
            _post_json(f"{base}/api/select", {"id": "missing"})
        assert excinfo.value.code == 400
    finally:
        _stop_server(server)


def test_gui_clear_selected_updates_selection(tmp_path: Path) -> None:
    state = gui.GuiState(temp_dir=tmp_path, html_bytes=b"")
    server, base = _start_server(state)
    try:
        png1 = _make_png_bytes((0, 255, 0, 255))
        png2 = _make_png_bytes((0, 0, 255, 255))
        _status, payload = _post_multipart(
            f"{base}/api/upload",
            [
                ("files", "one.png", png1, "image/png"),
                ("files", "two.png", png2, "image/png"),
            ],
        )
        assert payload["ok"] is True
        assert len(payload["files"]) == 2

        _status, cleared = _post_json(f"{base}/api/clear-selected", {})
        assert cleared["ok"] is True
        remaining = cleared["files"]
        assert isinstance(remaining, list) and len(remaining) == 1
        assert cleared["selected_id"] == remaining[0]["id"]

        _post_json(f"{base}/api/clear", {})
        with pytest.raises(HTTPError) as excinfo:
            _post_json(f"{base}/api/clear-selected", {})
        assert excinfo.value.code == 400
    finally:
        _stop_server(server)


def test_gui_fonts_and_font_file(tmp_path: Path) -> None:
    font_path = tmp_path / "TestFont.ttf"
    font_bytes = b"dummy-font-data"
    font_path.write_bytes(font_bytes)

    state = gui.GuiState(temp_dir=tmp_path, html_bytes=b"")
    state.system_fonts = [
        {
            "id": "font-test",
            "name": "Test Font",
            "path": str(font_path),
            "css_family": "mf-font-font-test",
        }
    ]
    state.system_font_map = {"font-test": font_path}

    server, base = _start_server(state)
    try:
        _status, payload = _post_json(f"{base}/api/fonts", {})
        assert payload["ok"] is True
        assert len(payload["fonts"]) == 1
        default_font = payload["default_font"]
        assert default_font["path"] == str(font_path)
        assert default_font["id"] == "font-test"

        status, body = _get_bytes(f"{base}/font/font-test")
        assert status == 200
        assert body == font_bytes
    finally:
        _stop_server(server)


def test_gui_static_helper_asset_is_served(tmp_path: Path) -> None:
    state = gui.GuiState(temp_dir=tmp_path, html_bytes=b"")
    server, base = _start_server(state)
    try:
        status, body = _get_bytes(f"{base}/static/ui_helpers.js")
        assert status == 200
        assert b"MarkforgeUiHelpers" in body
    finally:
        _stop_server(server)


def test_gui_preview_uses_system_font_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    font_path = asset_path("fonts", "DejaVuSans.ttf")
    source = _write_png(tmp_path / "photo.png", (255, 255, 255, 255))
    item = _file_item(source, file_id="photo")

    captured: dict[str, object] = {}

    def fake_run_cli_watermark(
        input_path: Path,
        output_path: Path,
        settings: dict[str, object],
        resolved_font_path: Path | None,
    ) -> None:
        captured["input_path"] = input_path
        captured["settings"] = settings
        captured["font_path"] = resolved_font_path
        Image.new("RGBA", (2, 2), (10, 20, 30, 255)).save(output_path, format="PNG")

    monkeypatch.setattr(gui, "_run_cli_watermark", fake_run_cli_watermark)

    state = gui.GuiState(
        temp_dir=tmp_path,
        files=[item],
        selected_id=item.id,
        system_fonts=[
            {
                "id": "font-test",
                "name": "Test Font",
                "path": str(font_path),
                "css_family": "mf-font-font-test",
            }
        ],
        system_font_map={"font-test": font_path},
        html_bytes=b"",
    )
    server, base = _start_server(state)
    try:
        _status, payload = _post_json(
            f"{base}/api/preview",
            {"settings": {"text": "Preview", "font_id": "font-test", "opacity": 0.2}},
        )
        assert payload["ok"] is True
        assert payload["preview_url"] == "/preview/photo"
        assert captured["font_path"] == font_path

        status, body = _get_bytes(f"{base}{payload['preview_url']}")
        assert status == 200
        assert body
    finally:
        _stop_server(server)


def test_gui_preview_and_forge_preserve_zero_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _write_png(tmp_path / "zero.png", (255, 255, 255, 255))
    item = _file_item(source, file_id="zero")
    calls: list[dict[str, object]] = []

    def fake_run_cli_watermark(
        input_path: Path,
        output_path: Path,
        settings: dict[str, object],
        resolved_font_path: Path | None,
    ) -> None:
        calls.append(dict(settings))
        Image.open(input_path).save(output_path, format="PNG")

    monkeypatch.setattr(gui, "_run_cli_watermark", fake_run_cli_watermark)

    state = gui.GuiState(
        temp_dir=tmp_path,
        files=[item],
        selected_id=item.id,
        html_bytes=b"",
    )
    server, base = _start_server(state)
    try:
        settings = {"text": "Zero", "angle": 0, "opacity": 0, "padding": 0}

        _status, preview = _post_json(f"{base}/api/preview", {"settings": settings})
        assert preview["ok"] is True

        _status, forged = _post_json(
            f"{base}/api/forge",
            {
                "apply_all": False,
                "naming": "append_wm",
                "format": "auto",
                "output_dir": str(tmp_path / "exports"),
                "settings": settings,
            },
        )
        assert forged["ok"] is True

        assert len(calls) == 2
        assert calls[0]["angle"] == 0
        assert calls[0]["opacity"] == 0
        assert calls[1]["angle"] == 0
        assert calls[1]["opacity"] == 0
    finally:
        _stop_server(server)


def test_gui_forge_overwrite_uses_original_basenames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_one = _write_png(tmp_path / "one.png", (255, 0, 0, 255))
    source_two = _write_png(tmp_path / "two.png", (0, 255, 0, 255))
    item_one = _file_item(source_one, file_id="one")
    item_two = _file_item(source_two, file_id="two")

    calls: list[tuple[Path, Path]] = []

    def fake_run_cli_watermark(
        input_path: Path,
        output_path: Path,
        settings: dict[str, object],
        resolved_font_path: Path | None,
    ) -> None:
        calls.append((input_path, output_path))
        Image.open(input_path).save(output_path, format="PNG")

    monkeypatch.setattr(gui, "_run_cli_watermark", fake_run_cli_watermark)

    state = gui.GuiState(
        temp_dir=tmp_path,
        files=[item_one, item_two],
        selected_id=item_one.id,
        html_bytes=b"",
    )
    server, base = _start_server(state)
    try:
        output_dir = tmp_path / "exports"
        _status, payload = _post_json(
            f"{base}/api/forge",
            {
                "apply_all": True,
                "naming": "overwrite",
                "format": "auto",
                "output_dir": str(output_dir),
                "settings": {"text": "Forge"},
            },
        )
        assert payload["ok"] is True
        assert [Path(p).name for p in payload["outputs"]] == ["one.png", "two.png"]
        assert (output_dir / "one.png").exists()
        assert (output_dir / "two.png").exists()
        assert state.last_output_dir == output_dir
        assert [output_path.name for (_input_path, output_path) in calls] == ["one.png", "two.png"]
    finally:
        _stop_server(server)


def test_gui_forge_uploads_use_original_uploaded_basename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, Path]] = []

    def fake_run_cli_watermark(
        input_path: Path,
        output_path: Path,
        settings: dict[str, object],
        resolved_font_path: Path | None,
    ) -> None:
        calls.append((input_path, output_path))
        Image.open(input_path).save(output_path, format="PNG")

    monkeypatch.setattr(gui, "_run_cli_watermark", fake_run_cli_watermark)

    state = gui.GuiState(temp_dir=tmp_path, html_bytes=b"")
    server, base = _start_server(state)
    try:
        original_name = "Gemini_Generated_Image_9ck4lw9ck4lw9ck4.png"
        png = _make_png_bytes((255, 0, 255, 255))
        _status, uploaded = _post_multipart(
            f"{base}/api/upload",
            [("files", original_name, png, "image/png")],
        )
        assert uploaded["ok"] is True
        assert uploaded["files"][0]["name"] == original_name
        assert state.files[0].path.stem != Path(original_name).stem

        output_dir = tmp_path / "exports"
        _status, forged = _post_json(
            f"{base}/api/forge",
            {
                "apply_all": False,
                "naming": "append_wm",
                "format": "auto",
                "output_dir": str(output_dir),
                "settings": {"text": "Forge"},
            },
        )
        expected_name = "Gemini_Generated_Image_9ck4lw9ck4lw9ck4_wm.png"
        assert forged["ok"] is True
        assert [Path(path).name for path in forged["outputs"]] == [expected_name]
        assert (output_dir / expected_name).exists()
        assert [output_path.name for (_input_path, output_path) in calls] == [expected_name]
    finally:
        _stop_server(server)


def test_gui_pick_files_and_output_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _write_png(tmp_path / "picked.png", (255, 255, 0, 255))
    output_dir = tmp_path / "chosen-output"

    monkeypatch.setattr(gui, "_pick_files", lambda: [source])
    monkeypatch.setattr(gui, "_pick_directory", lambda: output_dir)

    state = gui.GuiState(temp_dir=tmp_path, html_bytes=b"")
    server, base = _start_server(state)
    try:
        _status, picked = _post_json(f"{base}/api/pick-files", {})
        assert picked["ok"] is True
        assert picked["added"] == 1
        assert picked["files"][0]["name"] == "picked.png"

        _status, chosen = _post_json(f"{base}/api/pick-output", {})
        assert chosen["ok"] is True
        assert chosen["path"] == str(output_dir)
    finally:
        _stop_server(server)


def test_gui_open_output_uses_startfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    called: dict[str, object] = {}

    def fake_startfile(path: Path) -> None:
        called["path"] = path

    monkeypatch.setattr(gui.os, "startfile", fake_startfile, raising=False)

    state = gui.GuiState(temp_dir=tmp_path, last_output_dir=output_dir, html_bytes=b"")
    server, base = _start_server(state)
    try:
        _status, payload = _post_json(f"{base}/api/open-output", {})
        assert payload["ok"] is True
        assert called["path"] == output_dir
    finally:
        _stop_server(server)


def test_gui_custom_font_endpoints_removed(tmp_path: Path) -> None:
    state = gui.GuiState(temp_dir=tmp_path, html_bytes=b"")
    server, base = _start_server(state)
    try:
        with pytest.raises(HTTPError) as excinfo:
            _post_json(f"{base}/api/pick-font", {})
        assert excinfo.value.code == 404

        with pytest.raises(HTTPError) as excinfo:
            _post_multipart(
                f"{base}/api/upload-font",
                [("font", "font.ttf", b"not-a-real-font", "font/ttf")],
            )
        assert excinfo.value.code == 404
    finally:
        _stop_server(server)


def test_gui_load_html_falls_back_when_missing(tmp_path: Path) -> None:
    body = gui._load_html(tmp_path / "missing.html")
    assert b"Missing <code>static/index.html</code>" in body


def test_gui_pick_default_font_prefers_reasonable_match() -> None:
    fonts = [
        {"id": "arial-bold", "name": "Arial Bold", "path": "C:/Fonts/arialbd.ttf", "css_family": "f1"},
        {"id": "arial", "name": "Arial", "path": "C:/Fonts/arial.ttf", "css_family": "f2"},
    ]
    chosen = gui._pick_default_font(fonts)
    assert chosen is not None
    assert chosen["id"] == "arial"


def test_gui_run_cleans_temp_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Path] = {}

    class FakeServer:
        server_address = ("127.0.0.1", 8765)

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeServer:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

    def fake_make_handler(state: gui.GuiState):
        captured["temp_dir"] = state.temp_dir
        return object

    monkeypatch.setattr(gui, "_make_handler", fake_make_handler)
    monkeypatch.setattr(gui, "ThreadingHTTPServer", FakeServer)

    gui.run(host="127.0.0.1", port=0, open_browser=False, html=None)

    assert "temp_dir" in captured
    assert not captured["temp_dir"].exists()
