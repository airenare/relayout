"""evdev + hyprctl glue: feeds real keyboard events into the hotkey detector
and typed-text buffer, and queries the compositor for the active layout.

Not unit-tested (requires real input devices) — see README for manual
verification steps. The layout-JSON parsing itself is pure and tested in
tests/test_layout_resolver.py; this module only does the I/O around it.
"""
import asyncio
import json
import logging
import subprocess
import time

import evdev
from evdev import ecodes

from relayout.hotkey import HotkeyDetector
from relayout.buffer import TypedTextBuffer
from relayout.keymap import LayoutPair, evdev_to_xkb_keycode
from relayout.layout_resolver import resolve_active_layout

logger = logging.getLogger(__name__)

SHIFT_KEYS = {"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"}
BACKSPACE_KEY = "KEY_BACKSPACE"
# Keys that move the caret without producing text. None of these show up
# as a decodable character (so buffer.record() would otherwise silently do
# nothing), but they invalidate "the trailing chunk is what's on screen
# right before the cursor" -- so treat them as an explicit clear.
CARET_MOVING_KEYS = {
    "KEY_UP",
    "KEY_DOWN",
    "KEY_LEFT",
    "KEY_RIGHT",
    "KEY_HOME",
    "KEY_END",
    "KEY_PAGEUP",
    "KEY_PAGEDOWN",
}

# Re-running `hyprctl devices -j` on every keystroke was measured to add a
# real fork+exec (~5ms, worse if the compositor is busy) to every keypress.
# The active layout does not change keystroke-to-keystroke, so cache it
# briefly instead of querying synchronously in the hot path.
_LAYOUT_CACHE_TTL_S = 0.5


def find_keyboards() -> list[evdev.InputDevice]:
    """Open every keyboard-capable input device, skipping ones we can't open.

    A device this process doesn't have permission for (e.g. before the user
    has re-logged in after being added to the `input` group) must not take
    down enumeration of every other device.
    """
    devices: list[evdev.InputDevice] = []
    for path in evdev.list_devices():
        try:
            device = evdev.InputDevice(path)
        except OSError as exc:
            logger.warning("could not open input device %s: %s", path, exc)
            continue
        if ecodes.EV_KEY in device.capabilities():
            devices.append(device)
        else:
            device.close()
    return devices


def _fetch_hyprctl_devices() -> dict:
    try:
        output = subprocess.run(
            ["hyprctl", "devices", "-j"], capture_output=True, text=True, timeout=1.0
        )
        return json.loads(output.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        logger.warning("could not query hyprctl for active layout: %s", exc)
        return {}


class _CachedLayoutLookup:
    """Wraps resolve_active_layout() with a short TTL cache."""

    def __init__(self, layout_pair: LayoutPair, ttl_s: float = _LAYOUT_CACHE_TTL_S):
        self._layout_pair = layout_pair
        self._ttl_s = ttl_s
        self._cached_layout: str | None = None
        self._cached_at: float = 0.0

    def get(self) -> str:
        now = time.monotonic()
        if self._cached_layout is None or now - self._cached_at > self._ttl_s:
            data = _fetch_hyprctl_devices()
            self._cached_layout = resolve_active_layout(data, self._layout_pair)
            self._cached_at = now
        return self._cached_layout


def _key_name_for(code: int) -> str | None:
    """Look up an evdev keycode's name, tolerating vendor-specific codes.

    evdev.categorize() raises KeyError for a code it doesn't recognize
    (confirmed: several devices on this machine -- power/sleep buttons, a
    gaming mouse/keyboard combo -- emit exactly those). Reading the table
    directly and treating a miss as "ignore this key" keeps one odd device
    from taking down the whole listener.
    """
    name = ecodes.KEY.get(code)
    if isinstance(name, list):
        return name[0]
    return name


async def run(
    layout_pair: LayoutPair,
    hotkey: HotkeyDetector,
    buffer: TypedTextBuffer,
    on_trigger,
) -> None:
    keyboards = find_keyboards()
    if not keyboards:
        raise RuntimeError(
            "no keyboard input devices could be opened under /dev/input -- "
            "is this user in the 'input' group? (re-login after usermod -aG input)"
        )

    layout_lookup = _CachedLayoutLookup(layout_pair)
    shift_held: dict[str, bool] = {"KEY_LEFTSHIFT": False, "KEY_RIGHTSHIFT": False}

    async def read_device(device: evdev.InputDevice):
        try:
            async for event in device.async_read_loop():
                if event.type != ecodes.EV_KEY:
                    continue
                # value: 0 = up, 1 = down, 2 = autorepeat (held key)
                event_type = {0: "up", 1: "down", 2: "repeat"}.get(event.value)
                if event_type is None:
                    continue

                key_name = _key_name_for(event.code)
                if key_name is None:
                    continue  # unrecognized/vendor-specific code, ignore safely

                if key_name in SHIFT_KEYS:
                    shift_held[key_name] = event_type in ("down", "repeat")

                # Autorepeat only feeds the buffer's "still typing" signal
                # below, never the hotkey -- otherwise holding the trigger
                # key down would fire it repeatedly.
                if event_type == "down" and hotkey.feed(
                    key_name, "down", time.monotonic()
                ):
                    on_trigger()
                    continue

                if event_type not in ("down", "repeat"):
                    continue

                if key_name == BACKSPACE_KEY:
                    buffer.backspace()
                    continue

                if key_name in CARET_MOVING_KEYS:
                    buffer.clear()
                    continue

                layout = layout_lookup.get()
                xkb_keycode = evdev_to_xkb_keycode(event.code)
                level = 1 if any(shift_held.values()) else 0
                table = (
                    layout_pair._table_a
                    if layout == layout_pair.layout_a
                    else layout_pair._table_b
                )
                chars = table.get(xkb_keycode)
                displayed_char = (
                    chars[level] if chars and level < len(chars) else None
                )
                buffer.record(
                    xkb_keycode, level, layout, displayed_char, time.monotonic()
                )
        except OSError as exc:
            logger.warning("input device %s disconnected: %s", device.path, exc)

    await asyncio.gather(
        *(read_device(d) for d in keyboards), return_exceptions=True
    )
