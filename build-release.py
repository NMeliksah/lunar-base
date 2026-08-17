#!/usr/bin/env python3
"""
Build the Lunar Base release archives for both platforms.

    python build-release.py            # version from web/config.py
    python build-release.py 2.0.0      # explicit version

Produces, in dist/:
    lunar-base-v<version>-linux-amd64.tar.gz
    lunar-base-v<version>-windows-amd64.zip

Runs on Windows and Linux, and produces byte-identical archives from
either. Both shim binaries must be present in tools/grant/ first:

    tools/grant/grant        Linux    ./start-lunar-base.sh --rebuild-shim
    tools/grant/grant.exe    Windows  start-lunar-base.bat --rebuild-shim

If you only built one, copy the other across before packaging.
"""

from __future__ import annotations

import re
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

LINUX_SHIM = ROOT / "tools" / "grant" / "grant"
WINDOWS_SHIM = ROOT / "tools" / "grant" / "grant.exe"

# Files shared by both archives. tools/schemas.json and dump_masterdata.py
# are included on purpose: they came from lunar-scripts, and shipping them
# is what frees users from needing that repo as a sibling checkout.
COMMON = [
    "web",
    "tools/dump_masterdata.py",
    "tools/extract_names.py",
    "tools/dump_karma_options.py",
    "tools/schemas.json",
    "tools/grant/src",
    "start-lunar-base.py",
    "README.md",
    "LICENSE",
    "THIRD-PARTY-NOTICES.md",
]

OPTIONAL = ["KARMA_REFERENCE.md"]

REQUIRED = [
    "web/app.py",
    "web/config.py",
    "web/requirements.txt",
    "tools/dump_masterdata.py",
    "tools/extract_names.py",
    "tools/schemas.json",
    "start-lunar-base.py",
    "README.md",
    "LICENSE",
    "THIRD-PARTY-NOTICES.md",
]

# Anything matching these must never reach an archive.
FORBIDDEN = [
    re.compile(r"(^|/)\.venv/"),
    re.compile(r"(^|/)\.build/"),
    re.compile(r"^[^/]+/data/"),
    re.compile(r"__pycache__"),
    re.compile(r"\.pyc$"),
    re.compile(r"\.lunar-base\.json$"),
    re.compile(r"(^|/)setup\.bat$"),
    re.compile(r"(^|/)run-lunar-base\.bat$"),
    re.compile(r"(^|/)\.git/"),
]

# Files that must be executable on Linux. Windows has no permission bit to
# preserve, so building the tarball there would otherwise ship a launcher
# nobody can run without chmod.
EXECUTABLE = {"start-lunar-base.sh", "install-service.sh", "grant"}

# Shell scripts break on Linux with CRLF ("bad interpreter"); batch files
# need CRLF. Git's autocrlf on Windows can leave either in the wrong shape,
# so normalise on the way into the archive rather than trusting the tree.
LF_SUFFIXES = {".sh", ".py", ".md", ".json", ".txt", ".go", ".html", ".css", ".service"}
CRLF_SUFFIXES = {".bat"}

_USE_COLOR = sys.platform != "win32" and sys.stdout.isatty()
_C = {"ok": "\033[92m", "warn": "\033[93m", "err": "\033[91m",
      "info": "\033[94m", "reset": "\033[0m"}


def say(msg: str = "", level: str = "info") -> None:
    marks = {"info": "-", "ok": "+", "warn": "!", "err": "x"}
    if not msg:
        print()
        return
    if _USE_COLOR:
        print(f"{_C[level]}[{marks[level]}]{_C['reset']} {msg}")
    else:
        print(f"[{marks[level]}] {msg}")


def detect_version(explicit: str | None) -> str | None:
    if explicit:
        return explicit.lstrip("v")
    try:
        source = (ROOT / "web" / "config.py").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"""APP_VERSION[^=]*=\s*["']([^"']+)""", source)
    return match.group(1) if match else None


def check_binary(path: Path, expect: str) -> bool:
    """Verify a shim binary exists and targets the expected platform.

    Reads the magic bytes directly instead of shelling out to `file`,
    which Git Bash on Windows does not provide.
    """
    if not path.is_file():
        say(f"Missing {path.relative_to(ROOT)}", "err")
        return False

    head = path.read_bytes()[:2]
    if expect == "linux":
        ok = head == b"\x7fE"          # \x7fELF
        kind = "ELF (Linux)"
    else:
        ok = head == b"MZ"             # DOS/PE header
        kind = "PE (Windows)"

    if not ok:
        say(f"{path.relative_to(ROOT)} is not a {kind} binary. "
            "Did the two get swapped?", "err")
        return False

    size_mb = path.stat().st_size / (1 << 20)
    say(f"{path.relative_to(ROOT)} -- {kind}, {size_mb:.1f} MB", "ok")
    return True


def normalise_newlines(path: Path) -> None:
    """Force the line endings a file's platform requires."""
    suffix = path.suffix.lower()
    if suffix not in LF_SUFFIXES and suffix not in CRLF_SUFFIXES:
        return
    try:
        raw = path.read_bytes()
    except OSError:
        return
    if b"\x00" in raw[:4096]:        # binary, leave alone
        return
    body = raw.replace(b"\r\n", b"\n")
    if suffix in CRLF_SUFFIXES:
        body = body.replace(b"\n", b"\r\n")
    if body != raw:
        path.write_bytes(body)


def stage(target: Path, extra: list[str]) -> None:
    target.mkdir(parents=True, exist_ok=True)

    for item in COMMON + OPTIONAL + extra:
        source = ROOT / item
        if not source.exists():
            continue
        destination = target / item
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)

    # Strip anything that slipped in via a copied directory.
    for cache in list(target.rglob("__pycache__")):
        shutil.rmtree(cache, ignore_errors=True)
    for compiled in list(target.rglob("*.pyc")):
        compiled.unlink(missing_ok=True)

    for path in target.rglob("*"):
        if path.is_file():
            normalise_newlines(path)

    (target / "tools" / "grant").mkdir(parents=True, exist_ok=True)


def build_tar(staged: Path, archive: Path) -> None:
    def fix(info: tarfile.TarInfo) -> tarfile.TarInfo:
        # Windows gives every file 0o666; set sane modes explicitly so the
        # launcher is runnable no matter where the archive was built.
        name = Path(info.name).name
        info.mode = 0o755 if (info.isdir() or name in EXECUTABLE) else 0o644
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        return info

    with tarfile.open(archive, "w:gz") as tar:
        tar.add(staged, arcname=staged.name, filter=fix)


def build_zip(staged: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(staged.rglob("*")):
            if path.is_file():
                zf.write(path, staged.name + "/" + str(path.relative_to(staged)).replace("\\", "/"))


def audit(archive: Path) -> bool:
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
    else:
        with tarfile.open(archive) as tar:
            names = tar.getnames()

    clean = True
    for pattern in FORBIDDEN:
        hits = [n for n in names if pattern.search(n)]
        if hits:
            say(f"{archive.name} contains {len(hits)} forbidden entries "
                f"matching {pattern.pattern}", "err")
            for hit in hits[:3]:
                say(f"    {hit}", "err")
            clean = False
    return clean


def main() -> int:
    print()
    print("  Lunar Base -- release builder")
    print()

    version = detect_version(sys.argv[1] if len(sys.argv) > 1 else None)
    if not version:
        say("Could not determine the version. Pass it explicitly: "
            "python build-release.py 2.0.0", "err")
        return 1
    say(f"Version {version}", "ok")

    missing = [f for f in REQUIRED if not (ROOT / f).exists()]
    if missing:
        for f in missing:
            say(f"Missing required file: {f}", "err")
        return 1
    say(f"All {len(REQUIRED)} required files present", "ok")

    if not check_binary(LINUX_SHIM, "linux"):
        return 1
    if not check_binary(WINDOWS_SHIM, "windows"):
        return 1

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    results: list[Path] = []

    with tempfile.TemporaryDirectory(prefix="lunar-base-release-") as tmp:
        tmpdir = Path(tmp)

        # --- Linux ---
        name = f"lunar-base-v{version}-linux-amd64"
        say(f"Staging {name}", "info")
        staged = tmpdir / name
        stage(staged, ["start-lunar-base.sh", "install-service.sh", "lunar-base.service"])
        shutil.copy2(LINUX_SHIM, staged / "tools" / "grant" / "grant")
        archive = DIST / f"{name}.tar.gz"
        build_tar(staged, archive)
        results.append(archive)
        say(f"{archive.name}", "ok")

        # --- Windows ---
        name = f"lunar-base-v{version}-windows-amd64"
        say(f"Staging {name}", "info")
        staged = tmpdir / name
        stage(staged, ["start-lunar-base.bat"])
        shutil.copy2(WINDOWS_SHIM, staged / "tools" / "grant" / "grant.exe")
        archive = DIST / f"{name}.zip"
        build_zip(staged, archive)
        results.append(archive)
        say(f"{archive.name}", "ok")

    say()
    say("Auditing archives", "info")
    if not all(audit(a) for a in results):
        say("Refusing to report success with forbidden files present.", "err")
        return 1
    say("Archives are clean", "ok")

    say()
    say("Upload these as release assets:", "ok")
    for archive in results:
        say(f"    {archive.name}  ({archive.stat().st_size / (1 << 20):.1f} MB)", "info")
    say()
    say("Unpack one somewhere fresh and run it once before publishing.", "info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
