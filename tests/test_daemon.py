from unittest.mock import patch, MagicMock
from relayout.daemon import Daemon
from relayout.keymap import LayoutPair
from relayout.buffer import TypedTextBuffer


def test_correct_prefers_selection_when_present():
    pair = LayoutPair("us", "ru")
    buf = TypedTextBuffer()
    daemon = Daemon(pair, buf)

    with patch("relayout.daemon.selection.read_primary_selection", return_value="ghbdtn"), \
         patch("relayout.daemon.inject.type_text") as mock_type, \
         patch("relayout.daemon.inject.send_backspaces") as mock_backspace:
        daemon.correct()

    mock_type.assert_called_once_with("привет")
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
