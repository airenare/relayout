import json

from relayout.buffer import TypedTextBuffer
from relayout.daemon import Daemon
from relayout.detect import Detector
from relayout.hypr import CachedLock, session_locked
from relayout.keymap import LayoutPair
from relayout.output import KeyReplayer
from relayout.rules import Store
from tests.test_autocorrect import type_text, word_and_space


class FakeE:
    EV_KEY = 1
    KEY_LEFTSHIFT = 42
    KEY_BACKSPACE = 14
    KEY_SPACE = 57


class FakeUinput:
    def __init__(self):
        self.events = []

    def write(self, typ, code, value):
        self.events.append((code, value))

    def syn(self):
        pass


def test_replayer_taps_keys_with_shift():
    ui = FakeUinput()
    r = KeyReplayer(ui, FakeE, sleep=lambda s: None)
    # xkb keycode 32 -> evdev 24; level 1 holds shift
    r.replay([(32, 0, "us", "q"), (33, 1, "us", "W")], spaces=1)
    assert ui.events == [
        (24, 1), (24, 0),
        (42, 1), (25, 1), (25, 0), (42, 0),
        (57, 1), (57, 0),
    ]
    ui.events.clear()
    r.backspaces(2)
    assert ui.events == [(14, 1), (14, 0)] * 2


class Recorder:
    def __init__(self):
        self.calls = []

    def backspaces(self, n, guard=None):
        self.calls.append(("bs", n))
        return True

    def replay(self, entries, spaces=0, guard=None):
        self.calls.append(("replay", [e[0] for e in entries], spaces))
        return True

    def switch(self, layout):
        self.calls.append(("switch", layout))

    def get(self):
        return "us"


def make(tmp_path, locked=lambda: False):
    pair = LayoutPair("us", "ru")
    rec = Recorder()
    buf = TypedTextBuffer()
    d = Daemon(
        pair, buf, detector=Detector.for_layouts("us", "ru", commands=frozenset()),
        store=Store(tmp_path / "s.json"), hypr=rec, replayer=rec,
        locked=locked, sleep=lambda s: None,
    )
    return pair, d, buf, rec


def test_correction_replays_same_keys_after_switching(tmp_path):
    pair, d, buf, rec = make(tmp_path)
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    keys = [e[0] for e in chunk]
    assert d.auto_correct(chunk, spaces)
    assert rec.calls == [("bs", 7), ("switch", "ru"), ("replay", keys, 1)]


def test_undo_switches_back_and_replays_original_keys(tmp_path):
    pair, d, buf, rec = make(tmp_path)
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    keys = [e[0] for e in chunk]
    d.auto_correct(chunk, spaces)
    rec.calls.clear()
    d.correct()
    assert rec.calls == [("bs", 7), ("switch", "us"), ("replay", keys, 1)]


def test_no_correction_while_locked(tmp_path):
    state = {"locked": True}
    pair, d, buf, rec = make(tmp_path, locked=lambda: state["locked"])
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    assert d.suppressed() == "lock"
    assert not d.auto_correct(chunk, spaces)
    assert json.loads(d.handle_command("status"))["suppressed"] == "lock"
    state["locked"] = False
    assert d.auto_correct(chunk, spaces)


def test_session_locked_parses_hyprland_monitors():
    assert session_locked([{"solitaryBlockedBy": ["NOTIFICATION", "LOCK"]}])
    assert not session_locked([{"solitaryBlockedBy": ["WORKSPACE"]}, {}])
    assert not session_locked([{"solitaryBlockedBy": None}])
    assert not session_locked({"not": "a list"})


def test_cached_lock_probes_once_per_ttl(monkeypatch):
    calls = []
    now = [0.0]
    monkeypatch.setattr("relayout.hypr.time.monotonic", lambda: now[0])
    lock = CachedLock(ttl_s=1.0, probe=lambda: calls.append(1) or True)
    assert lock() and lock() and len(calls) == 1
    now[0] = 2.0
    assert lock() and len(calls) == 2
