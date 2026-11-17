import json
from unittest.mock import MagicMock

import pytest

from relayout.buffer import TypedTextBuffer
from relayout.daemon import Daemon
from relayout.detect import Detector
from relayout.hypr import layout_index
from relayout.keymap import LayoutPair
from relayout.rules import Store


@pytest.fixture(scope="module")
def pair():
    return LayoutPair("us", "ru")


@pytest.fixture(scope="module")
def detector():
    return Detector.for_layouts("us", "ru", commands=frozenset({"jq", "gcc"}))


def type_text(buf, pair, layout, text):
    """Feed `text` into the buffer as if typed on `layout`."""
    table = pair.table_for(layout)
    for i, ch in enumerate(text):
        for keycode, chars in table.items():
            if ch in chars:
                buf.record(keycode, chars.index(ch), layout, ch, float(i) * 0.01)
                break
        else:
            raise AssertionError(f"cannot type {ch!r} on {layout}")


class Fx:
    """Recording stand-ins for wtype / hyprctl / wl-paste."""

    def __init__(self, selected=""):
        self.calls = []
        self.selected = selected

    def send_backspaces(self, n):
        self.calls.append(("bs", n))

    def type_text(self, t):
        self.calls.append(("type", t))

    def read_primary_selection(self):
        return self.selected

    def switch(self, layout):
        self.calls.append(("switch", layout))

    def get(self):
        return "us"


def make(pair, detector, tmp_path, **kw):
    fx = Fx()
    buf = TypedTextBuffer()
    d = Daemon(
        pair, buf, detector=detector,
        store=Store(tmp_path / "state.json", default_excluded=["keepassxc"]),
        hypr=fx, typist=fx, selector=fx, **kw,
    )
    return d, buf, fx


def word_and_space(buf, pair, layout, text):
    type_text(buf, pair, layout, text + " ")
    return buf.last_word()


# --- detection -------------------------------------------------------

@pytest.mark.parametrize("typed,layout,expected", [
    ("ghbdtn", "us", True),     # привет typed on us
    ("руддщ", "ru", True),      # hello typed on ru
    ("hello", "us", False),
    ("привет", "ru", False),
    ("jq", "us", False),        # a command in $PATH
    ("Ghbdtn", "us", True),     # leading capital is fine
    ("iPhone", "us", False),    # deliberate case
    ("USA", "us", False),
    ("d", "us", True),          # lone в
    ("a", "us", False),
])
def test_detector_verdicts(pair, detector, typed, layout, expected):
    other = pair.other(layout)
    other_text = pair.swap_selection_text(typed)
    assert detector.decide(layout, typed, other, other_text) == expected


def test_digits_and_symbols_never_flip(pair, detector):
    assert not detector.decide("us", "ghbdtn1", "ru", "привет1")
    assert not detector.decide("us", "ghbdtn-x", "ru", "привет-ч")


# --- auto-correct ----------------------------------------------------

def test_auto_correct_retypes_switches_and_clears(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    assert d.auto_correct(chunk, spaces) is True
    assert fx.calls == [("bs", 7), ("type", "привет "), ("switch", "ru")]
    assert buf.last_word() == ([], 0)


def test_auto_correct_leaves_correct_word_alone(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    chunk, spaces = word_and_space(buf, pair, "us", "hello")
    assert d.auto_correct(chunk, spaces) is False
    assert fx.calls == []


def test_auto_correct_respects_auto_off_and_excluded_app(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    d.store.auto = False
    assert not d.auto_correct(chunk, spaces)
    d.store.auto = True
    d.set_app("KeePassXC")
    assert d.suppressed() == "app"
    assert not d.auto_correct(chunk, spaces)


def test_auto_correct_skipped_in_excluded_layer(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path, exclude_layers=("omarchy-polkit",))
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    d.set_layer("omarchy-polkit", True)
    assert d.suppressed() == "layer" and not d.auto_correct(chunk, spaces)
    d.set_layer("omarchy-polkit", False)
    assert d.auto_correct(chunk, spaces)


def test_double_space_does_not_recorrect(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    type_text(buf, pair, "us", "hello  ")
    chunk, spaces = buf.last_word()
    assert spaces == 2 and not d.auto_correct(chunk, spaces)


def test_mixed_layout_chunk_is_skipped(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    type_text(buf, pair, "us", "ghb")
    type_text(buf, pair, "ru", "дтн ")
    chunk, spaces = buf.last_word()
    assert not d.auto_correct(chunk, spaces)


# --- undo and learning -----------------------------------------------

def test_hotkey_undoes_auto_correction_and_learns_after_two(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    for _ in range(2):
        buf.clear()
        fx.calls.clear()
        chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
        assert d.auto_correct(chunk, spaces)
        d.correct()  # undo
        assert fx.calls[-3:] == [("bs", 7), ("type", "ghbdtn "), ("switch", "us")]
    assert d.store.words == {"ghbdtn": "us"}
    assert json.loads((tmp_path / "state.json").read_text())["words"] == {"ghbdtn": "us"}
    buf.clear()
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    assert not d.auto_correct(chunk, spaces)  # now protected


def test_manual_flip_of_last_word_after_space_and_learning(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    for _ in range(2):
        buf.clear()
        fx.calls.clear()
        type_text(buf, pair, "ru", "туче ")  # "next" typed on ru, a real ru word
        d.last = None
        d.correct()
        assert fx.calls == [("bs", 5), ("type", "next "), ("switch", "us")]
    assert d.store.words == {"next": "us"}
    # now it flips by itself
    buf.clear()
    chunk, spaces = word_and_space(buf, pair, "ru", "туче")
    assert d.auto_correct(chunk, spaces)


def test_undo_expires(pair, detector, tmp_path):
    t = [0.0]
    d, buf, fx = make(pair, detector, tmp_path, clock=lambda: t[0])
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    d.auto_correct(chunk, spaces)
    t[0] = 100.0
    fx.calls.clear()
    d.correct()  # buffer was cleared by the correction: nothing to do
    assert fx.calls == []


def test_key_typed_cancels_undo(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    d.auto_correct(chunk, spaces)
    d.key_typed()
    assert d.last is None


# --- control commands --------------------------------------------------

def test_commands(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    changes = []
    d.on_change = lambda: changes.append(1)
    assert json.loads(d.handle_command("status"))["auto"] is True
    assert d.handle_command("auto toggle") == "ok" and d.store.auto is False
    assert json.loads(d.handle_command("status"))["auto"] is False
    d.handle_command("auto on")
    d.handle_command("exclude add kitty")
    assert d.store.is_excluded("kitty")
    d.handle_command("exclude rm kitty")
    assert not d.store.is_excluded("kitty")
    assert d.handle_command("rules add next") == "ok"
    assert d.store.words == {"next": "us"}
    assert d.handle_command("rules add привет") == "ok"
    assert d.store.words["привет"] == "ru"
    assert json.loads(d.handle_command("rules list")) == {"next": "us", "привет": "ru"}
    assert d.handle_command("rules rm -weird").startswith("error")
    assert d.handle_command("rules rm next") == "ok"
    assert d.handle_command("auto maybe").startswith("error")
    assert d.handle_command("bogus").startswith("error")
    assert d.handle_command("").startswith("error")
    assert len(changes) >= 6


def test_state_persists(pair, detector, tmp_path):
    d, _, _ = make(pair, detector, tmp_path)
    d.handle_command("auto off")
    d.handle_command("rules add next")
    again = Store(tmp_path / "state.json")
    assert again.auto is False and again.words == {"next": "us"}
    assert "keepassxc" in again.excluded


def test_status_without_detector_reports_auto_off(pair, tmp_path):
    d, _, _ = make(pair, None, tmp_path)
    assert json.loads(d.handle_command("status"))["auto"] is False


def test_layout_index():
    devices = {"keyboards": [{"main": True, "layout": "us,ru"}]}
    assert layout_index(devices, "ru") == 1
    assert layout_index(devices, "de") is None
    assert layout_index({}, "us") is None


def test_typed_word_beats_stale_selection(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    fx.selected = "stale selection " * 50
    type_text(buf, pair, "us", "ghbdtn")
    d.correct()
    assert fx.calls == [("bs", 6), ("type", "привет"), ("switch", "ru")]


def test_selection_used_when_nothing_typed(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    fx.selected = "ghbdtn"
    d.arm_selection()
    d.correct()
    assert fx.calls == [("type", "привет")]
    assert not d.selection_armed


def test_stale_selection_ignored_when_not_armed(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    fx.selected = "old mouse selection " * 50
    d.correct()
    assert fx.calls == []


def test_typing_or_clicking_disarms_selection(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    fx.selected = "ghbdtn"
    d.arm_selection()
    d.key_typed()
    d.correct()
    assert fx.calls == []


def test_selection_swap_maps_through_physical_keys(pair):
    assert pair.swap_selection_text("ghbdtn?") == "привет,"
    assert pair.swap_selection_text("привет,") == "ghbdtn?"
    assert pair.swap_selection_text("руддщб") == "hello,"
    assert pair.swap_selection_text("ghbdtn. vbh!") == "приветю мир!"
    assert pair.swap_selection_text("Ghbdtn? Vbh!") == "Привет, Мир!"
    assert pair.swap_selection_text("привет 123") == "ghbdtn 123"
    assert pair.swap_selection_text("hello\nworld") == "руддщ\nцщкдв"


# --- word-ending punctuation without a space -------------------------------

def key_of(pair, layout, ch):
    for keycode, chars in pair.table_for(layout).items():
        if ch in chars:
            return keycode, chars.index(ch)


def test_boundary_kinds(pair):
    assert pair.boundary_kind(*key_of(pair, "us", ","), "us") == "strict"
    assert pair.boundary_kind(*key_of(pair, "us", "?"), "us") == "strict"
    assert pair.boundary_kind(*key_of(pair, "ru", "б"), "ru") == "loose"   # ,
    assert pair.boundary_kind(*key_of(pair, "ru", "."), "ru") == "strict"
    assert pair.boundary_kind(*key_of(pair, "us", "a"), "us") is None


def type_keys_on_other(buf, pair, layout, intended):
    """Press the keys that produce `intended` on `layout`, with the other layout
    active (what you get typing in the wrong layout). Returns what appears."""
    other = pair.other(layout)
    shown = ""
    for i, ch in enumerate(intended):
        keycode, level = key_of(pair, layout, ch)
        shown_ch = pair.table_for(other)[keycode][level]
        buf.record(keycode, level, other, shown_ch, float(i) * 0.01)
        shown += shown_ch
    return shown


@pytest.mark.parametrize("intended,layout", [
    ("привет,", "ru"), ("привет.", "ru"), ("привет?", "ru"), ("привет:", "ru"),
    ('привет"', "ru"), ("привет!", "ru"), ("привет)", "ru"), ("привет;", "ru"),
    ("hello,", "us"), ("hello.", "us"), ("hello?", "us"), ("hello!", "us"),
])
def test_punctuation_directly_after_word_flips(pair, detector, tmp_path, intended, layout):
    d, buf, fx = make(pair, detector, tmp_path)
    shown = type_keys_on_other(buf, pair, layout, intended)
    chunk, spaces = buf.last_word()
    assert spaces == 0
    # letter-keys (loose) need extra margin; use it for all to prove the worst case
    assert d.auto_correct(chunk, 0, extra_margin=8.0), shown
    assert fx.calls == [("bs", len(intended)), ("type", intended), ("switch", layout)]


def test_correct_word_with_punctuation_is_kept(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    for layout, text in (("us", "hello,"), ("ru", "привет?"), ("us", "world.")):
        buf.clear()
        type_text(buf, pair, layout, text)
        chunk, _ = buf.last_word()
        assert not d.auto_correct(chunk, 0, extra_margin=8.0)
    assert fx.calls == []


def test_lone_punctuation_is_not_a_word(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    type_text(buf, pair, "us", ",")
    chunk, _ = buf.last_word()
    assert not d.auto_correct(chunk, 0)


def test_symbols_inside_a_word_still_block(pair, detector):
    assert not detector.decide("us", "ghb&dtn", "ru", "при?вет")
    assert not detector.decide("us", "&ghbdtn", "ru", "?привет")
