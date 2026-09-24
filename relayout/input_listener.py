"""evdev + hyprctl glue: feeds real keyboard events into the hotkey detector
and typed-text buffer, and queries the compositor for the active layout.

Not unit-tested (requires real input devices) — see README for manual
verification steps.
"""
import asyncio
import json
import subprocess
import time

import evdev
from evdev import ecodes

from relayout.hotkey import HotkeyDetector
from relayout.buffer import TypedTextBuffer
from relayout.keymap import LayoutPair, evdev_to_xkb_keycode

SHIFT_KEYS = {"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"}


def find_keyboards() -> list[evdev.InputDevice]:
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    return [d for d in devices if ecodes.EV_KEY in d.capabilities()]


def active_layout_name(layout_pair: LayoutPair) -> str:
    """Best-effort lookup of which of the two configured layouts is active,
    via `hyprctl devices -j`. Defaults to layout_a if it can't be determined.
    """
    try:
        output = subprocess.run(
            ["hyprctl", "devices", "-j"], capture_output=True, text=True, timeout=1.0
        )
        data = json.loads(output.stdout)
        keyboards = data.get("keyboards", [])
        if not keyboards:
            return layout_pair.layout_a
        active_keymap = keyboards[0].get("active_keymap", "")
        # Hyprland reports human-readable names (e.g. "Russian"); match
        # loosely against the configured layout codes.
        if layout_pair.layout_b.lower() in active_keymap.lower():
            return layout_pair.layout_b
        return layout_pair.layout_a
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return layout_pair.layout_a


async def run(
    layout_pair: LayoutPair,
    hotkey: HotkeyDetector,
    buffer: TypedTextBuffer,
    on_trigger,
) -> None:
    keyboards = find_keyboards()
    if not keyboards:
        raise RuntimeError("no keyboard input devices found under /dev/input")

    shift_held = False

    async def read_device(device: evdev.InputDevice):
        nonlocal shift_held
        async for event in device.async_read_loop():
            if event.type != ecodes.EV_KEY:
                continue
            key_event = evdev.categorize(event)
            key_name = (
                key_event.keycode
                if isinstance(key_event.keycode, str)
                else key_event.keycode[0]
            )
            # keystate: 0 = up, 1 = down, 2 = hold/repeat (treated as down)
            event_type = {0: "up", 1: "down", 2: "down"}.get(key_event.keystate)
            if event_type is None:
                continue

            if key_name in SHIFT_KEYS:
                shift_held = event_type == "down"

            timestamp = time.monotonic()
            if hotkey.feed(key_name, event_type, timestamp):
                on_trigger()
                continue

            if event_type == "down":
                layout = active_layout_name(layout_pair)
                xkb_keycode = evdev_to_xkb_keycode(event.code)
                level = 1 if shift_held else 0
                table = (
                    layout_pair._table_a
                    if layout == layout_pair.layout_a
                    else layout_pair._table_b
                )
                chars = table.get(xkb_keycode)
                displayed_char = (
                    chars[level] if chars and level < len(chars) else None
                )
                buffer.record(xkb_keycode, level, layout, displayed_char, timestamp)

    await asyncio.gather(*(read_device(d) for d in keyboards))
