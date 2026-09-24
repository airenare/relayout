"""Wires hotkey firing to the actual correction: selection first, then buffer."""
from relayout import selection, inject
from relayout.keymap import LayoutPair
from relayout.buffer import TypedTextBuffer


class Daemon:
    def __init__(self, layout_pair: LayoutPair, buffer: TypedTextBuffer):
        self.layout_pair = layout_pair
        self.buffer = buffer

    def correct(self) -> None:
        selected = selection.read_primary_selection()
        if selected:
            corrected = self.layout_pair.swap_selection_text(selected)
            inject.type_text(corrected)
            return

        chunk = self.buffer.trailing_chunk()
        if not chunk:
            return

        corrected_chars = []
        for keycode, level, active_layout, displayed_char in chunk:
            ch = self.layout_pair.other_layout_char(keycode, level, active_layout)
            # Keep the count of corrected characters in lockstep with the
            # number of backspaces sent: a keycode/level with no mapped
            # counterpart falls back to what was actually on screen rather
            # than being silently dropped.
            corrected_chars.append(ch if ch else displayed_char)

        inject.send_backspaces(len(chunk))
        inject.type_text("".join(corrected_chars))
        self.buffer.clear()
