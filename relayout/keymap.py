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

# Punctuation that can directly follow a word.
WORD_END_PUNCT = frozenset(".,!?;:)\"'»")


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

    def _key_index(self, table: dict[int, list[str | None]]) -> dict[str, tuple[int, int]]:
        """char -> (keycode, level); lowest keycode/level wins, so the main
        alphanumeric block beats the keypad's duplicate punctuation keys."""
        index: dict[str, tuple[int, int]] = {}
        for keycode in sorted(table):
            for level, ch in enumerate(table[keycode]):
                if ch:
                    index.setdefault(ch, (keycode, level))
        return index

    def swap_selection_text(self, text: str) -> str:
        """Retype ``text`` as the same physical keys on the other layout.

        First work out which layout the text was typed in (the one that owns
        its letters), then map each character through its physical key. This
        keeps punctuation right where a char-to-char map cannot: `,` is on
        different keys in us and ru, so `привет,` comes from `ghbdtn?`.
        Characters on no key (digits shared by both, emoji...) pass through.
        """
        index_a = self._key_index(self._table_a)
        index_b = self._key_index(self._table_b)
        only_a = sum(1 for c in text if c in index_a and c not in index_b)
        only_b = sum(1 for c in text if c in index_b and c not in index_a)
        # Ties (digits, bare punctuation) are assumed to come from layout_a.
        source = self.layout_b if only_b > only_a else self.layout_a
        src_index, dst_table = (
            (index_a, self._table_b) if source == self.layout_a else (index_b, self._table_a)
        )
        out = []
        for ch in text:
            key = src_index.get(ch)
            dst = None
            if key:
                chars = dst_table.get(key[0])
                dst = chars[key[1]] if chars and key[1] < len(chars) else None
            out.append(dst or ch)
        return "".join(out)

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

    def other(self, layout: str) -> str:
        """The layout of the pair that is not ``layout``."""
        return self.layout_b if layout == self.layout_a else self.layout_a

    def render(self, chunk, layout: str) -> tuple[str, str]:
        """Render buffer entries as (text in ``layout``, text in the other).

        A key with no counterpart falls back to what was on screen, so the
        two texts always have the same length as ``chunk``.
        """
        cur = "".join(e[3] for e in chunk)
        other = "".join(
            self.other_layout_char(e[0], e[1], layout) or e[3] for e in chunk
        )
        return cur, other

    def table_for(self, layout: str) -> dict[int, list[str | None]]:
        return self._table_b if layout == self.layout_b else self._table_a

    def boundary_kind(self, keycode: int, level: int, layout: str) -> str | None:
        """Does this key end a word without a space ("hello," / "привет?")?

        "strict": punctuation in the current layout, so it cannot be part of a
        word. "loose": a letter here that is punctuation in the other layout
        (`.` is `ю` on ru), so it may be mid-word and needs more evidence.
        """
        chars = self.table_for(layout).get(keycode)
        cur = chars[level] if chars and level < len(chars) else None
        if cur is None:
            return None
        if cur in WORD_END_PUNCT:
            return "strict"
        if self.other_layout_char(keycode, level, layout) in WORD_END_PUNCT:
            return "loose"
        return None
