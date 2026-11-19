"""The built-in AI: a model catalog, downloads into Clippy's own folder, and a llama.cpp server that Clippy starts
when it needs it, stops when Whisper needs the graphics card, and stops again after a while without use."""
from __future__ import annotations

import atexit
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import aisetup, components, config

ABOUT = {
    "big": ("Qwen3.6 35B-A3B", "Best picks. It runs partly from RAM, so it needs about 24 GB of RAM; a graphics card makes it fast."),
    "medium": ("Qwen3.5 9B", "Good picks, quick with an 8 GB graphics card or 16 GB of RAM."),
    "small": ("Qwen3.5 4B", "Small and fast. Works on any PC, even without a graphics card."),
}
CATALOG = [{"id": m["file"].removesuffix(".gguf"), "name": ABOUT[m["size"]][0], "about": ABOUT[m["size"]][1],
            "file": m["file"], "url": f"https://huggingface.co/{m['repo']}/resolve/main/{m['file']}",
            "page": f"https://huggingface.co/{m['repo']}", "gb": m["gb"], "fits": m["fits"],
            "mmproj_url": f"https://huggingface.co/{m['repo']}/resolve/main/{m['mmproj']}" if m.get("mmproj") else "",
            "mmproj_gb": m.get("mmproj_gb", 0)} for m in aisetup.GGUF_MODELS]
CONTEXT = 32768


def _files() -> list[Path]:
    d = components.LLM_DIR
    return sorted(p for p in d.glob("*.gguf") if "mmproj" not in p.name.lower()) if d.exists() else []


def vision_file(model: Path) -> Path:
    """A model's vision file (mmproj), kept next to it: Qwen3.5-4B-Q4_K_M.gguf → Qwen3.5-4B-Q4_K_M.mmproj.gguf."""
    return model.with_name(model.stem + ".mmproj.gguf")


def model_path(cfg) -> Path | None:
    """The model the built-in AI uses: your choice, or the only one downloaded."""
    files = _files()
    if cfg.ai_model and (p := components.LLM_DIR / cfg.ai_model).exists():
        return p
    return files[0] if len(files) == 1 else (max(files, key=lambda p: p.stat().st_mtime) if files else None)


def has_ai(cfg) -> bool:
    """Can Clippy pick clips: a built-in model ready, or another AI app running?"""
    if components.engine_exe() and model_path(cfg):
        return True
    from . import llm
    try:
        llm.resolve(cfg)
        return True
    except RuntimeError:
        return False


def recommended(hw: dict) -> str:
    return next((m["id"] for m in CATALOG if m["fits"](hw["vram_mb"], hw["ram_mb"])), CATALOG[-1]["id"])


def models(cfg) -> list[dict]:
    hw = components.hardware()
    active = model_path(cfg)
    builtin = (cfg.ai_mode or "auto").lower() != "external"      # "Another App" doesn't use these
    rows = []
    for m in CATALOG:
        p = components.LLM_DIR / m["file"]
        t = components.TASKS.get("model:" + m["id"])
        vt = components.TASKS.get("vision:" + m["id"])
        if not (t and t.state != "done") and vt and vt.state != "done":
            t = vt                                       # adding vision shows on the model's row
        vision = "ready" if vision_file(p).exists() else "missing" if m["mmproj_url"] and p.exists() else "none"
        rows.append({k: v for k, v in m.items() if k != "fits"} | {
            "installed": p.exists(), "active": active == p and builtin, "fits": m["fits"](hw["vram_mb"], hw["ram_mb"]),
            "recommended": m["id"] == recommended(hw), "task": t.to_dict() if t and t.state != "done" else None,
            "vision": vision})
    known = {m["file"] for m in CATALOG}
    for p in _files():                                  # models added from a link
        if p.name not in known:
            rows.append({"id": p.stem, "name": p.stem, "about": "Added by you", "file": p.name, "url": "", "page": "",
                         "gb": round(p.stat().st_size / 1e9, 1), "installed": True, "active": active == p and builtin,
                         "fits": True,
                         "recommended": False, "task": None, "custom": True})
    return rows


def hf_link(url: str) -> tuple[str, str]:
    """A Hugging Face .gguf link (file page or download link) → (download URL, file name)."""
    url = url.strip()
    u = urlsplit(url)
    if u.netloc not in ("huggingface.co", "www.huggingface.co") or not u.path.lower().endswith(".gguf"):
        raise ValueError("Paste a link to a .gguf file on huggingface.co (open the file there and copy the address).")
    path = u.path.replace("/blob/", "/resolve/", 1)
    if "/resolve/" not in path:
        raise ValueError("That link isn't to a single file. Open the .gguf file on Hugging Face and copy its address.")
    return f"https://huggingface.co{path}", Path(path).name


def install_model(mid: str = "", url: str = "") -> components.Task:
    if url:
        link, name = hf_link(url)
        tid, label = "model:" + Path(name).stem, Path(name).stem
    else:
        m = next((m for m in CATALOG if m["id"] == mid), None)
        if not m:
            raise KeyError(mid)
        link, name, tid, label = m["url"], m["file"], "model:" + m["id"], m["name"]
    free = components.hardware()["disk_free_mb"] * 1024 * 1024

    def go(t: components.Task):
        r = httpx.head(link, follow_redirects=True, timeout=30)
        size = int(r.headers.get("Content-Length") or 0)
        if size and size + 2e9 > free:
            raise RuntimeError(f"Not enough free disk space: {aisetup.human(size)} needed plus 2 GB to spare.")
        components.fetch(link, components.LLM_DIR / name, t, label)
        if m_url := (m.get("mmproj_url") if not url else ""):
            if str(config.load().vision).lower() != "off":   # its eyes: framing and rating clips by looking
                t.label, t.done, t.total = f"Vision for {label}", 0, 0
                components.fetch(m_url, vision_file(components.LLM_DIR / name), t, f"Vision for {label}")
        if not components.engine_exe():                  # a model is no use without the engine that runs it
            t.label, t.done, t.total = "AI engine", 0, 0
            components.PARTS["engine"][3](t, config.load())

    return components.run_task(tid, label, go)


def install_vision(mid: str) -> components.Task:
    """Add the vision file to a catalog model that's already downloaded."""
    m = next((m for m in CATALOG if m["id"] == mid and m["mmproj_url"]), None)
    if not m:
        raise KeyError(mid)

    def go(t: components.Task):
        components.fetch(m["mmproj_url"], vision_file(components.LLM_DIR / m["file"]), t, f"Vision for {m['name']}")
        if ENGINE.model == components.LLM_DIR / m["file"]:
            ENGINE.stop()                                 # loads again with its eyes next time

    return components.run_task("vision:" + mid, f"Vision for {m['name']}", go)


def remove_model(file: str) -> None:
    p = components.LLM_DIR / Path(file).name
    if ENGINE.model == p:
        ENGINE.stop()
    p.unlink(missing_ok=True)
    vision_file(p).unlink(missing_ok=True)
    (components.DOWNLOADS / (p.name + ".part")).unlink(missing_ok=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Engine:
    """One llama-server process, owned by Clippy."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.model: Path | None = None
        self.vision = False
        self.port = 0
        self.context = 0
        self.last_used = 0.0
        self.idle_minutes = 10
        self.lock = threading.RLock()
        self._watch: threading.Thread | None = None

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self, cfg, model: Path) -> None:
        with self.lock:
            see = vision_file(model).exists() and str(getattr(cfg, "vision", "auto")).lower() != "off"
            if self.running() and self.model == model and self.vision == see:
                self.touch()
                return
            self.stop()
            exe = components.engine_exe()
            if not exe:
                raise RuntimeError("The AI engine isn't set up yet. Open AI & Tools and press Set Up.")
            hw = components.hardware()
            port = _free_port()
            log_dir = config.ROOT / "data"
            log_dir.mkdir(exist_ok=True)
            log_file = log_dir / "engine.log"
            try:
                if log_file.stat().st_size > 5_000_000:
                    log_file.replace(log_dir / "engine.old.log")   # keep the log from growing forever
            except OSError:                                         # none yet, or still open somewhere
                pass
            # the model by its name, from its own folder: Clippy's folder may have letters like ö or 测 in its path
            args = [str(exe), "-m", model.name, "--alias", model.stem, "--host", "127.0.0.1", "--port", str(port),
                    "-c", str(cfg.ai_context or CONTEXT), "--parallel", "1", "--threads", str(hw["threads"]),
                    "--fit", "on", "--fit-target", "4500" if hw["vram_mb"] >= 10 * 1024 else "1024"]
            if see:                                      # its eyes (clippy/vision.py), by name from the same folder
                args += ["--mmproj", vision_file(model).name]
            # Windows: tied to Clippy (clippy/quiet.py), so it ends when Clippy does, even if Clippy crashes
            extra = {"start_new_session": True} if sys.platform != "win32" else components.hidden()
            with open(log_file, "ab") as log:
                self.proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                             cwd=model.parent, **extra)
            self.model, self.port, self.vision = model, port, see
            t0 = time.time()
            while time.time() - t0 < 600:               # a big model can take a while to load from disk
                if self.proc.poll() is not None:
                    tail = log_file.read_bytes()[-600:].decode(errors="replace")
                    self.proc = None
                    raise RuntimeError(f"The AI engine stopped while loading {model.stem}. Last lines of its log:\n{tail}")
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                self.stop()
                raise RuntimeError(f"The AI engine took too long to load {model.stem}.")
            try:
                props = httpx.get(f"http://127.0.0.1:{port}/props", timeout=5).json()
                self.context = int(props["default_generation_settings"]["n_ctx"])
            except (httpx.HTTPError, KeyError, ValueError, TypeError):
                self.context = cfg.ai_context or CONTEXT
            self.idle_minutes = max(1, int(cfg.ai_idle_minutes or 10))
            self.touch()
            if not self._watch or not self._watch.is_alive():
                self._watch = threading.Thread(target=self._idle_watch, daemon=True, name="engine-idle")
                self._watch.start()

    def stop(self) -> None:
        with self.lock:
            p, self.proc = self.proc, None
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(15)
                except subprocess.TimeoutExpired:
                    p.kill()

    def touch(self) -> None:
        self.last_used = time.time()

    def _idle_watch(self) -> None:
        while True:
            time.sleep(30)
            if self.running() and time.time() - self.last_used > self.idle_minutes * 60:
                self.stop()                              # frees RAM and graphics memory; starts again when needed


ENGINE = Engine()
atexit.register(ENGINE.stop)


def ensure_engine(cfg, log=lambda m: None, progress=lambda m: None) -> None:
    """A model is downloaded for the built-in AI but the engine that runs it isn't (it was skipped because another AI
    app was found, or removed): get it now, once, like Whisper downloads itself on the first video."""
    if components.engine_exe() or (cfg.ai_mode or "auto").lower() == "external" or model_path(cfg) is None:
        return
    log("Getting the AI engine that runs your downloaded model (about 600 MB, only this once)…")
    t = components.install("engine", cfg)
    while t.state == "running":
        progress(f"Getting the AI engine… {aisetup.human(t.done)} of {aisetup.human(t.total)}" if t.total
                 else "Getting the AI engine…")
        time.sleep(1)
    if t.state != "done" or not components.engine_exe():
        raise RuntimeError(f"Clippy couldn't download the AI engine ({t.error or t.state}). Open AI & Tools and press "
                           "Download next to AI engine.")


def server(cfg, start: bool = False):
    """The built-in AI as an llm.Server; started first when `start` is set (getting its engine first if needed).
    None without a downloaded model."""
    from .llm import Server
    model = model_path(cfg)
    if not model:
        return None
    if start:
        ensure_engine(cfg)
        ENGINE.start(cfg, model)
    running = ENGINE.running() and ENGINE.model == model
    return Server(ENGINE.base if running else "", "Built-in AI", [model.stem],
                  [model.stem] if running else [], ENGINE.context if running else 0)


def setup_everything(cfg) -> components.Task:
    """One button: every missing part plus the recommended AI model (unless an AI is already available)."""
    def go(t: components.Task):
        for c in components.components(cfg):
            if not c["installed"] and c["id"] != "engine":
                t.label = c["name"]
                components.PARTS[c["id"]][3](t, cfg)
                t.done = t.total = 0
        if model_path(cfg) is None and not _other_ai(cfg):
            m = next(m for m in CATALOG if m["id"] == recommended(components.hardware()))
            t.label = m["name"]
            components.fetch(m["url"], components.LLM_DIR / m["file"], t, m["name"])
        if model_path(cfg) is not None and not components.engine_exe() and (cfg.ai_mode or "auto") != "external":
            t.label, t.done, t.total = "AI engine", 0, 0       # the model downloaded earlier needs it too
            components.PARTS["engine"][3](t, cfg)
        components.ensure_path()
    return components.run_task("everything", "Setting up", go)


def _other_ai(cfg) -> bool:
    from . import llm
    if (cfg.ai_mode or "auto") == "builtin":
        return False
    try:
        s = llm.resolve(cfg)
    except RuntimeError:
        return False
    # an app with only a specialist (a translation model, say) doesn't count: it would pick clips badly
    return s.kind != "Built-in AI" and llm.model_rank(llm.choose_model(s, cfg.llm_model)) < 2
