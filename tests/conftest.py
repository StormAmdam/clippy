import os
import sys
from pathlib import Path

import pytest

# CLIPPY_SRC lets a mutation check run this suite against a modified copy of the package.
ROOT = Path(os.environ.get("CLIPPY_SRC", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT))


@pytest.fixture
def tmp_output(monkeypatch, tmp_path):
    """Point Clippy's output folder (and UI settings file) at a temp dir."""
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("CLIPPY_OUTPUT_DIR", str(out))
    monkeypatch.setenv("CLIPPY_SETTINGS_FILE", str(tmp_path / "settings.json"))
    return out


def make_words(text: str, start: float = 0.0, step: float = 0.5, length: float = 0.4) -> list[dict]:
    return [{"w": w, "s": round(start + i * step, 3), "e": round(start + i * step + length, 3)}
            for i, w in enumerate(text.split())]
