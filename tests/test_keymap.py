from relayout.keymap import evdev_to_xkb_keycode, build_layout_table, LayoutPair


def test_evdev_to_xkb_keycode_offset():
    # evdev KEY_Q = 16, xkb keycode for the same physical key = 24
    assert evdev_to_xkb_keycode(16) == 24


def test_build_layout_table_us_q_key():
    table = build_layout_table("us")
    # xkb keycode 24 is the physical Q key; level 0 unshifted, level 1 shifted
    assert table[24][0] == "q"
    assert table[24][1] == "Q"


def test_build_layout_table_ru_q_key():
    table = build_layout_table("ru")
    # same physical key produces Cyrillic Й on a Russian layout
    assert table[24][0] == "й"
    assert table[24][1] == "Й"


def test_layout_pair_swap_selection_text():
    pair = LayoutPair("us", "ru")
    # "ghbdtn" typed on a US-labeled keyboard while Russian was intended
    # decodes, key-by-key, to the Russian word "привет"
    assert pair.swap_selection_text("ghbdtn") == "привет"


def test_layout_pair_swap_selection_text_passthrough_for_shared_chars():
    pair = LayoutPair("us", "ru")
    # digits and space are identical in both layouts -> unchanged
    assert pair.swap_selection_text("123 456") == "123 456"


def test_layout_pair_char_map_does_not_let_keypad_overwrite_main_row_punctuation():
    # Found in final review: keycode 61 (main-row '/','?') and the keypad
    # decimal key both produce '.' on one side, and the char_map build used
    # to let whichever keycode was iterated last silently overwrite the
    # other's mapping. The main-row '.' key (keycode 60, us) must map to
    # its real Russian counterpart 'ю', not get clobbered by keycode 61.
    pair = LayoutPair("us", "ru")
    assert pair.swap_selection_text(".") == "ю"
    assert pair.swap_selection_text(",") == "б"


def test_layout_pair_other_layout_char():
    pair = LayoutPair("us", "ru")
    # xkb keycode 24, level 0, typed while "us" was active -> the "ru" equivalent
    assert pair.other_layout_char(24, 0, "us") == "й"
    assert pair.other_layout_char(24, 0, "ru") == "q"
