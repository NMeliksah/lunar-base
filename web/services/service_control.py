"""Control the lunar-tear system service from Lunar Base.

Restoring a backup means copying a file over `game.db`, which is only safe
once lunar-tear has released the database. Doing that by hand is
    systemctl stop lunar-tear
    <restore>
    systemctl start lunar-tear
and this module automates exactly that, with one addition that matters:
after `systemctl stop` returns, we wait for the gRPC port to actually
close. systemd reports the unit stopped once the process has exited from
its point of view, which is not the same instant SQLite releases its file
handles. Swapping the database out from under a process that still holds
it open is the corruption case the whole restore guard exists to prevent.

Everything here degrades gracefully: on Windows, in a container without
systemd, or when the unit simply does not exist, `available()` returns
False and the caller falls back to refusing the restore as before.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field

from web import config


# Unit name without the .service suffix. Override with LUNAR_TEAR_UNIT.
UNIT_NAME: str = os.environ.get("LUNAR_TEAR_UNIT", "lunar-tear")

# How long to wait for the port to close after stop / open after start.
STOP_TIMEOUT_S: float = 30.0
START_TIMEOUT_S: float = 60.0
POLL_INTERVAL_S: float = 0.25

# Extra pause after the port closes, so in-flight SQLite cleanup finishes.
SETTLE_S: float = 1.0


class ServiceError(Exception):
    """Raised when a systemd operation fails."""


@dataclass
class ServiceReport:
    """What actually happened, for surfacing in the UI."""
    steps: list[str] = field(default_factory=list)
    stopped: bool = False
    started: bool = False

    def note(self, message: str) -> None:
        self.steps.append(message)


# --- systemd plumbing -------------------------------------------------------

def _systemctl() -> list[str] | None:
    """Return the systemctl command prefix, or None if unusable here."""
    if sys.platform == "win32":
        return None
    binary = shutil.which("systemctl")
    if binary is None:
        return None
    # systemd must actually be PID 1 for unit management to mean anything.
    if not os.path.isdir("/run/systemd/system"):
        return None
    if os.geteuid() == 0:
        return [binary]
    if shutil.which("sudo"):
        # -n: never prompt. A hung sudo password prompt inside a web request
        # would block the worker with no way for the user to answer it.
        return ["sudo", "-n", binary]
    return None


def _run(args: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True,
                          timeout=timeout, check=False)


def unit_exists() -> bool:
    prefix = _systemctl()
    if prefix is None:
        return False
    try:
        res = _run(prefix + ["cat", f"{UNIT_NAME}.service"])
    except (subprocess.TimeoutExpired, OSError):
        return False
    return res.returncode == 0


def available() -> bool:
    """True when this process can start and stop the lunar-tear unit."""
    return _systemctl() is not None and unit_exists()


def is_active() -> bool:
    prefix = _systemctl()
    if prefix is None:
        return False
    try:
        res = _run(prefix + ["is-active", f"{UNIT_NAME}.service"])
    except (subprocess.TimeoutExpired, OSError):
        return False
    return res.stdout.strip() == "active"


def unavailable_reason() -> str:
    """Human-readable explanation of why automatic control is off."""
    if sys.platform == "win32":
        return "Automatic server control needs systemd; this is Windows."
    if shutil.which("systemctl") is None:
        return "systemctl was not found on PATH."
    if not os.path.isdir("/run/systemd/system"):
        return "systemd is not running as init in this environment."
    if os.geteuid() != 0 and not shutil.which("sudo"):
        return "Lunar Base is not running as root and sudo is unavailable."
    if not unit_exists():
        return (f"No {UNIT_NAME}.service unit found. Create one, or set "
                f"LUNAR_TEAR_UNIT to the correct unit name.")
    return "Automatic server control is unavailable."


# --- port probing -----------------------------------------------------------

def grpc_port() -> int:
    """The port lunar-tear listens on, from .wizard.json when readable."""
    port = config.LUNAR_TEAR_DEFAULT_GRPC_PORT
    if config.WIZARD_CONFIG_PATH.exists():
        try:
            cfg = json.loads(config.WIZARD_CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return port
        # The wizard has used more than one key for this across versions;
        # accept any of them rather than silently falling back to 8003.
        for key in ("grpc_port", "grpcPort", "grpc-port", "port"):
            value = cfg.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
            # Some versions store "host:port".
            if isinstance(value, str) and ":" in value:
                tail = value.rsplit(":", 1)[-1]
                if tail.isdigit():
                    return int(tail)
    return port


def port_is_open(port: int, timeout: float = 0.5) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def _wait_for_port(port: int, want_open: bool, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_is_open(port) == want_open:
            return True
        time.sleep(POLL_INTERVAL_S)
    return port_is_open(port) == want_open


# --- operations -------------------------------------------------------------

def stop_and_wait(report: ServiceReport) -> None:
    """Stop lunar-tear and block until its port is closed.

    Raises ServiceError if the unit will not stop or the port stays open,
    so the caller aborts before touching the database.
    """
    prefix = _systemctl()
    if prefix is None:
        raise ServiceError(unavailable_reason())

    port = grpc_port()
    report.note(f"Stopping {UNIT_NAME}.service")
    try:
        res = _run(prefix + ["stop", f"{UNIT_NAME}.service"], timeout=60)
    except subprocess.TimeoutExpired:
        raise ServiceError(f"Timed out running systemctl stop {UNIT_NAME}.service")
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip()
        raise ServiceError(f"Could not stop {UNIT_NAME}.service: {detail}")

    report.stopped = True

    if not _wait_for_port(port, want_open=False, timeout=STOP_TIMEOUT_S):
        raise ServiceError(
            f"{UNIT_NAME}.service reported stopped, but port {port} is still "
            f"accepting connections after {STOP_TIMEOUT_S:.0f}s. Refusing to "
            "replace the database while something may still hold it open."
        )

    time.sleep(SETTLE_S)
    report.note(f"Port {port} closed; database is quiesced")


def start_and_wait(report: ServiceReport) -> None:
    """Start lunar-tear and block until its port accepts connections."""
    prefix = _systemctl()
    if prefix is None:
        raise ServiceError(unavailable_reason())

    port = grpc_port()
    report.note(f"Starting {UNIT_NAME}.service")
    try:
        res = _run(prefix + ["start", f"{UNIT_NAME}.service"], timeout=60)
    except subprocess.TimeoutExpired:
        raise ServiceError(f"Timed out running systemctl start {UNIT_NAME}.service")
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip()
        raise ServiceError(f"Could not start {UNIT_NAME}.service: {detail}")

    report.started = True

    if not _wait_for_port(port, want_open=True, timeout=START_TIMEOUT_S):
        raise ServiceError(
            f"{UNIT_NAME}.service was started but port {port} is not listening "
            f"after {START_TIMEOUT_S:.0f}s. Check: journalctl -u {UNIT_NAME} -n 50"
        )

    report.note(f"Port {port} listening again")
