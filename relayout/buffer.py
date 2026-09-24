"""In-memory ring buffer of recently typed keys.

Used to find the last word/phrase to correct when nothing is selected.
Never written to disk. Cleared on newline/tab/escape or after an idle
timeout so it never resurrects something typed long ago.
"""

BOUNDARY_CHARS = set(" \t\n.,!?;:()\"'")
CLEARING_CHARS = {"\n", "\t", "\x1b"}


class TypedTextBuffer:
    def __init__(self, max_len: int = 500, idle_timeout_s: float = 10.0):
        self.max_len = max_len
        self.idle_timeout_s = idle_timeout_s
        self._entries: list[tuple[int, int, str, str]] = []
        self._last_time: float | None = None

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

        self._entries.append((keycode, level, active_layout, displayed_char))
        if len(self._entries) > self.max_len:
            self._entries.pop(0)

    def clear(self) -> None:
        self._entries.clear()

    def trailing_chunk(self) -> list[tuple[int, int, str, str]]:
        chunk: list[tuple[int, int, str, str]] = []
        for entry in reversed(self._entries):
            displayed_char = entry[3]
            if displayed_char in BOUNDARY_CHARS:
                break
            chunk.append(entry)
        chunk.reverse()
        return chunk
