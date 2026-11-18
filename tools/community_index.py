"""Rebuild community/index.json (the community list of extensions) from the folders in community/.

    python tools/community_index.py          rewrite it
    python tools/community_index.py --check  only say whether it's up to date (the tests do this)"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clippy import extensions  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent / "community"


def build(root: Path = ROOT) -> str:
    items = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        m = extensions.read_manifest(d)
        files = sorted(f.relative_to(d).as_posix() for f in d.rglob("*")
                       if f.is_file() and "__pycache__" not in f.parts and not f.name.startswith("."))
        items.append({"id": m["id"], "name": m["name"], "description": m.get("description", ""),
                      "author": m.get("author", ""), "version": m.get("version", ""), "adds": extensions._adds(m),
                      "code": bool(m.get("code")), "files": files})
    about = "The community list of Clippy extensions. Add yours: see docs/extensions.md."
    return json.dumps({"about": about, "extensions": items}, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    text, f = build(), ROOT / "index.json"
    if "--check" in sys.argv:
        ok = f.exists() and f.read_text(encoding="utf-8") == text
        print("community/index.json is up to date" if ok else "community/index.json is out of date: run "
              "python tools/community_index.py")
        return 0 if ok else 1
    f.write_text(text, encoding="utf-8")
    print(f"wrote {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
