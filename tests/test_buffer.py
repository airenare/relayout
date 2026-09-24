from relayout.buffer import TypedTextBuffer


def _type(buf, chars, layout="us", start=0.0, step=0.05):
    t = start
    for ch in chars:
        buf.record(keycode=0, level=0, active_layout=layout, displayed_char=ch, timestamp=t)
        t += step
    return t


def test_trailing_chunk_returns_last_word():
    buf = TypedTextBuffer()
    _type(buf, "hello world ghbdtn")
    chunk = buf.trailing_chunk()
    assert "".join(c for _, _, _, c in chunk) == "ghbdtn"


def test_trailing_chunk_stops_at_punctuation():
    buf = TypedTextBuffer()
    _type(buf, "one, ghbdtn")
    chunk = buf.trailing_chunk()
    assert "".join(c for _, _, _, c in chunk) == "ghbdtn"


def test_enter_clears_buffer():
    buf = TypedTextBuffer()
    _type(buf, "hello")
    buf.record(keycode=0, level=0, active_layout="us", displayed_char="\n", timestamp=1.0)
    assert buf.trailing_chunk() == []


def test_idle_timeout_clears_buffer():
    buf = TypedTextBuffer(idle_timeout_s=10.0)
    _type(buf, "hello", start=0.0)
    # a keystroke arrives 20s later, well past the idle timeout
    buf.record(keycode=0, level=0, active_layout="us", displayed_char="x", timestamp=20.0)
    chunk = buf.trailing_chunk()
    assert "".join(c for _, _, _, c in chunk) == "x"


def test_max_len_caps_buffer():
    buf = TypedTextBuffer(max_len=5)
    _type(buf, "abcdefgh")
    assert len(buf.trailing_chunk()) <= 5


def test_empty_buffer_returns_empty_chunk():
    buf = TypedTextBuffer()
    assert buf.trailing_chunk() == []
