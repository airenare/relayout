"""Retype a word by replaying the same physical keys on a virtual keyboard.

After the layout is switched, pressing the keys that were typed produces the
right characters with no character mapping, so it works in any app that
reads normal key events (browsers, Electron, JetBrains, terminals), unlike
text injection which depends on the app accepting a replacement keymap.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

NAME = "relayout-virtual-keyboard"
KEY_PACE_S = 0.003      # between key events, so apps don't drop or merge them
LAYOUT_SETTLE_S = 0.04  # let the compositor apply a layout switch
XKB_OFFSET = 8


class KeyReplayer:
    """Presses keys through /dev/uinput. Build with KeyReplayer.open()."""

    def __init__(self, uinput, ecodes, sleep=time.sleep):
        self._ui = uinput
        self._e = ecodes
        self._sleep = sleep

    @classmethod
    def open(cls) -> "KeyReplayer | None":
        try:
            from evdev import UInput, ecodes
            keys = sorted(
                code for name, code in ecodes.ecodes.items()
                if name.startswith("KEY_") and code < 0x100
            )
            ui = UInput({ecodes.EV_KEY: keys}, name=NAME)
        except (ImportError, OSError, PermissionError) as exc:
            logger.warning("uinput unavailable (%s); falling back to wtype", exc)
            return None
        return cls(ui, ecodes)

    def close(self) -> None:
        self._ui.close()

    def _tap(self, code: int, shift: bool = False) -> None:
        e = self._e
        if shift:
            self._ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1)
            self._ui.syn()
        self._ui.write(e.EV_KEY, code, 1)
        self._ui.syn()
        self._ui.write(e.EV_KEY, code, 0)
        self._ui.syn()
        if shift:
            self._ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0)
            self._ui.syn()
        self._sleep(KEY_PACE_S)

    def backspaces(self, count: int) -> None:
        for _ in range(count):
            self._tap(self._e.KEY_BACKSPACE)

    def replay(self, entries, spaces: int = 0) -> None:
        """Press the buffer entries' keys (xkb keycode, level, ...) again."""
        for entry in entries:
            self._tap(entry[0] - XKB_OFFSET, shift=entry[1] == 1)
        for _ in range(spaces):
            self._tap(self._e.KEY_SPACE)
