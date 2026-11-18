"""clippy uninstall (Linux): removes what Clippy and its setup put on the PC, keeps the shorts, asks about the rest."""
import subprocess
import sys

import pytest

from clippy import autostart, desktop, uninstall

LINUX = pytest.mark.skipif(sys.platform == "win32", reason="clippy uninstall is for Linux; Windows has the app's uninstaller")


class Runner:
    """Stands in for every outside command (systemctl, sudo, dpkg-query, ollama, git, ss)."""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        out = ""
        if cmd[0] == "dpkg-query":
            out = "install ok installed"
        elif cmd[:2] == ["ollama", "list"]:
            out = "NAME          ID     SIZE    MODIFIED\nqwen3.5:9b    abc    6 GB    now\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    def sudo(self):
        return [c[1:] for c in self.calls if c[0] == "sudo"]


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """A pretend home folder with Clippy installed the way install.sh and setup.sh do it."""
    home = tmp_path / "home"
    app = home / "clippy"
    for f in ("clippy.sh", ".venv/bin/python", "models/whisper/model.bin", "settings.json", "extensions/x/extension.json"):
        (app / f).parent.mkdir(parents=True, exist_ok=True)
        (app / f).write_text("x")
    (app / "data").mkdir()
    (app / "data/setup-installed.txt").write_text("package ffmpeg\npackage fonts-noto-color-emoji\npackage python3\n"
                                                  "package bad;name\n")
    (home / "Videos").mkdir()
    (home / ".local/bin").mkdir(parents=True)
    (home / ".local/bin/clippy").symlink_to(app / "clippy.sh")
    cfg = home / ".config"
    (cfg / "systemd/user").mkdir(parents=True)
    (cfg / "systemd/user/clippy.service").write_text("[Service]")
    (home / ".ollama-serve.log").write_text("log")
    ai = [home / ".local/bin/llama-coder", home / ".local/opt/llama.cpp/b1-cuda/llama-server", cfg / "llama-coder.env",
          cfg / "systemd/user/llama-coder.service", home / "models/Qwen3.5-4B-Q4_K_M.gguf", home / ".llama-coder.log"]
    for f in ai:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    (home / "models/my-own-model.gguf").write_text("mine")       # not setup's: never touched
    shorts = app / "output"
    (shorts / "abc123/clips").mkdir(parents=True)
    (shorts / "abc123/clips/01-hook.mp4").write_bytes(b"video")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("CLIPPY_OUTPUT_DIR", str(shorts))
    monkeypatch.setenv("CLIPPY_SETTINGS_FILE", str(app / "settings.json"))
    monkeypatch.setattr(uninstall, "ROOT", app)
    monkeypatch.setattr(desktop, "probe", lambda port: "free")
    monkeypatch.setattr(desktop, "_saved_port", lambda: None)
    run = Runner()
    monkeypatch.setattr(uninstall, "_run", run)
    monkeypatch.setattr(autostart, "_systemctl", lambda *a: run.calls.append(["autostart", *a]) or (0, ""))
    tools = {"systemctl", "ss", "apt-get"}
    monkeypatch.setattr(uninstall.shutil, "which",
                        lambda name, *a, **k: None if name not in tools else    # ollama.com puts it in /usr/local
                        ("/usr/local/bin/ollama" if name == "ollama" else f"/usr/bin/{name}"))
    return {"home": home, "app": app, "ai": ai, "run": run, "tools": tools}


@LINUX
def test_uninstall_removes_clippy_and_keeps_the_shorts(pc):
    said = []
    assert uninstall.main(["--yes"], say=said.append) == 0
    home = pc["home"]
    assert not pc["app"].exists() and not (home / ".local/bin/clippy").is_symlink()
    assert not (home / ".config/systemd/user/clippy.service").exists() and not (home / ".ollama-serve.log").exists()
    assert (home / "Videos/Clippy shorts/abc123/clips/01-hook.mp4").read_bytes() == b"video"
    assert all(p.exists() for p in pc["ai"])                         # the AI only goes when asked
    assert pc["run"].sudo() == []                                     # and so do system packages
    assert ["systemctl", "--user", "disable", "--now", "clippy.service"] in pc["run"].calls
    text = "\n".join(said)
    assert "ffmpeg, fonts-noto-color-emoji" in text and "install.sh" in text and "llama-coder" in text
    assert "python3" not in text and "bad;name" not in text           # never offered


@LINUX
def test_all_removes_what_setup_installed_and_nothing_else(pc):
    assert uninstall.main(["--all"], say=lambda m: None) == 0
    home = pc["home"]
    assert not any(p.exists() for p in pc["ai"]) and not (home / ".local/opt/llama.cpp").exists()
    assert (home / "models/my-own-model.gguf").read_text() == "mine"
    assert ["apt-get", "remove", "-y", "-qq", "ffmpeg", "fonts-noto-color-emoji"] in pc["run"].sudo()
    assert (home / "Videos/Clippy shorts/abc123/clips/01-hook.mp4").exists()   # shorts are still kept
    assert ["systemctl", "--user", "disable", "--now", "llama-coder"] in pc["run"].calls


@LINUX
def test_ollama_goes_only_if_setup_installed_it(pc):
    pc["tools"].add("ollama")
    (pc["home"] / ".ollama/models").mkdir(parents=True)
    said = []
    uninstall.main(["--all"], say=said.append)
    assert not any(c[0] == "sh" for c in pc["run"].sudo())            # it was here before Clippy
    assert (pc["home"] / ".ollama/models").exists() and "before Clippy" in "\n".join(said)


@LINUX
def test_ollama_setup_installed_is_removed_with_its_own_steps(pc):
    pc["tools"].add("ollama")
    (pc["app"] / "data/setup-installed.txt").write_text("ollama\n")
    (pc["home"] / ".ollama/models").mkdir(parents=True)
    uninstall.main(["--all"], say=lambda m: None)
    script = next(c[2] for c in pc["run"].sudo() if c[0] == "sh")
    assert "rm -f /usr/local/bin/ollama" in script and "rm -rf /usr/local/lib/ollama" in script
    assert "userdel ollama" in script and not (pc["home"] / ".ollama").exists()


@LINUX
def test_the_model_setup_pulled_into_your_own_ollama(pc):
    pc["tools"].add("ollama")
    (pc["app"] / "data/setup-installed.txt").write_text("ollama-model qwen3.5:9b\nollama-model gone:1b\n")
    uninstall.main(["--all"], say=lambda m: None)
    assert ["ollama", "rm", "qwen3.5:9b"] in pc["run"].calls
    assert ["ollama", "rm", "gone:1b"] not in pc["run"].calls         # not in Ollama any more
    assert not any(c[0] == "sh" for c in pc["run"].sudo())            # Ollama itself stays


@LINUX
def test_answers_are_followed(pc):
    answers = {"Keep your videos": False, "AI for Clippy": True, "system packages": False, "Remove Clippy now": True}
    pick = lambda q, d: next(v for k, v in answers.items() if k in q)
    assert uninstall.main([], answers=pick, say=lambda m: None) == 0
    assert not (pc["home"] / "Videos/Clippy shorts").exists()        # shorts deleted as asked
    assert not any(p.exists() for p in pc["ai"]) and pc["run"].sudo() == []


@LINUX
def test_saying_no_removes_nothing(pc):
    assert uninstall.main([], answers=lambda q, d: False if "now" in q else d, say=lambda m: None) == 1
    assert pc["app"].exists() and (pc["home"] / ".local/bin/clippy").is_symlink()


@LINUX
def test_unsaved_work_is_never_removed_without_asking(pc, monkeypatch):
    monkeypatch.setattr(uninstall, "unsaved_work", lambda: "This folder has changes")
    assert uninstall.main(["--yes"], say=lambda m: None) == 1
    assert pc["app"].exists()


@LINUX
def test_another_folders_clippy_command_is_left_alone(pc, tmp_path):
    link = pc["home"] / ".local/bin/clippy"
    link.unlink()
    other = tmp_path / "other-clippy.sh"
    other.write_text("x")
    link.symlink_to(other)
    uninstall.main(["--yes"], say=lambda m: None)
    assert link.is_symlink()


def test_on_windows_it_points_to_the_app_uninstaller(pc, monkeypatch):
    monkeypatch.setattr(uninstall.sys, "platform", "win32")
    said = []
    assert uninstall.main([], say=said.append) == 0
    assert "Settings" in said[0] and pc["app"].exists()
    monkeypatch.setattr(uninstall.sys, "platform", sys.platform)
