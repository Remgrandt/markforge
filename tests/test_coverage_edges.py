from __future__ import annotations

import builtins
import importlib
import io
import json
import runpy
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

import markforge
from markforge import cli, gui

runner = CliRunner()


class _MiniHandler:
    def __init__(self, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status: int | None = None
        self.sent_headers: list[tuple[str, str]] = []
        self.error: tuple[int, str] | None = None

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, key: str, value: str) -> None:
        self.sent_headers.append((key, value))

    def end_headers(self) -> None:
        return

    def send_error(self, status: int, message: str) -> None:
        self.error = (status, message)
        self.status = status


def _direct_handler(state: gui.GuiState, *, path: str, body: bytes = b"", content_type: str = ""):
    handler_cls = gui._make_handler(state)
    handler = object.__new__(handler_cls)
    handler.path = path
    handler.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.status = None
    handler.sent_headers = []
    handler.error = None

    def send_response(status: int) -> None:
        handler.status = status

    def send_header(key: str, value: str) -> None:
        handler.sent_headers.append((key, value))

    def end_headers() -> None:
        return

    def send_error(status: int, message: str) -> None:
        handler.status = status
        handler.error = (status, message)

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers
    handler.send_error = send_error
    return handler


def test_read_local_version_handles_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "read_text", lambda self, encoding="utf-8": (_ for _ in ()).throw(OSError()))
    assert markforge._read_local_version() is None


def test_package___main___calls_cli_app(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"count": 0}

    def fake_app() -> None:
        called["count"] += 1

    monkeypatch.setattr(importlib.import_module("markforge.cli"), "app", fake_app)
    runpy.run_module("markforge.__main__", run_name="__main__")
    assert called["count"] == 1


def test_package___main___import_does_not_call_cli_app(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"count": 0}

    def fake_app() -> None:
        called["count"] += 1

    monkeypatch.setattr(importlib.import_module("markforge.cli"), "app", fake_app)
    sys.modules.pop("markforge.__main__", None)
    importlib.import_module("markforge.__main__")
    assert called["count"] == 0


def test_gui_module_main_guard_calls_app(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"app": 0}

    class FakeTyperApp:
        def command(self, *_args: object, **_kwargs: object):
            def decorator(func):
                return func

            return decorator

        def __call__(self) -> None:
            calls["app"] += 1

    fake_typer = types.SimpleNamespace(
        Typer=lambda *args, **kwargs: FakeTyperApp(),
        Option=lambda *args, **kwargs: object(),
        echo=lambda *args, **kwargs: None,
    )

    monkeypatch.setitem(sys.modules, "typer", fake_typer)
    runpy.run_path(str(Path(gui.__file__)), run_name="__main__")
    assert calls["app"] == 1


def test_cli_rejects_bad_offset_shapes_and_invokes_gui_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
    input_path = Path("tests/assets/input_magenta_256.png")
    output_path = Path("tests/assets/out.png")

    bad_shape = runner.invoke(
        cli.app,
        ["watermark", str(input_path), str(output_path), "--offset", "12"],
    )
    assert bad_shape.exit_code != 0
    assert "Offset must be two numbers" in (bad_shape.stderr or bad_shape.output)

    bad_numeric = runner.invoke(
        cli.app,
        ["watermark", str(input_path), str(output_path), "--offset", "a,b"],
    )
    assert bad_numeric.exit_code != 0
    assert "Offset must be numeric" in (bad_numeric.stderr or bad_numeric.output)

    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(importlib.import_module("markforge.gui"), "run", fake_run)
    result = runner.invoke(
        cli.app,
        ["gui", "--no-open", "--host", "0.0.0.0", "--port", "9000", "--html", "README.md"],
    )
    assert result.exit_code == 0
    assert captured == {
        "host": "0.0.0.0",
        "port": 9000,
        "open_browser": False,
        "html": Path("README.md"),
    }


def test_gui_static_asset_and_font_helpers_cover_edge_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert gui._resolve_static_asset("/static/ui_helpers.js") is not None
    assert gui._resolve_static_asset("/static/../secret.txt") is None

    static_root = tmp_path / "static"
    outside = tmp_path / "outside"
    original_resolve = Path.resolve

    def fake_resolve(self: Path, strict: bool = False) -> Path:
        if self == static_root / "linked" / "asset.js":
            return outside / "asset.js"
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(gui, "_static_dir", lambda: static_root)
    monkeypatch.setattr(Path, "resolve", fake_resolve)
    assert gui._resolve_static_asset("/static/linked/asset.js") is None

    class FakeFont:
        def __init__(self, family: str, style: str) -> None:
            self._family = family
            self._style = style

        def getname(self) -> tuple[str, str]:
            return self._family, self._style

    monkeypatch.setattr(gui.ImageFont, "truetype", lambda *_args, **_kwargs: FakeFont("Demo", "Bold"))
    assert gui._font_display_name(tmp_path / "demo.ttf") == "Demo Bold"

    monkeypatch.setattr(gui.ImageFont, "truetype", lambda *_args, **_kwargs: FakeFont("Demo", "Regular"))
    assert gui._font_display_name(tmp_path / "demo.ttf") == "Demo"

    monkeypatch.setattr(gui.ImageFont, "truetype", lambda *_args, **_kwargs: FakeFont("", "Regular"))
    assert gui._font_display_name(tmp_path / "fallback-name.ttf") == "fallback name"

    monkeypatch.setattr(
        gui.ImageFont,
        "truetype",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert gui._font_display_name(tmp_path / "fancy-font.otf") == "fancy font"
    assert gui._font_display_name(tmp_path / "----") == "----"


def test_list_system_fonts_and_pick_default_font_cover_platform_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    windir = tmp_path / "windir"
    fonts_dir = windir / "Fonts"
    user_fonts_dir = home / "AppData/Local/Microsoft/Windows/Fonts"
    error_dir = home / "error-fonts"
    fonts_dir.mkdir(parents=True)
    user_fonts_dir.mkdir(parents=True)
    error_dir.mkdir(parents=True)
    (fonts_dir / "one.ttf").write_bytes(b"font-one")
    (user_fonts_dir / "two.otf").write_bytes(b"font-two")

    original_rglob = Path.rglob

    def fake_rglob(self: Path, pattern: str):
        if self == error_dir:
            raise PermissionError("nope")
        return original_rglob(self, pattern)

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(gui.sys, "platform", "win32")
    monkeypatch.setitem(gui.os.environ, "WINDIR", str(windir))
    monkeypatch.setattr(Path, "rglob", fake_rglob)
    monkeypatch.setattr(gui, "_font_display_name", lambda path: "Same Name")

    fonts = gui._list_system_fonts()
    assert len(fonts) == 2
    assert all("(" in item["name"] for item in fonts)

    monkeypatch.setattr(gui.sys, "platform", "darwin")
    assert gui._list_system_fonts() == []

    monkeypatch.setattr(gui.sys, "platform", "linux")
    assert gui._list_system_fonts() == []

    assert gui._pick_default_font([]) is None

    monkeypatch.setattr(gui.sys, "platform", "darwin")
    assert gui._pick_default_font(
        [{"id": "a", "name": "Helvetica Bold", "path": "x", "css_family": "f"}]
    )["id"] == "a"

    monkeypatch.setattr(gui.sys, "platform", "linux")
    assert gui._pick_default_font(
        [{"id": "b", "name": "Custom Font", "path": "x", "css_family": "f"}]
    )["id"] == "b"

    single_font_dir = tmp_path / "single-home" / ".local" / "share" / "fonts"
    blocked_font_dir = tmp_path / "single-home" / ".fonts"
    single_font_dir.mkdir(parents=True)
    blocked_font_dir.mkdir(parents=True)
    (single_font_dir / "subdir").mkdir()
    (single_font_dir / "note.txt").write_text("nope", encoding="utf-8")
    (single_font_dir / "solo.ttf").write_bytes(b"font")
    original_rglob = Path.rglob

    def branchy_rglob(self: Path, pattern: str):
        if self == single_font_dir:
            yield single_font_dir / "subdir"
            yield single_font_dir / "note.txt"
            yield single_font_dir / "solo.ttf"
            return
        if self == blocked_font_dir:
            raise OSError("blocked")
        yield from original_rglob(self, pattern)

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "single-home"))
    monkeypatch.setattr(gui.sys, "platform", "linux")
    monkeypatch.setattr(Path, "rglob", branchy_rglob)
    monkeypatch.setattr(gui, "_font_display_name", lambda path: "Solo Font")
    fonts = gui._list_system_fonts()
    assert [font["name"] for font in fonts] == ["Solo Font"]


def test_json_and_subprocess_helpers_cover_remaining_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = _MiniHandler(headers={"Content-Length": "0"})
    assert gui._read_json(empty) == {}

    body_handler = _MiniHandler(
        body=json.dumps({"ok": True}).encode("utf-8"),
        headers={"Content-Length": "12"},
    )
    assert gui._read_json(body_handler) == {"ok": True}

    send_bytes_handler = _MiniHandler()
    gui._send_bytes(send_bytes_handler, b"abc", "text/plain")
    assert send_bytes_handler.status == 200
    assert send_bytes_handler.wfile.getvalue() == b"abc"

    send_json_handler = _MiniHandler()
    gui._send_json(send_json_handler, {"ok": True}, status=201)
    assert send_json_handler.status == 201
    assert b'"ok": true' in send_json_handler.wfile.getvalue()

    captured_args: list[str] = []

    class Result:
        def __init__(self, returncode: int, stderr: str = "", stdout: str = "") -> None:
            self.returncode = returncode
            self.stderr = stderr
            self.stdout = stdout

    def fake_run(args: list[str], **_kwargs: object) -> Result:
        captured_args[:] = args
        return Result(0)

    monkeypatch.setattr(gui.subprocess, "run", fake_run)
    gui._run_cli_watermark(
        tmp_path / "in.png",
        tmp_path / "out.png",
        {
            "text": "Run",
            "opacity": 0.5,
            "angle": 0,
            "fill": "#ffffff",
            "font_size": 10,
            "padding": 0,
            "blend": "normal",
            "offset_x": 0,
            "offset_y": 0,
            "scale": 0.25,
            "tile": False,
            "center": True,
            "antialias": False,
        },
        tmp_path / "font.ttf",
    )
    assert "--scale" in captured_args
    assert "--font" in captured_args
    assert "--no-tile" in captured_args
    assert "--center" in captured_args
    assert "--no-antialias" in captured_args

    monkeypatch.setattr(gui.subprocess, "run", lambda *_args, **_kwargs: Result(1, stderr="boom"))
    with pytest.raises(RuntimeError, match="boom"):
        gui._run_cli_watermark(tmp_path / "in.png", tmp_path / "out.png", {"text": "x"}, None)


def test_picker_helpers_cover_success_and_import_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"destroyed": 0}

    class FakeRoot:
        def withdraw(self) -> None:
            return

        def wm_attributes(self, *_args: object) -> None:
            return

        def destroy(self) -> None:
            calls["destroyed"] += 1

    fake_filedialog = types.SimpleNamespace(
        askopenfilenames=lambda **_kwargs: [str(tmp_path / "one.png")],
        askdirectory=lambda **_kwargs: str(tmp_path / "out"),
    )
    fake_tk = types.SimpleNamespace(Tk=lambda: FakeRoot(), filedialog=fake_filedialog)
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)

    assert gui._pick_files() == [tmp_path / "one.png"]
    assert gui._pick_directory() == tmp_path / "out"
    assert calls["destroyed"] == 2

    original_import = builtins.__import__

    def fail_tk(name: str, *args: object, **kwargs: object):
        if name == "tkinter":
            raise ImportError("missing tkinter")
        return original_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "tkinter", raising=False)
    monkeypatch.setattr(builtins, "__import__", fail_tk)
    assert gui._pick_files() == []
    assert gui._pick_directory() is None


def test_handler_covers_remaining_http_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    missing_state = gui.GuiState(temp_dir=tmp_path, html_bytes=b"INDEX")
    handler = _direct_handler(missing_state, path="/")
    handler.do_GET()
    assert handler.status == 200

    handler = _direct_handler(missing_state, path="/static/missing.js")
    handler.do_GET()
    assert handler.error == (404, "Static asset not found")

    handler = _direct_handler(missing_state, path="/preview/missing")
    handler.do_GET()
    assert handler.error == (404, "Preview not found")

    handler = _direct_handler(missing_state, path="/font/missing")
    handler.do_GET()
    assert handler.error == (404, "Font not found")

    handler = _direct_handler(missing_state, path="/source/missing")
    handler.do_GET()
    assert handler.error == (404, "Source not found")

    handler = _direct_handler(missing_state, path="/unknown")
    handler.do_GET()
    assert handler.error == (404, "Not Found")

    handler = _direct_handler(missing_state, path="/api/unknown")
    handler.do_POST()
    assert handler.error == (404, "Not Found")

    handler = _direct_handler(missing_state, path="/api/upload", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 400

    handler = _direct_handler(missing_state, path="/api/upload", body=b"{}", content_type="application/json")
    handler._parse_form = lambda: {"files": gui._FormFile(filename="", file=io.BytesIO(b""))}
    handler.do_POST()
    assert handler.status == 200

    multipart = (
        b"--boundary\r\n"
        b"Content-Disposition: form-data; name=\"files\"; filename=\"bad.txt\"\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"not an image\r\n"
        b"--boundary--\r\n"
    )
    handler = _direct_handler(
        missing_state,
        path="/api/upload",
        body=multipart,
        content_type="multipart/form-data; boundary=boundary",
    )
    handler.do_POST()
    assert handler.status == 200
    assert missing_state.files == []

    monkeypatch.setattr(gui, "_pick_files", lambda: [tmp_path / "missing.png", tmp_path / "bad.txt"])
    (tmp_path / "bad.txt").write_text("not an image", encoding="utf-8")
    handler = _direct_handler(missing_state, path="/api/pick-files", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 200
    assert b'"added": 0' in handler.wfile.getvalue()

    one = tmp_path / "one.png"
    import PIL.Image

    PIL.Image.new("RGBA", (2, 2), (255, 255, 255, 255)).save(one, format="PNG")
    existing = gui.FileItem(id="existing", name="existing.png", path=one, size=one.stat().st_size, width=2, height=2)
    selected_state = gui.GuiState(temp_dir=tmp_path, files=[existing], selected_id="existing", html_bytes=b"INDEX")
    monkeypatch.setattr(gui, "_pick_files", lambda: [one])
    handler = _direct_handler(selected_state, path="/api/pick-files", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 200
    assert selected_state.selected_id == "existing"

    monkeypatch.setattr(gui, "_pick_directory", lambda: None)
    handler = _direct_handler(missing_state, path="/api/pick-output", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 400

    handler = _direct_handler(missing_state, path="/api/preview", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 400

    item = gui.FileItem(id="one", name="one.png", path=one, size=one.stat().st_size, width=2, height=2)
    state = gui.GuiState(temp_dir=tmp_path, files=[item], selected_id="one", html_bytes=b"INDEX")

    monkeypatch.setattr(gui, "_run_cli_watermark", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("preview failed")))
    handler = _direct_handler(state, path="/api/preview", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 500

    empty = gui.GuiState(temp_dir=tmp_path, html_bytes=b"INDEX")
    handler = _direct_handler(empty, path="/api/forge", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 400

    state = gui.GuiState(temp_dir=tmp_path, files=[item], selected_id="one", html_bytes=b"INDEX")

    def fake_success(input_path: Path, output_path: Path, settings: dict[str, object], font_path: Path | None) -> None:
        PIL.Image.open(input_path).save(output_path, format="PNG")

    monkeypatch.setattr(gui, "_run_cli_watermark", fake_success)
    forge_body = json.dumps({"naming": "append_markforge", "format": "jpeg", "settings": {"text": "x"}}).encode("utf-8")
    handler = _direct_handler(state, path="/api/forge", body=forge_body, content_type="application/json")
    handler.do_POST()
    assert handler.status == 200
    assert b"_MARKFORGE.jpg" in handler.wfile.getvalue()

    rel_body = json.dumps(
        {"naming": "append_wm", "format": "auto", "output_dir": "relative-exports", "settings": {"text": "x"}}
    ).encode("utf-8")
    handler = _direct_handler(state, path="/api/forge", body=rel_body, content_type="application/json")
    handler.do_POST()
    assert handler.status == 200

    monkeypatch.setattr(gui, "_run_cli_watermark", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("forge failed")))
    handler = _direct_handler(state, path="/api/forge", body=forge_body, content_type="application/json")
    handler.do_POST()
    assert handler.status == 500


def test_handler_clear_and_open_output_cover_file_error_branches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    temp_file = tmp_path / "temp.png"
    preview_file = tmp_path / "preview.png"
    temp_file.write_bytes(b"tmp")
    preview_file.write_bytes(b"preview")
    item = gui.FileItem(id="temp", name="temp.png", path=temp_file, size=3, width=1, height=1, is_temp=True, preview_path=preview_file)
    state = gui.GuiState(temp_dir=tmp_path, files=[item], selected_id=item.id, html_bytes=b"INDEX")

    temp_file.unlink()
    handler = _direct_handler(state, path="/api/clear", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 200
    assert state.files == []
    assert not preview_file.exists()

    source_file = tmp_path / "source.png"
    source_preview = tmp_path / "source-preview.png"
    source_file.write_bytes(b"tmp")
    source_preview.write_bytes(b"preview")
    source_item = gui.FileItem(
        id="source",
        name="source.png",
        path=source_file,
        size=3,
        width=1,
        height=1,
        is_temp=False,
        preview_path=source_preview,
    )
    state = gui.GuiState(temp_dir=tmp_path, files=[source_item], selected_id=source_item.id, html_bytes=b"INDEX")
    handler = _direct_handler(state, path="/api/clear", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 200
    assert source_file.exists()
    assert not source_preview.exists()

    state = gui.GuiState(temp_dir=tmp_path, selected_id="missing", html_bytes=b"INDEX")
    handler = _direct_handler(state, path="/api/clear-selected", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 400

    temp_file = tmp_path / "temp2.png"
    preview_file = tmp_path / "preview2.png"
    temp_file.write_bytes(b"tmp")
    preview_file.write_bytes(b"preview")
    item = gui.FileItem(id="temp2", name="temp2.png", path=temp_file, size=3, width=1, height=1, is_temp=True, preview_path=preview_file)
    state = gui.GuiState(temp_dir=tmp_path, files=[item], selected_id=item.id, html_bytes=b"INDEX")
    temp_file.unlink()
    handler = _direct_handler(state, path="/api/clear-selected", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 200
    assert state.selected_id is None
    assert not preview_file.exists()

    source_file = tmp_path / "selected-source.png"
    source_preview = tmp_path / "selected-preview.png"
    source_file.write_bytes(b"tmp")
    source_preview.write_bytes(b"preview")
    source_item = gui.FileItem(
        id="source-selected",
        name="selected-source.png",
        path=source_file,
        size=3,
        width=1,
        height=1,
        is_temp=False,
        preview_path=source_preview,
    )
    state = gui.GuiState(temp_dir=tmp_path, files=[source_item], selected_id=source_item.id, html_bytes=b"INDEX")
    handler = _direct_handler(state, path="/api/clear-selected", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 200
    assert source_file.exists()
    assert not source_preview.exists()

    state = gui.GuiState(temp_dir=tmp_path, html_bytes=b"INDEX")
    handler = _direct_handler(state, path="/api/open-output", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 400

    opened: dict[str, str] = {}
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    state = gui.GuiState(temp_dir=tmp_path, last_output_dir=output_dir, html_bytes=b"INDEX")

    def fail_startfile(_path: Path) -> None:
        raise OSError("no startfile")

    monkeypatch.setattr(gui.os, "startfile", fail_startfile, raising=False)
    monkeypatch.setattr(gui.webbrowser, "open", lambda uri: opened.setdefault("uri", uri))
    handler = _direct_handler(state, path="/api/open-output", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 200
    assert opened["uri"] == output_dir.as_uri()


def test_parse_form_and_fonts_loader_cover_remaining_parser_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = gui.GuiState(temp_dir=tmp_path, html_bytes=b"INDEX")
    handler = _direct_handler(state, path="/api/upload")
    assert handler._parse_form() == {}

    handler = _direct_handler(state, path="/api/upload", body=b"", content_type="multipart/form-data")
    assert handler._parse_form() == {}

    handler = _direct_handler(
        state,
        path="/api/upload",
        body=b"",
        content_type='multipart/form-data; boundary="quoted"',
    )
    assert handler._parse_form() == {}

    body = (
        b"--edge\r\n"
        b"HeaderWithoutColon\r\n"
        b"\r\n"
        b"ignored\r\n"
        b"--edge\r\n"
        b"Content-Disposition: form-data; name=\"note\"\r\n\r\n"
        b"value-one\r\n"
        b"--edge\r\n"
        b"Content-Disposition: form-data; name=\"note\"\r\n\r\n"
        b"value-two\r\n"
        b"--edge\r\n"
        b"Content-Disposition: form-data; name=\"files\"; filename=\"a.txt\"\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"aaa\r\n"
        b"--edge\r\n"
        b"Content-Disposition: form-data; name=\"files\"; filename=\"b.txt\"\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"bbb\r\n"
        b"--edge\r\n"
        b"Content-Disposition: form-data\r\n\r\n"
        b"missing-name\r\n"
        b"--edge\r\n"
        b"Content-Disposition: form-data; name=\"broken\"\r\n"
        b"X-Test: one\r\n"
        b"--edge--\r\n"
    )
    handler = _direct_handler(
        state,
        path="/api/upload",
        body=body,
        content_type="multipart/form-data; boundary=edge",
    )
    parsed = handler._parse_form()
    assert parsed["note"] == ["value-one", "value-two"]
    assert len(parsed["files"]) == 2

    branchy_body = (
        b"junk"
        b"--edge2\r\n\r\n"
        b"--edge2\r\n"
        b"Content-Disposition: form-data; token; name=plain; foo=bar\r\n\r\n"
        b"value-one\r\n"
        b"--edge2\r\n"
        b"Content-Disposition: form-data; name=plain\r\n\r\n"
        b"value-two\r\n"
        b"--edge2\r\n"
        b"Content-Disposition: form-data; name=plain\r\n\r\n"
        b"value-three\r\n"
        b"--edge2\r\n"
        b"Content-Disposition: form-data; name=files; filename=a.txt\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"aaa\r\n"
        b"--edge2\r\n"
        b"Content-Disposition: form-data; name=files; filename=b.txt\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"bbb\r\n"
        b"--edge2\r\n"
        b"Content-Disposition: form-data; name=files; filename=c.txt\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"ccc\r\n"
        b"--edge2--"
    )
    handler = _direct_handler(
        state,
        path="/api/upload",
        body=branchy_body,
        content_type="multipart/form-data; boundary=edge2",
    )
    parsed = handler._parse_form()
    assert parsed["plain"] == ["value-one", "value-two", "value-three"]
    assert len(parsed["files"]) == 3

    monkeypatch.setattr(
        gui,
        "_list_system_fonts",
        lambda: [{"id": "font-1", "name": "Font 1", "path": "C:/font.ttf", "css_family": "f1"}],
    )
    handler = _direct_handler(state, path="/api/fonts", body=b"{}", content_type="application/json")
    handler.do_POST()
    assert handler.status == 200
    assert b'"font-1"' in handler.wfile.getvalue()


def test_gui_run_open_browser_and_main_wrapper(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    opened: dict[str, str] = {}

    class FakeServer:
        server_address = ("0.0.0.0", 4321)

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> FakeServer:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

    monkeypatch.setattr(gui, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(gui.webbrowser, "open", lambda url: opened.setdefault("url", url))
    monkeypatch.setattr(gui.typer, "echo", lambda *_args, **_kwargs: None)
    gui.run(host="0.0.0.0", port=0, open_browser=True, html=tmp_path / "missing.html")
    assert opened["url"] == "http://127.0.0.1:4321/"

    called = {"app": 0}
    monkeypatch.setattr(gui, "app", lambda: called.__setitem__("app", called["app"] + 1))
    gui.main()
    assert called["app"] == 1
