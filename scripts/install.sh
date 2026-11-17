#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/relayout"
SERVICE_DIR="$HOME/.config/systemd/user"
CONFIG_DIR="$HOME/.config/relayout"

if ! groups "$USER" | grep -qw input; then
    echo "Adding $USER to the 'input' group (needed to read /dev/input/*)."
    sudo usermod -aG input "$USER"
    echo "You must log out and back in for this to take effect, then re-run this script."
    exit 1
fi

mkdir -p "$INSTALL_DIR" "$SERVICE_DIR" "$CONFIG_DIR"
rsync -a --exclude ".venv" --exclude ".git" ./ "$INSTALL_DIR/"

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --quiet "$INSTALL_DIR"

cp packaging/relayout.service "$SERVICE_DIR/relayout.service"

# `relayout` control command (also used by the Omarchy bar widget)
mkdir -p "$HOME/.local/bin"
ln -sf "$INSTALL_DIR/.venv/bin/relayout" "$HOME/.local/bin/relayout"

if [ ! -f "$CONFIG_DIR/config.toml" ]; then
    cat > "$CONFIG_DIR/config.toml" <<'EOF'
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
enabled = true            # correct the last word when you press Space
EOF
fi

if [ ! -w /dev/uinput ]; then
    echo "note: /dev/uinput is not writable by you; relayout will retype with wtype instead."
    echo "      For key replay: add a udev rule 'KERNEL==\"uinput\", GROUP=\"input\", MODE=\"0660\"' and run 'sudo modprobe uinput'."
fi

systemctl --user daemon-reload
systemctl --user enable relayout
systemctl --user restart relayout

echo "relayout installed and started (auto-correction is on: type, press Space). Edit $CONFIG_DIR/config.toml to customize the hotkey or layout pair, then: systemctl --user restart relayout"
