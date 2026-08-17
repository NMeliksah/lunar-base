#!/usr/bin/env bash
#
# Install Lunar Base as a systemd service.
#
# Run once from inside the lunar-base directory:
#     sudo ./install-service.sh
#
# Afterwards Lunar Base starts on boot and can be managed with:
#     systemctl status  lunar-base
#     systemctl restart lunar-base
#     journalctl -u lunar-base -f
#

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_PATH="/etc/systemd/system/lunar-base.service"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

HOST="${LUNAR_BASE_HOST:-0.0.0.0}"
PORT="${LUNAR_BASE_PORT:-8888}"

if [ -t 1 ]; then
    GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[0;31m'
    BLUE=$'\033[0;34m'; NC=$'\033[0m'
else
    GREEN=''; YELLOW=''; RED=''; BLUE=''; NC=''
fi

say() {
    case "$1" in
        ok)   printf '%s[+]%s %s\n' "$GREEN"  "$NC" "$2" ;;
        warn) printf '%s[!]%s %s\n' "$YELLOW" "$NC" "$2" ;;
        err)  printf '%s[x]%s %s\n' "$RED"    "$NC" "$2" ;;
        *)    printf '%s[-]%s %s\n' "$BLUE"   "$NC" "$2" ;;
    esac
}

if [ "$(id -u)" -ne 0 ]; then
    say err "Run this with sudo — it writes to /etc/systemd/system."
    exit 1
fi

if [ ! -x "$VENV_PYTHON" ]; then
    say err "No virtualenv at $VENV_PYTHON"
    say info "Run ./start-lunar-base.sh once first to build it."
    exit 1
fi

# Read saved host/port so the unit matches how you actually run it.
CONFIG_FILE="$SCRIPT_DIR/.lunar-base.json"
if [ -f "$CONFIG_FILE" ]; then
    SAVED_HOST=$("$VENV_PYTHON" -c "import json;print(json.load(open('$CONFIG_FILE')).get('host',''))" 2>/dev/null || true)
    SAVED_PORT=$("$VENV_PYTHON" -c "import json;print(json.load(open('$CONFIG_FILE')).get('port',''))" 2>/dev/null || true)
    [ -n "${SAVED_HOST:-}" ] && HOST="$SAVED_HOST"
    [ -n "${SAVED_PORT:-}" ] && PORT="$SAVED_PORT"
    say ok "Using saved settings: $HOST:$PORT"
fi

# If Lunar Tear is not the conventional sibling, pin it in the unit so the
# service does not have to re-detect it on every boot.
LUNAR_TEAR_ENV=""
if [ -f "$CONFIG_FILE" ]; then
    SAVED_LT=$("$VENV_PYTHON" -c "import json;print(json.load(open('$CONFIG_FILE')).get('lunar_tear_dir',''))" 2>/dev/null || true)
    if [ -n "${SAVED_LT:-}" ] && [ "$SAVED_LT" != "$(dirname "$SCRIPT_DIR")/lunar-tear" ]; then
        LUNAR_TEAR_ENV="Environment=LUNAR_TEAR_DIR=$SAVED_LT"
        say ok "Pinning Lunar Tear path: $SAVED_LT"
    fi
fi

say info "Writing $UNIT_PATH"
cat > "$UNIT_PATH" <<UNIT
[Unit]
Description=Lunar Base - save manager for a Lunar Tear private server
After=network-online.target
Wants=network-online.target

# Deliberately NOT After=lunar-tear.service. Lunar Base manages that unit
# and must stay reachable when lunar-tear is down — that is exactly when
# you need the restore page.

[Service]
Type=simple
User=root
WorkingDirectory=$SCRIPT_DIR
ExecStart=$VENV_PYTHON -m uvicorn web.app:app --host $HOST --port $PORT
$LUNAR_TEAR_ENV
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lunar-base
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
UNIT

say info "Reloading systemd"
systemctl daemon-reload

say info "Enabling lunar-base"
systemctl enable lunar-base.service >/dev/null 2>&1

if systemctl is-active --quiet lunar-base.service; then
    say info "Restarting the running instance"
    systemctl restart lunar-base.service
else
    say info "Starting lunar-base"
    systemctl start lunar-base.service
fi

sleep 2
if systemctl is-active --quiet lunar-base.service; then
    say ok "Lunar Base is running at http://$HOST:$PORT"
    say ok "Enabled at boot."
else
    say err "The service failed to start. Recent log:"
    journalctl -u lunar-base -n 20 --no-pager
    exit 1
fi

# The restore flow shells out to systemctl for lunar-tear; warn early if
# that unit is not where the app expects it.
UNIT_NAME="${LUNAR_TEAR_UNIT:-lunar-tear}"
if systemctl cat "${UNIT_NAME}.service" >/dev/null 2>&1; then
    say ok "Found ${UNIT_NAME}.service — automatic restore control will work."
else
    say warn "No ${UNIT_NAME}.service found."
    say info "Restores will refuse while the server is up, as before."
    say info "If your unit has another name, add to the [Service] section:"
    say info "    Environment=LUNAR_TEAR_UNIT=<name>"
fi

echo
say info "systemctl status lunar-base"
say info "journalctl -u lunar-base -f"
