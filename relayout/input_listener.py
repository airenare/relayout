"""evdev + hyprctl glue: feeds real keyboard events into the hotkey detector
and typed-text buffer, and queries the compositor for the active layout.

Not unit-tested (requires real input devices) — see README for manual
verification steps. The layout-JSON parsing itself is pure and tested in
tests/test_layout_resolver.py; this module only does the I/O around it.
"""
import asyncio
import logging
import time

import evdev
from evdev import ecodes

from relayout.daemon import LOOSE_TRIGGER_MARGIN
from relayout.hotkey import HotkeyDetector
from relayout.keymap import evdev_to_xkb_keycode

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

# Keys held together with these are shortcuts, not text.
SHORTCUT_MODIFIERS = {
    "KEY_LEFTCTRL", "KEY_RIGHTCTRL", "KEY_LEFTALT", "KEY_RIGHTALT",
    "KEY_LEFTMETA", "KEY_RIGHTMETA",
}
POINTER_BUTTONS = {"BTN_LEFT", "BTN_RIGHT", "BTN_MIDDLE", "BTN_TOUCH"}
SPACE_KEY = "KEY_SPACE"
# How long an auto-correction waits for the user to stop pressing keys.
SETTLE_S = 0.025
MAX_WAIT_S = 0.4


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


async def run(daemon, lookup, hotkey: HotkeyDetector) -> None:
    keyboards = find_keyboards()
    if not keyboards:
        raise RuntimeError(
            "no keyboard input devices could be opened under /dev/input -- "
            "is this user in the 'input' group? (re-login after usermod -aG input)"
        )

    pair = daemon.layout_pair
    buffer = daemon.buffer
    held: set[str] = set()
    # Bumped by every text key press; a pending auto-correction is dropped
    # if it changes, because the user has already typed past the word.
    epoch = 0

    async def auto_correct_when_idle(
        chunk, spaces: int, started: int, extra_margin: float = 0.0
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + MAX_WAIT_S
        while loop.time() < deadline:
            if epoch != started:
                return
            if not (held - SHIFT_KEYS):
                await asyncio.sleep(SETTLE_S)
                if epoch == started and not (held - SHIFT_KEYS):
                    daemon.auto_correct(chunk, spaces, extra_margin)
                return
            await asyncio.sleep(0.01)

    async def read_device(device: evdev.InputDevice):
        nonlocal epoch
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

                if event_type == "down":
                    held.add(key_name)
                elif event_type == "up":
                    held.discard(key_name)

                if key_name in POINTER_BUTTONS:
                    if event_type == "down":
                        buffer.clear()
                        daemon.key_typed()
                        epoch += 1
                    continue

                # Autorepeat only feeds the buffer's "still typing" signal
                # below, never the hotkey -- otherwise holding the trigger
                # key down would fire it repeatedly.
                if event_type == "down" and hotkey.feed(
                    key_name, "down", time.monotonic()
                ):
                    daemon.correct()
                    continue

                if event_type not in ("down", "repeat"):
                    continue
                if key_name in SHIFT_KEYS or key_name in SHORTCUT_MODIFIERS:
                    continue  # modifiers alone neither type nor move the caret

                epoch += 1
                daemon.key_typed()

                if held & SHORTCUT_MODIFIERS:
                    buffer.clear()  # Ctrl+A, Super+Enter...: not text
                    continue

                if key_name == BACKSPACE_KEY:
                    buffer.backspace()
                    continue

                if key_name in CARET_MOVING_KEYS:
                    buffer.clear()
                    continue

                layout = lookup.get()
                xkb_keycode = evdev_to_xkb_keycode(event.code)
                level = 1 if held & SHIFT_KEYS else 0
                table = pair.table_for(layout)
                chars = table.get(xkb_keycode)
                displayed_char = (
                    chars[level] if chars and level < len(chars) else None
                )
                buffer.record(
                    xkb_keycode, level, layout, displayed_char, time.monotonic()
                )

                if event_type != "down":
                    continue
                if key_name == SPACE_KEY:
                    chunk, spaces = buffer.last_word()
                    margin = 0.0
                else:
                    kind = pair.boundary_kind(xkb_keycode, level, layout)
                    if kind is None:
                        continue
                    chunk, spaces = buffer.last_word()
                    margin = LOOSE_TRIGGER_MARGIN if kind == "loose" else 0.0
                if chunk:
                    asyncio.create_task(
                        auto_correct_when_idle(chunk, spaces, epoch, margin)
                    )
        except OSError as exc:
            logger.warning("input device %s disconnected: %s", device.path, exc)

    await asyncio.gather(
        *(read_device(d) for d in keyboards), return_exceptions=True
    )
