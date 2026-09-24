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
        for keycode, level, active_layout, _ in chunk:
            ch = self.layout_pair.other_layout_char(keycode, level, active_layout)
            if ch:
                corrected_chars.append(ch)

        inject.send_backspaces(len(chunk))
        inject.type_text("".join(corrected_chars))
        self.buffer.clear()
