# relayout

Automatic keyboard-layout correction for Wayland/Hyprland (Omarchy), in the
spirit of Punto Switcher.

Type without thinking about the layout. When a word comes out in the wrong
one (`ghbdtn` → `привет`, `руддщ` → `hello`), relayout retypes it in the
right layout when you press Space **and switches the layout for you**, so you
keep typing. Everything runs locally; nothing typed is sent anywhere or
written to disk.

## Features

- **Auto-correct on Space or punctuation.** A word-frequency list plus a letter-trigram
  model scores the word in both layouts and flips it when the other layout
  is clearly more likely (about 99% of common words flip correctly, under
  0.05% of correct words flip by mistake on the bundled lists). Punctuation
  typed right after a word (`ghbdtn?` → `привет,`, `руддщ.` → `hello.`) triggers
  it too; keys that are letters on the other layout (`.` is `ю`) need extra
  evidence so the first half of a correct word is never flipped.
- **Double-tap Left Shift** (configurable) to flip by hand: selected text,
  or the last word, even after you've pressed Space. Right after an
  auto-correction the same hotkey **undoes** it.
- **Learns your words.** Flip the same word by hand twice, or undo the same
  auto-correction twice, and relayout remembers: `next` typed on the
  Russian layout (`туче`, a real Russian word) now always flips.
- **Careful by design.** It never touches words with digits or symbols,
  `camelCase`/`iPhone`/ALL CAPS, executables in `$PATH` (`jq`, `gcc`), text
  typed with Ctrl/Alt/Super held, or anything after a click or arrow key.
  Password managers and the polkit prompt are excluded by default, and
  because it only acts on Space, passwords are rarely affected.
- **Works in every app**, text is retyped with `wtype`.
- **Bar widget** for Omarchy: on/off state, per-app exclusion and learned
  words (see [Bar widget](#bar-widget)).

## How it works

relayout reads key events passively from `/dev/input` (it never grabs the
keyboard, so typing is never delayed) and compiles the real XKB keymap of
each layout in the pair with `libxkbcommon`, so it knows exactly which
character each physical key produces in either layout. On Space it renders
the last word in both layouts, scores each, and, if the other one wins by a
margin, sends Backspace, types the corrected word with `wtype` and switches
the layout with `hyprctl switchxkblayout`. A correction is dropped if you
type another key before it runs.

Layout pairs need a word list in `relayout/data/<lang>.txt.gz`. `us`/`gb`
(en) and `ru` ship by default; other pairs still get the hotkey, and you can
add a language with `scripts/build-wordlists.py` (see `relayout/data/README.md`).

## Privacy and permissions

relayout has to see what you type, so:

- Only the current line's recent keys are kept, in memory, and cleared on
  Enter, Tab, clicks, arrow keys, shortcuts and after 10 s idle. Nothing is
  logged or sent anywhere.
- `~/.local/share/relayout/state.json` stores only your settings, excluded
  apps and words you taught it by hand. It is plain JSON.
- Reading keyboards needs membership in the `input` group. Any program
  running as you with that permission can read your keystrokes: that is the
  cost of a global layout corrector on Wayland.

## Requirements

- Linux, Wayland, Hyprland (`hyprctl`); Omarchy is only needed for the widget
- Python 3.11+
- `wl-clipboard` and `wtype` (installed on Omarchy by default)
- Membership in the `input` group (the install script sets this up)

## Install

```bash
git clone https://github.com/airenare/relayout.git
cd relayout
./scripts/install.sh
```

If you weren't in the `input` group, the script adds you and asks you to log
out and in, then re-run it. Re-run it after `git pull` to update.

## Bar widget

```bash
omarchy plugin add https://github.com/airenare/relayout --enable
```

A keyboard icon, dimmed while auto-correction is off. Left click opens a
panel (auto-correct on/off, turn it off for the current app, remove learned
words); right click toggles auto-correction. The widget only talks to the
daemon through the `relayout` command, so the daemon must be installed.

## Commands

```
relayout status                      # JSON state
relayout auto on|off|toggle
relayout exclude add|rm CLASS        # window class, see `hyprctl activewindow`
relayout exclude list
relayout rules list | add WORD [LAYOUT] | rm WORD
relayout flip                        # same as the hotkey
```

`rules add next` makes `next` always come out as `next` (typing `туче`
turns into it); `rules add привет` does the opposite for a Russian word.

## Configuration

Edit `~/.config/relayout/config.toml`, then `systemctl --user restart relayout`:

```toml
[layouts]
pair = ["us", "ru"]       # any two XKB layout codes configured in Hyprland

[hotkey]
key = "KEY_LEFTSHIFT"     # any evdev key name
taps = 2                  # number of taps to trigger
window_ms = 400           # max milliseconds between taps

[buffer]
max_len = 500             # max buffered keystrokes
idle_timeout_s = 10       # buffer clears after this many seconds idle

[auto]
enabled = true            # correct on Space (also toggled by the widget)
threshold = 4.0           # higher = more cautious; 2-6 is the useful range
learn_threshold = 2       # manual flips/undos before a word is remembered
notify = true             # desktop notification when a word is learned
exclude_apps = ["org.keepassxc.KeePassXC", "1Password", "Bitwarden",
                "gcr-prompter", "pinentry-qt", "pinentry-gtk"]
exclude_layers = ["omarchy-polkit"]   # shell popups (layer-shell namespaces)
```

`enabled` and `exclude_apps` seed `state.json` the first time; after that the
widget/`relayout` commands own them (edit `state.json` to change them by hand).

## Uninstall

```bash
omarchy plugin remove air.relayout          # the widget, if installed
systemctl --user disable --now relayout
rm -f ~/.config/systemd/user/relayout.service ~/.local/bin/relayout
rm -rf ~/.local/share/relayout              # program and learned words
```

Settings in `~/.config/relayout` are kept; delete them by hand. Leave the
`input` group with `sudo gpasswd -d "$USER" input` if nothing else needs it.

## Development

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/pytest
```

The evdev glue (`relayout/input_listener.py`) needs real input devices and is
verified end to end by injecting keys through a virtual `uinput` keyboard
into a terminal running the daemon. Release checklist: tests green,
`omarchy plugin validate` on a clean checkout.

## Credits and license

Auto-detection (word list + letter-trigram scoring) is modelled on
[layoutless](https://github.com/kladaFOX/layoutless) by kladaFOX, which is
worth a look for a Rust implementation with a uinput-based replay.

MIT for the code. The bundled word lists in `relayout/data/` derive from
[hermitdave/FrequencyWords](https://github.com/hermitdave/FrequencyWords) and
are licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
