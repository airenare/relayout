from unittest.mock import patch, MagicMock
from relayout.daemon import Daemon
from relayout.keymap import LayoutPair
from relayout.buffer import TypedTextBuffer


def test_correct_prefers_selection_when_present():
    pair = LayoutPair("us", "ru")
    buf = TypedTextBuffer()
    daemon = Daemon(pair, buf)
    daemon.arm_selection()

    with patch("relayout.daemon.selection.read_primary_selection", return_value="ghbdtn"), \
         patch("relayout.daemon.inject.type_text") as mock_type, \
         patch("relayout.daemon.inject.send_backspaces") as mock_backspace:
        daemon.correct()

    assert "".join(c.args[0] for c in mock_type.call_args_list) == "привет"
    mock_backspace.assert_not_called()


def test_correct_falls_back_to_buffer_when_no_selection():
    pair = LayoutPair("us", "ru")
    buf = TypedTextBuffer()
    # xkb keycode 24 = physical Q key, level 0 = unshifted 'q' under "us"
    buf.record(keycode=24, level=0, active_layout="us", displayed_char="q", timestamp=0.0)
    daemon = Daemon(pair, buf)

    with patch("relayout.daemon.selection.read_primary_selection", return_value=""), \
         patch("relayout.daemon.inject.type_text") as mock_type, \
         patch("relayout.daemon.inject.send_backspaces") as mock_backspace:
        daemon.correct()

    mock_type.assert_called_once_with("й")
    mock_backspace.assert_called_once_with(1)


def test_correct_clears_buffer_after_use():
    pair = LayoutPair("us", "ru")
    buf = TypedTextBuffer()
    buf.record(keycode=24, level=0, active_layout="us", displayed_char="q", timestamp=0.0)
    daemon = Daemon(pair, buf)

    with patch("relayout.daemon.selection.read_primary_selection", return_value=""), \
         patch("relayout.daemon.inject.type_text"), \
         patch("relayout.daemon.inject.send_backspaces"):
        daemon.correct()

    assert buf.trailing_chunk() == []


def test_correct_falls_back_to_displayed_char_when_no_counterpart():
    # Found in final review: other_layout_char can return None for a
    # keycode/level with no counterpart in the other layout's table (e.g.
    # a multi-keysym level). Dropping it desynced the backspace count from
    # the retyped text, deleting one extra character the user didn't type
    # wrong. The original displayed character must be kept instead.
    pair = LayoutPair("us", "ru")
    buf = TypedTextBuffer()
    buf.record(keycode=24, level=0, active_layout="us", displayed_char="q", timestamp=0.0)
    # xkb keycode 63 (keypad '*') decodes to the same '*' in both layouts,
    # via multi-keysym levels in the real table -- other_layout_char
    # returns None for a level index past what's meaningfully mapped here.
    buf.record(keycode=999999, level=0, active_layout="us", displayed_char="*", timestamp=0.05)
    daemon = Daemon(pair, buf)

    with patch("relayout.daemon.selection.read_primary_selection", return_value=""), \
         patch("relayout.daemon.inject.type_text") as mock_type, \
         patch("relayout.daemon.inject.send_backspaces") as mock_backspace:
        daemon.correct()

    assert sum(c.args[0] for c in mock_backspace.call_args_list) == 2  # one key per call
    assert "".join(c.args[0] for c in mock_type.call_args_list) == "й*"


def test_correct_noops_when_nothing_to_correct():
    pair = LayoutPair("us", "ru")
    buf = TypedTextBuffer()
    daemon = Daemon(pair, buf)

    with patch("relayout.daemon.selection.read_primary_selection", return_value=""), \
         patch("relayout.daemon.inject.type_text") as mock_type, \
         patch("relayout.daemon.inject.send_backspaces") as mock_backspace:
        daemon.correct()

    mock_type.assert_not_called()
    mock_backspace.assert_not_called()
