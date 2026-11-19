"""The AI that picks clips: find a server, choose a model, fit requests into its context window, call it.

Works with llama.cpp, Ollama, LM Studio, Jan, KoboldCpp, vLLM and any other OpenAI-compatible server, on this
machine or, inside WSL, on the Windows side. `llm_url = "auto"` (the default) finds whichever one is running.
"""
from __future__ import annotations

import base64
import concurrent.futures as cf
import ipaddress
import json
import os
import re
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .config import Settings

# Where local AI apps listen by default, in the order Clippy prefers them.
KNOWN_PORTS = {8080: "llama.cpp", 11434: "Ollama", 1234: "LM Studio", 1337: "Jan", 5001: "KoboldCpp",
               8000: "vLLM", 5000: "text-generation-webui", 4891: "GPT4All"}
_NAMED_BY_PORT = {1337, 5001, 8000, 5000, 4891}      # 8080 is shared by llama.cpp and others, so it isn't trusted
NOT_CHAT = re.compile(r"embed|bge|minilm|nomic|rerank|(^|[-_/:])e5[-_]|(^|[-_/:])gte[-_]|mxbai|whisper|tts|clip(?![a-z])",
                      re.I)
CHARS_PER_TOKEN = 3.0     # measured on Clippy's transcript lines with the Qwen tokenizer; other tokenizers do ≥ 3
PROMPT_TOKENS = 800       # the instructions around the transcript (~450 measured) plus a safety margin
OLLAMA_CONTEXT = 16384    # context Clippy asks Ollama for, unless llm_context says otherwise
CONTEXT_ERROR = re.compile(r"context|too long|exceed|n_ctx|maximum.{0,20}length|token limit|too many tokens", re.I)

NO_SERVER_HELP = ("No local AI server found. Clippy looked for llama.cpp, Ollama, LM Studio, Jan, KoboldCpp and vLLM "
                  "on their usual ports{where}. Start one (for example `ollama serve`, then `ollama pull qwen3.5:9b`), "
                  "run `bash setup.sh` to set one up, or enter its address under Settings → AI.")
NO_AI_HELP_WINDOWS = ("Clippy has no AI to pick clips with yet. Open AI & Tools and press Set Up Everything to download "
                      "one, or start Ollama or LM Studio (Clippy finds them by itself), or enter an AI's address under "
                      "Settings → AI.")


class ContextTooSmall(RuntimeError):
    """The server refused a prompt because it doesn't fit its context window."""


@dataclass
class Server:
    base: str                                         # OpenAI-style base URL, usually ending in /v1
    kind: str                                         # llama.cpp | Ollama | LM Studio | OpenAI-compatible | …
    models: list[str]
    loaded: list[str] = field(default_factory=list)   # models already in memory (no load wait)
    context: int = 0                                  # tokens per request, when the server says; 0 = unknown
    recent: list[str] = field(default_factory=list)   # Ollama: newest download first

    @property
    def root(self) -> str:
        return re.sub(r"/v1/?$", "", self.base.rstrip("/"))

    @property
    def where(self) -> str:
        u = urlsplit(self.base)
        return f"{u.hostname}:{u.port}" if u.port else (u.hostname or self.base)

    @property
    def label(self) -> str:
        return self.kind if self.kind == "Built-in AI" else f"{self.kind} at {self.where}"

    def to_dict(self) -> dict:
        return {"label": self.label, "kind": self.kind, "base": self.base, "context": self.context,
                "models": [m for m in self.models if can_chat(m)], "loaded": self.loaded}


# Models made for one narrow job (translating, writing code, filtering unsafe text, reading images): they can chat,
# but pick clips badly, so they're only used when nothing else is there.
SPECIALIST = re.compile(r"translat|nllb|madlad|seamless|opus-mt|guard|shield|ocr|moondream|"
                        r"cod(?:er|ellama|egemma|estral)|starcoder|devstral|math|sql", re.I)
PREFERRED = re.compile(r"qwen3", re.I)                # what Clippy's instructions are written and tested with


def can_chat(model: str) -> bool:
    return bool(model) and not NOT_CHAT.search(model)


def model_rank(model: str) -> int:
    """0: Qwen 3 (Clippy's instructions are made with it), 1: another general model, 2: a specialist."""
    return 2 if SPECIALIST.search(model) else 0 if PREFERRED.search(model) else 1


def choose_model(server: Server, wanted: str = "") -> str:
    """Your setting wins. Otherwise the best kind of model (model_rank), and within a kind one that's already loaded,
    then the newest download. Ollama loads any model by itself, so there the kind comes first; other apps may only
    serve what's loaded, so there a loaded model comes first."""
    if wanted:
        return wanted
    seen: dict[str, tuple] = {}
    for p, pool in enumerate((server.loaded, server.recent, server.models)):
        for i, m in enumerate(pool):
            if can_chat(m) and m not in seen:
                seen[m] = (p == 0, p, i)
    if not seen:
        return ""
    on_demand = server.kind == "Ollama"

    def key(m: str):
        loaded, p, i = seen[m]
        return (model_rank(m), not loaded, p, i) if on_demand else (not loaded, model_rank(m), p, i)
    return min(seen, key=key)


def normalize(url: str) -> str:
    url = url.strip().rstrip("/")
    if "://" not in url:
        url = "http://" + url
    return url + "/v1" if urlsplit(url).path in ("", "/") else url


def _get(client: httpx.Client, url: str):
    try:
        r = client.get(url)
        return r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


def probe(base: str, timeout: float = 1.0, api_key: str = "") -> Server | None:
    """What answers at this address, and which models does it have? None if nothing does."""
    base = normalize(base)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(timeout=timeout, headers=headers) as c:
        data = _get(c, base + "/models")
        if not isinstance(data, dict):
            return None
        rows = data.get("data") or data.get("models") or []
        ids = [m.get("id") or m.get("name") for m in rows if isinstance(m, dict)]
        ids = [i for i in ids if i]
        if not base.endswith("/v1"):                       # a cloud API with its own path: nothing more to ask
            return Server(base, "OpenAI-compatible", ids)
        root = base[:-3]
        ver = _get(c, root + "/api/version")
        if isinstance(ver, dict) and "version" in ver:
            tags = _get(c, root + "/api/tags") or {}
            ps = _get(c, root + "/api/ps") or {}
            recent = [m.get("name") for m in sorted(tags.get("models") or [], key=lambda m: m.get("modified_at") or "",
                                                     reverse=True) if m.get("name")]
            loaded = [m.get("name") or m.get("model") for m in ps.get("models") or []]
            return Server(base, "Ollama", ids or recent, [m for m in loaded if m], 0, recent)
        lms = _get(c, root + "/api/v0/models")
        if isinstance(lms, dict) and isinstance(lms.get("data"), list):
            info = [r for r in lms["data"] if isinstance(r, dict) and r.get("id")]
            chat = [r["id"] for r in info if r.get("type") != "embeddings"]
            loaded = [r for r in info if r.get("state") == "loaded" and r.get("type") != "embeddings"]
            ctx = next((r.get("loaded_context_length") for r in loaded if r.get("loaded_context_length")), 0)
            return Server(base, "LM Studio", [i for i in ids if i in chat] or chat, [r["id"] for r in loaded], int(ctx or 0))
        props = _get(c, root + "/props")
        if isinstance(props, dict) and isinstance(props.get("default_generation_settings"), dict):
            ctx = props["default_generation_settings"].get("n_ctx") or props.get("n_ctx") or 0
            return Server(base, "llama.cpp", ids, list(ids), int(ctx))
        port = urlsplit(base).port
        return Server(base, KNOWN_PORTS[port] if port in _NAMED_BY_PORT else "OpenAI-compatible", ids)


def wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def windows_host(route: str | None = None) -> str | None:
    """Inside WSL (default NAT networking) Windows is the default gateway, so apps running there are on its IP."""
    if route is None:
        try:
            route = Path("/proc/net/route").read_text()
        except OSError:
            return None
    for line in route.splitlines()[1:]:
        f = line.split()
        if len(f) > 2 and f[1] == "00000000" and f[2] != "00000000":
            try:
                return socket.inet_ntoa(struct.pack("<L", int(f[2], 16)))
            except (ValueError, struct.error):
                return None
    return None


def _hosts() -> list[str]:
    hosts = ["127.0.0.1"]
    if wsl() and (h := windows_host()):
        hosts.append(h)
    return hosts


def detect(ports=None, hosts=None, timeout: float = 0.8) -> list[Server]:
    """Every AI server answering on the usual ports; ones with a chat model already loaded come first."""
    ports = list(ports or KNOWN_PORTS)
    urls = [f"http://{h}:{p}/v1" for h in (hosts or _hosts()) for p in ports]
    with cf.ThreadPoolExecutor(max_workers=min(32, len(urls))) as ex:
        found = [s for s in ex.map(lambda u: probe(u, timeout), urls) if s]
    order = {u: i for i, u in enumerate(urls)}
    found.sort(key=lambda s: (not any(can_chat(m) for m in s.loaded), order.get(s.base, 99)))
    return found


_cache: dict = {}
_last_seen = {"t": 0.0}


def resolve(cfg: Settings, max_age: float = 20, start: bool = False) -> Server:
    """The server Clippy should talk to right now (remembered for a few seconds). The built-in AI comes first when a
    model is downloaded for it; `start` loads it (otherwise it's reported as ready but not running)."""
    mode = (getattr(cfg, "ai_mode", "auto") or "auto").lower()
    if mode in ("auto", "builtin"):
        from . import engine
        if (s := engine.server(cfg, start=start)) is not None:
            return s
        if mode == "builtin":
            raise RuntimeError("The built-in AI has no model yet. Open AI & Tools and download one.")
    key = (cfg.llm_url, cfg.llm_api_key)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    url = (cfg.llm_url or "auto").strip()
    if url.lower() == "auto":
        found = detect()
        if not found:
            if sys.platform == "win32":
                raise RuntimeError(NO_AI_HELP_WINDOWS)
            raise RuntimeError(NO_SERVER_HELP.format(where=" here and on Windows" if wsl() else ""))
        server = found[0]
    else:
        server = probe(url, timeout=3, api_key=cfg.llm_api_key)
        if server is None:
            others = [s.label for s in detect() if s.base != normalize(url)]
            hint = (f" Found {', '.join(others)} instead: set the server address to “auto” under Settings → AI to use it."
                    if others else "")
            raise RuntimeError(f"The AI server at {url} isn't answering.{hint} Start it, or change the address in Settings.")
    _cache[key] = (time.time(), server)
    _last_seen["t"] = time.time()
    return server


def start_local_ai(cfg: Settings) -> str:
    """Nothing answers: start an installed AI server (a stopped systemd service, or Ollama). Only called right before
    clips are picked, never while Whisper may have paused the service on purpose. Returns what was started."""
    import shutil
    import subprocess

    from . import gpu
    if gpu.service_known(cfg.llama_service) and not gpu.service_active(cfg.llama_service):
        gpu.start_service(cfg.llama_service, log=lambda m: None)
        return f"the {cfg.llama_service} service"
    if shutil.which("ollama"):
        try:
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return "Ollama (ollama serve)"
        except OSError:
            pass
    if shutil.which("llama-coder") and not gpu.service_known(cfg.llama_service):
        try:
            subprocess.Popen(["llama-coder"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return "llama-coder"
        except OSError:
            pass
    return ""


def unload_ollama(root: str | None = None, timeout: float = 15) -> list[str]:
    """Ask Ollama to drop its models from GPU memory now; it loads them again by itself on the next request."""
    roots = [root.rstrip("/")] if root else ["http://127.0.0.1:11434"] + (
        [f"http://{h}:11434"] if wsl() and (h := windows_host()) else [])
    freed = []
    for r in roots:
        try:
            ps = httpx.get(r + "/api/ps", timeout=2).json()
        except (httpx.HTTPError, ValueError):
            continue
        for m in ps.get("models") or []:
            name = m.get("name") or m.get("model")
            try:
                httpx.post(r + "/api/generate", json={"model": name, "keep_alive": 0}, timeout=timeout)
                freed.append(name)
            except httpx.HTTPError:
                pass
    return freed


def parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise ValueError("no JSON in model output")


def _is_local(base: str) -> bool:
    host = urlsplit(base).hostname or ""
    if host in ("localhost", "0.0.0.0"):
        return True
    try:
        return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class LLM:
    def __init__(self, cfg: Settings, log=print):
        self.cfg = cfg
        self.log = log
        self.server: Server | None = None
        self.base = "" if (cfg.llm_url or "auto").lower() == "auto" else normalize(cfg.llm_url)
        self.local = _is_local(self.base) if self.base else True
        self.model = cfg.llm_model
        self.context = 0
        self.headers = {"Content-Type": "application/json"}
        if cfg.llm_api_key:
            self.headers["Authorization"] = f"Bearer {cfg.llm_api_key}"
        self._schema_ok = True
        self._kwargs_ok = True
        self._think: bool | None = None      # Ollama: True when the model can "think" (so it must be told not to)
        self._vision: bool | None = None     # can the model see images (clippy/vision.py); None = not asked yet

    @property
    def kind(self) -> str:
        return self.server.kind if self.server else "OpenAI-compatible"

    def wait_ready(self, timeout: float = 300, progress=lambda m: None) -> None:
        """Connect to the AI server; waits for one that is (re)starting, gives up fast if none is expected."""
        from . import engine, gpu
        engine.ensure_engine(self.cfg, log=self.log, progress=progress)   # a downloaded model needs its engine
        expected = (self.base or gpu.service_known(self.cfg.llama_service) or time.time() - _last_seen["t"] < 3600)
        limit = timeout if expected else min(timeout, 6)
        t0, started = time.time(), False
        while True:
            try:
                self._use(resolve(self.cfg, start=True))
                return
            except RuntimeError as e:
                if not started and not self.base:
                    started = True
                    if how := start_local_ai(self.cfg):
                        self.log(f"No AI server was running, so Clippy started {how}")
                        limit = max(limit, 90)
                        continue
                if time.time() - t0 >= limit:
                    raise
                progress(f"Waiting for the AI server ({int(time.time() - t0)}s)… {str(e)[:80]}")
            time.sleep(2)

    def _use(self, s: Server) -> None:
        self.server, self.base, self.local = s, s.base, _is_local(s.base)
        self.model = choose_model(s, self.cfg.llm_model)
        if s.kind == "Ollama":
            info = self._post(s.root + "/api/show", {"model": self.model}, 20) or {}
            top = next((v for k, v in (info.get("model_info") or {}).items() if k.endswith(".context_length")), 0)
            want = self.cfg.llm_context or OLLAMA_CONTEXT
            self.context = min(want, int(top)) if top else want
            self._think = "thinking" in (info.get("capabilities") or [])
            self._vision = "vision" in (info.get("capabilities") or [])
        else:
            self.context = self.cfg.llm_context or s.context
            if s.kind == "LM Studio" and 0 < s.context < 12000:
                self.log(f"LM Studio loaded {self.model} with a {s.context}-token context, so Clippy reads the video in "
                         f"small pieces. Load it with 16384 or more for faster, better picks.")

    def _post(self, url: str, body: dict, timeout: float):
        try:
            r = httpx.post(url, json=body, headers=self.headers, timeout=timeout)
            return r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

    def budget_chars(self, out_tokens: int = 3000) -> int:
        """How much transcript fits in one request next to the instructions and the answer."""
        cap = self.cfg.llm_chunk_chars
        if not self.context:
            return cap
        return max(3000, min(cap, int((self.context - out_tokens - PROMPT_TOKENS) * CHARS_PER_TOKEN)))

    def can_see(self) -> bool:
        """Whether the model takes images: llama.cpp (and the built-in AI) say so in /props once it has its mmproj,
        Ollama in the model's capabilities. Other servers: no (Clippy doesn't guess)."""
        if self._vision is None:
            if self.server is None:
                self.wait_ready(timeout=30)
            if self._vision is None:
                self._vision = False
                if self.kind in ("llama.cpp", "Built-in AI"):
                    try:
                        r = httpx.get(self.server.root + "/props", headers=self.headers, timeout=5)
                        self._vision = bool(((r.json() or {}).get("modalities") or {}).get("vision"))
                    except (httpx.HTTPError, ValueError, AttributeError):
                        pass
        return bool(self._vision)

    def json(self, system: str, user: str, schema: dict, max_tokens: int = 3000, temperature: float = 0.4,
             images: list[bytes] | None = None) -> dict:
        """images: JPEGs to show the model with the prompt (only for a model that can_see())."""
        if self.server is None:
            self.wait_ready(timeout=30)
        if self.kind == "Built-in AI":
            from . import engine
            if not engine.ENGINE.running():             # stopped for Whisper or after idling: load it again
                self._use(resolve(self.cfg, start=True))
            engine.ENGINE.touch()
        if self.kind == "Ollama":
            return self._ollama_json(system, user, schema, max_tokens, temperature, images)
        content: str | list = user
        if images:
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(j).decode()}}
                for j in images]
        body: dict = {"model": self.model or "default", "temperature": temperature, "max_tokens": max_tokens,
                      "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        schema_ok, kwargs_ok = self._schema_ok, self._kwargs_ok
        for attempt in range(3):
            b = dict(body)
            if schema_ok:
                b["response_format"] = {"type": "json_schema",
                                        "json_schema": {"name": "result", "schema": schema, "strict": True}}
            else:
                b["response_format"] = {"type": "json_object"}
            if self.local and kwargs_ok:
                b["chat_template_kwargs"] = {"enable_thinking": bool(self.cfg.llm_thinking)}
            try:
                r = httpx.post(self.base + "/chat/completions", headers=self.headers, json=b, timeout=1200)
            except httpx.HTTPError as e:
                if attempt == 2:
                    raise RuntimeError(f"AI request failed: {e}")
                time.sleep(3)
                continue
            if r.status_code in (400, 413, 422) and (len(user) > 2000 or images) and CONTEXT_ERROR.search(r.text):
                raise ContextTooSmall(r.text[:300])
            if r.status_code == 400 and (schema_ok or "chat_template_kwargs" in b):
                # provider doesn't support json_schema or chat_template_kwargs → degrade gracefully
                if "chat_template_kwargs" in b:
                    kwargs_ok = False
                else:
                    schema_ok = False
                if not images:                  # with pictures, the 400 may be about them: just for this request
                    self._schema_ok, self._kwargs_ok = schema_ok, kwargs_ok
                continue
            if images and r.status_code in (400, 413, 422):     # the pictures were refused: say so
                raise RuntimeError(f"AI server error {r.status_code}: {r.text[:300]}")
            if r.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise RuntimeError(f"AI server error {r.status_code}: {r.text[:300]}")
            choice = r.json()["choices"][0]
            content = choice["message"].get("content") or ""
            try:
                return parse_json(content)
            except ValueError:
                if choice.get("finish_reason") == "length" and len(user) > 2000:
                    raise ContextTooSmall("the answer was cut off: the prompt left too little room in the context window")
                if attempt == 2:
                    raise RuntimeError(f"AI returned invalid JSON: {content[:300]}")
        raise RuntimeError("AI request failed after retries")

    def _ollama_json(self, system: str, user: str, schema: dict, max_tokens: int, temperature: float,
                     images: list[bytes] | None = None) -> dict:
        """Ollama's own API: the only way to give it a big enough context (its OpenAI endpoint silently cuts prompts)."""
        msg: dict = {"role": "user", "content": user}
        if images:
            msg["images"] = [base64.b64encode(j).decode() for j in images]
        body: dict = {"model": self.model, "stream": False, "keep_alive": "10m",
                      "messages": [{"role": "system", "content": system}, msg],
                      "format": schema if self._schema_ok else "json",
                      "options": {"temperature": temperature, "num_ctx": self.context, "num_predict": max_tokens}}
        if self._think:
            body["think"] = bool(self.cfg.llm_thinking)
        for attempt in range(3):
            try:
                r = httpx.post(self.server.root + "/api/chat", json=body, timeout=1200)
            except httpx.HTTPError as e:
                if attempt == 2:
                    raise RuntimeError(f"AI request failed: {e}")
                time.sleep(3)
                continue
            err = r.text[:300]
            if r.status_code == 404 and "not found" in err:
                raise RuntimeError(f"Ollama doesn't have the model {self.model}. Download it with: ollama pull {self.model}")
            if r.status_code == 400 and "think" in err and "think" in body:
                del body["think"]
                continue
            if r.status_code in (400, 500) and self._schema_ok and "format" in err:
                self._schema_ok, body["format"] = False, "json"
                continue
            if r.status_code != 200:
                if CONTEXT_ERROR.search(err) and len(user) > 2000:
                    raise ContextTooSmall(err)
                raise RuntimeError(f"Ollama error {r.status_code}: {err}")
            data = r.json()
            content = (data.get("message") or {}).get("content") or ""
            try:
                return parse_json(content)
            except ValueError:
                if data.get("done_reason") == "length" and len(user) > 2000:
                    raise ContextTooSmall("the answer was cut off: the prompt left too little room in the context window")
                if attempt == 2:
                    raise RuntimeError(f"AI returned invalid JSON: {content[:300]}")
        raise RuntimeError("AI request failed after retries")
