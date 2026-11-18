"""clippy uninstall: remove Clippy from a Linux PC, and what its setup put there.

  always    the Clippy folder (app, Python packages, speech and AI models, settings, extensions, logs),
            the clippy command (~/.local/bin/clippy), Start at login, setup's log files
  asked     your videos and finished shorts: kept by default, moved to ~/Videos/Clippy shorts (a shorts folder you
            set outside Clippy's folder is never touched)
  asked     AI setup installed for Clippy: the llama.cpp AI (llama-coder) and the model it downloaded, Ollama, or the
            model it pulled into an Ollama you already had. Kept by default: other apps may use it.
  asked     system packages setup installed (ffmpeg, the emoji font…), except any another program needs. Kept by default.

setup.sh notes in data/setup-installed.txt what it installed that wasn't on the PC before, so this only ever offers
those: never a package, llama.cpp, model or Ollama you already had. Flags: --yes (take the defaults, don't ask), --all
(also remove the AI and packages setup installed), --remove-ai, --delete-shorts. On Windows the app has its own
uninstaller."""
from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from .config import ROOT, load, output_root
from .updates import INSTALL_LINE

RECORD = "data/setup-installed.txt"                   # under ROOT; written by setup.sh
NEVER_REMOVE = {"python", "python3", "sudo", "curl", "git", "bash", "coreutils"}
OLLAMA_UNINSTALL = "https://github.com/ollama/ollama/blob/main/docs/linux.md#uninstall"
HELP = """clippy uninstall           remove Clippy from this PC (it asks what to keep)
  --yes                    don't ask: keep the shorts, the AI and system packages, remove the rest
  --all                    also remove the AI and the system packages setup installed for Clippy
  --remove-ai              also remove the AI setup installed
  --delete-shorts          delete your videos and finished shorts instead of keeping them"""


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Every outside command goes through here (the tests replace it)."""
    return subprocess.run(cmd, **kw)


def _say(msg: str) -> None:
    print(msg, flush=True)                               # before sudo's and apt's own output, also through a pipe


def _human(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB" if n >= 1e6 else "less than 1 MB"


def _size(p: Path) -> int:
    if p.is_symlink():
        return 0
    if p.is_file():
        return p.stat().st_size
    total = 0
    for f in p.rglob("*") if p.is_dir() else []:
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _inside(p: Path, folder: Path) -> bool:
    try:
        p.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _remove(p: Path) -> None:
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p, ignore_errors=True)
    else:
        p.unlink(missing_ok=True)


def _home() -> Path:
    return Path.home()


def _config() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config")


def _systemctl(*args: str) -> None:
    if shutil.which("systemctl"):
        _run(["systemctl", "--user", *args], capture_output=True, timeout=60)


# ───────────────────────── what's there ─────────────────────────

def command_link() -> Path | None:
    """~/.local/bin/clippy, when it's this Clippy's (another folder's stays)."""
    link = _home() / ".local/bin/clippy"
    try:
        return link if link.is_symlink() and link.resolve() == (ROOT / "clippy.sh").resolve() else None
    except OSError:
        return None


def recorded() -> dict:
    """What setup.sh noted it installed: packages, llama.cpp and its models, Ollama, models pulled into Ollama."""
    out: dict = {"known": False, "packages": [], "llamacpp": False, "models": [], "ollama": False, "ollama_models": []}
    try:
        lines = (ROOT / RECORD).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    out["known"] = True
    models = _home() / "models"
    for line in lines:
        kind, _, name = line.strip().partition(" ")
        name = name.strip()
        if kind == "package" and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]*", name) and name not in NEVER_REMOVE:
            out["packages"] += [name] if name not in out["packages"] else []
        elif kind == "llamacpp":
            out["llamacpp"] = True
        elif kind == "model" and name.endswith(".gguf") and Path(name).parent == models:
            out["models"] += [Path(name)] if Path(name) not in out["models"] else []
        elif kind == "ollama":
            out["ollama"] = True
        elif kind == "ollama-model" and name and name not in out["ollama_models"]:
            out["ollama_models"].append(name)
    return out


def llamacpp_pieces(rec: dict) -> list[Path]:
    """What setup's llama.cpp option added (aisetup: LLAMA_DIR, ENV_FILE, install_service, MODELS_DIR): llama.cpp
    itself only when setup installed it, and only the models it downloaded."""
    home, cfg = _home(), _config()
    pieces = [home / ".local/bin/llama-coder", home / ".local/opt/llama.cpp", cfg / "llama-coder.env",
              cfg / "systemd/user/llama-coder.service", home / ".llama-coder.log"] if rec["llamacpp"] else []
    pieces += rec["models"]
    return [p for p in pieces if p.exists() or p.is_symlink()]


def logs() -> list[Path]:
    return [p for p in [_home() / ".ollama-serve.log"] if p.exists()]


def _package_manager() -> tuple[list[str], list[str]] | None:
    """(remove command, is-it-installed query) for this distro's package manager."""
    for tool, remove, query in (("apt-get", ["apt-get", "remove", "-y", "-q"], ["dpkg-query", "-W", "-f=${Status}"]),
                                ("pacman", ["pacman", "-Rs", "--noconfirm"], ["pacman", "-Q"]),
                                ("dnf", ["dnf", "remove", "-y"], ["rpm", "-q"]),
                                ("zypper", ["zypper", "--non-interactive", "remove", "--clean-deps"], ["rpm", "-q"])):
        if shutil.which(tool):
            return remove, query
    return None


def installed_packages(names: list[str]) -> list[str]:
    pm = _package_manager()
    if not pm or not names:
        return []
    found = []
    for n in names:
        r = _run([*pm[1], n], capture_output=True, text=True)
        if r.returncode == 0 and (pm[1][0] != "dpkg-query" or "ok installed" in r.stdout):
            found.append(n)
    return found


def dependents(pkg: str) -> list[str]:
    """Installed packages that need this one: removing it would take them along, so it stays."""
    if shutil.which("apt-get"):
        r = _run(["apt-get", "-s", "remove", pkg], capture_output=True, text=True)
        if r.returncode != 0:
            return ["(apt couldn't tell)"]
        return [n for n in (m.split(":")[0] for m in re.findall(r"^Remv (\S+)", r.stdout, re.M)) if n != pkg]
    if shutil.which("pacman"):
        r = _run(["pacman", "-Qi", pkg], capture_output=True, text=True)
        m = re.search(r"^Required By\s*:\s*(.*)$", r.stdout, re.M)
        return [n for n in (m.group(1).split() if m else []) if n != "None"]
    if shutil.which("rpm"):
        r = _run(["rpm", "-q", "--whatrequires", pkg], capture_output=True, text=True)
        return [] if r.returncode != 0 else r.stdout.split()   # exit 1: "no package requires …"
    return ["(no package manager)"]


def ollama_models_present(names: list[str]) -> list[str]:
    if not names or not shutil.which("ollama"):
        return []
    r = _run(["ollama", "list"], capture_output=True, text=True, timeout=20)
    have = {line.split()[0] for line in r.stdout.splitlines()[1:] if line.strip()} if r.returncode == 0 else set()
    return [n for n in names if n in have or f"{n}:latest" in have]


def keep_folder() -> Path:
    """Where the videos and shorts go: ~/Videos/Clippy shorts (or a dated name if that's taken)."""
    base = _home() / "Videos" if (_home() / "Videos").is_dir() else _home()
    target = base / "Clippy shorts"
    return target if not target.exists() else base / f"Clippy shorts {time.strftime('%Y-%m-%d %H%M')}"


def unsaved_work() -> str:
    """A warning when the folder holds changes that aren't anywhere else (someone working on Clippy itself)."""
    if not (ROOT / ".git").exists() or not shutil.which("git"):
        return ""
    try:
        r = _run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True, timeout=20)
        ahead = _run(["git", "-C", str(ROOT), "log", "--oneline", "@{u}..HEAD"], capture_output=True, text=True,
                     timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    if r.stdout.strip() or (ahead.returncode == 0 and ahead.stdout.strip()):
        return "This folder has changes that aren't anywhere else (someone is working on Clippy here). They'd be lost."
    return ""


# ───────────────────────── removing ─────────────────────────

def _pid_on(port: int) -> int | None:
    if not shutil.which("ss"):
        return None
    out = _run(["ss", "-ltnpH", f"sport = :{port}"], capture_output=True, text=True).stdout
    m = re.search(r"pid=(\d+)", out)
    return int(m.group(1)) if m else None


def _stop(pid: int, port: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    for _ in range(50):                                 # wait until it has let go of the port
        if _pid_on(port) is None:
            return
        time.sleep(0.2)


def stop_running(say=_say) -> None:
    """A Clippy from this folder that's still running (on its usual ports) is stopped first."""
    from . import desktop
    for port in dict.fromkeys([*(p for p in [desktop._saved_port()] if p), *range(7860, 7870)]):
        if desktop.probe(port) != "ours":
            continue
        pid = _pid_on(port)
        if not pid or pid == os.getpid():
            raise SystemExit(f"Clippy is still running at http://127.0.0.1:{port}. Close it (Ctrl+C in its terminal), "
                             "then run clippy uninstall again.")
        _stop(pid, port)
        say(f"  Stopped the Clippy running at http://127.0.0.1:{port}")


def remove_llamacpp(pieces: list[Path], tool: bool) -> None:
    """tool: setup installed llama.cpp itself (not only a model), so its service and server go too."""
    if tool:
        _systemctl("disable", "--now", "llama-coder")
        pid = _pid_on(8080)                             # llama-coder started by hand (no systemd)
        if pid:
            try:
                if "llama" in Path(f"/proc/{pid}/cmdline").read_text(errors="replace"):
                    _stop(pid, 8080)
            except OSError:
                pass
    for p in pieces:
        _remove(p)
    if tool:
        _systemctl("daemon-reload")
    models = _home() / "models"
    if models.is_dir() and not any(models.iterdir()):
        models.rmdir()


def remove_ollama(say=_say) -> bool:
    """Ollama's own uninstall steps (OLLAMA_UNINSTALL), for an Ollama setup installed with ollama.com's installer."""
    pid = _pid_on(11434)
    if pid:
        _stop(pid, 11434)                               # an `ollama serve` setup started (no systemd); a service stops below
    binary = shutil.which("ollama")
    steps = ["systemctl stop ollama 2>/dev/null", "systemctl disable ollama 2>/dev/null",
             "rm -f /etc/systemd/system/ollama.service", "systemctl daemon-reload 2>/dev/null"]
    if binary and binary.startswith("/usr/"):           # where ollama.com's installer puts it
        b = Path(binary)
        steps += [f"rm -f {shlex.quote(str(b))}", f"rm -rf {shlex.quote(str(b.parent.parent / 'lib' / 'ollama'))}"]
    steps += ["rm -rf /usr/share/ollama", "id ollama >/dev/null 2>&1 && userdel ollama",
              "getent group ollama >/dev/null && groupdel ollama", "true"]
    r = _run(["sudo", "sh", "-c", "; ".join(steps)])
    if r.returncode != 0:
        say(f"  Couldn't remove Ollama (sudo said no). Its own steps: {OLLAMA_UNINSTALL}")
        return False
    _remove(_home() / ".ollama")                        # models and keys of an Ollama run as you
    return True


def remove_ollama_models(models: list[str], say=_say) -> list[str]:
    removed = []
    for m in models:
        r = _run(["ollama", "rm", m], capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            removed.append(m)
        else:
            say(f"  Couldn't remove {m} from Ollama (is it running? start it with: ollama serve). "
                f"Later: ollama rm {m}")
    return removed


def remove_packages(pkgs: list[str], say=_say) -> bool:
    """Only packages nothing else needs (dependents() checked each), so -y can't take other programs along."""
    pm = _package_manager()
    if not pm:
        return False
    if _run(["sudo", "-v"]).returncode != 0:            # the password, asked in the terminal
        say(f"  Didn't remove {', '.join(pkgs)} (no sudo). Later: sudo {' '.join(pm[0][:2])} {' '.join(pkgs)}")
        return False
    r = _run(["sudo", "-n", *pm[0], *pkgs], capture_output=True, text=True)
    if r.returncode != 0:
        say((r.stderr or r.stdout).strip()[-600:])
        say(f"  Couldn't remove {', '.join(pkgs)} (see above). Later: sudo {' '.join(pm[0][:2])} {' '.join(pkgs)}")
        return False
    return True


# ───────────────────────── the command ─────────────────────────

def _ask(question: str, default: bool, answers) -> bool:
    if answers is not None:
        return answers(question, default)
    hint = "[Y/n]" if default else "[y/N]"
    try:
        reply = input(f"{question} {hint} ").strip().lower()
    except EOFError:
        return default
    return default if not reply else reply in ("y", "yes", "j", "ja")


def main(argv: list[str] | None = None, answers=None, say=_say) -> int:
    """answers(question, default) -> bool replaces the questions (the tests; --yes takes every default)."""
    argv = list(argv or [])
    if {"-h", "--help"} & set(argv):
        say(HELP)
        return 0
    if sys.platform == "win32":
        say("On Windows, uninstall Clippy from Settings → Apps → Installed apps → Clippy. It removes everything and "
            "offers to keep your shorts. (A portable copy: delete its folder.)")
        return 0
    everything = "--all" in argv
    if "--yes" in argv or everything:
        answers = answers or (lambda q, d: d)

    out = output_root(load())
    shorts = out if out.is_dir() and any(out.iterdir()) else None
    own_shorts = bool(shorts) and _inside(out, ROOT)    # in Clippy's folder; one you chose elsewhere is left alone
    from . import autostart
    rec = recorded()
    link, extra, llama = command_link(), logs(), llamacpp_pieces(rec)
    unit = autostart.unit_path() if autostart.unit_path().exists() else None
    ollama = rec["ollama"] and shutil.which("ollama") is not None
    ollama_models = [] if ollama else ollama_models_present(rec["ollama_models"])
    packages, needed = [], {}
    for p in installed_packages(rec["packages"]):
        deps = dependents(p)
        if deps:
            needed[p] = deps
        else:
            packages.append(p)

    say("This removes Clippy from this PC:")
    say(f"  • the Clippy folder {ROOT} ({_human(_size(ROOT) - (_size(shorts) if own_shorts else 0))}): the app, its "
        "Python packages, speech and AI models, settings and extensions")
    if link:
        say(f"  • the clippy command ({link})")
    if unit:
        say("  • Start at login")
    if extra:
        say(f"  • setup's log files ({', '.join(p.name for p in extra)})")
    if shorts and not own_shorts:
        say(f"  Your shorts folder {out} is outside Clippy's folder, so it stays as it is.")
    warning = unsaved_work()
    if warning:
        say(f"\n  ⚠ {warning}")

    keep = True
    target = keep_folder()
    if own_shorts:
        keep = "--delete-shorts" not in argv and _ask(
            f"\nKeep your videos and finished shorts ({_human(_size(shorts))})? They move to {target}.", True, answers)
    ai = []
    if rec["llamacpp"] and llama:
        ai.append(f"the llama.cpp AI (llama-coder) and its model, {_human(sum(_size(p) for p in llama))}")
    elif llama:
        ai.append(f"the AI model it downloaded for llama.cpp ({', '.join(p.name for p in llama)})")
    if ollama:
        ai.append("Ollama and its AI models")
    elif ollama_models:
        ai.append(f"the AI model it downloaded into Ollama ({', '.join(ollama_models)})")
    remove_ai = bool(ai) and (everything or "--remove-ai" in argv or _ask(
        f"\nSetup also installed AI for Clippy: {'; '.join(ai)}. Other apps may use it too. Remove it as well?",
        False, answers))
    for p, deps in needed.items():
        say(f"\n  {p} stays: {', '.join(deps[:5])} need{'s' if len(deps) == 1 else ''} it.")
    remove_pkgs = bool(packages) and (everything or _ask(
        f"\nSetup also installed these system packages: {', '.join(packages)}. Other programs may use them too. "
        "Remove them as well? (It asks for your password.)", False, answers))
    if not _ask("\nRemove Clippy now?", ("--yes" in argv or everything) and not warning, answers):
        say("Nothing was removed.")
        return 1

    if unit:                                            # stop the Start-at-login Clippy so it can't come back
        _systemctl("disable", "--now", autostart.UNIT)
        autostart.disable()
        say("  Turned off Start at login")
    stop_running(say)
    pkgs_gone = False
    if remove_ai:
        if llama:
            remove_llamacpp(llama, tool=rec["llamacpp"])
            say("  Removed the llama.cpp AI" if rec["llamacpp"] else "  Removed the model it downloaded for llama.cpp")
        if ollama and remove_ollama(say):
            say("  Removed Ollama")
        gone = remove_ollama_models(ollama_models, say) if ollama_models else []
        if gone:
            say(f"  Removed {', '.join(gone)} from Ollama")
    if remove_pkgs and remove_packages(packages, say):
        pkgs_gone = True
        say(f"  Removed {', '.join(packages)}")
    if own_shorts and keep:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(shorts), str(target))
        say(f"  Your videos and shorts are in {target}")
    if link:
        link.unlink(missing_ok=True)
    for p in extra:
        p.unlink(missing_ok=True)
    shutil.rmtree(ROOT, ignore_errors=True)
    if ROOT.exists():
        say(f"  Some files in {ROOT} couldn't be removed; delete that folder yourself.")

    say("\nClippy is uninstalled.")
    stays = []
    if packages and not pkgs_gone:
        stays.append(f"the system packages setup installed ({', '.join(packages)})")
    if needed:
        stays.append(f"{', '.join(needed)}, which other programs need")
    if ai and not remove_ai:
        stays.append("; ".join(ai))
    if not rec["known"]:                                # set up before setup kept track of what it installed
        stays.append("anything setup installed before it kept a list (ffmpeg, the emoji font, an AI): remove those "
                     f"yourself if you don't need them (Ollama: {OLLAMA_UNINSTALL})")
    elif shutil.which("ollama") and not ollama:
        stays.append(f"Ollama, which was on this PC before Clippy (to remove it: {OLLAMA_UNINSTALL})")
    if stays:
        say("These stay:\n" + "\n".join(f"  • {s}" for s in stays))
    if pkgs_gone and shutil.which("apt-get"):
        say("To free the space ffmpeg's helper packages use: sudo apt autoremove")
    if os.environ.get("OLDPWD", "").startswith(str(ROOT)):
        say("Your terminal was in the removed folder: run  cd ~")
    say(f"To install Clippy again: {INSTALL_LINE}")
    return 0
