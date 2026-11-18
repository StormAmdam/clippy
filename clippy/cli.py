"""Command line: clippy <youtube-url> [options]  |  clippy web  |  clippy app  |  clippy auto  |  clippy ai [test]
|  clippy uninstall (removes Clippy and what its setup installed; see clippy/uninstall.py)"""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import config
from .download import have_tools, install_hint


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "web":
        from .server import main as web
        return web(argv[1:])
    if argv and argv[0] == "auto":
        return _auto(argv[1:])
    if argv and argv[0] == "ai":
        return _ai(argv[1:])
    if argv and argv[0] == "app":
        from .desktop import main as app
        return app(argv[1:])
    if argv and argv[0] == "uninstall":
        from .uninstall import main as uninstall
        return uninstall(argv[1:])

    ap = argparse.ArgumentParser(prog="clippy", description="Turn a YouTube video into ready-to-post vertical clips.",
                                 epilog="Other commands: clippy web | clippy app | clippy auto | clippy ai [test] | "
                                        "clippy uninstall [--help]")
    ap.add_argument("url", help="YouTube link (or a local video file)")
    ap.add_argument("-n", "--clips", type=int, help="number of clips (default 5)")
    ap.add_argument("--min", dest="min_seconds", type=int, help="min clip length in seconds (default 20)")
    ap.add_argument("--max", dest="max_seconds", type=int, help="max clip length in seconds (default 60)")
    ap.add_argument("--color", dest="highlight_color", help="highlight colour, e.g. '#FFE135'")
    ap.add_argument("--style", dest="caption_style", help="caption style: beast, hormozi, box, clean, or one an "
                                                          "extension adds")
    ap.add_argument("--top", dest="top_theme", nargs="?", const="funny", metavar="THEME",
                    help="make one Top countdown short instead (funny, crazy, shocking, wholesome…)")
    ap.add_argument("--top-count", type=int, help="moments in the countdown (default 3)")
    ap.add_argument("--no-title", action="store_true", help="no hook title at the top")
    ap.add_argument("--no-sfx", action="store_true", help="no whoosh/pop sound effects")
    ap.add_argument("--no-motion", action="store_true", help="no zoom/slam/punch animations")
    ap.add_argument("--no-teaser", action="store_true", help="don't open with a flash-forward")
    ap.add_argument("--no-talking", action="store_true", help="video has no speech (music, gameplay…): skip Whisper")
    ap.add_argument("--keep-silences", action="store_true", help="don't cut pauses")
    ap.add_argument("--no-split", action="store_true", help="never use split screen")
    ap.add_argument("--reuse", action="store_true", help="reuse the AI's previous picks (fast re-render)")
    ap.add_argument("--cpu", action="store_true", help="transcribe on CPU (don't touch the GPU/LLM service)")
    a = ap.parse_args(argv)

    missing = have_tools()
    if missing:
        print("Missing tools: " + ", ".join(missing) + "  →  " + install_hint())
        return 1

    ov = {"clips": a.clips, "min_seconds": a.min_seconds, "max_seconds": a.max_seconds,
          "highlight_color": a.highlight_color, "reuse_picks": a.reuse, "caption_style": a.caption_style}
    if a.top_theme:
        ov.update(format="top", top_theme=a.top_theme, top_count=a.top_count)
    for flag, key in (("no_sfx", "sfx"), ("no_motion", "motion"), ("no_teaser", "teaser")):
        if getattr(a, flag):
            ov[key] = False
    if a.no_title:
        ov["title_seconds"] = 0
    if a.keep_silences:
        ov["remove_silences"] = False
    if a.no_split:
        ov["split_screen"] = False
    if a.no_talking:
        ov["speech"] = "off"
    if a.cpu:
        ov["whisper_device"] = "cpu"

    last = [0.0, ""]

    def prog(stage, pct, msg):
        now = time.time()
        if msg != last[1] and (now - last[0] > 0.5 or stage == "done"):
            print(f"\r\033[K[{pct * 100:5.1f}%] {msg}", end="", flush=True)
            last[0], last[1] = now, msg

    def log(msg):
        print("\r\033[K" + msg, flush=True)

    from .pipeline import run
    try:
        res = run(a.url, ov, prog, log)
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except Exception as e:
        print(f"\n✗ {e}")
        return 1
    root = config.output_root(config.load())
    where = (root / res["clips"][0]["file"]).parent if res["clips"] else root / res["id"]
    what = "countdown" if res["clips"] and res["clips"][0].get("format") == "top" else f"{len(res['clips'])} clips"
    print(f"\n\n✓ {what} in {res['seconds'] // 60}m{res['seconds'] % 60:02d}s → {where}\n")
    for c in res["clips"]:
        print(f"  [{c['score']}] {c['title']}  ({c['duration']:.0f}s)")
        print(f"      {root / c['file']}")
        if c.get("caption"):
            print(f"      {c['caption']} {' '.join(c.get('hashtags') or [])}")
    return 0


def _auto(argv: list[str]) -> int:
    """clippy auto [profile name | all]  — scrape, pick and render shorts into the review queue."""
    from . import autopilot
    from .pipeline import run
    profiles = autopilot.list_profiles()
    if not profiles:
        print("No Autopilot channels yet: create one on the Autopilot page in the app.")
        return 1
    want = " ".join(argv).strip().lower()
    chosen = profiles if want in ("", "all") else [p for p in profiles if p["name"].lower() == want or p["id"] == want]
    if not chosen:
        print("Profiles: " + ", ".join(p["name"] for p in profiles))
        return 1
    rc = 0
    for p in chosen:
        try:
            r = autopilot.run_profile(p["id"], run, lambda st, f, m: print(f"\r\033[K[{f * 100:5.1f}%] {m}", end="", flush=True),
                                      lambda m: print("\r\033[K" + m, flush=True))
            print(f"\n✓ {p['name']}: {r['clips']} shorts waiting for review in the web app")
        except Exception as e:
            print(f"\n✗ {p['name']}: {e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())


def _ai(argv: list[str]) -> int:
    """clippy ai: which AI servers are running and which model Clippy will use.  clippy ai test: time a request."""
    from . import llm
    cfg = config.load()
    found = llm.detect()
    using, error = None, ""
    try:
        s = llm.resolve(cfg)
        using = {**s.to_dict(), "model": llm.choose_model(s, cfg.llm_model)}
    except RuntimeError as e:
        error = str(e)
    if "--json" in argv:
        print(json.dumps({"servers": [f.to_dict() for f in found], "using": using, "error": error}))
        return 0 if using else 1
    if found:
        print("AI servers found:")
        for f in found:
            models = [m for m in f.models if llm.can_chat(m)]
            more = f" and {len(models) - 5} more" if len(models) > 5 else ""
            print(f"  {f.label}: {', '.join(models[:5]) or 'no chat models'}{more}")
    else:
        print("No AI server is running on the usual ports" + (" here or on Windows." if llm.wsl() else "."))
    if not using:
        print("\n" + error)
        return 1
    how = "found automatically" if (cfg.llm_url or "auto").lower() == "auto" else "from your settings"
    if using["kind"] == "Built-in AI":
        print(f"\nClippy will use {using['model']} with its built-in AI (models/llm, AI & Tools in the app).")
    else:
        print(f"\nClippy will use {using['model'] or 'the loaded model'} on {using['label']} ({how}).")
    if argv[:1] == ["test"]:
        c = llm.LLM(cfg, log=print)
        c.wait_ready(timeout=20)
        t0 = time.time()
        out = c.json("You answer in JSON.", 'Reply with {"ok": true, "word": "<one word describing space>"}.',
                     {"type": "object", "properties": {"ok": {"type": "boolean"}, "word": {"type": "string"}},
                      "required": ["ok", "word"]}, max_tokens=300, temperature=0)
        print(f"Test answer in {time.time() - t0:.1f}s: {out}  (context window: {c.context or 'unknown'} tokens)")
    return 0
