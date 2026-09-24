"""Pure logic for picking the active layout out of `hyprctl devices -j` JSON.

Split out from input_listener.py so the parsing/matching logic (found to be
buggy in review: wrong device picked, substring-matched against display
names instead of exact codes, no defense against malformed JSON) can be
unit-tested without a real compositor.
"""
from relayout.keymap import LayoutPair


def resolve_active_layout(hyprctl_data: dict, layout_pair: LayoutPair) -> str:
    """Return whichever of layout_pair's two layouts is currently active.

    Defaults to layout_pair.layout_a for anything unexpected (no keyboards,
    malformed entries, an out-of-range index) rather than raising.
    """
    keyboards = hyprctl_data.get("keyboards")
    if not isinstance(keyboards, list) or not keyboards:
        return layout_pair.layout_a

    keyboard = next(
        (kb for kb in keyboards if isinstance(kb, dict) and kb.get("main")), None
    )
    if keyboard is None:
        keyboard = keyboards[0]
    if not isinstance(keyboard, dict):
        return layout_pair.layout_a

    layout_str = keyboard.get("layout")
    index = keyboard.get("active_layout_index")
    if not isinstance(layout_str, str) or not isinstance(index, int):
        return layout_pair.layout_a

    codes = [code.strip() for code in layout_str.split(",")]
    if index < 0 or index >= len(codes):
        return layout_pair.layout_a

    active_code = codes[index]
    if active_code == layout_pair.layout_b:
        return layout_pair.layout_b
    return layout_pair.layout_a
