from relayout.hotkey import HotkeyDetector


def test_double_tap_within_window_fires():
    hk = HotkeyDetector("KEY_LEFTSHIFT", taps=2, window_ms=400)
    assert hk.feed("KEY_LEFTSHIFT", "down", 0.0) is False
    assert hk.feed("KEY_LEFTSHIFT", "up", 0.05) is False
    assert hk.feed("KEY_LEFTSHIFT", "down", 0.20) is True


def test_taps_outside_window_do_not_fire():
    hk = HotkeyDetector("KEY_LEFTSHIFT", taps=2, window_ms=400)
    assert hk.feed("KEY_LEFTSHIFT", "down", 0.0) is False
    assert hk.feed("KEY_LEFTSHIFT", "down", 1.0) is False  # 1000ms later


def test_other_key_between_taps_resets_sequence():
    # A real Shift+letter (typing a capital) must not count toward the hotkey.
    hk = HotkeyDetector("KEY_LEFTSHIFT", taps=2, window_ms=400)
    assert hk.feed("KEY_LEFTSHIFT", "down", 0.0) is False
    assert hk.feed("KEY_A", "down", 0.05) is False
    assert hk.feed("KEY_LEFTSHIFT", "down", 0.10) is False


def test_fires_again_after_reset():
    hk = HotkeyDetector("KEY_LEFTSHIFT", taps=2, window_ms=400)
    assert hk.feed("KEY_LEFTSHIFT", "down", 0.0) is False
    assert hk.feed("KEY_LEFTSHIFT", "down", 0.1) is True
    assert hk.feed("KEY_LEFTSHIFT", "down", 0.2) is False
    assert hk.feed("KEY_LEFTSHIFT", "down", 0.3) is True


def test_configurable_tap_count():
    hk = HotkeyDetector("KEY_LEFTSHIFT", taps=3, window_ms=400)
    assert hk.feed("KEY_LEFTSHIFT", "down", 0.0) is False
    assert hk.feed("KEY_LEFTSHIFT", "down", 0.1) is False
    assert hk.feed("KEY_LEFTSHIFT", "down", 0.2) is True
