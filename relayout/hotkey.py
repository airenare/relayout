"""Detects N taps of a configured key within a time window.

Any other key being pressed between taps resets the sequence, so that
holding Shift to type a capital letter never counts as a tap.
"""


class HotkeyDetector:
    def __init__(self, key_name: str, taps: int = 2, window_ms: int = 400):
        self.key_name = key_name
        self.taps = taps
        self.window_ms = window_ms
        self._tap_times: list[float] = []

    def feed(self, key_name: str, event_type: str, timestamp: float) -> bool:
        if key_name != self.key_name:
            if event_type == "down":
                self._tap_times.clear()
            return False

        if event_type != "down":
            return False

        window_start = timestamp - (self.window_ms / 1000.0)
        self._tap_times = [t for t in self._tap_times if t >= window_start]
        self._tap_times.append(timestamp)

        if len(self._tap_times) >= self.taps:
            self._tap_times.clear()
            return True
        return False
