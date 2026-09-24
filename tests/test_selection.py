import subprocess
from unittest.mock import patch, MagicMock
from relayout.selection import read_primary_selection


def test_returns_selection_text():
    fake_result = MagicMock(returncode=0, stdout="ghbdtn")
    with patch("subprocess.run", return_value=fake_result) as mock_run:
        assert read_primary_selection() == "ghbdtn"
        args = mock_run.call_args[0][0]
        assert args[0] == "wl-paste"
        assert "--primary" in args


def test_returns_empty_string_on_nonzero_exit():
    fake_result = MagicMock(returncode=1, stdout="")
    with patch("subprocess.run", return_value=fake_result):
        assert read_primary_selection() == ""


def test_returns_empty_string_when_wl_paste_missing():
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        assert read_primary_selection() == ""


def test_returns_empty_string_on_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="wl-paste", timeout=1.0)):
        assert read_primary_selection() == ""
