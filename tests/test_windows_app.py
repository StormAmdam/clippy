"""The Windows app's own behaviour: one Clippy per folder on a free port, nothing left running after Clippy ends,
start at login, notifications, and files that Windows keeps locked while something has them open.
Tests marked for Windows run on the Windows build machine (packaging/windows/build.ps1)."""
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from clippy import config, desktop, notify, quiet, storage

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows behaviour")
ROOT = Path(__file__).resolve().parent.parent


# ───────────────────────── one Clippy per folder, on a free port ─────────────────────────

def _serve(body: dict | None):
    """A local web server on a free port: a Clippy (answers /api/status with `body`) or, with None, another program."""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            ok = body is not None and self.path == "/api/status"
            data = json.dumps(body if ok else {"detail": "Not Found"}).encode()
            self.send_response(200 if ok else 404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def ports(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop, "PORT_FILE", tmp_path / "port.txt")
    servers = []
    yield lambda body: servers.append(_serve(body)) or servers[-1].server_address[1]
    for s in servers:
        s.shutdown()
        s.server_close()


def test_a_port_another_program_uses_is_skipped(ports, monkeypatch):
    taken, free = ports(None), _free_port()
    monkeypatch.setattr(desktop, "PORTS", [taken, free])
    assert desktop.probe(taken) == "other"
    assert desktop.find_port() == (free, False)


def test_a_running_clippy_from_this_folder_is_found_not_started_twice(ports, monkeypatch):
    mine = ports({"llm": False, "folder": str(config.ROOT)})
    monkeypatch.setattr(desktop, "PORTS", [ports(None), mine])
    assert desktop.find_port() == (mine, True)


def test_a_clippy_from_another_folder_counts_as_another_program(ports, monkeypatch):
    elsewhere, free = ports({"llm": False, "folder": "C:\\Somewhere\\Else\\Clippy"}), _free_port()
    monkeypatch.setattr(desktop, "PORTS", [elsewhere, free])
    assert desktop.find_port() == (free, False)


def test_the_port_this_clippy_last_used_is_tried_first(ports, monkeypatch):
    mine = ports({"llm": False, "folder": str(config.ROOT)})      # e.g. all of 7860–7869 were busy back then
    monkeypatch.setattr(desktop, "PORTS", [_free_port()])
    desktop.PORT_FILE.write_text(str(mine))
    assert desktop.find_port() == (mine, True)


def test_when_every_usual_port_is_taken_any_free_one_will_do(ports, monkeypatch):
    taken = [ports(None), ports(None)]
    monkeypatch.setattr(desktop, "PORTS", taken)
    port, running = desktop.find_port()
    assert port not in taken and not running and desktop.probe(port) == "free"


# ───────────────────────── nothing left running after Clippy ends ─────────────────────────

def test_every_started_program_is_tied_to_clippy():
    tied = []

    class FakePopen:
        def __init__(self, *args, **kwargs):
            pass

    Quiet = quiet.make_quiet(FakePopen, tie_child=tied.append)
    a, b = Quiet(["llama-server"]), Quiet(["ffmpeg"], creationflags=0)
    assert tied == [a, b]


def _alive(pid: int) -> bool:
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x00100000, False, pid)          # SYNCHRONIZE
    if not h:
        return False
    try:
        return k32.WaitForSingleObject(h, 0) == 0x102       # WAIT_TIMEOUT: still running
    finally:
        k32.CloseHandle(h)


@windows_only
def test_on_windows_the_ai_engine_ends_when_clippy_is_ended_in_task_manager(tmp_path):
    pid_file = tmp_path / "engine.pid"
    fake_clippy = (
        "import subprocess, sys, time, pathlib\n"
        "import clippy\n"                                   # what every Clippy start does first
        "engine = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
        f"pathlib.Path(r'{pid_file}').write_text(str(engine.pid))\n"
        "time.sleep(300)\n")
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    clippy_proc = quiet.plain_popen()([sys.executable, "-c", fake_clippy], env=env)
    try:
        for _ in range(100):
            if pid_file.exists() and pid_file.read_text():
                break
            time.sleep(0.1)
        engine = int(pid_file.read_text())
        assert _alive(engine)
        clippy_proc.kill()                                  # TerminateProcess: what Task Manager's End task does
        clippy_proc.wait(10)
        for _ in range(100):
            if not _alive(engine):
                break
            time.sleep(0.1)
        assert not _alive(engine), "the engine kept running after Clippy was ended"
    finally:
        clippy_proc.kill()


# ───────────────────────── start at login ─────────────────────────

@windows_only
def test_on_windows_start_at_login_is_a_run_entry_for_clippy_exe(tmp_path, monkeypatch):
    import winreg

    from clippy import autostart
    app = tmp_path / "Clippy Jörg"
    app.mkdir()
    monkeypatch.setattr(autostart, "ROOT", app)
    assert autostart.status() == {"supported": False, "installed": False, "enabled": False, "how": "windows-source"}
    with pytest.raises(RuntimeError, match="Clippy app"):
        autostart.enable()
    (app / "Clippy.exe").write_bytes(b"MZ")
    before = autostart._reg_get("Clippy")
    try:
        assert autostart.enable()["enabled"]
        assert autostart._reg_get("Clippy") == f'"{app}\\Clippy.exe" --background'
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, autostart.APPROVED_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "Clippy", 0, winreg.REG_BINARY, b"\x03" + bytes(11))   # "Disabled" in Task Manager
        assert not autostart.status()["enabled"]
        assert autostart.enable()["enabled"]                      # turning it on again undoes that
        assert not autostart.disable()["enabled"]
        assert autostart._reg_get("Clippy") is None
    finally:
        autostart._reg_delete("Clippy")
        autostart._reg_delete("Clippy", autostart.APPROVED_KEY)
        if before is not None:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, autostart.RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "Clippy", 0, winreg.REG_SZ, before)


# ───────────────────────── notifications ─────────────────────────

def test_toast_text_cannot_break_the_notification():
    xml = notify.toast_xml("Clippy", 'Ready: “Tom & Jerry <3” 🎬')
    assert "Tom &amp; Jerry &lt;3" in xml and "🎬" in xml
    import xml.dom.minidom
    xml_doc = xml.dom.minidom.parseString(notify.toast_xml("a<b", "c&d"))
    assert [t.firstChild.data for t in xml_doc.getElementsByTagName("text")] == ["a<b", "c&d"]


@windows_only
def test_on_windows_a_notification_shows_without_anything_installed():
    r = notify.windows_toast("Clippy test", "3 new shorts for “Jörg’s channel” are waiting 🎬")
    assert r.returncode == 0, r.stderr


# ───────────────────────── files Windows keeps locked ─────────────────────────

def test_saving_waits_for_a_reader_that_has_the_file_open(tmp_path, monkeypatch):
    target = tmp_path / "review.json"
    target.write_text("[]")
    real, refusals = os.replace, []

    def busy_then_free(src, dst):
        if len(refusals) < 3:                               # Windows: "the file is being used by another process"
            refusals.append(dst)
            raise PermissionError(13, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(config.os, "replace", busy_then_free)
    config.write_atomic(target, '[{"title": "Jörg 🎬"}]')
    assert len(refusals) == 3 and json.loads(target.read_text(encoding="utf-8")) == [{"title": "Jörg 🎬"}]
    assert list(tmp_path.iterdir()) == [target]             # no temp file left behind


@windows_only
def test_on_windows_saving_works_while_another_thread_reads_the_file(tmp_path):
    target = tmp_path / "jobs.json"
    target.write_text("old", encoding="utf-8")
    reader = open(target, encoding="utf-8")                 # Python opens files without delete sharing
    threading.Timer(0.5, reader.close).start()
    config.write_atomic(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def _project(out: Path) -> Path:
    d = out / "A"
    (d / "clips").mkdir(parents=True)
    (d / "source.mp4").write_bytes(b"x" * 10)
    (d / "clips" / "01-hook.mp4").write_bytes(b"y")
    return d


def test_deleting_a_project_with_a_short_open_elsewhere_says_what_to_do(tmp_output, monkeypatch):
    from fastapi.testclient import TestClient

    from clippy import server
    d = _project(tmp_output)
    real = os.unlink

    def open_in_player(path, *a, **k):
        if str(path).endswith("01-hook.mp4"):
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real(path, *a, **k)

    monkeypatch.setattr(os, "unlink", open_in_player)
    monkeypatch.setattr(os, "chmod", lambda *a, **k: None)
    with pytest.raises(storage.FileInUse, match="01-hook.mp4: it's open in another program"):
        storage.delete_project(tmp_output, "A")
    monkeypatch.setattr(server, "OUT", tmp_output)
    r = TestClient(server.app, base_url="http://127.0.0.1:7860").delete("/api/storage/A")
    assert r.status_code == 409 and "Close it and try again" in r.json()["detail"]
    monkeypatch.setattr(os, "unlink", real)                 # the player is closed
    storage.delete_project(tmp_output, "A")
    assert not d.exists()


@windows_only
def test_on_windows_a_short_open_in_a_player_blocks_delete_with_a_clear_message(tmp_output):
    d = _project(tmp_output)
    player = open(d / "clips" / "01-hook.mp4", "rb")
    try:
        with pytest.raises(storage.FileInUse, match="01-hook.mp4"):
            storage.delete_project(tmp_output, "A")
        with pytest.raises(storage.FileInUse):
            storage.remove_file(d / "clips" / "01-hook.mp4")
    finally:
        player.close()
    storage.delete_project(tmp_output, "A")
    assert not d.exists()


def test_read_only_files_are_deleted_too(tmp_output):
    import stat
    d = _project(tmp_output)
    os.chmod(d / "clips" / "01-hook.mp4", stat.S_IREAD)     # e.g. copied from a USB stick
    os.chmod(d / "source.mp4", stat.S_IREAD)
    assert storage.delete_source(tmp_output, "A") == 10
    storage.delete_project(tmp_output, "A")
    assert not d.exists()


def test_settings_saved_by_notepad_with_a_bom_still_load(tmp_output):
    config.settings_file().write_bytes('\ufeff{"clips": 3, "caption_color": "#FFFFFF"}'.encode("utf-8"))
    assert config.load().clips == 3


# ───────────────────────── quitting a Clippy that runs in the background ─────────────────────────

def test_the_quit_button_ends_a_background_clippy(monkeypatch, tmp_path):
    import httpx

    from clippy import server
    port = _free_port()
    monkeypatch.setattr(desktop, "PORTS", [port])
    monkeypatch.setattr(desktop, "PORT_FILE", tmp_path / "port.txt")
    monkeypatch.setattr(desktop, "open_window", lambda url: pytest.fail("--background must not open a window"))
    monkeypatch.setitem(server.APP, "desktop", False)
    monkeypatch.setitem(server.APP, "quit", False)
    ended = []
    th = threading.Thread(target=lambda: ended.append(desktop.main(["--background"])), daemon=True)
    th.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if desktop.PORT_FILE.exists():
            break
        time.sleep(0.1)
    assert desktop.PORT_FILE.read_text() == str(port)
    assert httpx.get(base + "/api/autostart").json()["can_quit"] is True
    assert httpx.post(base + "/api/quit").json() == {"ok": True}
    th.join(20)
    assert ended == [0]


def test_a_clippy_started_from_a_terminal_says_how_to_stop_it(tmp_output, monkeypatch):
    from fastapi.testclient import TestClient

    from clippy import server
    monkeypatch.setitem(server.APP, "desktop", False)
    r = TestClient(server.app, base_url="http://127.0.0.1:7860").post("/api/quit")
    assert r.status_code == 400 and "Ctrl+C" in r.json()["detail"] and not server.APP["quit"]
