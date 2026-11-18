"""In-memory ring buffer of recently typed keys.

Used to find the last word/phrase to correct when nothing is selected.
Never written to disk. Cleared on newline/tab/escape or after an idle
timeout so it never resurrects something typed long ago.
"""

BOUNDARY_CHARS = set(" \t\n\r.,!?;:()\"'")
CLEARING_CHARS = {"\n", "\r", "\t", "\x1b"}


class TypedTextBuffer:
    def __init__(self, max_len: int = 500, idle_timeout_s: float = 10.0):
        self.max_len = max_len
        self.idle_timeout_s = idle_timeout_s
        self._entries: list[tuple[int, int, str, str]] = []
        self._last_time: float | None = None
        # Layout of the last word before the buffer was emptied by a
        # correction; lets the next word still see what language you are in.
        self.context_layout: str | None = None

    def record(
        self,
        keycode: int,
        level: int,
        active_layout: str,
        displayed_char: str | None,
        timestamp: float,
    ) -> None:
        if displayed_char is None:
            return

        if self._last_time is not None and timestamp - self._last_time > self.idle_timeout_s:
            self.clear()

        self._last_time = timestamp

        if displayed_char in CLEARING_CHARS:
            self.clear()
            return

        if not displayed_char.isprintable():
            # Any other control character (e.g. a stray keysym we don't
            # otherwise special-case) is neither text nor a clear signal --
            # ignore it rather than appending it as if it were typed text.
            return

        self._entries.append((keycode, level, active_layout, displayed_char))
        if len(self._entries) > self.max_len:
            self._entries.pop(0)

    def backspace(self) -> None:
        """Remove the most recently recorded entry, mirroring a real Backspace."""
        if self._entries:
            self._entries.pop()

    def clear(self) -> None:
        self._entries.clear()
        self.context_layout = None

    def previous_word_layout(self) -> str | None:
        """Layout the word before the last word was typed in (same line)."""
        entries = self._entries
        end = len(entries)
        while end > 0 and entries[end - 1][3] == " ":
            end -= 1
        while end > 0 and entries[end - 1][3] != " ":
            end -= 1
        while end > 0 and entries[end - 1][3] == " ":
            end -= 1
        return entries[end - 1][2] if end > 0 else self.context_layout

    def trailing_chunk(self) -> list[tuple[int, int, str, str]]:
        chunk: list[tuple[int, int, str, str]] = []
        for entry in reversed(self._entries):
            displayed_char = entry[3]
            if displayed_char in BOUNDARY_CHARS:
                break
            chunk.append(entry)
        chunk.reverse()
        return chunk

    def last_word(self) -> tuple[list[tuple[int, int, str, str]], int]:
        """The last whitespace-delimited word and the spaces typed after it.

        Unlike trailing_chunk(), punctuation does not split the word: keys
        like ``,`` ``.`` ``;`` are letters in other layouts (ru: б ю ж).
        """
        end = len(self._entries)
        while end > 0 and self._entries[end - 1][3] == " ":
            end -= 1
        start = end
        while start > 0 and self._entries[start - 1][3] != " ":
            start -= 1
        return list(self._entries[start:end]), len(self._entries) - end
