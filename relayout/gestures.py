"""Tells whether a left-button press/release sequence selected text.

Wayland keeps the last selection indefinitely, so relayout only trusts the
primary selection right after a selecting gesture: a drag, or a double/triple
click. Pure logic so it can be tested without a pointer.
"""

# Pointer travel (device units) while the button is down that counts as a drag.
DRAG_THRESHOLD = 8
# Max gap between presses of a double/triple click.
MULTI_CLICK_S = 0.5


class PointerGestures:
    def __init__(self) -> None:
        self._last_down = float("-inf")
        self._multi = False
        self._travel = 0.0

    def down(self, now: float) -> None:
        self._multi = now - self._last_down <= MULTI_CLICK_S
        self._last_down = now
        self._travel = 0.0

    def moved(self, amount: float) -> None:
        self._travel += amount

    def up(self) -> bool:
        """True if the release ends a selection."""
        return self._travel >= DRAG_THRESHOLD or self._multi
