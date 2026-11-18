#!/usr/bin/env bash
# Install relayout for the current user. Usage: ./scripts/install.sh [--force]
#   --force   replace a service file or `relayout` command that relayout did not create
set -euo pipefail

FORCE=0
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        -h|--help) sed -n '2,3p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

# $RELAYOUT_HOME lets tests install into a scratch home; defaults to $HOME.
BASE="${RELAYOUT_HOME:-$HOME}"
INSTALL_DIR="$BASE/.local/share/relayout"
SERVICE_DIR="$BASE/.config/systemd/user"
CONFIG_DIR="$BASE/.config/relayout"
BIN_DIR="$BASE/.local/bin"
SERVICE_FILE="$SERVICE_DIR/relayout.service"
COMMAND="$BIN_DIR/relayout"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRATCH="${RELAYOUT_HOME:+1}"   # non-empty: skip group, systemd and uinput steps

missing=()
for tool in python3 rsync; do
    command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
[ -n "$SCRATCH" ] || command -v systemctl >/dev/null 2>&1 || missing+=("systemctl (systemd)")
python3 -c 'import venv, ensurepip' >/dev/null 2>&1 || missing+=("python3-venv (the venv/ensurepip modules)")
if [ ${#missing[@]} -gt 0 ]; then
    echo "error: missing required tools: ${missing[*]}" >&2
    echo "Install them with your package manager and re-run." >&2
    exit 1
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
    || { echo "error: Python 3.11 or newer is required" >&2; exit 1; }

# Refuse to overwrite files we did not create (unless --force).
owned_service() {
    [ ! -e "$SERVICE_FILE" ] && return 0
    grep -q 'managed-by: relayout' "$SERVICE_FILE" 2>/dev/null \
        || grep -q "^ExecStart=.*/share/relayout/.venv/bin/relayoutd" "$SERVICE_FILE" 2>/dev/null
}
owned_command() {
    { [ ! -e "$COMMAND" ] && [ ! -L "$COMMAND" ]; } && return 0
    [ -L "$COMMAND" ] && [ "$(readlink "$COMMAND")" = "$INSTALL_DIR/.venv/bin/relayout" ]
}
owned_install_dir() {
    [ ! -e "$INSTALL_DIR" ] && return 0
    [ -z "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ] && return 0
    grep -q '^name = "relayout"' "$INSTALL_DIR/pyproject.toml" 2>/dev/null
}
conflict=0
for check in "owned_install_dir:$INSTALL_DIR" "owned_service:$SERVICE_FILE" "owned_command:$COMMAND"; do
    fn="${check%%:*}"; path="${check#*:}"
    if ! "$fn"; then
        echo "refusing to overwrite $path: it was not created by relayout." >&2
        conflict=1
    fi
done
if [ "$conflict" = 1 ] && [ "$FORCE" = 0 ]; then
    echo "Move it aside, or re-run with --force to replace it." >&2
    exit 1
fi

if [ -z "$SCRATCH" ] && ! groups "$USER" | grep -qw input; then
    echo "Adding $USER to the 'input' group (needed to read /dev/input/*)."
    sudo usermod -aG input "$USER"
    echo "You must log out and back in for this to take effect, then re-run this script."
    exit 1
fi

mkdir -p "$INSTALL_DIR" "$SERVICE_DIR" "$CONFIG_DIR" "$BIN_DIR"
rsync -a --exclude ".venv" --exclude ".git" --exclude "__pycache__" \
    --exclude "*.egg-info" "$SRC/" "$INSTALL_DIR/"

# Exact versions with hashes: the same commit always installs the same code.
python3 -m venv --clear "$INSTALL_DIR/.venv"
PIP="$INSTALL_DIR/.venv/bin/pip"
"$PIP" install --quiet --require-hashes --no-deps -r "$INSTALL_DIR/requirements.lock"
"$PIP" install --quiet --no-deps --no-build-isolation --no-index "$INSTALL_DIR"
"$INSTALL_DIR/.venv/bin/python" -c 'import evdev, xkbcommon.xkb, relayout.keymap' \
    || { echo "error: installed packages failed to import; aborting before touching the service" >&2; exit 1; }

cp "$INSTALL_DIR/packaging/relayout.service" "$SERVICE_FILE"
# `relayout` control command (also used by the Omarchy bar widget)
ln -sfn "$INSTALL_DIR/.venv/bin/relayout" "$COMMAND"

if [ ! -f "$CONFIG_DIR/config.toml" ]; then
    cat > "$CONFIG_DIR/config.toml" <<'CFG'
[layouts]
pair = ["us", "ru"]

[hotkey]
key = "KEY_LEFTSHIFT"
taps = 2
window_ms = 400

[buffer]
max_len = 500
idle_timeout_s = 10

[auto]
enabled = true            # correct the last word on Space or punctuation
CFG
fi

if [ -n "$SCRATCH" ]; then
    echo "installed into $BASE (scratch install: service not started)"
    exit 0
fi

if [ ! -w /dev/uinput ]; then
    echo "note: /dev/uinput is not writable by you; relayout will retype with wtype instead."
    echo "      For key replay: add a udev rule 'KERNEL==\"uinput\", GROUP=\"input\", MODE=\"0660\"' and run 'sudo modprobe uinput'."
fi

systemctl --user daemon-reload
systemctl --user enable relayout
systemctl --user restart relayout

echo "relayout installed and started (auto-correction is on: type, press Space). Edit $CONFIG_DIR/config.toml to customize the hotkey or layout pair, then: systemctl --user restart relayout"
