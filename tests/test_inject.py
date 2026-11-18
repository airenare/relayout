from unittest.mock import patch, MagicMock
from relayout.inject import send_backspaces, type_text


def test_send_backspaces_calls_wtype_n_times():
    with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
        send_backspaces(3)
        args = mock_run.call_args[0][0]
        assert args.count("BackSpace") == 3
        assert args[0] == "wtype"


def test_send_backspaces_zero_is_noop():
    with patch("subprocess.run") as mock_run:
        send_backspaces(0)
        mock_run.assert_not_called()


def test_type_text_sends_text_on_stdin_not_in_arguments():
    with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
        type_text("привет")
        assert mock_run.call_args[0][0] == ["wtype", "-"]
        assert mock_run.call_args[1]["input"] == "привет".encode()


def test_type_text_empty_string_is_noop():
    with patch("subprocess.run") as mock_run:
        type_text("")
        mock_run.assert_not_called()


def test_type_text_swallows_missing_wtype():
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        type_text("hello")  # must not raise
