"""Correction logic: auto-correct on word boundary, manual flip, undo, learning.

All effects (typing, layout switching, selection, notifications) are injected
so the policy can be unit-tested without a compositor.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from relayout import inject, selection
from relayout.buffer import TypedTextBuffer
from relayout.detect import Detector, deliberate_case, language_for
from relayout.keymap import LayoutPair
from relayout.output import LAYOUT_SETTLE_S
from relayout.rules import Store, rule_key

# How long the hotkey keeps toggling the last corrected word. Any other key,
# click or window change ends it sooner.
UNDO_WINDOW_S = 60.0
# Extra log-probability margin when a letter-in-this-layout key (ru `ю` for `.`)
# triggers a correction: measured 0 false flips on 3.6k correct mid-word prefixes.
LOOSE_TRIGGER_MARGIN = 8.0


@dataclass
class Correction:
    """The last thing we retyped, so the hotkey can undo it."""

    orig_text: str
    new_text: str
    orig_layout: str
    spaces: int
    auto: bool
    at: float
    chunk: tuple = ()  # buffer entries of the original keys, for key replay
    flipped: bool = True  # False once the hotkey has put the original text back


def notify_send(message: str) -> None:
    try:
        subprocess.run(["notify-send", "-a", "relayout", "relayout", message], check=False)
    except FileNotFoundError:
        pass


class Daemon:
    def __init__(
        self,
        layout_pair: LayoutPair,
        buffer: TypedTextBuffer,
        detector: Detector | None = None,
        store: Store | None = None,
        hypr=None,
        typist=inject,
        selector=selection,
        learn_threshold: int = 2,
        exclude_layers: tuple[str, ...] = (),
        notify: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        replayer=None,
        locked: Callable[[], bool] = lambda: False,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.layout_pair = layout_pair
        self.buffer = buffer
        self.detector = detector
        self.store = store or Store()
        self.hypr = hypr  # needs .switch(layout) and .get()
        self.typist = typist
        self.selector = selector
        self.learn_threshold = learn_threshold
        self.exclude_layers = {x.lower() for x in exclude_layers}
        self.notify = notify
        self.clock = clock
        self.replayer = replayer  # KeyReplayer, or None to type text with wtype
        self.locked = locked
        self._sleep = sleep
        self.app = ""
        self.layers: set[str] = set()
        self.last: Correction | None = None
        # True only right after a selection gesture (drag, double click,
        # Shift+arrows, Ctrl+A). Wayland keeps stale selections forever.
        self.selection_armed = False
        self.on_change: Callable[[], None] = lambda: None
        self._counts: dict[tuple[str, str], int] = {}

    # --- state -------------------------------------------------------

    def suppressed(self) -> str | None:
        if self.locked():
            return "lock"
        if self.store.is_excluded(self.app):
            return "app"
        if self.layers & self.exclude_layers:
            return "layer"
        return None

    def set_app(self, app: str) -> None:
        if app != self.app:
            self.app = app
            self.buffer.clear()
            self.last = None
            self.on_change()

    def set_layer(self, namespace: str, opened: bool) -> None:
        ns = namespace.lower()
        before = self.suppressed()
        (self.layers.add if opened else self.layers.discard)(ns)
        if ns in self.exclude_layers:
            self.buffer.clear()
        if before != self.suppressed():
            self.on_change()

    def key_typed(self) -> None:
        """Any real key press invalidates a pending undo and a selection gesture."""
        self.last = None
        self.selection_armed = False

    def arm_selection(self) -> None:
        self.selection_armed = True

    def disarm_selection(self) -> None:
        self.selection_armed = False

    def status(self) -> dict:
        active = self.hypr.get() if self.hypr else self.layout_pair.layout_a
        return {
            "auto": self.store.auto and self.detector is not None,
            "suppressed": self.suppressed(),
            "app": self.app,
            "excluded": list(self.store.excluded),
            "layouts": [self.layout_pair.layout_a, self.layout_pair.layout_b],
            "active": active,
            "rules": dict(self.store.words),
        }

    # --- corrections -------------------------------------------------

    def _rule_verdict(self, cur, cur_text, other, other_text) -> bool | None:
        words = self.store.words
        if words.get(rule_key(cur_text)) == cur:
            return False
        if words.get(rule_key(other_text)) == other:
            return True
        return None

    def should_flip(
        self, chunk, cur: str, cur_text: str, other_text: str, extra_margin: float = 0.0
    ) -> bool:
        other = self.layout_pair.other(cur)
        verdict = self._rule_verdict(cur, cur_text, other, other_text)
        if verdict is not None:
            return verdict
        if self.detector is None:
            return False
        return self.detector.decide(
            cur, cur_text, other, other_text,
            deliberate_case([e[1] == 1 for e in chunk], cur_text, other_text),
            extra_margin,
        )

    def auto_correct(self, chunk, spaces: int = 1, extra_margin: float = 0.0) -> bool:
        """Called right after Space (spaces=1) or a word-ending punctuation key
        (spaces=0): retype the word if misspelled in the current layout.
        Returns True if it did."""
        if not chunk or spaces > 1 or not self.store.auto or self.suppressed():
            return False
        if spaces == 0 and len(chunk) < 2:
            return False  # punctuation alone is not a word
        layouts = {e[2] for e in chunk}
        if len(layouts) != 1:
            return False
        cur = next(iter(layouts))
        cur_text, other_text = self.layout_pair.render(chunk, cur)
        if not self.should_flip(chunk, cur, cur_text, other_text, extra_margin):
            return False
        self._retype(chunk, cur, cur_text, other_text, spaces, auto=True)
        return True

    def _emit(self, entries, old_len: int, text: str, spaces: int, layout: str) -> None:
        """Replace ``old_len`` characters (+ trailing spaces) with ``text`` and
        make ``layout`` active, by key replay when available, else wtype."""
        if self.replayer is not None:
            self.replayer.backspaces(old_len + spaces)
            if self.hypr:
                self.hypr.switch(layout)
                self._sleep(LAYOUT_SETTLE_S)
            self.replayer.replay(entries, spaces)
            return
        self.typist.send_backspaces(old_len + spaces)
        self.typist.type_text(text + " " * spaces)
        if self.hypr:
            self.hypr.switch(layout)

    def _retype(self, chunk, cur, cur_text, other_text, spaces, auto) -> None:
        other = self.layout_pair.other(cur)
        self._emit(chunk, len(chunk), other_text, spaces, other)
        self.buffer.clear()
        self.last = Correction(
            cur_text, other_text, cur, spaces, auto, self.clock(), tuple(chunk)
        )

    def correct(self) -> None:
        """The hotkey: toggle the last corrected word back and forth, else flip
        the selection or the last word."""
        last = self.last
        if last and self.clock() - last.at <= UNDO_WINDOW_S:
            self._toggle(last)
            return

        # Recent typing wins over the selection: Wayland keeps the last mouse
        # selection indefinitely, so a stale one would otherwise be retyped
        # (hundreds of words) instead of the word just typed. Clicks and caret
        # keys clear the buffer, so a real selection still takes the selection path.
        chunk, spaces = self.buffer.last_word()
        if not chunk:
            if self.selection_armed:
                selected = self.selector.read_primary_selection()
                self.selection_armed = False
                if selected:
                    self.typist.type_text(self.layout_pair.swap_selection_text(selected))
            return

        cur = chunk[-1][2]
        cur_text, other_text = self.layout_pair.render(chunk, cur)
        self._retype(chunk, cur, cur_text, other_text, spaces, auto=False)
        self._learn(other_text, self.layout_pair.other(cur))

    def _toggle(self, last: Correction) -> None:
        """Swap the corrected word and the original again, as often as asked."""
        if last.flipped:  # back to what was typed
            self._emit(last.chunk, len(last.new_text), last.orig_text, last.spaces, last.orig_layout)
            last.flipped = False
            if last.auto:
                self._learn(last.orig_text, last.orig_layout)
        else:  # corrected again
            self._emit(
                last.chunk, len(last.orig_text), last.new_text, last.spaces,
                self.layout_pair.other(last.orig_layout),
            )
            last.flipped = True
        last.at = self.clock()
        self.buffer.clear()

    def _learn(self, text: str, layout: str) -> None:
        key = rule_key(text)
        if not key or len(key) < 2:
            return
        n = self._counts.get((key, layout), 0) + 1
        if n >= self.learn_threshold:
            self._counts.pop((key, layout), None)
            self.store.add_word(key, layout)
            if self.notify:
                self.notify(f"learned: “{key}” is always {layout}")
            self.on_change()
        else:
            self._counts[(key, layout)] = n

    # --- control commands (used by the socket server) ----------------

    def guess_layout(self, word: str) -> str:
        pair = self.layout_pair
        if self.detector:
            for layout in (pair.layout_a, pair.layout_b):
                model = self.detector.models.get(language_for(layout))
                if model and all(c in model.letters for c in rule_key(word)):
                    return layout
        return pair.layout_a

    def handle_command(self, line: str) -> str:
        parts = line.split()
        if not parts:
            return "error: empty command"
        cmd, args = parts[0], parts[1:]
        try:
            return self._dispatch(cmd, args)
        except (IndexError, ValueError):
            return f"error: bad arguments for {cmd}"

    def _dispatch(self, cmd: str, args: list[str]) -> str:
        store = self.store
        if cmd == "status":
            return json.dumps(self.status(), ensure_ascii=False)
        if cmd == "flip":
            self.correct()
            return "ok"
        if cmd == "auto":
            mode = args[0]
            if mode not in ("on", "off", "toggle"):
                raise ValueError
            store.auto = {"on": True, "off": False, "toggle": not store.auto}[mode]
            store.save()
            self.on_change()
            return "ok"
        if cmd == "exclude":
            sub = args[0]
            if sub == "list":
                return json.dumps(store.excluded, ensure_ascii=False)
            cls = args[1]
            if sub == "add" and cls not in store.excluded:
                store.excluded.append(cls)
            elif sub == "rm":
                store.excluded = [x for x in store.excluded if x.lower() != cls.lower()]
            elif sub != "add":
                raise ValueError
            store.save()
            self.on_change()
            return "ok"
        if cmd == "rules":
            sub = args[0]
            if sub == "list":
                return json.dumps(store.words, ensure_ascii=False)
            if sub == "add":
                word = args[1]
                layout = args[2] if len(args) > 2 else self.guess_layout(word)
                if layout not in (self.layout_pair.layout_a, self.layout_pair.layout_b):
                    return f"error: unknown layout {layout}"
                store.add_word(word, layout)
            elif sub == "rm":
                if not store.remove_word(args[1]):
                    return "error: no such rule"
            else:
                raise ValueError
            self.on_change()
            return "ok"
        return f"error: unknown command {cmd}"
