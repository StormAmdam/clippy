"""Community extensions: things other people made that add to Clippy.

An extension is a folder in Clippy's own folder, extensions/<id>/, with an extension.json that says what it adds:

  caption_styles     new looks for the captions (fonts, sizes, colours, how they bounce)
  countdown_themes   new kinds of Top countdown ("Top 3 most awkward moments")
  sounds             whoosh / pop / impact sound effects
  finder_topics      new topics for Find Videos
  code               a Python file with hooks that run after a short or a whole video is made

The first four are only data, so they're safe and switch on when installed. Code can do anything on the PC, so an
extension with code stays off until the person says they trust it. docs/extensions.md explains how to make one.
The community list (community/index.json in Clippy's repository) is read online, or from the copy in the app."""
from __future__ import annotations

import functools
import importlib.util
import io
import json
import re
import shutil
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from .config import ROOT, write_atomic

EXT_DIR = ROOT / "extensions"
STATE_FILE = EXT_DIR / "_state.json"                 # which are off, which code extensions are trusted
LOCAL_CATALOG = ROOT / "community"                   # the community list as it was when this Clippy was built
CATALOG = "https://raw.githubusercontent.com/StormAmdam/clippy/main/community/"
ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
MAX_BYTES = 200_000_000                              # an extension bigger than this is surely a mistake
SOUND_EXT = (".wav", ".mp3", ".ogg", ".flac", ".m4a")
FONT_EXT = (".ttf", ".otf")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
STYLE_KEYS = {"size": int, "upper": bool, "words": int, "stroke": int, "shadow": int, "active": str, "tilt": float,
              "pop": float, "rest": float, "emph_always": bool, "title": str}
_lock = threading.RLock()
_modules: dict[str, object] = {}


class ExtensionError(ValueError):
    """Said to the person installing or switching on an extension."""


# ───────────────────────── what's installed ─────────────────────────

def _state() -> dict:
    try:
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(s: dict) -> None:
    EXT_DIR.mkdir(parents=True, exist_ok=True)
    write_atomic(STATE_FILE, json.dumps(s, indent=2))
    changed()


def _inside(folder: Path, rel) -> Path | None:
    """A file named in a manifest, only if it really is inside the extension's folder."""
    if not isinstance(rel, str) or not rel.strip():
        return None
    p = (folder / rel).resolve()
    try:
        p.relative_to(folder.resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


def read_manifest(folder: Path) -> dict:
    """The extension.json in this folder, checked. ExtensionError says what's wrong."""
    try:
        m = json.loads((folder / "extension.json").read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise ExtensionError("There's no extension.json in it, so it isn't a Clippy extension.")
    except (OSError, ValueError) as e:
        raise ExtensionError(f"Its extension.json can't be read: {e}")
    if not isinstance(m, dict) or not ID.match(str(m.get("id", ""))):
        raise ExtensionError("Its extension.json needs an \"id\": lowercase letters, digits and dashes.")
    if not str(m.get("name", "")).strip():
        raise ExtensionError("Its extension.json needs a \"name\".")
    if m.get("code") and not _inside(folder, m["code"]):
        raise ExtensionError(f"Its code file {m['code']} isn't in the extension.")
    return m


def _adds(m: dict) -> list[str]:
    out = []
    for key, one, many in (("caption_styles", "caption style", "caption styles"),
                           ("countdown_themes", "countdown theme", "countdown themes"),
                           ("finder_topics", "Find Videos topic", "Find Videos topics")):
        n = len(m.get(key) or [])
        if n:
            out.append(f"{n} {one if n == 1 else many}")
    if m.get("sounds"):
        out.append("sound effects")
    return out                                             # code is shown as its own "Runs code" tag


def installed() -> list[dict]:
    """Every extension in the extensions folder, with whether it's on. Broken ones are listed with what's wrong."""
    rows, st = [], _state()
    off, trusted = set(st.get("off") or []), set(st.get("trusted") or [])
    if not EXT_DIR.exists():
        return rows
    for d in sorted(p for p in EXT_DIR.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        try:
            m = read_manifest(d)
        except ExtensionError as e:
            rows.append({"id": d.name, "name": d.name, "error": str(e), "enabled": False, "folder": str(d)})
            continue
        code = bool(m.get("code"))
        on = m["id"] not in off and (not code or m["id"] in trusted)
        rows.append({"id": m["id"], "name": str(m["name"]), "version": str(m.get("version", "")),
                     "author": str(m.get("author", "")), "description": str(m.get("description", "")),
                     "homepage": str(m.get("homepage", "")), "code": code, "trusted": m["id"] in trusted,
                     "enabled": on, "adds": _adds(m), "folder": str(d), "error": "" if d.name == m["id"] else
                     f"Its folder should be called {m['id']}"})
    return rows


def _active() -> list[tuple[Path, dict]]:
    out = []
    for row in installed():
        if row["enabled"] and not row.get("error"):
            d = Path(row["folder"])
            out.append((d, read_manifest(d)))
    return out


@functools.cache
def _cached_active() -> tuple:
    return tuple(_active())


def changed() -> None:
    """Something was installed, removed or switched: forget what was worked out from the old set."""
    _cached_active.cache_clear()
    try:
        from . import sfx
        sfx.forget_user_sounds()
    except ImportError:
        pass


# ───────────────────────── what they add ─────────────────────────

def caption_styles() -> dict[str, dict]:
    """Caption styles from switched-on extensions, ready for overlay.Overlay ("font_path" is a real file)."""
    out: dict[str, dict] = {}
    for d, m in _cached_active():
        for sid, st in styles_in(d, m).items():
            out.setdefault(sid, st)
    return out


def styles_in(d: Path, m: dict) -> dict[str, dict]:
    """The caption styles one extension folder defines (also used by tools/style_preview.py)."""
    from .overlay import FONTS, STYLES
    out: dict[str, dict] = {}
    for s in m.get("caption_styles") or []:
        if not isinstance(s, dict) or not ID.match(str(s.get("id", ""))) or s["id"] in STYLES or s["id"] in out:
            continue
        base = dict(STYLES.get(str(s.get("base", "")), STYLES["clean"]))
        for k, kind in STYLE_KEYS.items():
            if k in s:
                try:
                    base[k] = kind(s[k])
                except (TypeError, ValueError):
                    pass
        if base.get("active") not in ("color", "box"):
            base["active"] = "color"
        if base.get("title") not in ("beast", "box"):
            base["title"] = "box"
        font = _inside(d, s.get("font"))
        if font is not None and font.suffix.lower() in FONT_EXT:
            base["font_path"] = str(font)
        elif not (FONTS / str(base["font"])).exists():
            continue
        preview = _inside(d, s.get("preview"))
        out[s["id"]] = {**base, "name": str(s.get("name") or s["id"])[:30], "about": str(s.get("about", ""))[:80],
                        "extension": m["id"],
                        "preview": f"/ext/{m['id']}/{preview.relative_to(d.resolve()).as_posix()}"
                        if preview is not None and preview.suffix.lower() in IMAGE_EXT else ""}
    return out


def top_themes() -> dict[str, dict]:
    from .top import THEMES
    out: dict[str, dict] = {}
    for _, m in _cached_active():
        for t in m.get("countdown_themes") or []:
            if not isinstance(t, dict) or not ID.match(str(t.get("id", ""))) or t["id"] in THEMES or t["id"] in out:
                continue
            if not str(t.get("name", "")).strip() or not str(t.get("look_for", "")).strip():
                continue
            out[t["id"]] = {"name": str(t["name"])[:30], "emoji": str(t.get("emoji", ""))[:4],
                            "title": str(t.get("title") or f"Top {{n}} {t['name']} Moments")[:60],
                            "look_for": str(t["look_for"])[:600], "word": str(t.get("word") or t["name"])[:30],
                            "hashtags": [str(h) for h in t.get("hashtags") or []][:6],
                            "laughter": bool(t.get("laughter")), "extension": m["id"]}
    return out


def sounds(name: str) -> list[Path]:
    """Sound files for one effect (whoosh, pop, impact) from switched-on extensions."""
    out = []
    for d, m in _cached_active():
        files = (m.get("sounds") or {}).get(name) if isinstance(m.get("sounds"), dict) else None
        for rel in files or []:
            p = _inside(d, rel)
            if p is not None and p.suffix.lower() in SOUND_EXT:
                out.append(p)
    return out


def finder_topics() -> dict[str, list[str]]:
    from .finder import NICHES
    out: dict[str, list[str]] = {}
    for _, m in _cached_active():
        topics = m.get("finder_topics") or {}
        if not isinstance(topics, dict):
            continue
        for name, queries in topics.items():
            name = str(name).strip().lower()[:30]
            qs = [str(q).strip()[:80] for q in queries or [] if str(q).strip()][:5] if isinstance(queries, list) else []
            if name and qs and name not in NICHES and name not in out:
                out[name] = qs
    return out


def file_for_page(ext_id: str, rel: str) -> Path | None:
    """A preview picture of an installed extension, for the app's pages (nothing else is served)."""
    d = EXT_DIR / ext_id
    if not ID.match(ext_id) or not d.is_dir():
        return None
    p = _inside(d, rel)
    return p if p is not None and p.suffix.lower() in IMAGE_EXT else None


# ───────────────────────── code hooks ─────────────────────────

HOOKS = ("clip_rendered", "video_done")


def run_hook(name: str, log=print, **kwargs) -> None:
    """Call `name(**kwargs)` in every switched-on, trusted code extension. Their mistakes never stop a video."""
    for d, m in _cached_active():
        if not m.get("code"):
            continue
        try:
            mod = _load(d, m)
            fn = getattr(mod, name, None)
            if callable(fn):
                fn(**kwargs)
        except Exception as e:                            # someone else's code: report it, carry on
            log(f"  Extension “{m.get('name')}” failed in {name}: {str(e)[:200]}")


def _load(d: Path, m: dict):
    code = _inside(d, m["code"])
    key = f"{m['id']}:{code}:{code.stat().st_mtime}"
    with _lock:
        if key not in _modules:
            spec = importlib.util.spec_from_file_location(f"clippy_extension_{m['id'].replace('-', '_')}", code)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _modules[key] = mod
        return _modules[key]


# ───────────────────────── switching on and off, removing ─────────────────────────

def set_enabled(ext_id: str, on: bool, trust: bool = False) -> dict:
    row = next((r for r in installed() if r["id"] == ext_id), None)
    if row is None:
        raise ExtensionError("That extension isn't installed.")
    if row.get("error"):
        raise ExtensionError(row["error"])
    st = _state()
    off, trusted = set(st.get("off") or []), set(st.get("trusted") or [])
    if on and row["code"] and ext_id not in trusted:
        if not trust:
            raise ExtensionError("This extension runs its own code. Confirm that you trust it to switch it on.")
        trusted.add(ext_id)
    (off.discard if on else off.add)(ext_id)
    _save_state({**st, "off": sorted(off), "trusted": sorted(trusted)})
    return next(r for r in installed() if r["id"] == ext_id)


def remove(ext_id: str) -> None:
    d = EXT_DIR / ext_id
    if not ID.match(ext_id) or not d.is_dir():
        raise ExtensionError("That extension isn't installed.")
    from .storage import remove_tree
    remove_tree(d)
    st = _state()
    _save_state({**st, "off": [x for x in st.get("off") or [] if x != ext_id],
                 "trusted": [x for x in st.get("trusted") or [] if x != ext_id]})


# ───────────────────────── installing ─────────────────────────

def _put_in_place(staged: Path) -> dict:
    """Move a checked extension folder into extensions/<id> (replacing an older version of it)."""
    m = read_manifest(staged)
    target = EXT_DIR / m["id"]
    EXT_DIR.mkdir(parents=True, exist_ok=True)
    if target.exists():
        from .storage import remove_tree
        remove_tree(target)
    shutil.move(str(staged), str(target))
    st = _state()
    trusted = [x for x in st.get("trusted") or [] if x != m["id"]]   # new code: ask again
    _save_state({**st, "trusted": trusted})
    return next(r for r in installed() if r["id"] == m["id"])


def _staging() -> Path:
    d = EXT_DIR / "_incoming" / f"{int(time.time() * 1000)}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def install_from_folder(folder: Path) -> dict:
    """Copy an extension folder (for example from the community list in the app) and install it."""
    read_manifest(folder)
    stage = _staging()
    try:
        dest = stage / "x"
        shutil.copytree(folder, dest, ignore=shutil.ignore_patterns("__pycache__", ".*"))
        return _put_in_place(dest)
    finally:
        shutil.rmtree(stage.parent, ignore_errors=True)


def install_from_zip(data: bytes, subdir: str = "") -> dict:
    """Unpack a zip that holds an extension (at its top, in one folder, or in `subdir`) and install it."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ExtensionError("That download isn't a zip file.")
    names = [n for n in z.namelist() if not n.endswith("/")]
    if sum(i.file_size for i in z.infolist()) > MAX_BYTES:
        raise ExtensionError("That extension is too big (over 200 MB unpacked).")
    manifests = sorted((n for n in names if PurePosixPath(n).name == "extension.json"),
                       key=lambda n: (subdir.strip("/") not in n, n.count("/"), n))
    if not manifests:
        raise ExtensionError("There's no extension.json in it, so it isn't a Clippy extension.")
    root = str(PurePosixPath(manifests[0]).parent)
    root = "" if root == "." else root + "/"
    stage = _staging()
    try:
        dest = stage / "x"
        for n in names:
            if not n.startswith(root):
                continue
            rel = PurePosixPath(n[len(root):])
            if rel.is_absolute() or ".." in rel.parts or any(p.startswith(".") for p in rel.parts):
                continue
            out = dest.joinpath(*rel.parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(out, "wb") as f:
                shutil.copyfileobj(src, f)
        return _put_in_place(dest)
    finally:
        shutil.rmtree(stage.parent, ignore_errors=True)


def _download(url: str) -> bytes:
    import httpx
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
            if r.status_code != 200:
                raise ExtensionError(f"Couldn't download it ({r.status_code} from {urlsplit(url).netloc}).")
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) > MAX_BYTES:
                    raise ExtensionError("That download is too big for an extension (over 200 MB).")
            return bytes(buf)
    except httpx.HTTPError as e:
        raise ExtensionError(f"Couldn't download it: {e}")


def zip_url(url: str) -> tuple[str, str]:
    """A link people paste → (zip download URL, folder inside it). GitHub repositories and folders in them work."""
    url = url.strip()
    u = urlsplit(url)
    if u.scheme not in ("http", "https"):
        raise ExtensionError("Paste a link that starts with https://")
    parts = [p for p in u.path.split("/") if p]
    if u.netloc in ("github.com", "www.github.com") and len(parts) >= 2 and not url.lower().endswith(".zip"):
        owner, repo = parts[0], parts[1].removesuffix(".git")
        ref, sub = "HEAD", ""
        if len(parts) >= 4 and parts[2] == "tree":
            ref, sub = parts[3], "/".join(parts[4:])
        return f"https://codeload.github.com/{owner}/{repo}/zip/{ref}", sub
    return url, ""


def install_from_url(url: str) -> dict:
    link, sub = zip_url(url)
    return install_from_zip(_download(link), sub)


# ───────────────────────── the community list ─────────────────────────

def _local_index() -> list[dict]:
    try:
        data = json.loads((LOCAL_CATALOG / "index.json").read_text(encoding="utf-8"))
        return data.get("extensions") or [] if isinstance(data, dict) else []
    except (OSError, ValueError):
        return []


def catalog(online: bool = True) -> dict:
    """The community list: online when it can be read, else the copy that came with this Clippy."""
    items, source, note = None, "online", ""
    if online:
        import httpx
        try:
            r = httpx.get(CATALOG + "index.json", timeout=8, follow_redirects=True)
            if r.status_code == 200:
                data = r.json()
                items = data.get("extensions") if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            pass
    if items is None:
        items, source = _local_index(), "bundled"
        note = "The online list couldn't be reached, so this is the list that came with Clippy."
    have = {r["id"]: r for r in installed()}
    rows = []
    for e in items:
        if not isinstance(e, dict) or not ID.match(str(e.get("id", ""))):
            continue
        mine = have.get(e["id"])
        rows.append({"id": e["id"], "name": str(e.get("name", e["id"])), "description": str(e.get("description", "")),
                     "author": str(e.get("author", "")), "version": str(e.get("version", "")),
                     "code": bool(e.get("code")), "adds": [str(a) for a in e.get("adds") or []],
                     "homepage": str(e.get("homepage", "")), "installed": bool(mine),
                     "update": bool(mine and e.get("version") and mine.get("version") != str(e.get("version")))})
    return {"items": rows, "source": source, "note": note}


def install_from_catalog(ext_id: str) -> dict:
    entry = next((e for e in _local_index() if e.get("id") == ext_id), None)
    online = None
    try:
        import httpx
        r = httpx.get(CATALOG + "index.json", timeout=8, follow_redirects=True)
        if r.status_code == 200:
            online = next((e for e in r.json().get("extensions") or [] if e.get("id") == ext_id), None)
    except Exception:
        online = None
    e = online or entry
    if e is None:
        raise ExtensionError("That extension isn't in the community list.")
    if e.get("zip"):                                     # made and hosted by someone else
        return install_from_url(str(e["zip"]))
    folder = LOCAL_CATALOG / ext_id
    if online:                                           # in Clippy's repository: fetch its files
        files = [str(f) for f in e.get("files") or []]
        if "extension.json" not in files:
            raise ExtensionError("The community list's entry for it is incomplete.")
        stage = _staging()
        try:
            dest = stage / "x"
            for rel in files:
                p = PurePosixPath(rel)
                if p.is_absolute() or ".." in p.parts:
                    continue
                out = dest.joinpath(*p.parts)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(_download(f"{CATALOG}{ext_id}/{p.as_posix()}"))
            return _put_in_place(dest)
        except ExtensionError:
            if not folder.is_dir():                      # the copy that came with Clippy will do
                raise
        finally:
            shutil.rmtree(stage.parent, ignore_errors=True)
    if not folder.is_dir():
        raise ExtensionError("That extension can't be downloaded right now. Check the internet connection.")
    return install_from_folder(folder)
