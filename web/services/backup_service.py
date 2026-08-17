"""Backup and restore operations for game.db.

- create_backup() uses sqlite3.Connection.backup() so it is safe to run while
  lunar-tear has the database open.
- restore_backup() refuses if lunar-tear appears to be running (port probe),
  takes a safety pre-restore backup, then copies the chosen file over game.db.
- list_backups() / prune_to_last_n() manage the rolling pool under data/backups/.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from web import config
from web.services import service_control


class RestoreBlocked(Exception):
    """Raised when a restore is refused for safety reasons."""


VALID_REASONS = (
    "manual", "auto", "item-editor", "costume-editor", "weapon-editor",
    "upgrade-manager", "memoir-editor", "pre-restore",
)

# Display labels used by templates. Filename forms stay kebab-case for safety.
REASON_LABELS: dict[str, str] = {
    "manual": "Manual",
    "auto": "Auto",
    "item-editor": "Item Editor",
    "costume-editor": "Costume Editor",
    "weapon-editor": "Weapon Editor",
    "upgrade-manager": "Upgrade Manager",
    "memoir-editor": "Memoir Editor",
    "pre-restore": "Pre-Restore",
}


def reason_label(reason: str) -> str:
    return REASON_LABELS.get(reason, reason)


@dataclass(frozen=True)
class BackupInfo:
    filename: str
    path: Path
    created_at: datetime
    size_bytes: int
    reason: str

    @property
    def size_human(self) -> str:
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @property
    def reason_display(self) -> str:
        return reason_label(self.reason)


def ensure_dirs() -> None:
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def create_backup(reason: str = "manual") -> BackupInfo:
    """Take a live-safe snapshot of game.db. Prunes to BACKUP_RETENTION afterward."""
    if reason not in VALID_REASONS:
        raise ValueError(f"reason must be one of {VALID_REASONS}, got {reason!r}")
    if not config.GAME_DB_PATH.exists():
        raise FileNotFoundError(f"Game database not found: {config.GAME_DB_PATH}")

    ensure_dirs()
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    filename = f"backup_{timestamp}_{reason}.db"
    dest = config.BACKUP_DIR / filename

    src = sqlite3.connect(str(config.GAME_DB_PATH))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    prune_to_last_n(config.BACKUP_RETENTION)
    return _info_from_path(dest)


def list_backups() -> list[BackupInfo]:
    """Return all backups, newest first."""
    ensure_dirs()
    files = sorted(
        config.BACKUP_DIR.glob("backup_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [_info_from_path(f) for f in files]


def prune_to_last_n(n: int) -> int:
    """Delete the oldest backups beyond the n most recent. Returns count deleted."""
    backups = list_backups()
    excess = backups[n:]
    for b in excess:
        try:
            b.path.unlink()
        except OSError:
            pass
    return len(excess)


def detect_lunar_tear_running() -> str | None:
    """Return a human-readable reason string if lunar-tear looks like it is up.

    Probes the gRPC port (8003 by default, or whatever .wizard.json says).
    Something listening means lunar-tear is almost certainly running.
    """
    port = service_control.grpc_port()
    if service_control.port_is_open(port):
        return (f"lunar-tear gRPC server is listening on port {port}. "
                "Stop it before restoring.")
    return None


@dataclass(frozen=True)
class RestoreResult:
    """Outcome of a restore, including any service management performed."""
    source: BackupInfo
    steps: tuple[str, ...]
    server_restarted: bool


def _swap_database(backup_path: Path) -> None:
    """Replace game.db with the backup, atomically.

    Copying straight over game.db leaves a window where the file is half
    written; a crash there loses the save entirely. Writing a sibling
    temp file and renaming it means the path is only ever the complete
    old database or the complete new one. os.replace is atomic on the
    same filesystem, which a sibling path guarantees.
    """
    target = config.GAME_DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".restore-tmp")

    try:
        shutil.copyfile(backup_path, staging)
        os.replace(staging, target)
    except PermissionError as exc:
        # Windows refuses to replace a file another process holds open.
        # POSIX allows it silently, so this only fires on Windows -- and
        # it fires instead of corrupting anything, which is the outcome
        # we want. Translate it into something the user can act on.
        raise RestoreBlocked(
            "The game database is locked by another process, so it cannot "
            "be replaced. Stop the Lunar Tear server (and close anything "
            f"else holding {target.name}) and try again."
        ) from exc
    finally:
        if staging.exists():
            try:
                staging.unlink()
            except OSError:
                pass

    # Drop stale WAL/SHM sidecars so SQLite reopens against the new file
    # instead of replaying a log belonging to the old one.
    for suffix in ("-wal", "-shm"):
        sidecar = target.with_name(target.name + suffix)
        if sidecar.exists():
            try:
                sidecar.unlink()
            except OSError:
                pass


def restore_backup(filename: str, manage_server: bool = False) -> RestoreResult:
    """Overwrite game.db with the named backup file.

    With `manage_server` False the behaviour is unchanged: refuse while
    lunar-tear is listening.

    With `manage_server` True, perform the sequence by hand-rolling it:
    stop the unit, wait for the port to close, snapshot, swap, start the
    unit again. The server is restarted even if the swap fails, so a
    failure never leaves the game server down.
    """
    backup_path = (config.BACKUP_DIR / filename).resolve()
    if backup_path.parent != config.BACKUP_DIR.resolve():
        raise FileNotFoundError(f"Backup not found: {filename}")
    if not backup_path.exists() or not backup_path.is_file():
        raise FileNotFoundError(f"Backup not found: {filename}")

    if not manage_server:
        blocker = detect_lunar_tear_running()
        if blocker:
            raise RestoreBlocked(blocker)
        if config.GAME_DB_PATH.exists():
            create_backup(reason="pre-restore")
        _swap_database(backup_path)
        return RestoreResult(
            source=_info_from_path(backup_path),
            steps=("Restored while the server was already stopped",),
            server_restarted=False,
        )

    if not service_control.available():
        raise RestoreBlocked(service_control.unavailable_reason())

    report = service_control.ServiceReport()
    was_active = service_control.is_active()

    if was_active:
        # Raises before anything is touched if the unit will not stop or
        # the port stays open.
        service_control.stop_and_wait(report)
    else:
        report.note("Server was already stopped")

    try:
        if config.GAME_DB_PATH.exists():
            create_backup(reason="pre-restore")
            report.note("Pre-restore snapshot taken")
        _swap_database(backup_path)
        report.note(f"Database replaced from {backup_path.name}")
    finally:
        # Bring the server back up regardless of what happened above. The
        # swap is atomic, so on failure the old database is intact and
        # starting again is safe.
        if was_active:
            service_control.start_and_wait(report)

    return RestoreResult(
        source=_info_from_path(backup_path),
        steps=tuple(report.steps),
        server_restarted=report.started,
    )


def _info_from_path(p: Path) -> BackupInfo:
    stat = p.stat()
    stem = p.stem  # backup_YYYY-MM-DDTHH-MM-SS_reason
    parts = stem.split("_", 2)
    ts_str = parts[1] if len(parts) > 1 else ""
    reason = parts[2] if len(parts) > 2 else "manual"
    try:
        created = datetime.strptime(ts_str, "%Y-%m-%dT%H-%M-%S")
    except ValueError:
        created = datetime.fromtimestamp(stat.st_mtime)
    return BackupInfo(
        filename=p.name,
        path=p,
        created_at=created,
        size_bytes=stat.st_size,
        reason=reason,
    )
