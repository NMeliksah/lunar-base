#!/usr/bin/env bash
#
# Lunar Base - one-command launcher for Linux and macOS.
#
# Makes sure a usable Python is present, then hands over to the Python wizard,
# which does the rest (virtualenv, dependencies, master data, grant shim, run).
#
#   ./start-lunar-base.sh
#   ./start-lunar-base.sh --prefer-saved
#   ./start-lunar-base.sh --host 0.0.0.0
#   ./start-lunar-base.sh --yes              unattended: accept every prompt
#   ./start-lunar-base.sh --lunar-tear PATH  when the server is not a sibling
#

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIZARD="$SCRIPT_DIR/start-lunar-base.py"

# --yes / -y also suppresses this script's own prompts, not just the
# wizard's, so a single flag covers the whole install unattended.
ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        --yes|-y) ASSUME_YES=1 ;;
    esac
done

if [ -t 1 ]; then
    BLUE=$'\033[0;34m'; GREEN=$'\033[0;32m'
    YELLOW=$'\033[1;33m'; RED=$'\033[0;31m'; NC=$'\033[0m'
else
    BLUE=''; GREEN=''; YELLOW=''; RED=''; NC=''
fi

say() {
    case "$1" in
        ok)   printf '%s[+]%s %s\n' "$GREEN"  "$NC" "$2" ;;
        warn) printf '%s[!]%s %s\n' "$YELLOW" "$NC" "$2" ;;
        err)  printf '%s[x]%s %s\n' "$RED"    "$NC" "$2" ;;
        *)    printf '%s[-]%s %s\n' "$BLUE"   "$NC" "$2" ;;
    esac
}

banner() {
    echo
    echo "  ====================================================="
    echo "             LUNAR BASE - setup and launcher"
    echo "      Web manager for a Lunar Tear private server"
    echo "  ====================================================="
    echo
}

# Elevation prefix: empty when already root, sudo otherwise, "" + failure if neither.
apt_prefix() {
    if [ "$(id -u)" -eq 0 ]; then
        echo ""
        return 0
    fi
    if command -v sudo >/dev/null 2>&1; then
        echo "sudo"
        return 0
    fi
    return 1
}

apt_install() {
    local label="$1"; shift
    local prefix

    if ! command -v apt-get >/dev/null 2>&1; then
        say err "$label is missing and apt-get is not available on this system."
        return 1
    fi

    if ! prefix="$(apt_prefix)"; then
        say err "$label is missing, and neither root nor sudo is available."
        say info "Install it manually:  apt install $*"
        return 1
    fi

    if [ "$ASSUME_YES" -eq 1 ]; then
        say info "Installing $label (--yes)."
    else
        read -r -p "    Install $label via apt? [y/N] " reply
        case "$reply" in
            y|Y|yes|YES) ;;
            *) say warn "Skipped installing $label."; return 1 ;;
        esac
    fi

    say info "Installing $label (this can take a minute)..."
    DEBIAN_FRONTEND=noninteractive $prefix apt-get update -qq >/dev/null 2>&1
    if DEBIAN_FRONTEND=noninteractive $prefix apt-get install -y "$@" >/dev/null 2>&1; then
        say ok "$label installed."
        return 0
    fi

    say err "Failed to install $label."
    return 1
}

find_python() {
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
                PYTHON="$candidate"
                return 0
            fi
        fi
    done
    return 1
}

main() {
    banner

    if [ ! -f "$WIZARD" ]; then
        say err "Wizard not found: $WIZARD"
        say info "Run this script from inside the lunar-base folder."
        return 1
    fi

    # --- Python itself ---
    if find_python; then
        say ok "Python $("$PYTHON" -c 'import platform; print(platform.python_version())')"
    else
        say warn "No Python 3.10 or newer found."
        apt_install "Python 3" python3 python3-venv || return 1
        if ! find_python; then
            say err "Python is still unavailable after installation."
            return 1
        fi
        say ok "Python $("$PYTHON" -c 'import platform; print(platform.python_version())')"
    fi

    # --- ensurepip ---
    # Debian and Ubuntu ship `venv` but split `ensurepip` into pythonX.Y-venv,
    # so importing venv proves nothing. Test for ensurepip directly.
    if "$PYTHON" -c 'import ensurepip' >/dev/null 2>&1; then
        say ok "Python venv support (ensurepip)"
    else
        say warn "Python venv support is missing (ensurepip is not installed)."
        PYVER="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

        if ! apt_install "python${PYVER}-venv" "python${PYVER}-venv"; then
            apt_install "python3-venv" python3-venv || true
        fi

        if ! "$PYTHON" -c 'import ensurepip' >/dev/null 2>&1; then
            say err "ensurepip is still unavailable. Cannot continue."
            say info "Install it manually:  apt install python${PYVER}-venv"
            return 1
        fi
        say ok "Python venv support (ensurepip)"
    fi

    echo
    say info "Handing over to the setup wizard..."

    "$PYTHON" "$WIZARD" "$@"
}

main "$@"
