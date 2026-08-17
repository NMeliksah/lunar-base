"""Constants and paths for Lunar Base.

All paths resolve relative to the lunar-base/ root, so the app works the same
no matter what cwd it is launched from.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parent.parent

APP_VERSION: str = "2.0.0"

SETTINGS_FILE: Path = ROOT / ".lunar-base.json"


def _saved_setting(key: str):
    """Read one value from .lunar-base.json, or None."""
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get(key)
    except (json.JSONDecodeError, OSError, AttributeError):
        return None


def looks_like_lunar_tear(candidate: Path) -> bool:
    """True if the directory plausibly holds a Lunar Tear install.

    Checks markers from both shapes: the prebuilt release (flat, with a
    wizard binary next to db/ and assets/) and a source checkout (server/
    with go.mod). Only one marker needs to be present, because a fresh
    install has assets but no database yet, and a source checkout has
    neither until it is built.
    """
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


def detect_lunar_tear_dir() -> Path:
    """Locate the Lunar Tear install.

    Not everyone keeps it at ../lunar-tear — the release archives unpack
    under names like lunar-tear-server-v1.0.0-linux-amd64. Resolution
    order, most explicit first:

      1. LUNAR_TEAR_DIR environment variable
      2. lunar_tear_dir saved in .lunar-base.json (written by the wizard)
      3. the conventional sibling ../lunar-tear
      4. any sibling directory that looks like a Lunar Tear install

    Falls back to the conventional path so error messages still name
    something sensible when nothing is found.
    """
    from_env = os.environ.get("LUNAR_TEAR_DIR")
    if from_env:
        return Path(from_env).expanduser().resolve()

    saved = _saved_setting("lunar_tear_dir")
    if saved:
        candidate = Path(saved).expanduser()
        if looks_like_lunar_tear(candidate):
            return candidate.resolve()

    conventional = ROOT.parent / "lunar-tear"
    if looks_like_lunar_tear(conventional):
        return conventional.resolve()

    try:
        siblings = sorted(
            p for p in ROOT.parent.iterdir()
            if p.is_dir() and p.resolve() != ROOT.resolve()
        )
    except OSError:
        siblings = []

    # Prefer names mentioning lunar-tear before falling back to any match,
    # so a directory named after the release archive wins over something
    # unrelated that happens to carry a marker.
    named = [p for p in siblings if "lunar" in p.name.lower() and "tear" in p.name.lower()]
    for group in (named, siblings):
        for candidate in group:
            if looks_like_lunar_tear(candidate):
                return candidate.resolve()

    return conventional.resolve()


LUNAR_TEAR_DIR: Path = detect_lunar_tear_dir()

# Detect structure: source build (server/) or prebuilt (flat)
def _find_db_path() -> Path:
    """Auto-detect game.db location (source vs prebuilt structure)."""
    source_path = LUNAR_TEAR_DIR / "server" / "db" / "game.db"
    prebuilt_path = LUNAR_TEAR_DIR / "db" / "game.db"
    
    # Prefer source if it exists, fall back to prebuilt
    if source_path.parent.exists():
        return source_path.resolve()
    return prebuilt_path.resolve()


def _find_wizard_config() -> Path:
    """Auto-detect .wizard.json location (source vs prebuilt structure)."""
    source_path = LUNAR_TEAR_DIR / "server" / ".wizard.json"
    prebuilt_path = LUNAR_TEAR_DIR / ".wizard.json"
    
    if source_path.exists():
        return source_path.resolve()
    return prebuilt_path.resolve()


def _find_assets_dir() -> Path:
    """Auto-detect assets directory location (source vs prebuilt structure)."""
    source_path = LUNAR_TEAR_DIR / "server" / "assets"
    prebuilt_path = LUNAR_TEAR_DIR / "assets"
    
    if source_path.exists():
        return source_path.resolve()
    return prebuilt_path.resolve()


GAME_DB_PATH: Path = _find_db_path()
WIZARD_CONFIG_PATH: Path = _find_wizard_config()
ASSETS_DIR: Path = _find_assets_dir()
RELEASE_DIR: Path = ASSETS_DIR / "release"
REVISIONS_DIR: Path = ASSETS_DIR / "revisions"

DATA_DIR: Path = ROOT / "data"
BACKUP_DIR: Path = DATA_DIR / "backups"
MASTERDATA_DIR: Path = DATA_DIR / "masterdata"
NAMES_DIR: Path = DATA_DIR / "names"

# The shim is grant.exe on Windows and a plain `grant` binary elsewhere.
GRANT_EXE_PATH: Path = (
    ROOT / "tools" / "grant" / ("grant.exe" if sys.platform == "win32" else "grant")
)


def find_master_data_bin() -> Path | None:
    """Locate the encrypted master-data binary inside lunar-tear.

    The filename embeds a build timestamp and changes whenever the game data is
    repatched, so we glob for `*.bin.e` and take the most recently modified.
    Returns None if the file is missing — callers should surface that as a
    user-actionable error.
    """
    release_dir = RELEASE_DIR
    if not release_dir.is_dir():
        return None
    candidates = sorted(release_dir.glob("*.bin.e"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


BACKUP_RETENTION: int = 50

HOST: str = "127.0.0.1"
PORT: int = 8888

LUNAR_TEAR_DEFAULT_GRPC_PORT: int = 8003
