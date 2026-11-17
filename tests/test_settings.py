import sys
import configparser
import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


def test_ui_settings_override_defaults_and_persist(tmp_output, monkeypatch):
    from clippy import config
    s = config.save_ui_settings({"clips": "7", "caption_style": "box", "sfx": "false"})
    assert (s.clips, s.caption_style, s.sfx) == (7, "box", False)
    assert config.load().clips == 7                                   # persisted
    assert config.load({"clips": 2}).clips == 2                       # a single job's option still wins
    monkeypatch.setenv("CLIPPY_CLIPS", "3")
    assert config.load().clips == 3                                   # env beats the UI file
    saved = json.loads(Path(config.settings_file()).read_text())
    assert saved == {"clips": 7, "caption_style": "box", "sfx": False}


def test_ui_settings_rejects_unknown_key(tmp_output):
    from clippy import config
    config.save_ui_settings({"clips": 4})
    with pytest.raises(ValueError):
        config.save_ui_settings({"bogus": 1, "clips": 9})
    assert config.load().clips == 4                                   # nothing half-applied


@pytest.mark.skipif(sys.platform == "win32", reason="start at login uses systemd, which is Linux-only")
def test_unit_file_runs_clippy_from_its_folder():
    from clippy import autostart
    unit = configparser.ConfigParser(interpolation=None)
    unit.read_string(autostart.unit_text(Path("/x/Clippy")))
    assert unit["Service"]["ExecStart"] == '"/x/Clippy/.venv/bin/python" -m clippy web --no-browser'
    assert unit["Service"]["WorkingDirectory"] == "/x/Clippy"
    assert unit["Install"]["WantedBy"] == "default.target"


@pytest.mark.skipif(sys.platform == "win32", reason="start at login uses systemd, which is Linux-only")
def test_unit_file_survives_a_folder_with_spaces_and_percent_signs():
    # after moving PCs the folder can be anywhere, e.g. "~/My Projects/100% Clippy"
    from clippy import autostart
    unit = configparser.ConfigParser(interpolation=None)
    unit.read_string(autostart.unit_text(Path("/home/a/My Projects/100% Clippy")))
    assert unit["Service"]["ExecStart"] == \
        '"/home/a/My Projects/100%% Clippy/.venv/bin/python" -m clippy web --no-browser'
    assert unit["Service"]["WorkingDirectory"] == "/home/a/My Projects/100%% Clippy"


def test_enable_and_disable_drive_systemctl(tmp_path, monkeypatch):
    from clippy import autostart
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    calls = []
    monkeypatch.setattr(autostart, "_systemctl", lambda *a: calls.append(a) or (0, "enabled"))
    autostart.enable()
    assert autostart.unit_path().exists()
    assert calls[:2] == [("daemon-reload",), ("enable", "clippy.service")]
    calls.clear()
    autostart.disable()
    assert not autostart.unit_path().exists()
    assert calls[0] == ("disable", "clippy.service") and ("daemon-reload",) in calls


def test_settings_endpoints(tmp_output):
    from fastapi.testclient import TestClient

    from clippy import config, server
    server = importlib.reload(server)
    c = TestClient(server.app, base_url="http://127.0.0.1:7860")
    config.save_ui_settings({"llm_api_key": "secret"})
    got = c.get("/api/settings").json()
    assert "llm_api_key" not in got and got["has_llm_api_key"] is True
    assert c.post("/api/settings", json={"clips": 4}).status_code == 200
    assert config.load().clips == 4
    assert c.post("/api/settings", json={"nope": 1}).status_code == 400


class _Status(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/api/status" else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"llm": true}')

    def log_message(self, *a):
        pass


def test_detects_clippy_already_running():
    from clippy import server
    httpd = HTTPServer(("127.0.0.1", 0), _Status)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        assert server._already_running(f"http://127.0.0.1:{httpd.server_port}") is True
    finally:
        httpd.shutdown()
    assert server._already_running(f"http://127.0.0.1:{httpd.server_port}") is False
