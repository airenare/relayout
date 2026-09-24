from relayout.keymap import LayoutPair
from relayout.layout_resolver import resolve_active_layout


def test_resolve_picks_main_device_not_first_in_list():
    # Found in final review: the real machine has 9 "keyboards" (including
    # power buttons and mice); the flagged main=true device is not index 0.
    pair = LayoutPair("us", "ru")
    data = {
        "keyboards": [
            {"name": "2.4g-dongle", "main": False, "layout": "us,ru", "active_layout_index": 0},
            {"name": "hl-virtual-keyboard-fcitx5", "main": True, "layout": "us,ru", "active_layout_index": 1},
        ]
    }
    assert resolve_active_layout(data, pair) == "ru"


def test_resolve_falls_back_to_first_keyboard_when_no_main_flagged():
    pair = LayoutPair("us", "ru")
    data = {"keyboards": [{"name": "kbd", "layout": "us,ru", "active_layout_index": 1}]}
    assert resolve_active_layout(data, pair) == "ru"


def test_resolve_defaults_to_layout_a_when_no_keyboards():
    pair = LayoutPair("us", "ru")
    assert resolve_active_layout({"keyboards": []}, pair) == "us"
    assert resolve_active_layout({}, pair) == "us"


def test_resolve_does_not_substring_match_display_names():
    # Found in final review: "de" in "german".lower() is False, so a
    # substring match against the human-readable active_keymap name
    # silently always fell back to layout_a for any pair other than
    # us/ru. Matching the exact configured code from `layout`/
    # `active_layout_index` must not have this failure mode.
    pair = LayoutPair("us", "de")
    data = {
        "keyboards": [
            {"name": "kbd", "main": True, "layout": "us,de", "active_layout_index": 1}
        ]
    }
    assert resolve_active_layout(data, pair) == "de"


def test_resolve_handles_malformed_data_without_raising():
    pair = LayoutPair("us", "ru")
    assert resolve_active_layout({"keyboards": "not-a-list"}, pair) == "us"
    assert resolve_active_layout({"keyboards": [{"name": "kbd"}]}, pair) == "us"
    assert resolve_active_layout({"keyboards": ["not-a-dict"]}, pair) == "us"
    assert (
        resolve_active_layout(
            {"keyboards": [{"layout": "us,ru", "active_layout_index": 99}]}, pair
        )
        == "us"
    )
