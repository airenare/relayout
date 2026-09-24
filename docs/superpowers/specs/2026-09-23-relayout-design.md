# relayout — Design Spec

Date: 2026-09-23

## Purpose

A local, privacy-preserving keyboard layout autocorrect tool for Linux/Wayland
(developed and used on Omarchy + Hyprland), inspired by Windows' PuntoSwitcher.

When the user types text in the wrong keyboard layout (e.g. typing Russian
words while the "us" layout is active, producing garbled Latin text), they
press a configurable hotkey (default: double-tap Left Shift) and the tool
replaces the offending text with the correctly-typed version in the other
layout — either the current text selection, or (if nothing is selected) the
last word/phrase typed.

Nothing typed or corrected is ever transmitted anywhere or persisted to disk.
All processing is local and in-memory.

## Non-goals

- Not a general input-method-editor (IME) replacement.
- Not a full multi-layout-N-way switcher — v1 supports exactly one configured
  layout pair (default `us`/`ru`), swapped bidirectionally.
- Not required to work outside Wayland/Hyprland (evdev/libxkbcommon/wtype are
  Linux/Wayland-native; no X11 fallback is in scope).
- No GUI. Configuration is a TOML file.

## Architecture

A single Python daemon (`relayoutd`), run as a `systemd --user` service,
composed of independent, testable units:

1. **Keymap resolver** (`relayout/keymap.py`)
   Uses `libxkbcommon` (via Python bindings) to compile the real keymaps for
   the two configured layouts (default `us`, `ru`) at startup. Produces:
   - `keycode_to_char[layout][keycode][modifier_state] -> str` for both
     layouts, covering unshifted/shifted/capslock states.
   - A derived bidirectional `char_map: dict[str, str]` built by iterating
     every keycode, decoding it under both layouts, and pairing the two
     resulting characters. Used for selection-mode correction. Keys that
     decode identically in both layouts (e.g. digits) map to themselves and
     are effectively no-ops.

   This is pure, input-free logic and fully unit-testable.

2. **Hotkey detector** (`relayout/hotkey.py`)
   A small state machine that takes a stream of (keycode, event_type,
   timestamp) tuples and returns whether the configured trigger fired.
   Default config: double-tap of `KEY_LEFTSHIFT` within 400ms. Both the key
   and the timing window are configurable. Pure logic, fully unit-testable
   against synthetic event streams.

3. **Typed-text buffer** (`relayout/buffer.py`)
   An in-memory ring buffer (capped, e.g. 500 entries) of raw
   `(keycode, modifier_state)` tuples for recently typed keys, using the
   *currently active* layout's keymap to know what actually appeared on
   screen (only needed to correctly identify boundary characters like
   punctuation — the correction itself re-decodes raw keycodes under the
   other layout, per keymap resolver above).

   Cleared on: Enter, Tab, Escape, focus-changing keys (best-effort), or
   after a configurable idle timeout (default 10s). Never written to disk.

   On correction request, returns the trailing run of keycodes back to the
   nearest boundary (whitespace or `.,!?;:()"'` or buffer start).

   Pure logic over synthetic input, fully unit-testable.

4. **Input listener** (`relayout/input_listener.py`)
   Thin glue: enumerates keyboard-capable devices via `evdev`, multiplexes
   their event streams (`asyncio` + `evdev.InputDevice.async_read_loop`),
   and feeds raw key events to the hotkey detector and buffer. Requires the
   running user to be in the `input` group. Not unit-tested (requires real
   input devices); verified manually.

5. **Selection reader** (`relayout/selection.py`)
   Shells out to `wl-paste --primary --no-newline` to read the current
   primary selection, if any. Thin glue, not unit-tested beyond a mocked
   subprocess boundary.

6. **Text injector** (`relayout/inject.py`)
   Shells out to `wtype` to send corrected text and, for buffer-mode
   corrections, the right number of `Backspace` keystrokes first. Thin glue.

7. **Orchestrator** (`relayout/daemon.py`)
   Wires the above together: on hotkey fire, checks the selection reader
   first; if there's a non-empty selection, corrects it via `char_map` and
   injects (typing over a selection replaces it, no backspaces needed). If
   there's no selection, pulls the trailing chunk from the buffer, re-decodes
   those keycodes under the other layout, sends that many backspaces, then
   types the corrected text.

8. **Config** (`relayout/config.py`)
   Loads `~/.config/relayout/config.toml`:
   ```toml
   [layouts]
   pair = ["us", "ru"]

   [hotkey]
   key = "KEY_LEFTSHIFT"
   taps = 2
   window_ms = 400

   [buffer]
   max_len = 500
   idle_timeout_s = 10
   ```
   Ships with sane defaults if the file is absent.

## Data flow

```
evdev devices --> input_listener --> hotkey detector (fires?) 
                                  \-> typed-text buffer (rolling)

hotkey fires --> selection reader --> has selection? --yes--> char_map swap --> wtype (types over selection)
                                             |
                                             no
                                             v
                                  buffer trailing chunk --> re-decode keycodes under other layout --> wtype(backspaces) + wtype(corrected text)
```

## Installation

- One-time: `sudo usermod -aG input $USER`, then re-login (required for
  `evdev` device access).
- `systemd --user` unit (`packaging/relayout.service`) installed via a
  `make install` / install script, enabled with
  `systemctl --user enable --now relayout`.
- README covers setup for third-party installers from the public repo.

## Testing

- `keymap.py`, `hotkey.py`, `buffer.py`: unit tests with plain pytest,
  no real devices needed.
- `selection.py`, `inject.py`: unit tests against mocked `subprocess` calls.
- `input_listener.py`, end-to-end daemon behavior: manual verification only
  (documented steps in README), since it requires real keyboard hardware
  events on the target machine.

## Open questions / deferred

- Multi-pair layout support (more than one non-default pair active
  simultaneously) — deferred, not needed for the stated use case.
- AltGr / dead-key handling — deferred; `us`/`ru` don't need it for the
  primary use case, revisit if more layout pairs are added later.
