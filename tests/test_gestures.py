from relayout.gestures import PointerGestures


def test_plain_click_does_not_select():
    g = PointerGestures()
    g.down(0.0)
    g.moved(2)  # jitter
    assert not g.up()


def test_drag_selects():
    g = PointerGestures()
    g.down(0.0)
    for _ in range(10):
        g.moved(5)
    assert g.up()


def test_double_click_selects_but_slow_second_click_does_not():
    g = PointerGestures()
    g.down(0.0); assert not g.up()
    g.down(0.3); assert g.up()      # double click
    g.down(5.0); assert not g.up()  # long pause: a fresh single click


def test_drag_travel_resets_each_press():
    g = PointerGestures()
    g.down(0.0); g.moved(100); assert g.up()
    g.down(10.0); assert not g.up()
