"""Finding and talking to local AI servers (llama.cpp, Ollama, LM Studio, anything OpenAI-compatible)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from clippy import llm
from clippy.config import Settings


def fake_server(routes: dict):
    """routes: {(method, path): (status, body) or callable(body_dict) -> (status, body)}. Returns (base_url, calls, stop)."""
    calls = []

    class H(BaseHTTPRequestHandler):
        def _go(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            calls.append((method, self.path, body))
            hit = routes.get((method, self.path))
            if hit is None:
                status, out = 404, {"error": "not found"}
            else:
                status, out = hit(body) if callable(hit) else hit
            data = json.dumps(out).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._go("GET")

        def do_POST(self):
            self._go("POST")

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_port}", calls, httpd.shutdown


OLLAMA = {
    ("GET", "/v1/models"): (200, {"data": [{"id": "nomic-embed-text:latest"}, {"id": "qwen3.5:9b"}, {"id": "gemma3:4b"}]}),
    ("GET", "/api/version"): (200, {"version": "0.13.0"}),
    ("GET", "/api/tags"): (200, {"models": [
        {"name": "nomic-embed-text:latest", "size": 274_000_000, "modified_at": "2026-11-10T10:00:00Z"},
        {"name": "gemma3:4b", "size": 3_300_000_000, "modified_at": "2026-10-01T10:00:00Z"},
        {"name": "qwen3.5:9b", "size": 6_600_000_000, "modified_at": "2026-11-01T10:00:00Z"}]}),
    ("GET", "/api/ps"): (200, {"models": []}),
}
LMSTUDIO = {
    ("GET", "/v1/models"): (200, {"data": [{"id": "text-embedding-nomic-embed-text-v1.5"}, {"id": "qwen3.5-9b"}, {"id": "gemma-3-12b"}]}),
    ("GET", "/api/v0/models"): (200, {"data": [
        {"id": "text-embedding-nomic-embed-text-v1.5", "type": "embeddings", "state": "not-loaded"},
        {"id": "qwen3.5-9b", "type": "llm", "state": "not-loaded", "max_context_length": 262144},
        {"id": "gemma-3-12b", "type": "vlm", "state": "loaded", "max_context_length": 131072, "loaded_context_length": 8192}]}),
}
LLAMACPP = {
    ("GET", "/v1/models"): (200, {"data": [{"id": "qwen3.6-heretic"}]}),
    ("GET", "/props"): (200, {"default_generation_settings": {"n_ctx": 65536}, "total_slots": 1}),
}


@pytest.fixture
def serve():
    stops = []

    def start(routes):
        base, calls, stop = fake_server(routes)
        stops.append(stop)
        return base, calls

    yield start
    for s in stops:
        s()


def test_probe_recognises_ollama_and_its_models(serve):
    base, _ = serve(OLLAMA)
    s = llm.probe(base + "/v1")
    assert s.kind == "Ollama" and s.base == base + "/v1"
    assert s.models == ["nomic-embed-text:latest", "qwen3.5:9b", "gemma3:4b"]
    assert s.loaded == []


def test_probe_recognises_lm_studio_with_loaded_model_and_its_context(serve):
    base, _ = serve(LMSTUDIO)
    s = llm.probe(base + "/v1")
    assert s.kind == "LM Studio"
    assert s.loaded == ["gemma-3-12b"] and s.context == 8192
    assert "text-embedding-nomic-embed-text-v1.5" not in s.models       # LM Studio says it's an embedding model


def test_probe_recognises_llama_cpp_and_reads_its_context(serve):
    base, _ = serve(LLAMACPP)
    s = llm.probe(base + "/v1")
    assert s.kind == "llama.cpp" and s.context == 65536 and s.loaded == ["qwen3.6-heretic"]


def test_probe_falls_back_to_plain_openai_compatible(serve):
    base, _ = serve({("GET", "/v1/models"): (200, {"data": [{"id": "my-model"}]})})
    s = llm.probe(base + "/v1")
    assert s.kind == "OpenAI-compatible" and s.models == ["my-model"]


def test_probe_returns_none_when_nothing_answers():
    assert llm.probe("http://127.0.0.1:9/v1", timeout=0.3) is None


def test_choose_model_skips_embeddings_and_prefers_what_is_loaded():
    ollama = llm.Server("http://x/v1", "Ollama", ["nomic-embed-text:latest", "qwen3.5:9b", "gemma3:4b"], [],
                        recent=["nomic-embed-text:latest", "qwen3.5:9b", "gemma3:4b"])
    assert llm.choose_model(ollama) == "qwen3.5:9b"                   # newest pull that can chat
    ollama.loaded = ["gemma3:4b"]
    assert llm.choose_model(ollama) == "gemma3:4b"                    # already in memory: no load wait
    assert llm.choose_model(ollama, "llama3.2:3b") == "llama3.2:3b"   # your setting always wins
    embed_only = llm.Server("http://x/v1", "OpenAI-compatible", ["bge-m3", "text-embedding-3-small"], [])
    assert llm.choose_model(embed_only) == ""


def test_detect_finds_servers_on_the_given_ports_loaded_ones_first(serve):
    a, _ = serve(OLLAMA)
    b, _ = serve(LLAMACPP)
    pa, pb = int(a.rsplit(":", 1)[1]), int(b.rsplit(":", 1)[1])
    found = llm.detect(ports=[pa, pb, 9], hosts=["127.0.0.1"], timeout=0.5)
    assert [s.kind for s in found] == ["llama.cpp", "Ollama"]         # llama.cpp has a model loaded


def test_windows_host_is_read_from_the_wsl_default_route():
    route = ("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
             "eth0\t00000000\t0150A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
             "eth0\t0050A8C0\t00000000\t0001\t0\t0\t0\t00F0FFFF\t0\t0\t0\n")
    assert llm.windows_host(route) == "192.168.80.1"
    assert llm.windows_host("Iface\tDestination\tGateway\n") is None


def test_resolve_explains_what_to_do_when_no_ai_is_running(monkeypatch):
    monkeypatch.setattr(llm, "detect", lambda **k: [])
    llm._cache.clear()
    with pytest.raises(RuntimeError) as e:
        llm.resolve(Settings(llm_url="auto"))
    msg = str(e.value)
    assert "No local AI server found" in msg and "ollama" in msg.lower() and "Settings" in msg


def test_resolve_uses_an_explicit_url_and_suggests_others_when_it_is_down(monkeypatch, serve):
    base, _ = serve(LLAMACPP)
    llm._cache.clear()
    assert llm.resolve(Settings(llm_url=base + "/v1")).kind == "llama.cpp"
    monkeypatch.setattr(llm, "detect", lambda **k: [llm.Server("http://127.0.0.1:11434/v1", "Ollama", ["qwen3.5:9b"], [])])
    llm._cache.clear()
    with pytest.raises(RuntimeError) as e:
        llm.resolve(Settings(llm_url="http://127.0.0.1:9/v1"))
    assert "Ollama at 127.0.0.1:11434" in str(e.value)


def test_ollama_requests_use_the_native_api_with_a_big_enough_context(serve):
    def chat(body):
        return 200, {"message": {"role": "assistant", "content": '{"ok": true}'}, "done": True}
    routes = dict(OLLAMA)
    routes[("POST", "/api/show")] = (200, {"capabilities": ["completion", "thinking"],
                                           "model_info": {"qwen35.context_length": 262144}})
    routes[("POST", "/api/chat")] = chat
    base, calls = serve(routes)
    llm._cache.clear()
    client = llm.LLM(Settings(llm_url=base + "/v1"), log=lambda m: None)
    client.wait_ready(timeout=5)
    assert client.model == "qwen3.5:9b" and client.context == 16384
    assert client.json("sys", "user", {"type": "object"}, max_tokens=500) == {"ok": True}
    body = next(b for m, p, b in calls if p == "/api/chat")
    assert body["options"]["num_ctx"] == 16384 and body["options"]["num_predict"] == 500
    assert body["format"] == {"type": "object"} and body["think"] is False and body["stream"] is False


def test_too_long_prompts_raise_context_too_small(serve):
    routes = dict(LLAMACPP)
    routes[("POST", "/v1/chat/completions")] = (400, {"error": {"message": "the request exceeds the available context size (4096 tokens)"}})
    base, _ = serve(routes)
    llm._cache.clear()
    client = llm.LLM(Settings(llm_url=base + "/v1"), log=lambda m: None)
    client.wait_ready(timeout=5)
    with pytest.raises(llm.ContextTooSmall):
        client.json("sys", "x" * 50000, {"type": "object"})


def test_transcript_budget_follows_the_server_context():
    c = llm.LLM(Settings(), log=lambda m: None)
    c.context = 65536
    assert c.budget_chars(out_tokens=3000) == 60000                    # capped by llm_chunk_chars
    c.context = 16384
    assert 30000 < c.budget_chars(out_tokens=3000) < 38000
    c.context = 4096
    assert c.budget_chars(out_tokens=1700) >= 3000                     # never absurdly small
    c.context = 0
    assert c.budget_chars(out_tokens=3000) == 60000                    # unknown: start big, shrink on error


def test_unload_ollama_frees_every_loaded_model(serve):
    routes = dict(OLLAMA)
    routes[("GET", "/api/ps")] = (200, {"models": [{"name": "qwen3.5:9b"}, {"name": "gemma3:4b"}]})
    routes[("POST", "/api/generate")] = (200, {"done": True})
    base, calls = serve(routes)
    assert llm.unload_ollama(base) == ["qwen3.5:9b", "gemma3:4b"]
    sent = [b for m, p, b in calls if p == "/api/generate"]
    assert sent == [{"model": "qwen3.5:9b", "keep_alive": 0}, {"model": "gemma3:4b", "keep_alive": 0}]


def test_an_answer_cut_off_by_the_context_window_also_counts_as_too_long(serve):
    # llama.cpp, KoboldCpp & co. don't refuse a prompt that fits; they stop writing when the window is full
    routes = dict(LLAMACPP)
    routes[("POST", "/v1/chat/completions")] = (200, {"choices": [{"finish_reason": "length",
                                                                   "message": {"content": '{"clips": [{"start_id": 3, "wh'}}]})
    base, _ = serve(routes)
    llm._cache.clear()
    client = llm.LLM(Settings(llm_url=base + "/v1"), log=lambda m: None)
    client.wait_ready(timeout=5)
    with pytest.raises(llm.ContextTooSmall):
        client.json("sys", "x" * 9000, {"type": "object"})


def test_waiting_for_the_ai_starts_an_installed_one_when_none_is_running(monkeypatch, serve):
    base, _ = serve(LLAMACPP)
    started = []

    def fake_resolve(cfg, max_age=20):
        if not started:
            raise RuntimeError("No local AI server found.")
        return llm.probe(base + "/v1")

    monkeypatch.setattr(llm, "resolve", fake_resolve)
    monkeypatch.setattr(llm, "start_local_ai", lambda cfg: started.append(1) or "Ollama (ollama serve)")
    logs = []
    client = llm.LLM(Settings(llm_url="auto"), log=logs.append)
    client.wait_ready(timeout=10)
    assert started == [1] and client.server.kind == "llama.cpp"
    assert any("Clippy started Ollama" in m for m in logs)
