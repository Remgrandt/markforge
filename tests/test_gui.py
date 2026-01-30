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
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode(
                "utf-8"
            )
        )
        parts.append(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        parts.append(content)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
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

        status, body = _get_bytes(f"{base}/font/font-test")
        assert status == 200
        assert body == font_bytes
    finally:
        _stop_server(server)
