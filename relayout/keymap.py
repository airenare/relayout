"""Keycode <-> character resolution using real XKB keymaps.

Uses libxkbcommon (via the `xkbcommon` PyPI bindings) to compile the actual
keymap for each configured layout, rather than a hand-maintained table. This
is the same mechanism the compositor itself uses, so it stays correct for
shift levels, capslock, etc. without us re-deriving that logic.
"""
from xkbcommon import xkb

# evdev keycodes are offset by 8 from the X11/XKB keycode space by
# long-standing convention (X11 reserves keycodes 0-7).
EVDEV_TO_XKB_OFFSET = 8


def evdev_to_xkb_keycode(evdev_keycode: int) -> int:
    return evdev_keycode + EVDEV_TO_XKB_OFFSET


def build_layout_table(layout: str) -> dict[int, list[str | None]]:
    """Return {xkb_keycode: [level0_char, level1_char, ...]} for a layout."""
    ctx = xkb.Context()
    keymap = ctx.keymap_new_from_names(layout=layout)
    if keymap is None:
        raise ValueError(f"unknown or uncompilable layout: {layout!r}")

    table: dict[int, list[str | None]] = {}
    for keycode in range(keymap.min_keycode(), keymap.max_keycode() + 1):
        if keymap.num_layouts_for_key(keycode) == 0:
            continue
        num_levels = keymap.num_levels_for_key(keycode, 0)
        chars: list[str | None] = []
        for level in range(num_levels):
            syms = keymap.key_get_syms_by_level(keycode, 0, level)
            if len(syms) == 1:
                chars.append(xkb.keysym_to_string(syms[0]))
            else:
                chars.append(None)
        table[keycode] = chars
    return table


class LayoutPair:
    """Bidirectional keycode/character resolution between two layouts."""

    def __init__(self, layout_a: str, layout_b: str):
        self.layout_a = layout_a
        self.layout_b = layout_b
        self._table_a = build_layout_table(layout_a)
        self._table_b = build_layout_table(layout_b)
        self._char_map = self._build_char_map()

    def _build_char_map(self) -> dict[str, str]:
        char_map: dict[str, str] = {}
        for keycode, chars_a in self._table_a.items():
            chars_b = self._table_b.get(keycode)
            if not chars_b:
                continue
            for level, ch_a in enumerate(chars_a):
                if level >= len(chars_b):
                    continue
                ch_b = chars_b[level]
                if not ch_a or not ch_b or ch_a == ch_b:
                    continue
                # First mapping wins: keycodes are iterated in ascending
                # order, so the main alphanumeric block (lower keycodes)
                # is resolved before the keypad's duplicate punctuation
                # keys, and a later keycode can never silently overwrite
                # an earlier, more canonical mapping.
                char_map.setdefault(ch_a, ch_b)
                char_map.setdefault(ch_b, ch_a)
        return char_map

    def swap_selection_text(self, text: str) -> str:
        """Swap every character to its counterpart in the other layout.

        Characters with no counterpart (digits, space, punctuation shared
        by both layouts, emoji, etc.) pass through unchanged.
        """
        return "".join(self._char_map.get(ch, ch) for ch in text)

    def other_layout_char(
        self, keycode: int, level: int, current_layout: str
    ) -> str | None:
        """Re-decode (keycode, level) under the layout NOT named by current_layout."""
        other_table = (
            self._table_b if current_layout == self.layout_a else self._table_a
        )
        chars = other_table.get(keycode)
        if not chars or level >= len(chars):
            return None
        return chars[level]
