#!/usr/bin/env python3
"""
Lunar Base - setup and launcher wizard.

One command to check prerequisites, install what is missing, and run the app.
Works on Windows and Linux.

Usage:
    python3 start-lunar-base.py
    python3 start-lunar-base.py --prefer-saved
    python3 start-lunar-base.py --host 0.0.0.0 --port 8888
    python3 start-lunar-base.py --lunar-tear-ref v1.0.0
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import tarfile
import urllib.request
import venv
import zipfile
from pathlib import Path

# ===== Platform =====

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_ROOT = (not IS_WINDOWS) and os.geteuid() == 0
PY_VER = f"{sys.version_info.major}.{sys.version_info.minor}"

_MACHINE = platform.machine().lower()
GOARCH = {"x86_64": "amd64", "amd64": "amd64",
          "aarch64": "arm64", "arm64": "arm64"}.get(_MACHINE, "amd64")
GOOS = "windows" if IS_WINDOWS else ("darwin" if sys.platform == "darwin" else "linux")

# ===== Paths =====

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
VENV_BIN = VENV_DIR / ("Scripts" if IS_WINDOWS else "bin")
VENV_PYTHON = VENV_BIN / ("python.exe" if IS_WINDOWS else "python")

CONFIG_FILE_PATH = ROOT / ".lunar-base.json"


def _looks_like_lunar_tear(candidate: Path) -> bool:
    """True if the directory plausibly holds a Lunar Tear install."""
    if not candidate.is_dir():
        return False
    markers = (
        candidate / "db" / "game.db",
        candidate / "server" / "db" / "game.db",
        candidate / "assets" / "release",
        candidate / "server" / "assets" / "release",
        candidate / "assets" / "revisions",
        candidate / "server" / "assets" / "revisions",
        candidate / "server" / "go.mod",
        candidate / "wizard",
        candidate / "wizard.exe",
    )
    return any(marker.exists() for marker in markers)


def _saved_setting(key: str):
    try:
        return json.loads(CONFIG_FILE_PATH.read_text(encoding="utf-8")).get(key)
    except (json.JSONDecodeError, OSError, AttributeError):
        return None


def detect_lunar_tear_dir(explicit: str | None = None) -> Path:
    """Locate the Lunar Tear install.

    The conventional layout is a sibling named lunar-tear, but release
    archives unpack as lunar-tear-server-<version>-<os>-<arch>, and people
    keep things wherever they like. Order, most explicit first:

      1. --lunar-tear on the command line
      2. LUNAR_TEAR_DIR in the environment
      3. lunar_tear_dir saved in .lunar-base.json
      4. the conventional sibling ../lunar-tear
      5. any sibling directory carrying Lunar Tear's marker files
    """
    if explicit:
        return Path(explicit).expanduser().resolve()

    from_env = os.environ.get("LUNAR_TEAR_DIR")
    if from_env:
        return Path(from_env).expanduser().resolve()

    saved = _saved_setting("lunar_tear_dir")
    if saved:
        candidate = Path(saved).expanduser()
        if _looks_like_lunar_tear(candidate):
            return candidate.resolve()

    conventional = ROOT.parent / "lunar-tear"
    if _looks_like_lunar_tear(conventional):
        return conventional.resolve()

    try:
        siblings = sorted(
            item for item in ROOT.parent.iterdir()
            if item.is_dir() and item.resolve() != ROOT.resolve()
        )
    except OSError:
        siblings = []

    named = [s for s in siblings if "lunar" in s.name.lower() and "tear" in s.name.lower()]
    for group in (named, siblings):
        for candidate in group:
            if _looks_like_lunar_tear(candidate):
                return candidate.resolve()

    return conventional.resolve()


LUNAR_TEAR_DIR = detect_lunar_tear_dir()

DATA_DIR = ROOT / "data"
MASTERDATA_DIR = DATA_DIR / "masterdata"
NAMES_DIR = DATA_DIR / "names"

TOOLS_DIR = ROOT / "tools"
GRANT_DIR = TOOLS_DIR / "grant"
GRANT_BIN = GRANT_DIR / ("grant.exe" if IS_WINDOWS else "grant")
GRANT_SRC_DIR = GRANT_DIR / "src"
DUMP_MASTERDATA = TOOLS_DIR / "dump_masterdata.py"
EXTRACT_NAMES = TOOLS_DIR / "extract_names.py"

BUILD_DIR = ROOT / ".build"          # scratch space for source + Go toolchain
CONFIG_FILE = CONFIG_FILE_PATH

LUNAR_TEAR_REPO = "https://github.com/Walter-Sparrow/lunar-tear"
DEFAULT_LT_REF = "v1.0.0"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8888


# ===== lunar-tear layout detection =====
# The prebuilt release is flat (lunar-tear/db, lunar-tear/assets).
# A source checkout nests everything under lunar-tear/server/.

def _pick(*candidates: Path) -> Path:
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


def _refresh_lunar_tear_paths() -> None:
    """Recompute everything derived from LUNAR_TEAR_DIR.

    Called after --lunar-tear overrides the detected location so the
    module-level constants stay consistent with it.
    """
    g = globals()
    server_dir = LUNAR_TEAR_DIR / "server"
    assets_dir = _pick(server_dir / "assets", LUNAR_TEAR_DIR / "assets")
    g["LT_SERVER_DIR"] = server_dir
    g["LT_DB_DIR"] = _pick(server_dir / "db", LUNAR_TEAR_DIR / "db")
    g["LT_ASSETS_DIR"] = assets_dir
    g["LT_RELEASE_DIR"] = assets_dir / "release"
    g["LT_REVISIONS_DIR"] = assets_dir / "revisions"
    g["GAME_DB_PATH"] = g["LT_DB_DIR"] / "game.db"


LT_SERVER_DIR = LUNAR_TEAR_DIR / "server"        # only in a source checkout
LT_DB_DIR = _pick(LT_SERVER_DIR / "db", LUNAR_TEAR_DIR / "db")
LT_ASSETS_DIR = _pick(LT_SERVER_DIR / "assets", LUNAR_TEAR_DIR / "assets")
LT_RELEASE_DIR = LT_ASSETS_DIR / "release"
LT_REVISIONS_DIR = LT_ASSETS_DIR / "revisions"
GAME_DB_PATH = LT_DB_DIR / "game.db"


# ===== Output =====

_USE_COLOR = (not IS_WINDOWS) and sys.stdout.isatty()
_C = {"info": "\033[94m", "ok": "\033[92m",
      "warn": "\033[93m", "err": "\033[91m", "reset": "\033[0m"}


def say(msg: str = "", level: str = "info") -> None:
    marks = {"info": "-", "ok": "+", "warn": "!", "err": "x"}
    if not msg:
        print()
        return
    mark = marks.get(level, "-")
    if _USE_COLOR:
        print(f"{_C[level]}[{mark}]{_C['reset']} {msg}")
    else:
        print(f"[{mark}] {msg}")


def tail(res: subprocess.CompletedProcess, level: str, lines: int = 6) -> None:
    text = (res.stderr or "") + (res.stdout or "")
    for line in text.strip().splitlines()[-lines:]:
        say(f"  {line}", level)


def banner() -> None:
    print()
    print("  =====================================================")
    print("             LUNAR BASE - setup and launcher")
    print("      Web manager for a Lunar Tear private server")
    print("  =====================================================")
    print()


def ask_yes_no(question: str, assume_yes: bool = False, default_yes: bool = False) -> bool:
    if assume_yes:
        say(f"{question} -> yes", "info")
        return True
    if not sys.stdin.isatty():
        say(f"{question} -> {'yes' if default_yes else 'no'} (no terminal)", "warn")
        return default_yes
    suffix = "[Y/n]" if default_yes else "[y/N]"
    try:
        answer = input(f"    {question} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default_yes
    return answer in ("y", "yes")


# ===== System packages =====

def apt_available() -> bool:
    return IS_LINUX and shutil.which("apt-get") is not None


def _apt_prefix() -> list[str] | None:
    if IS_ROOT:
        return []
    if shutil.which("sudo"):
        return ["sudo"]
    return None


def apt_install(packages: list[str], label: str, assume_yes: bool = False) -> bool:
    if not apt_available():
        say(f"{label} is missing and cannot be installed automatically here.", "err")
        return False

    prefix = _apt_prefix()
    if prefix is None:
        say(f"{label} is missing, and neither root nor sudo is available.", "err")
        say(f"Install it manually:  apt install {' '.join(packages)}", "info")
        return False

    if not ask_yes_no(f"Install {label} via apt?", assume_yes):
        say(f"Skipped installing {label}.", "warn")
        return False

    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive")
    say(f"Installing {label} (this can take a minute)...", "info")
    try:
        subprocess.run(prefix + ["apt-get", "update"], env=env, timeout=300,
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        res = subprocess.run(prefix + ["apt-get", "install", "-y"] + packages,
                             env=env, timeout=1800, check=False,
                             capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        say(f"Installing {label} timed out.", "err")
        return False

    if res.returncode != 0:
        say(f"Failed to install {label}.", "err")
        tail(res, "err")
        return False

    say(f"{label} installed.", "ok")
    return True


# ===== Prerequisites =====

def check_python_version() -> bool:
    if sys.version_info < (3, 10):
        say(f"Python 3.10 or newer is required (found {PY_VER}).", "err")
        say("On Ubuntu:  apt install python3 python3-venv", "info")
        return False
    say(f"Python {PY_VER}", "ok")
    return True


def ensurepip_available() -> bool:
    """Debian and Ubuntu ship `venv` but split out `ensurepip`, so importing
    venv proves nothing. Test for ensurepip directly."""
    return importlib.util.find_spec("ensurepip") is not None


def ensure_ensurepip(assume_yes: bool = False) -> bool:
    if ensurepip_available():
        say("Python venv support (ensurepip)", "ok")
        return True

    say("Python venv support is missing (ensurepip is not installed).", "warn")
    for packages, label in (([f"python{PY_VER}-venv"], f"python{PY_VER}-venv"),
                            (["python3-venv"], "python3-venv")):
        if apt_install(packages, label, assume_yes) and ensurepip_available():
            return True

    say("Cannot continue without venv support.", "err")
    say(f"Install it manually:  apt install python{PY_VER}-venv", "info")
    return False


def check_lunar_tear() -> bool:
    if not LUNAR_TEAR_DIR.is_dir() or not _looks_like_lunar_tear(LUNAR_TEAR_DIR):
        say("Could not find a Lunar Tear install.", "err")
        say(f"Looked beside this folder ({ROOT.parent}) for a directory "
            "containing db/, assets/, or a wizard binary.", "info")
        say("The usual layout is:", "info")
        say("    <parent>/lunar-tear/", "info")
        say("    <parent>/lunar-base/   <- this folder", "info")
        say("If it lives elsewhere, point at it directly:", "info")
        say("    ./start-lunar-base.sh --lunar-tear /path/to/lunar-tear", "info")
        return False

    layout = "source checkout" if LT_SERVER_DIR.is_dir() else "prebuilt release"
    say(f"Lunar Tear found at {LUNAR_TEAR_DIR} ({layout})", "ok")
    if LUNAR_TEAR_DIR.name != "lunar-tear":
        say("Detected by its contents, not its name. Override with "
            "--lunar-tear PATH if this is the wrong folder.", "info")

    if GAME_DB_PATH.exists():
        say(f"Game database: {GAME_DB_PATH}", "ok")
    else:
        say(f"Game database not found at {GAME_DB_PATH}", "warn")
        say("Start the Lunar Tear server once to create it.", "info")

    if not LT_RELEASE_DIR.is_dir():
        say(f"Master data folder not found at {LT_RELEASE_DIR}", "warn")
    if not LT_REVISIONS_DIR.is_dir():
        say(f"Asset revisions not found at {LT_REVISIONS_DIR}", "warn")

    return True


def find_master_data_bin() -> Path | None:
    if not LT_RELEASE_DIR.is_dir():
        return None
    files = sorted(LT_RELEASE_DIR.glob("*.bin.e"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def has_json(directory: Path) -> bool:
    return directory.is_dir() and any(directory.glob("*.json"))


# ===== Virtual environment =====

def venv_pip_works() -> bool:
    if not VENV_PYTHON.exists():
        return False
    try:
        res = subprocess.run([str(VENV_PYTHON), "-m", "pip", "--version"],
                             capture_output=True, text=True, timeout=60, check=False)
        return res.returncode == 0
    except Exception:
        return False


def create_venv() -> bool:
    if VENV_DIR.exists():
        if venv_pip_works():
            say("Virtual environment is present and healthy.", "ok")
            return True
        say("Virtual environment is broken; rebuilding it.", "warn")
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    say("Creating virtual environment...", "info")
    try:
        venv.create(VENV_DIR, with_pip=True, clear=True)
    except SystemExit as exc:
        # Debian's patched venv calls sys.exit() when ensurepip is missing,
        # and SystemExit does not derive from Exception.
        say(f"Virtual environment creation aborted (exit code {exc.code}).", "err")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        return False
    except Exception as exc:
        say(f"Failed to create virtual environment: {exc}", "err")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        return False

    if not venv_pip_works():
        say("Virtual environment was created but pip is not usable.", "err")
        return False

    say("Virtual environment created.", "ok")
    return True


def pip_install(args: list[str], label: str, required: bool) -> bool:
    level = "err" if required else "warn"
    try:
        res = subprocess.run([str(VENV_PYTHON), "-m", "pip", "install"] + args,
                             capture_output=True, text=True, timeout=1800, check=False)
    except subprocess.TimeoutExpired:
        say(f"Installing {label} timed out.", level)
        return False
    if res.returncode != 0:
        say(f"Failed to install {label}.", level)
        tail(res, level)
        return False
    say(f"{label} installed.", "ok")
    return True


def install_app_dependencies() -> bool:
    requirements = ROOT / "web" / "requirements.txt"
    if not requirements.exists():
        say(f"requirements.txt not found at {requirements}", "err")
        return False
    say("Installing application dependencies...", "info")
    subprocess.run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"],
                   capture_output=True, text=True, timeout=600, check=False)
    return pip_install(["-r", str(requirements)], "application dependencies", True)


# ===== Game data =====

def dump_master_data() -> bool:
    if has_json(MASTERDATA_DIR):
        say("Master data already decoded; skipping.", "ok")
        return True
    if not DUMP_MASTERDATA.exists():
        say(f"Missing {DUMP_MASTERDATA}; skipping master-data dump.", "warn")
        return False

    schemas = TOOLS_DIR / "schemas.json"
    if not schemas.exists():
        say(f"schemas.json not found at {schemas}", "warn")
        say("Copy it from the lunar-scripts repo into tools/.", "info")
        return False

    source = find_master_data_bin()
    if source is None:
        say("No .bin.e master data found in Lunar Tear; skipping dump.", "warn")
        return False

    say(f"Decoding master data from {source.name}...", "info")
    MASTERDATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        res = subprocess.run([str(VENV_PYTHON), str(DUMP_MASTERDATA),
                              "--input", str(source), "--output", str(MASTERDATA_DIR)],
                             capture_output=True, text=True, timeout=1800, check=False)
    except subprocess.TimeoutExpired:
        say("Master-data dump timed out.", "warn")
        return False
    if res.returncode != 0:
        say("Master-data dump failed.", "warn")
        tail(res, "warn")
        return False
    say("Master data decoded.", "ok")
    return True


# Files the editors refuse to start without. Checked after extraction so a
# silent partial run cannot look like success.
REQUIRED_NAME_FILES: tuple[str, ...] = (
    "materials.json",
    "consumables.json",
    "important_items.json",
    "weapons.json",
    "playable_costumes.json",
)


def find_text_revision() -> tuple[int, Path] | None:
    """Locate an English text root, mirroring extract_names' own search.

    Handles both revisions/<n>/assetbundle/... and the platform-nested
    revisions/<n>/<platform>/assetbundle/... that lunar-tear v1.0.0 uses.
    """
    if not LT_REVISIONS_DIR.is_dir():
        return None
    found: list[tuple[int, Path]] = []
    for revision_dir in LT_REVISIONS_DIR.iterdir():
        if not revision_dir.is_dir():
            continue
        try:
            revision = int(revision_dir.name)
        except ValueError:
            continue
        direct = revision_dir / "assetbundle" / "text" / "en"
        if direct.is_dir():
            found.append((revision, direct))
            continue
        for child in sorted(revision_dir.iterdir()):
            if not child.is_dir():
                continue
            nested = child / "assetbundle" / "text" / "en"
            if nested.is_dir():
                found.append((revision, nested))
                break
    if not found:
        return None
    found.sort(key=lambda item: item[0])
    return found[-1]


def missing_name_files() -> list[str]:
    return [n for n in REQUIRED_NAME_FILES if not (NAMES_DIR / n).exists()]


def extract_names(revision: str | None = None) -> bool:
    if has_json(NAMES_DIR) and not missing_name_files():
        say("English names already extracted; skipping.", "ok")
        return True

    if not EXTRACT_NAMES.exists():
        say(f"Missing {EXTRACT_NAMES}; skipping name extraction.", "warn")
        return False
    if not has_json(MASTERDATA_DIR):
        say("Master data unavailable; skipping name extraction.", "warn")
        return False
    if not LT_REVISIONS_DIR.is_dir():
        say(f"Asset revisions not found at {LT_REVISIONS_DIR}", "warn")
        return False

    located = find_text_revision()
    if located is None:
        say("No English text bundles found under the revisions tree.", "err")
        say(f"Looked under {LT_REVISIONS_DIR} for", "info")
        say("    <revision>/assetbundle/text/en", "info")
        say("    <revision>/<platform>/assetbundle/text/en", "info")
        say("Without these the editors have no item names and stay empty.", "warn")
        return False

    say(f"Using text revision {located[0]} ({located[1]})", "ok")

    say("Extracting English names from text bundles...", "info")
    NAMES_DIR.mkdir(parents=True, exist_ok=True)
    command = [str(VENV_PYTHON), str(EXTRACT_NAMES),
               "--master-data-dir", str(MASTERDATA_DIR),
               "--revisions-dir", str(LT_REVISIONS_DIR),
               "--output-dir", str(NAMES_DIR)]
    if revision:
        command += ["--revision", revision]

    try:
        res = subprocess.run(command, cwd=str(ROOT), capture_output=True,
                             text=True, timeout=1800, check=False)
    except subprocess.TimeoutExpired:
        say("Name extraction timed out.", "warn")
        return False

    if res.returncode != 0:
        say("Name extraction failed; the editors will have no item names.", "err")
        tail(res, "err", 10)
        return False

    # A zero exit is not proof of success: the script warns and continues on
    # individual kinds, so verify the files the editors actually need.
    absent = missing_name_files()
    if absent:
        say("Name extraction finished but required files are missing:", "err")
        for name in absent:
            say(f"  {name}", "err")
        tail(res, "warn", 10)
        return False

    report_name_resolution(res.stdout)
    say("English names extracted.", "ok")
    return True


def report_name_resolution(output: str) -> None:
    """Surface the per-kind 'N/M names resolved' counts the script prints.

    A revision holding only partial text bundles still exits zero but leaves
    most names unresolved, which shows up in the UI as raw numeric IDs.
    """
    poor: list[str] = []
    for line in output.splitlines():
        if "names resolved" not in line or "(" not in line:
            continue
        try:
            kind = line.split(":", 1)[0].strip()
            fraction = line.split("(", 1)[1].split(" ", 1)[0]
            resolved, total = (int(part) for part in fraction.split("/"))
        except (ValueError, IndexError):
            continue
        if total and resolved / total < 0.5:
            poor.append(f"{kind} {resolved}/{total}")
    if poor:
        say("Some categories resolved few names:", "warn")
        for entry in poor[:8]:
            say(f"  {entry}", "warn")
        say("Try a different revision with --text-revision <n>.", "info")


# ===== Go toolchain =====

def _download(url: str, dest: Path, label: str) -> bool:
    say(f"Downloading {label}...", "info")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as response, open(dest, "wb") as out:
            shutil.copyfileobj(response, out)
    except Exception as exc:
        say(f"Download failed: {exc}", "err")
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unpack(archive: Path, dest: Path) -> bool:
    try:
        dest.mkdir(parents=True, exist_ok=True)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(dest)
        else:
            with tarfile.open(archive) as tf:
                # `filter` landed in 3.12 and its default changes in 3.14;
                # ask for the safe behaviour explicitly where available.
                try:
                    tf.extractall(dest, filter="data")
                except TypeError:
                    tf.extractall(dest)
        return True
    except Exception as exc:
        say(f"Could not unpack {archive.name}: {exc}", "err")
        return False


def _version_tuple(text: str) -> tuple[int, ...]:
    parts = []
    for piece in text.split("."):
        digits = "".join(c for c in piece if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def required_go_version(server_dir: Path) -> tuple[int, ...]:
    """Read the `go` directive from go.mod."""
    go_mod = server_dir / "go.mod"
    try:
        for line in go_mod.read_text().splitlines():
            line = line.strip()
            if line.startswith("go "):
                return _version_tuple(line.split()[1])
    except Exception:
        pass
    return (1, 25)


def system_go_version(go_exe: str) -> tuple[int, ...] | None:
    try:
        res = subprocess.run([go_exe, "version"], capture_output=True,
                             text=True, timeout=60, check=False)
        if res.returncode != 0:
            return None
        for token in res.stdout.split():
            if token.startswith("go1"):
                return _version_tuple(token[2:])
    except Exception:
        return None
    return None


def download_go(minimum: tuple[int, ...]) -> Path | None:
    """Fetch an official Go toolchain into .build/go and return its go binary."""
    say("Fetching the list of Go releases...", "info")
    try:
        with urllib.request.urlopen("https://go.dev/dl/?mode=json", timeout=60) as response:
            releases = json.loads(response.read().decode())
    except Exception as exc:
        say(f"Could not reach go.dev: {exc}", "err")
        return None

    for release in releases:
        version = release.get("version", "")
        if not version.startswith("go"):
            continue
        if _version_tuple(version[2:]) < minimum:
            continue
        for entry in release.get("files", []):
            if (entry.get("os") == GOOS and entry.get("arch") == GOARCH
                    and entry.get("kind") == "archive"):
                filename = entry["filename"]
                archive = BUILD_DIR / filename
                url = f"https://dl.google.com/go/{filename}"
                if not _download(url, archive, f"{version} ({GOOS}/{GOARCH})"):
                    return None
                expected = entry.get("sha256", "")
                if expected and _sha256(archive) != expected:
                    say("Checksum mismatch on the Go archive; refusing to use it.", "err")
                    archive.unlink(missing_ok=True)
                    return None
                say("Checksum verified.", "ok")
                target = BUILD_DIR / "toolchain"
                shutil.rmtree(target, ignore_errors=True)
                if not _unpack(archive, target):
                    return None
                archive.unlink(missing_ok=True)
                go_exe = target / "go" / "bin" / ("go.exe" if IS_WINDOWS else "go")
                if go_exe.exists():
                    say(f"Go {version} ready.", "ok")
                    return go_exe
                say("Go archive unpacked but the binary is missing.", "err")
                return None

    say("No suitable Go release found for this platform.", "err")
    return None


def ensure_go(server_dir: Path, assume_yes: bool) -> Path | None:
    minimum = required_go_version(server_dir)
    pretty = ".".join(str(p) for p in minimum)

    system = shutil.which("go")
    if system:
        found = system_go_version(system)
        if found and found >= minimum:
            say(f"Go {'.'.join(str(p) for p in found)} found on PATH.", "ok")
            return Path(system)
        found_text = ".".join(str(p) for p in found) if found else "unknown"
        say(f"Go on PATH is {found_text}, but {pretty} or newer is required.", "warn")
    else:
        say(f"Go is not installed; {pretty} or newer is required to build the shim.", "warn")

    say("The official toolchain can be downloaded into .build/ without touching "
        "your system.", "info")
    if not ask_yes_no("Download the Go toolchain now?", assume_yes, default_yes=True):
        return None
    return download_go(minimum)


# ===== Grant shim =====

def locate_lunar_tear_source(explicit: str | None) -> Path | None:
    """Find a lunar-tear source tree whose server/ has a go.mod."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())
    candidates += [
        LUNAR_TEAR_DIR,
        ROOT.parent / "lunar-tear-src",
        BUILD_DIR / "lunar-tear-src",
    ]
    for candidate in candidates:
        if (candidate / "server" / "go.mod").exists():
            return candidate
    return None


def fetch_lunar_tear_source(ref: str) -> Path | None:
    """Download the lunar-tear source archive for a tag into .build/."""
    target = BUILD_DIR / "lunar-tear-src"
    shutil.rmtree(target, ignore_errors=True)

    url = f"{LUNAR_TEAR_REPO}/archive/refs/tags/{ref}.tar.gz"
    archive = BUILD_DIR / f"lunar-tear-{ref}.tar.gz"
    if not _download(url, archive, f"lunar-tear source {ref}"):
        say(f"Could not download {ref}. Check the tag name with --lunar-tear-ref.", "err")
        return None

    staging = BUILD_DIR / "unpack"
    shutil.rmtree(staging, ignore_errors=True)
    if not _unpack(archive, staging):
        return None
    archive.unlink(missing_ok=True)

    extracted = next((p for p in staging.iterdir() if p.is_dir()), None)
    if extracted is None:
        say("Source archive was empty.", "err")
        return None

    shutil.move(str(extracted), str(target))
    shutil.rmtree(staging, ignore_errors=True)

    if not (target / "server" / "go.mod").exists():
        say("Downloaded source does not contain server/go.mod.", "err")
        return None

    say(f"Source {ref} ready at {target}", "ok")
    return target


def build_grant_shim(source_dir: Path, go_exe: Path, assume_yes: bool) -> bool:
    server_dir = source_dir / "server"
    cmd_dir = server_dir / "cmd" / "lunar-base-grant"

    if not GRANT_SRC_DIR.is_dir() or not any(GRANT_SRC_DIR.glob("*.go")):
        say(f"Shim sources missing at {GRANT_SRC_DIR}", "err")
        return False

    say("Copying shim sources into the lunar-tear source tree...", "info")
    cmd_dir.mkdir(parents=True, exist_ok=True)
    for src in GRANT_SRC_DIR.glob("*.go"):
        shutil.copy2(src, cmd_dir / src.name)

    GRANT_DIR.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ,
               GOCACHE=str(BUILD_DIR / "gocache"),
               GOPATH=str(BUILD_DIR / "gopath"),
               GOTOOLCHAIN="local")
    env["PATH"] = str(go_exe.parent) + os.pathsep + env.get("PATH", "")

    def run_build() -> subprocess.CompletedProcess:
        say("Building the grant shim (first build downloads modules)...", "info")
        return subprocess.run(
            [str(go_exe), "build", "-o", str(GRANT_BIN), "./cmd/lunar-base-grant/"],
            cwd=str(server_dir), env=env, capture_output=True, text=True,
            timeout=1800, check=False)

    try:
        res = run_build()
    except subprocess.TimeoutExpired:
        say("Build timed out.", "err")
        return False

    combined = ((res.stderr or "") + (res.stdout or "")).lower()
    if res.returncode != 0 and ("cgo" in combined or "gcc" in combined
                                or "c compiler" in combined):
        say("The build needs a C compiler (cgo).", "warn")
        if apt_install(["build-essential"], "build tools (gcc)", assume_yes):
            try:
                res = run_build()
            except subprocess.TimeoutExpired:
                say("Build timed out.", "err")
                return False

    if res.returncode != 0:
        say("Grant shim build failed.", "err")
        tail(res, "err", 12)
        return False

    if not IS_WINDOWS:
        GRANT_BIN.chmod(GRANT_BIN.stat().st_mode | 0o111)
    say(f"Grant shim built: {GRANT_BIN}", "ok")
    return True


def ensure_grant_shim(args) -> bool:
    if GRANT_BIN.exists():
        if not IS_WINDOWS:
            GRANT_BIN.chmod(GRANT_BIN.stat().st_mode | 0o111)
        say(f"Grant shim found: {GRANT_BIN.name}", "ok")
        return True

    say(f"Grant shim not found at {GRANT_BIN}", "warn")

    source = locate_lunar_tear_source(args.lunar_tear_src)
    if source:
        say(f"Using lunar-tear source at {source}", "ok")
    else:
        say("No lunar-tear source tree available. The shim compiles against "
            "lunar-tear's internal packages, which the prebuilt release omits.", "info")
        say(f"The source for {args.lunar_tear_ref} can be downloaded into .build/ "
            "and removed afterwards.", "info")
        if not ask_yes_no(f"Download lunar-tear {args.lunar_tear_ref} and build the shim?",
                          args.yes, default_yes=True):
            return False
        source = fetch_lunar_tear_source(args.lunar_tear_ref)
        if source is None:
            return False

    go_exe = ensure_go(source / "server", args.yes)
    if go_exe is None:
        return False

    if not build_grant_shim(source, go_exe, args.yes):
        return False

    say("The shim matches the source version it was built from; rebuild it "
        "after upgrading Lunar Tear.", "info")

    if BUILD_DIR.exists():
        size_mb = sum(f.stat().st_size for f in BUILD_DIR.rglob("*") if f.is_file()) // (1 << 20)
        if ask_yes_no(f"Delete the build scratch folder (.build, {size_mb} MB)?",
                      args.yes, default_yes=True):
            shutil.rmtree(BUILD_DIR, ignore_errors=True)
            say("Build files removed.", "ok")
        else:
            say(f"Kept at {BUILD_DIR}", "info")

    return True


# ===== Optional systemd service =====

SERVICE_NAME = "lunar-base"
SERVICE_UNIT_PATH = Path("/etc/systemd/system") / f"{SERVICE_NAME}.service"


def systemd_usable() -> tuple[bool, str]:
    """Whether this process can install and manage systemd units."""
    if not IS_LINUX:
        return False, "systemd services are Linux-only."
    if shutil.which("systemctl") is None:
        return False, "systemctl is not on PATH."
    if not os.path.isdir("/run/systemd/system"):
        return False, "systemd is not running as init here."
    if not IS_ROOT and shutil.which("sudo") is None:
        return False, "not running as root and sudo is unavailable."
    return True, ""


def _systemctl_prefix() -> list[str]:
    binary = shutil.which("systemctl") or "systemctl"
    return [binary] if IS_ROOT else ["sudo", binary]


def service_installed() -> bool:
    prefix = _systemctl_prefix()
    try:
        res = subprocess.run(prefix + ["cat", f"{SERVICE_NAME}.service"],
                             capture_output=True, text=True, timeout=30, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return res.returncode == 0


def service_active() -> bool:
    prefix = _systemctl_prefix()
    try:
        res = subprocess.run(prefix + ["is-active", f"{SERVICE_NAME}.service"],
                             capture_output=True, text=True, timeout=30, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return res.stdout.strip() == "active"


def _unit_text(host: str, port: int) -> str:
    return f"""[Unit]
Description=Lunar Base - save manager for a Lunar Tear private server
After=network-online.target
Wants=network-online.target

# Deliberately NOT After=lunar-tear.service. Lunar Base manages that unit
# and must stay reachable while it is down, which is exactly when the
# restore page is needed.

[Service]
Type=simple
User=root
WorkingDirectory={ROOT}
ExecStart={VENV_PYTHON} -m uvicorn web.app:app --host {host} --port {port}
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier={SERVICE_NAME}
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
"""


def _write_unit(host: str, port: int) -> bool:
    """Write the unit file, using sudo tee when not root."""
    text = _unit_text(host, port)
    try:
        if IS_ROOT:
            SERVICE_UNIT_PATH.write_text(text)
            return True
        res = subprocess.run(["sudo", "tee", str(SERVICE_UNIT_PATH)],
                             input=text, capture_output=True, text=True,
                             timeout=60, check=False)
        if res.returncode != 0:
            say(f"Could not write {SERVICE_UNIT_PATH}: "
                f"{(res.stderr or '').strip()}", "err")
            return False
        return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        say(f"Could not write {SERVICE_UNIT_PATH}: {exc}", "err")
        return False


def install_service(host: str, port: int) -> bool:
    """Install, enable, and start the lunar-base unit."""
    prefix = _systemctl_prefix()

    say(f"Writing {SERVICE_UNIT_PATH}", "info")
    if not _write_unit(host, port):
        return False

    for args, label in (
        (["daemon-reload"], "reloading systemd"),
        (["enable", f"{SERVICE_NAME}.service"], "enabling at boot"),
        (["restart", f"{SERVICE_NAME}.service"], "starting the service"),
    ):
        try:
            res = subprocess.run(prefix + args, capture_output=True,
                                 text=True, timeout=120, check=False)
        except subprocess.TimeoutExpired:
            say(f"Timed out while {label}.", "err")
            return False
        if res.returncode != 0:
            say(f"Failed while {label}.", "err")
            tail(res, "err")
            return False

    time.sleep(2)
    if not service_active():
        say("The service was installed but is not running.", "err")
        say(f"Check:  journalctl -u {SERVICE_NAME} -n 30", "info")
        return False

    say(f"{SERVICE_NAME}.service is running and enabled at boot.", "ok")
    return True


def maybe_install_service(host: str, port: int, args) -> bool:
    """Offer to run Lunar Base as a systemd service.

    Returns True when the app is now being served by systemd, in which
    case the caller must not also start uvicorn in the foreground — both
    would fight over the same port.
    """
    if args.no_service:
        return False

    usable, reason = systemd_usable()
    if not usable:
        # Not worth mentioning on Windows or a plain shell; it is simply
        # not applicable there.
        if IS_LINUX and not args.yes:
            say(f"Skipping the boot service: {reason}", "info")
        return False

    if service_installed():
        if service_active():
            say(f"{SERVICE_NAME}.service is already running.", "ok")
            say("Restarting it so this run's changes take effect.", "info")
            return install_service(host, port)
        say(f"{SERVICE_NAME}.service is installed but stopped.", "info")
        if ask_yes_no("Start it now?", args.yes, default_yes=True):
            return install_service(host, port)
        return False

    say("Lunar Base can run as a background service, so it starts "
        "automatically whenever this machine boots.", "info")
    say("Without it, you start it by hand with this script each time.", "info")
    if not ask_yes_no("Install Lunar Base as a startup service?",
                      args.yes, default_yes=True):
        say("Not installing the service; starting in the foreground.", "info")
        return False

    return install_service(host, port)


# ===== Settings =====

def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    except Exception as exc:
        say(f"Could not save settings: {exc}", "warn")


# ===== Run =====

def run_app(host: str, port: int) -> int:
    say()
    say(f"Lunar Base is starting on http://{host}:{port}", "ok")
    if host == "0.0.0.0":
        say("Reachable from other machines on your network.", "info")
    say("Press Ctrl+C to stop.", "info")
    say()
    try:
        res = subprocess.run([str(VENV_PYTHON), "-m", "uvicorn", "web.app:app",
                              "--host", host, "--port", str(port)],
                             cwd=str(ROOT), check=False)
        return res.returncode
    except KeyboardInterrupt:
        say()
        say("Lunar Base stopped.", "info")
        return 0


# ===== Main =====

def main() -> int:
    parser = argparse.ArgumentParser(description="Lunar Base setup and launcher",
                                     prog="start-lunar-base")
    parser.add_argument("--prefer-saved", action="store_true",
                        help="reuse saved settings without prompting")
    parser.add_argument("--host", default=None,
                        help=f"bind address (default {DEFAULT_HOST}; "
                             "use 0.0.0.0 to reach it from other machines)")
    parser.add_argument("--port", type=int, default=None,
                        help=f"port (default {DEFAULT_PORT})")
    parser.add_argument("--lunar-tear", default=None, metavar="PATH",
                        help="path to the Lunar Tear install "
                             "(default: auto-detected among sibling folders)")
    parser.add_argument("--no-service", action="store_true",
                        help="skip the offer to install the boot service")
    parser.add_argument("--lunar-tear-src", default=None,
                        help="path to a lunar-tear source checkout for building the shim")
    parser.add_argument("--lunar-tear-ref", default=None,
                        help=f"lunar-tear tag to build the shim from (default {DEFAULT_LT_REF})")
    parser.add_argument("--text-revision", default=None,
                        help="asset revision to read English text from (default: newest)")
    parser.add_argument("--rebuild-shim", action="store_true",
                        help="discard the existing grant binary and build it again")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="answer yes to every prompt: install packages, "
                             "build the shim, install the boot service")
    args = parser.parse_args()

    banner()

    cfg = load_config()
    host = args.host or cfg.get("host") or DEFAULT_HOST
    port = args.port or cfg.get("port") or DEFAULT_PORT
    args.lunar_tear_ref = (args.lunar_tear_ref or cfg.get("lunar_tear_ref")
                           or DEFAULT_LT_REF)

    # Re-resolve against an explicit path, then publish it through the
    # environment so the extractor and the app agree with the wizard.
    if args.lunar_tear:
        globals()["LUNAR_TEAR_DIR"] = detect_lunar_tear_dir(args.lunar_tear)
        _refresh_lunar_tear_paths()
    os.environ["LUNAR_TEAR_DIR"] = str(LUNAR_TEAR_DIR)

    say("Checking prerequisites", "info")
    say()
    if not check_python_version():
        return 1
    if not ensure_ensurepip(args.yes):
        return 1
    if not check_lunar_tear():
        return 1

    say()
    say("Preparing the environment", "info")
    say()
    if not create_venv():
        return 1
    if not install_app_dependencies():
        return 1

    say()
    say("Preparing game data", "info")
    say()
    if not has_json(MASTERDATA_DIR):
        say("Installing master-data decoding libraries...", "info")
        pip_install(["pycryptodome", "msgpack", "lz4"], "master-data libraries", False)
    dump_master_data()
    if not extract_names(args.text_revision):
        say("The editors need these names; only backup, restore, and the "
            "viewer will work without them.", "warn")

    say()
    say("Checking the grant shim", "info")
    say()
    if args.rebuild_shim and GRANT_BIN.exists():
        GRANT_BIN.unlink()
        say("Existing grant binary removed; rebuilding.", "info")

    if not ensure_grant_shim(args):
        say()
        say("Backup, restore, and the read-only viewer will still work.", "warn")
        say("The editors need the shim and will fail without it.", "warn")
        if not ask_yes_no("Start Lunar Base anyway?", args.yes):
            return 1

    save_config({
        "host": host,
        "port": port,
        "lunar_tear_ref": args.lunar_tear_ref,
        "lunar_tear_dir": str(LUNAR_TEAR_DIR),
    })

    say()
    say("Startup", "info")
    say()

    if maybe_install_service(host, port, args):
        say()
        say(f"Lunar Base is at http://{host}:{port}", "ok")
        say("It will start again on its own after a reboot.", "info")
        say(f"  systemctl status {SERVICE_NAME}", "info")
        say(f"  systemctl restart {SERVICE_NAME}", "info")
        say(f"  journalctl -u {SERVICE_NAME} -f", "info")
        return 0

    return run_app(host, port)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
