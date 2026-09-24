# relayout

Local keyboard-layout autocorrect for Wayland/Hyprland, inspired by PuntoSwitcher.

Typed something in the wrong keyboard layout? Select the garbled text (or
just leave your cursor where you were typing) and double-tap Left Shift —
relayout swaps it to the correct layout's text, in place. Everything runs
locally; nothing typed is ever sent anywhere or written to disk.

## How it works

relayout uses the same XKB keymap compiler the compositor uses
(`libxkbcommon`) to know exactly which character each physical key produces
in each of two configured layouts (default: US English / Russian), and
swaps between them:

- **With a selection:** reads the current primary selection and retypes it
  in the other layout.
- **Without a selection:** keeps a small in-memory buffer of recently typed
  keys (never persisted), and retypes the last word/phrase since the last
  punctuation or whitespace.

## Requirements

- Linux, Wayland, a compositor exposing `hyprctl` (Hyprland)
- Python 3.11+
- `wl-clipboard` and `wtype` (both already installed on Omarchy by default)
- Membership in the `input` group (the install script sets this up)

## Install

```bash
git clone https://github.com/airenare/relayout.git
cd relayout
./scripts/install.sh
```

If you weren't already in the `input` group, the script will add you to it
and ask you to log out/in, then re-run it.

## Configuration

Edit `~/.config/relayout/config.toml`:

```toml
[layouts]
pair = ["us", "ru"]       # any two XKB layout codes, e.g. ["us", "de"]

[hotkey]
key = "KEY_LEFTSHIFT"     # any evdev key name
taps = 2                  # number of taps to trigger
window_ms = 400           # max milliseconds between taps

[buffer]
max_len = 500             # max buffered keystrokes
idle_timeout_s = 10       # buffer clears after this many seconds idle
```

Then: `systemctl --user restart relayout`

## Development

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/pytest
```

## Manual verification

The evdev/hyprctl input glue (`relayout/input_listener.py`) isn't covered by
the automated test suite — it requires real keyboard hardware. After
installing:

```bash
sudo usermod -aG input $USER   # one-time, if not already done; re-login after
./.venv/bin/relayoutd &
```

1. Focus a text editor. Type `ghbdtn` (should appear as literal Latin text).
2. Select it, tap Left Shift twice quickly.
3. Confirm it becomes `привет`.
4. Clear the field. Type `ghbdtn` again, do NOT select anything, tap Left
   Shift twice quickly.
5. Confirm the word is deleted and retyped as `привет`.
6. Kill the background process: `kill %1`.

## License

MIT
