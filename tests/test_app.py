"""The self-contained app: downloads into Clippy's folder, the model chooser, and the built-in AI process."""
import sys
import textwrap
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from clippy import aisetup, components, engine, llm
from clippy.config import Settings


@pytest.fixture
def app_dirs(tmp_path, monkeypatch):
    """Point every app folder at a temp dir."""
    for name, sub in (("LLM_DIR", "models/llm"), ("ENGINE_DIR", "engine"), ("DOWNLOADS", "downloads"), ("BIN", "bin")):
        monkeypatch.setattr(components, name, tmp_path / sub)
    monkeypatch.setattr(components, "hardware", lambda: {"vram_mb": 0, "ram_mb": 16384, "disk_free_mb": 100000,
                                                         "threads": 2, "arch": "x86_64", "nvidia": False, "vulkan": False})
    monkeypatch.setattr(engine.config, "ROOT", tmp_path)
    llm._cache.clear()
    yield tmp_path
    engine.ENGINE.stop()


def test_hugging_face_links_become_download_links():
    assert engine.hf_link("https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/blob/main/Qwen3.5-4B-Q4_K_M.gguf") == (
        "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf", "Qwen3.5-4B-Q4_K_M.gguf")
    for bad in ("https://example.com/x.gguf", "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF",
                "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/tree/main/x.gguf"):
        with pytest.raises(ValueError):
            engine.hf_link(bad)


def test_the_chosen_model_wins_then_the_only_or_newest_one(app_dirs):
    d = components.LLM_DIR
    d.mkdir(parents=True)
    assert engine.model_path(Settings()) is None
    (d / "a.gguf").write_bytes(b"x")
    assert engine.model_path(Settings()).name == "a.gguf"
    time.sleep(0.01)
    (d / "b.gguf").write_bytes(b"x")
    (d / "b-mmproj-f16.gguf").write_bytes(b"x")                       # vision add-ons aren't chat models
    assert engine.model_path(Settings()).name == "b.gguf"
    assert engine.model_path(Settings(ai_model="a.gguf")).name == "a.gguf"


def test_catalog_marks_what_fits_and_what_is_downloaded(app_dirs):
    components.LLM_DIR.mkdir(parents=True)
    (components.LLM_DIR / "Qwen3.5-4B-Q4_K_M.gguf").write_bytes(b"x")
    rows = {m["name"]: m for m in engine.models(Settings())}
    assert rows["Qwen3.5 4B"]["installed"] and rows["Qwen3.5 4B"]["active"]
    assert rows["Qwen3.5 9B"]["fits"] and rows["Qwen3.5 9B"]["recommended"]   # 16 GB RAM, no GPU
    assert not rows["Qwen3.6 35B-A3B"]["fits"]


def test_zip_archives_unpack_without_their_top_folder_or_only_chosen_files(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("ffmpeg-n8.1-win64/bin/ffmpeg.exe", "ff")
        f.writestr("ffmpeg-n8.1-win64/bin/ffprobe.exe", "fp")
        f.writestr("ffmpeg-n8.1-win64/doc/readme.txt", "r")
    aisetup.extract(z, tmp_path / "all")
    assert (tmp_path / "all/bin/ffmpeg.exe").read_text() == "ff"
    aisetup.extract(z, tmp_path / "bin", only=lambda n: n.endswith((".exe",)))
    assert sorted(p.name for p in (tmp_path / "bin").iterdir()) == ["ffmpeg.exe", "ffprobe.exe"]


def test_downloads_report_progress_and_can_be_cancelled_and_resumed(tmp_path):
    data = b"x" * (5 << 20)

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            start = int(self.headers.get("Range", "bytes=0-")[6:].split("-")[0] or 0)
            self.send_response(206 if start else 200)
            self.send_header("Content-Length", str(len(data) - start))
            self.end_headers()
            for i in range(start, len(data), 1 << 20):
                self.wfile.write(data[i:i + (1 << 20)])
                time.sleep(0.3)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url, dest = f"http://127.0.0.1:{httpd.server_port}/m.gguf", tmp_path / "m.gguf"
    seen = []
    with pytest.raises(aisetup.Cancelled):
        aisetup.download(url, dest, "m", progress=lambda d, t: seen.append(d), cancelled=lambda: len(seen) >= 1)
    assert not dest.exists() and (tmp_path / "m.gguf.part").stat().st_size > 0      # partial file kept
    aisetup.download(url, dest, "m", progress=lambda d, t: None)
    assert dest.read_bytes() == data
    httpd.shutdown()


FAKE_SERVER = textwrap.dedent('''
    import json, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    port = int(sys.argv[sys.argv.index("--port") + 1])
    alias = sys.argv[sys.argv.index("--alias") + 1]
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = {"/health": {"status": "ok"}, "/props": {"default_generation_settings": {"n_ctx": 32768}},
                    "/v1/models": {"data": [{"id": alias}]}}.get(self.path)
            self.send_response(200 if body else 404); self.end_headers()
            self.wfile.write(json.dumps(body or {}).encode())
        def log_message(self, *a): pass
    HTTPServer(("127.0.0.1", port), H).serve_forever()
''')


@pytest.mark.skipif(sys.platform == "win32", reason="the fake engine is a shell-script wrapper")
def test_built_in_ai_starts_on_demand_reports_itself_and_stops(app_dirs):
    build = components.ENGINE_DIR / "b1-cpu"
    build.mkdir(parents=True)
    (build / "fake_server.py").write_text(FAKE_SERVER)
    exe = build / "llama-server"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{build / "fake_server.py"}" "$@"\n')
    exe.chmod(0o755)
    (components.ENGINE_DIR / "current.txt").write_text("b1-cpu")
    components.LLM_DIR.mkdir(parents=True)
    (components.LLM_DIR / "Qwen3.5-4B-Q4_K_M.gguf").write_bytes(b"x")
    cfg = Settings()

    idle = llm.resolve(cfg)                                         # the status light: ready, not loaded
    assert idle.kind == "Built-in AI" and idle.loaded == [] and not engine.ENGINE.running()
    client = llm.LLM(cfg, log=lambda m: None)
    client.wait_ready(timeout=30)                                   # picking clips: loads it
    assert engine.ENGINE.running() and client.model == "Qwen3.5-4B-Q4_K_M" and client.context == 32768
    assert llm.resolve(cfg).loaded == ["Qwen3.5-4B-Q4_K_M"]
    engine.remove_model("Qwen3.5-4B-Q4_K_M.gguf")                   # deleting the model in use stops it first
    assert not engine.ENGINE.running() and engine.model_path(cfg) is None


def test_external_mode_skips_the_built_in_ai(app_dirs, monkeypatch):
    monkeypatch.setattr(components, "engine_exe", lambda: components.ENGINE_DIR / "llama-server")
    components.LLM_DIR.mkdir(parents=True)
    (components.LLM_DIR / "m.gguf").write_bytes(b"x")
    monkeypatch.setattr(llm, "detect", lambda **k: [])
    assert llm.resolve(Settings()).kind == "Built-in AI"
    llm._cache.clear()
    with pytest.raises(RuntimeError, match="No local AI server found|Clippy has no AI to pick clips with yet"):
        llm.resolve(Settings(ai_mode="external"))


def test_a_downloaded_model_is_used_and_gets_its_engine_when_needed(app_dirs, monkeypatch):
    # what happened on Windows: Qwen downloaded in the app, its engine skipped because Ollama was running
    components.LLM_DIR.mkdir(parents=True)
    (components.LLM_DIR / "Qwen3.5-4B-Q4_K_M.gguf").write_bytes(b"x")
    monkeypatch.setattr(llm, "detect", lambda **k: [llm.Server("http://o/v1", "Ollama", ["translategemma:12b"],
                                                               ["translategemma:12b"])])
    s = llm.resolve(Settings())
    assert s.kind == "Built-in AI" and s.models == ["Qwen3.5-4B-Q4_K_M"]     # not Ollama's translation model
    assert "ai" not in components.missing(Settings())
    installs = []

    def fake_engine_install(task, cfg):
        installs.append(cfg)
        if len(installs) == 1:
            raise RuntimeError("no internet")
        build = components.ENGINE_DIR / "b1-cpu"
        build.mkdir(parents=True)
        (build / f"llama-server{components.EXE}").write_bytes(b"x")
        (components.ENGINE_DIR / "current.txt").write_text("b1-cpu")

    name, about, status, _, remove, gb = components.PARTS["engine"]
    monkeypatch.setitem(components.PARTS, "engine", (name, about, status, fake_engine_install, remove, gb))
    with pytest.raises(RuntimeError, match="couldn't download the AI engine \\(no internet\\).*AI & Tools"):
        engine.ensure_engine(Settings())
    logs = []
    engine.ensure_engine(Settings(), log=logs.append)
    assert len(installs) == 2 and components.engine_exe() and "AI engine" in logs[0]
    engine.ensure_engine(Settings())                                          # there now: nothing to do
    engine.ensure_engine(Settings(ai_mode="external"))                        # "Another App": never
    assert len(installs) == 2


def test_another_app_mode_marks_no_built_in_model_as_in_use(app_dirs):
    components.LLM_DIR.mkdir(parents=True)
    (components.LLM_DIR / "Qwen3.5-4B-Q4_K_M.gguf").write_bytes(b"x")
    active = lambda cfg: [m["id"] for m in engine.models(cfg) if m["active"]]
    assert active(Settings()) == ["Qwen3.5-4B-Q4_K_M"]
    assert active(Settings(ai_mode="external")) == []


def test_set_up_everything_ignores_an_app_that_only_has_a_translation_model(app_dirs, monkeypatch):
    found = [llm.Server("http://o/v1", "Ollama", ["translategemma:12b"], ["translategemma:12b"])]
    monkeypatch.setattr(llm, "detect", lambda **k: found)
    assert not engine._other_ai(Settings())                                  # so the built-in AI gets set up
    found[0].models = found[0].recent = ["translategemma:12b", "qwen3.5:9b"]
    llm._cache.clear()
    assert engine._other_ai(Settings())                                      # a good model there: no download
