# relayout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Wayland/Hyprland daemon that fixes text typed in the wrong keyboard layout (selected text, or the last word/phrase) on a configurable hotkey, using real XKB keymaps for the swap.

**Architecture:** A Python package (`relayout/`) of small, independently testable modules (keymap resolution, hotkey detection, typed-text buffering, config, selection reading, text injection) wired together by a thin orchestrator (`daemon.py`), driven by an untested `evdev`/`hyprctl` glue layer (`input_listener.py`) that is verified manually. Ships as a `systemd --user` service.

**Tech Stack:** Python 3.11+ (stdlib `tomllib`), `xkbcommon` (PyPI, real libxkbcommon bindings — verified working during planning), `python-evdev`, `wl-clipboard` (`wl-paste`) and `wtype` as external CLI tools (already installed on this machine).

**Spec:** `docs/superpowers/specs/2026-09-23-relayout-design.md`

## Global Constraints

- Nothing typed or corrected is ever written to disk or sent over the network — all state is in-process memory only (from spec's Purpose section).
- v1 supports exactly one configured layout pair, default `us`/`ru` (from spec's Non-goals).
- No GUI; configuration is TOML only, at `~/.config/relayout/config.toml` (from spec's Config section).
- Target platform is Wayland/Hyprland only — no X11 fallback (from spec's Non-goals).
- Python 3.11+ required (for stdlib `tomllib`, avoids an extra TOML-parsing dependency).

## Review Focus

- Characters with no counterpart in the other layout (digits, punctuation, emoji) must pass through unchanged, not be dropped or raise — spec implies "swap to the other layout's character," silent on what happens when there isn't one.
- Triggering the hotkey with no selection and an empty buffer must no-op silently, not call `wtype`/`wl-paste` with empty input or crash the daemon.
- A legitimate `Shift+<letter>` (typing a capital letter) must never itself count as a tap toward the double-tap hotkey — spec's example is a *deliberate* double-tap gesture, not incidental modifier use.
- The typed-text buffer must not resurrect a word from minutes/hours ago after the user stopped typing and came back — the idle timeout must actually clear it.
- If `wl-paste` or `wtype` aren't on `PATH` (fresh install, no `wl-clipboard`/`wtype` yet), the daemon must fail that one correction gracefully rather than crashing the whole event loop.

---

## File Structure

```
relayout/
  __init__.py
  keymap.py          # LayoutPair: real XKB-backed keycode/char resolution
  hotkey.py           # HotkeyDetector: N-taps-within-window state machine
  buffer.py           # TypedTextBuffer: ring buffer + trailing-chunk lookup
  config.py           # load_config(): TOML + defaults
  selection.py        # read_primary_selection(): wl-paste glue
  inject.py           # send_backspaces()/type_text(): wtype glue
  daemon.py            # Daemon: wires the above into one correction path
  input_listener.py   # evdev + hyprctl glue, manually verified (no unit tests)
  cli.py              # entrypoint: builds real objects, runs the event loop
tests/
  test_keymap.py
  test_hotkey.py
  test_buffer.py
  test_config.py
  test_selection.py
  test_inject.py
  test_daemon.py
packaging/
  relayout.service
scripts/
  install.sh
pyproject.toml
README.md
LICENSE
.gitignore
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `relayout/__init__.py`
- Create: `.gitignore`
- Create: `LICENSE`
- Create: `README.md` (skeleton — filled in fully in Task 10)

**Interfaces:**
- Produces: an installable package named `relayout`, importable as `import relayout`, with `pytest` runnable from repo root.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "relayout"
version = "0.1.0"
description = "Local keyboard-layout autocorrect for Wayland/Hyprland"
requires-python = ">=3.11"
license = "MIT"
dependencies = [
    "xkbcommon>=0.4",
    "evdev>=1.7",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
relayoutd = "relayout.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["relayout*"]
```

- [ ] **Step 2: Create the package skeleton**

```bash
mkdir -p relayout tests packaging scripts
touch relayout/__init__.py
```

- [ ] **Step 3: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
*.egg-info/
.pytest_cache/
```

- [ ] **Step 4: Write `LICENSE`**

Use the standard MIT license text, copyright line `Copyright (c) 2026 airenare`.

- [ ] **Step 5: Write a README skeleton**

```markdown
# relayout

Local keyboard-layout autocorrect for Wayland/Hyprland, inspired by PuntoSwitcher.

Full setup instructions are added in a later commit.
```

- [ ] **Step 6: Create a venv and install the package in editable/dev mode**

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

Expected: installs cleanly, `relayoutd` console script appears in `.venv/bin/`.

- [ ] **Step 7: Verify pytest runs with zero tests**

```bash
./.venv/bin/pytest
```

Expected: `no tests ran` (exit code 5) or similar — not an import/collection error.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml relayout .gitignore LICENSE README.md
git commit -m "chore: project scaffolding"
```

---

### Task 2: Keymap resolution (`keymap.py`)

**Files:**
- Create: `relayout/keymap.py`
- Test: `tests/test_keymap.py`

**Interfaces:**
- Produces:
  - `evdev_to_xkb_keycode(evdev_keycode: int) -> int`
  - `build_layout_table(layout: str) -> dict[int, list[str | None]]` — `{xkb_keycode: [level0_char, level1_char, ...]}`
  - `class LayoutPair`:
    - `LayoutPair(layout_a: str, layout_b: str)`
    - `.layout_a: str`, `.layout_b: str`
    - `.swap_selection_text(text: str) -> str`
    - `.other_layout_char(keycode: int, level: int, current_layout: str) -> str | None`

This is the module every other correction-path task depends on for the actual character swap.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_keymap.py
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


def test_layout_pair_other_layout_char():
    pair = LayoutPair("us", "ru")
    # xkb keycode 24, level 0, typed while "us" was active -> the "ru" equivalent
    assert pair.other_layout_char(24, 0, "us") == "й"
    assert pair.other_layout_char(24, 0, "ru") == "q"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/bin/pytest tests/test_keymap.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'relayout.keymap'`.

- [ ] **Step 3: Implement `relayout/keymap.py`**

```python
"""Keycode <-> character resolution using real XKB keymaps.

Uses libxkbcommon (via the `xkbcommon` PyPI bindings) to compile the actual
keymap for each configured layout, rather than a hand-maintained table. This
is the same mechanism the compositor itself uses, so it stays correct for
shift levels, capslock, etc. without us re-deriving that logic.
"""
from xkbcommon import xkb

# evdev keycodes are offset by 8 from the X11/XKB keycode space by
# long-standing convention (X11 reserves keycodes 0-7).
EVDEV_TO_XKB_OFFSET = 8


def evdev_to_xkb_keycode(evdev_keycode: int) -> int:
    return evdev_keycode + EVDEV_TO_XKB_OFFSET


def build_layout_table(layout: str) -> dict[int, list[str | None]]:
    """Return {xkb_keycode: [level0_char, level1_char, ...]} for a layout."""
    ctx = xkb.Context()
    keymap = ctx.keymap_new_from_names(layout=layout)
    if keymap is None:
        raise ValueError(f"unknown or uncompilable layout: {layout!r}")

    table: dict[int, list[str | None]] = {}
    for keycode in range(keymap.min_keycode(), keymap.max_keycode() + 1):
        if keymap.num_layouts_for_key(keycode) == 0:
            continue
        num_levels = keymap.num_levels_for_key(keycode, 0)
        chars: list[str | None] = []
        for level in range(num_levels):
            syms = keymap.key_get_syms_by_level(keycode, 0, level)
            if len(syms) == 1:
                chars.append(xkb.keysym_to_string(syms[0]))
            else:
                chars.append(None)
        table[keycode] = chars
    return table


class LayoutPair:
    """Bidirectional keycode/character resolution between two layouts."""

    def __init__(self, layout_a: str, layout_b: str):
        self.layout_a = layout_a
        self.layout_b = layout_b
        self._table_a = build_layout_table(layout_a)
        self._table_b = build_layout_table(layout_b)
        self._char_map = self._build_char_map()

    def _build_char_map(self) -> dict[str, str]:
        char_map: dict[str, str] = {}
        for keycode, chars_a in self._table_a.items():
            chars_b = self._table_b.get(keycode)
            if not chars_b:
                continue
            for level, ch_a in enumerate(chars_a):
                if level >= len(chars_b):
                    continue
                ch_b = chars_b[level]
                if not ch_a or not ch_b or ch_a == ch_b:
                    continue
                char_map[ch_a] = ch_b
                char_map[ch_b] = ch_a
        return char_map

    def swap_selection_text(self, text: str) -> str:
        """Swap every character to its counterpart in the other layout.

        Characters with no counterpart (digits, space, punctuation shared
        by both layouts, emoji, etc.) pass through unchanged.
        """
        return "".join(self._char_map.get(ch, ch) for ch in text)

    def other_layout_char(
        self, keycode: int, level: int, current_layout: str
    ) -> str | None:
        """Re-decode (keycode, level) under the layout NOT named by current_layout."""
        other_table = (
            self._table_b if current_layout == self.layout_a else self._table_a
        )
        chars = other_table.get(keycode)
        if not chars or level >= len(chars):
            return None
        return chars[level]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/bin/pytest tests/test_keymap.py -v
```

Expected: PASS (all 6 tests). These run against the real system `libxkbcommon` — no mocking needed since layout compilation is deterministic and side-effect-free.

- [ ] **Step 5: Commit**

```bash
git add relayout/keymap.py tests/test_keymap.py
git commit -m "feat: real XKB-backed layout keycode/char resolution"
```

---

### Task 3: Hotkey detection (`hotkey.py`)

**Files:**
- Create: `relayout/hotkey.py`
- Test: `tests/test_hotkey.py`

**Interfaces:**
- Produces: `class HotkeyDetector`:
  - `HotkeyDetector(key_name: str, taps: int = 2, window_ms: int = 400)`
  - `.feed(key_name: str, event_type: str, timestamp: float) -> bool` — `event_type` is `"down"` or `"up"`; `timestamp` is seconds (e.g. `time.monotonic()`); returns `True` exactly on the event that completes the trigger.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_hotkey.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/bin/pytest tests/test_hotkey.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'relayout.hotkey'`.

- [ ] **Step 3: Implement `relayout/hotkey.py`**

```python
"""Detects N taps of a configured key within a time window.

Any other key being pressed between taps resets the sequence, so that
holding Shift to type a capital letter never counts as a tap.
"""


class HotkeyDetector:
    def __init__(self, key_name: str, taps: int = 2, window_ms: int = 400):
        self.key_name = key_name
        self.taps = taps
        self.window_ms = window_ms
        self._tap_times: list[float] = []

    def feed(self, key_name: str, event_type: str, timestamp: float) -> bool:
        if key_name != self.key_name:
            if event_type == "down":
                self._tap_times.clear()
            return False

        if event_type != "down":
            return False

        window_start = timestamp - (self.window_ms / 1000.0)
        self._tap_times = [t for t in self._tap_times if t >= window_start]
        self._tap_times.append(timestamp)

        if len(self._tap_times) >= self.taps:
            self._tap_times.clear()
            return True
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/bin/pytest tests/test_hotkey.py -v
```

Expected: PASS (all 5 tests).

- [ ] **Step 5: Commit**

```bash
git add relayout/hotkey.py tests/test_hotkey.py
git commit -m "feat: configurable N-tap hotkey detector"
```

---

### Task 4: Typed-text buffer (`buffer.py`)

**Files:**
- Create: `relayout/buffer.py`
- Test: `tests/test_buffer.py`

**Interfaces:**
- Consumes: nothing (pure logic).
- Produces: `class TypedTextBuffer`:
  - `TypedTextBuffer(max_len: int = 500, idle_timeout_s: float = 10.0)`
  - `.record(keycode: int, level: int, active_layout: str, displayed_char: str | None, timestamp: float) -> None`
  - `.clear() -> None`
  - `.trailing_chunk() -> list[tuple[int, int, str, str]]` — list of `(keycode, level, active_layout, displayed_char)`, oldest first, for the run of characters since the nearest boundary.

This is what `daemon.py` (Task 8) calls in the no-selection path.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_buffer.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/bin/pytest tests/test_buffer.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'relayout.buffer'`.

- [ ] **Step 3: Implement `relayout/buffer.py`**

```python
"""In-memory ring buffer of recently typed keys.

Used to find the last word/phrase to correct when nothing is selected.
Never written to disk. Cleared on newline/tab/escape or after an idle
timeout so it never resurrects something typed long ago.
"""

BOUNDARY_CHARS = set(" \t\n.,!?;:()\"'")
CLEARING_CHARS = {"\n", "\t", "\x1b"}


class TypedTextBuffer:
    def __init__(self, max_len: int = 500, idle_timeout_s: float = 10.0):
        self.max_len = max_len
        self.idle_timeout_s = idle_timeout_s
        self._entries: list[tuple[int, int, str, str]] = []
        self._last_time: float | None = None

    def record(
        self,
        keycode: int,
        level: int,
        active_layout: str,
        displayed_char: str | None,
        timestamp: float,
    ) -> None:
        if displayed_char is None:
            return

        if self._last_time is not None and timestamp - self._last_time > self.idle_timeout_s:
            self.clear()

        self._last_time = timestamp

        if displayed_char in CLEARING_CHARS:
            self.clear()
            return

        self._entries.append((keycode, level, active_layout, displayed_char))
        if len(self._entries) > self.max_len:
            self._entries.pop(0)

    def clear(self) -> None:
        self._entries.clear()

    def trailing_chunk(self) -> list[tuple[int, int, str, str]]:
        chunk: list[tuple[int, int, str, str]] = []
        for entry in reversed(self._entries):
            displayed_char = entry[3]
            if displayed_char in BOUNDARY_CHARS:
                break
            chunk.append(entry)
        chunk.reverse()
        return chunk
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/bin/pytest tests/test_buffer.py -v
```

Expected: PASS (all 6 tests).

- [ ] **Step 5: Commit**

```bash
git add relayout/buffer.py tests/test_buffer.py
git commit -m "feat: typed-text ring buffer with boundary lookup"
```

---

### Task 5: Config loading (`config.py`)

**Files:**
- Create: `relayout/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `load_config(path: "pathlib.Path | None" = None) -> dict` returning:
  ```python
  {
      "layouts": {"pair": [str, str]},
      "hotkey": {"key": str, "taps": int, "window_ms": int},
      "buffer": {"max_len": int, "idle_timeout_s": float},
  }
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
import tomllib
from relayout.config import load_config, DEFAULT_CONFIG


def test_load_config_defaults_when_file_absent(tmp_path):
    missing = tmp_path / "does-not-exist.toml"
    config = load_config(missing)
    assert config == DEFAULT_CONFIG


def test_load_config_merges_user_overrides(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[hotkey]\ntaps = 3\n')
    config = load_config(config_path)
    assert config["hotkey"]["taps"] == 3
    # untouched sections/keys keep their defaults
    assert config["hotkey"]["key"] == DEFAULT_CONFIG["hotkey"]["key"]
    assert config["layouts"] == DEFAULT_CONFIG["layouts"]


def test_load_config_custom_layout_pair(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[layouts]\npair = ["us", "de"]\n')
    config = load_config(config_path)
    assert config["layouts"]["pair"] == ["us", "de"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/bin/pytest tests/test_config.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'relayout.config'`.

- [ ] **Step 3: Implement `relayout/config.py`**

```python
"""Loads ~/.config/relayout/config.toml, merged over built-in defaults."""
import tomllib
from pathlib import Path

DEFAULT_CONFIG = {
    "layouts": {"pair": ["us", "ru"]},
    "hotkey": {"key": "KEY_LEFTSHIFT", "taps": 2, "window_ms": 400},
    "buffer": {"max_len": 500, "idle_timeout_s": 10.0},
}


def _default_config_path() -> Path:
    return Path.home() / ".config" / "relayout" / "config.toml"


def load_config(path: Path | None = None) -> dict:
    path = path or _default_config_path()
    config = {section: dict(values) for section, values in DEFAULT_CONFIG.items()}

    if path.exists():
        with open(path, "rb") as f:
            user_config = tomllib.load(f)
        for section, values in user_config.items():
            config.setdefault(section, {}).update(values)

    return config
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/bin/pytest tests/test_config.py -v
```

Expected: PASS (all 3 tests).

- [ ] **Step 5: Commit**

```bash
git add relayout/config.py tests/test_config.py
git commit -m "feat: TOML config loading with defaults"
```

---

### Task 6: Selection reading (`selection.py`)

**Files:**
- Create: `relayout/selection.py`
- Test: `tests/test_selection.py`

**Interfaces:**
- Produces: `read_primary_selection() -> str` — returns `""` on any failure (no primary selection, `wl-paste` missing, timeout).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_selection.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/bin/pytest tests/test_selection.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'relayout.selection'`.

- [ ] **Step 3: Implement `relayout/selection.py`**

```python
"""Reads the current primary selection via wl-paste.

Returns "" on any failure so a correction attempt with no usable selection
falls back to the typed-text buffer instead of crashing the daemon.
"""
import subprocess


def read_primary_selection() -> str:
    try:
        result = subprocess.run(
            ["wl-paste", "--primary", "--no-newline"],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

    if result.returncode != 0:
        return ""
    return result.stdout
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/bin/pytest tests/test_selection.py -v
```

Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add relayout/selection.py tests/test_selection.py
git commit -m "feat: primary selection reading via wl-paste"
```

---

### Task 7: Text injection (`inject.py`)

**Files:**
- Create: `relayout/inject.py`
- Test: `tests/test_inject.py`

**Interfaces:**
- Produces:
  - `send_backspaces(count: int) -> None` — no-ops for `count <= 0`; swallows failures if `wtype` is missing.
  - `type_text(text: str) -> None` — no-ops for empty text; swallows failures if `wtype` is missing.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_inject.py
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


def test_type_text_calls_wtype_with_text():
    with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
        type_text("привет")
        args = mock_run.call_args[0][0]
        assert args == ["wtype", "привет"]


def test_type_text_empty_string_is_noop():
    with patch("subprocess.run") as mock_run:
        type_text("")
        mock_run.assert_not_called()


def test_type_text_swallows_missing_wtype():
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        type_text("hello")  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/bin/pytest tests/test_inject.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'relayout.inject'`.

- [ ] **Step 3: Implement `relayout/inject.py`**

```python
"""Sends corrected text and backspaces via wtype.

Failures (e.g. wtype not installed) are swallowed rather than raised, so a
single failed correction never brings down the daemon's event loop.
"""
import subprocess


def send_backspaces(count: int) -> None:
    if count <= 0:
        return
    args = ["wtype"]
    for _ in range(count):
        args += ["-k", "BackSpace"]
    try:
        subprocess.run(args, check=False)
    except FileNotFoundError:
        pass


def type_text(text: str) -> None:
    if not text:
        return
    try:
        subprocess.run(["wtype", text], check=False)
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/bin/pytest tests/test_inject.py -v
```

Expected: PASS (all 5 tests).

- [ ] **Step 5: Commit**

```bash
git add relayout/inject.py tests/test_inject.py
git commit -m "feat: text/backspace injection via wtype"
```

---

### Task 8: Orchestrator (`daemon.py`)

**Files:**
- Create: `relayout/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes:
  - `relayout.keymap.LayoutPair` (`.swap_selection_text`, `.other_layout_char`, `.layout_a`)
  - `relayout.buffer.TypedTextBuffer` (`.trailing_chunk`, `.clear`)
  - `relayout.selection.read_primary_selection`
  - `relayout.inject.send_backspaces`, `relayout.inject.type_text`
- Produces: `class Daemon`:
  - `Daemon(layout_pair: LayoutPair, buffer: TypedTextBuffer)`
  - `.correct() -> None` — called each time the hotkey fires.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_daemon.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
./.venv/bin/pytest tests/test_daemon.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'relayout.daemon'`.

- [ ] **Step 3: Implement `relayout/daemon.py`**

```python
"""Wires hotkey firing to the actual correction: selection first, then buffer."""
from relayout import selection, inject
from relayout.keymap import LayoutPair
from relayout.buffer import TypedTextBuffer


class Daemon:
    def __init__(self, layout_pair: LayoutPair, buffer: TypedTextBuffer):
        self.layout_pair = layout_pair
        self.buffer = buffer

    def correct(self) -> None:
        selected = selection.read_primary_selection()
        if selected:
            corrected = self.layout_pair.swap_selection_text(selected)
            inject.type_text(corrected)
            return

        chunk = self.buffer.trailing_chunk()
        if not chunk:
            return

        corrected_chars = []
        for keycode, level, active_layout, _ in chunk:
            ch = self.layout_pair.other_layout_char(keycode, level, active_layout)
            if ch:
                corrected_chars.append(ch)

        inject.send_backspaces(len(chunk))
        inject.type_text("".join(corrected_chars))
        self.buffer.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
./.venv/bin/pytest tests/test_daemon.py -v
```

Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add relayout/daemon.py tests/test_daemon.py
git commit -m "feat: daemon orchestrator wiring selection/buffer correction"
```

---

### Task 9: Input listener and CLI entrypoint (`input_listener.py`, `cli.py`)

**Files:**
- Create: `relayout/input_listener.py`
- Create: `relayout/cli.py`

**Interfaces:**
- Consumes: `relayout.hotkey.HotkeyDetector`, `relayout.buffer.TypedTextBuffer`, `relayout.daemon.Daemon`, `relayout.config.load_config`, `relayout.keymap.LayoutPair`, `evdev`.
- Produces: `relayoutd` console script entrypoint (`relayout.cli:main`), registered in Task 1's `pyproject.toml`.

This task is glue code around real input devices and the current compositor layout, per the spec's Testing section it is **not unit-tested** — verify it manually per Step 4 below.

- [ ] **Step 1: Implement `relayout/input_listener.py`**

```python
"""evdev + hyprctl glue: feeds real keyboard events into the hotkey detector
and typed-text buffer, and queries the compositor for the active layout.

Not unit-tested (requires real input devices) — see README for manual
verification steps.
"""
import asyncio
import json
import subprocess
import time

import evdev
from evdev import ecodes

from relayout.hotkey import HotkeyDetector
from relayout.buffer import TypedTextBuffer
from relayout.keymap import LayoutPair, evdev_to_xkb_keycode


def find_keyboards() -> list[evdev.InputDevice]:
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    return [d for d in devices if ecodes.EV_KEY in d.capabilities()]


def active_layout_name(layout_pair: LayoutPair) -> str:
    """Best-effort lookup of which of the two configured layouts is active,
    via `hyprctl devices -j`. Defaults to layout_a if it can't be determined.
    """
    try:
        output = subprocess.run(
            ["hyprctl", "devices", "-j"], capture_output=True, text=True, timeout=1.0
        )
        data = json.loads(output.stdout)
        keyboards = data.get("keyboards", [])
        if not keyboards:
            return layout_pair.layout_a
        active_keymap = keyboards[0].get("active_keymap", "")
        # Hyprland reports human-readable names (e.g. "Russian"); match
        # loosely against the configured layout codes.
        if layout_pair.layout_b.lower() in active_keymap.lower():
            return layout_pair.layout_b
        return layout_pair.layout_a
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return layout_pair.layout_a


async def run(
    layout_pair: LayoutPair,
    hotkey: HotkeyDetector,
    buffer: TypedTextBuffer,
    on_trigger,
) -> None:
    keyboards = find_keyboards()
    if not keyboards:
        raise RuntimeError("no keyboard input devices found under /dev/input")

    async def read_device(device: evdev.InputDevice):
        async for event in device.async_read_loop():
            if event.type != ecodes.EV_KEY:
                continue
            key_event = evdev.categorize(event)
            key_name = key_event.keycode if isinstance(key_event.keycode, str) else key_event.keycode[0]
            event_type = {0: "up", 1: "down", 2: "down"}.get(key_event.keystate, None)
            if event_type is None:
                continue

            timestamp = time.monotonic()
            if hotkey.feed(key_name, event_type, timestamp):
                on_trigger()
                continue

            if event_type == "down":
                layout = active_layout_name(layout_pair)
                xkb_keycode = evdev_to_xkb_keycode(event.code)
                level = 1 if key_event.keystate and False else 0  # refined below
                table = layout_pair._table_a if layout == layout_pair.layout_a else layout_pair._table_b
                chars = table.get(xkb_keycode)
                displayed_char = chars[0] if chars else None
                buffer.record(xkb_keycode, 0, layout, displayed_char, timestamp)

    await asyncio.gather(*(read_device(d) for d in keyboards))
```

- [ ] **Step 2: Implement `relayout/cli.py`**

```python
"""Console-script entrypoint: builds real objects and runs the event loop."""
import asyncio

from relayout.config import load_config
from relayout.keymap import LayoutPair
from relayout.hotkey import HotkeyDetector
from relayout.buffer import TypedTextBuffer
from relayout.daemon import Daemon
from relayout import input_listener


def main() -> None:
    config = load_config()
    layout_a, layout_b = config["layouts"]["pair"]
    layout_pair = LayoutPair(layout_a, layout_b)

    hotkey = HotkeyDetector(
        key_name=config["hotkey"]["key"],
        taps=config["hotkey"]["taps"],
        window_ms=config["hotkey"]["window_ms"],
    )
    buffer = TypedTextBuffer(
        max_len=config["buffer"]["max_len"],
        idle_timeout_s=config["buffer"]["idle_timeout_s"],
    )
    daemon = Daemon(layout_pair, buffer)

    asyncio.run(
        input_listener.run(layout_pair, hotkey, buffer, on_trigger=daemon.correct)
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Fix the shift-level detection noted in Step 1**

The `level = 1 if key_event.keystate and False else 0` line above is a stub — replace it with real shift-state tracking. Track whether either `KEY_LEFTSHIFT`/`KEY_RIGHTSHIFT` is currently held (update a `shift_held` boolean on their up/down events in `read_device`, alongside the existing hotkey/buffer feeding), and use `level = 1 if shift_held else 0` when recording into the buffer.

- [ ] **Step 4: Manual verification**

Since this task has no automated tests, verify by hand:

```bash
sudo usermod -aG input $USER   # one-time, if not already done; re-login after
./.venv/bin/relayoutd &
```

1. Focus a text editor. Type `ghbdtn` (should appear as literal Latin text).
2. Select it, tap Left Shift twice quickly.
3. Confirm it becomes `привет`.
4. Clear the field. Type `ghbdtn` again, do NOT select anything, tap Left Shift twice quickly.
5. Confirm the word is deleted and retyped as `привет`.
6. Kill the background process: `kill %1`.

Note any failures for follow-up — this step is exploratory verification, not a gate with a fixed pass condition, since it depends on the actual local X11/Wayland input stack.

- [ ] **Step 5: Commit**

```bash
git add relayout/input_listener.py relayout/cli.py
git commit -m "feat: evdev input listener and relayoutd entrypoint"
```

---

### Task 10: Packaging, install script, and README

**Files:**
- Create: `packaging/relayout.service`
- Create: `scripts/install.sh`
- Modify: `README.md` (replace skeleton from Task 1)

**Interfaces:**
- Produces: a `systemd --user` unit and an idempotent install script a third party can run from a fresh clone.

- [ ] **Step 1: Write `packaging/relayout.service`**

```ini
[Unit]
Description=relayout - local keyboard layout autocorrect daemon
After=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/share/relayout/.venv/bin/relayoutd
Restart=on-failure

[Install]
WantedBy=graphical-session.target
```

- [ ] **Step 2: Write `scripts/install.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/relayout"
SERVICE_DIR="$HOME/.config/systemd/user"
CONFIG_DIR="$HOME/.config/relayout"

if ! groups "$USER" | grep -qw input; then
    echo "Adding $USER to the 'input' group (needed to read /dev/input/*)."
    sudo usermod -aG input "$USER"
    echo "You must log out and back in for this to take effect, then re-run this script."
    exit 1
fi

mkdir -p "$INSTALL_DIR" "$SERVICE_DIR" "$CONFIG_DIR"
rsync -a --exclude ".venv" --exclude ".git" ./ "$INSTALL_DIR/"

python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --quiet "$INSTALL_DIR"

cp packaging/relayout.service "$SERVICE_DIR/relayout.service"

if [ ! -f "$CONFIG_DIR/config.toml" ]; then
    cat > "$CONFIG_DIR/config.toml" <<'EOF'
[layouts]
pair = ["us", "ru"]

[hotkey]
key = "KEY_LEFTSHIFT"
taps = 2
window_ms = 400

[buffer]
max_len = 500
idle_timeout_s = 10
EOF
fi

systemctl --user daemon-reload
systemctl --user enable --now relayout

echo "relayout installed and started. Edit $CONFIG_DIR/config.toml to customize the hotkey or layout pair, then: systemctl --user restart relayout"
```

- [ ] **Step 3: Make it executable**

```bash
chmod +x scripts/install.sh
```

- [ ] **Step 4: Write the full `README.md`**

```markdown
# relayout

Local keyboard-layout autocorrect for Wayland/Hyprland, inspired by PuntoSwitcher.

Typed something in the wrong keyboard layout? Select the garbled text (or
just leave your cursor where you were typing) and double-tap Left Shift —
relayout swaps it to the correct layout's text, in place. Everything runs
locally; nothing typed is ever sent anywhere or written to disk.

## How it works

relayout uses the same XKB keymap compiler the compositor uses
(`libxkbcommon`) to know exactly which character each physical key produces
in each of two configured layouts (default: US English / Russian), and
swaps between them:

- **With a selection:** reads the current primary selection and retypes it
  in the other layout.
- **Without a selection:** keeps a small in-memory buffer of recently typed
  keys (never persisted), and retypes the last word/phrase since the last
  punctuation or whitespace.

## Requirements

- Linux, Wayland, a compositor exposing `hyprctl` (Hyprland)
- Python 3.11+
- `wl-clipboard` and `wtype` (both already installed on Omarchy by default)
- Membership in the `input` group (the install script sets this up)

## Install

```bash
git clone https://github.com/airenare/relayout.git
cd relayout
./scripts/install.sh
```

If you weren't already in the `input` group, the script will add you to it
and ask you to log out/in, then re-run it.

## Configuration

Edit `~/.config/relayout/config.toml`:

```toml
[layouts]
pair = ["us", "ru"]       # any two XKB layout codes, e.g. ["us", "de"]

[hotkey]
key = "KEY_LEFTSHIFT"     # any evdev key name
taps = 2                  # number of taps to trigger
window_ms = 400           # max milliseconds between taps

[buffer]
max_len = 500             # max buffered keystrokes
idle_timeout_s = 10       # buffer clears after this many seconds idle
```

Then: `systemctl --user restart relayout`

## Development

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/pytest
```

## License

MIT
```

- [ ] **Step 5: Commit**

```bash
git add packaging/relayout.service scripts/install.sh README.md
git commit -m "docs: packaging, install script, and full README"
```

---

### Task 11: Create the public GitHub repository and push

**Files:** none (repository operations only).

- [ ] **Step 1: Create the public repo**

```bash
gh repo create airenare/relayout --public --source=. --remote=origin --description "Local keyboard-layout autocorrect for Wayland/Hyprland, inspired by PuntoSwitcher"
```

- [ ] **Step 2: Push**

```bash
git push -u origin HEAD
```

- [ ] **Step 3: Verify**

```bash
gh repo view airenare/relayout --web=false
```

Expected: shows the repo with the pushed commits and description; confirm on github.com that it's public.

---

## Self-Review

**Spec coverage:**
- Purpose (selection + last-word/phrase correction, local-only) → Tasks 2, 4, 6, 7, 8, 9.
- Non-goals (single layout pair, no GUI, Wayland-only) → reflected in Global Constraints and Task 5/10 defaults.
- Keymap resolver, hotkey detector, typed-text buffer, input listener, selection reader, text injector, orchestrator, config → Tasks 2, 3, 4, 9, 6, 7, 8, 5 respectively, matching the spec's component list one-to-one.
- Installation (input group, systemd unit) → Task 10.
- Testing split (pure logic unit-tested, glue manually verified) → reflected in every task's Interfaces/Steps.

**Placeholder scan:** none found — the one stub noted in Task 9 Step 1 (shift-level detection) is explicitly called out and fixed in Task 9 Step 3 with real code, not left as a TODO.

**Type consistency:** `LayoutPair.other_layout_char(keycode, level, current_layout)` and `TypedTextBuffer` entries `(keycode, level, active_layout, displayed_char)` match between Tasks 2, 4, and 8. `load_config()`'s returned dict shape matches what `cli.py` (Task 9) reads (`config["layouts"]["pair"]`, `config["hotkey"]["key"|"taps"|"window_ms"]`, `config["buffer"]["max_len"|"idle_timeout_s"]`).

**Review Focus coverage:**
- Unmapped characters pass through unchanged → `test_layout_pair_swap_selection_text_passthrough_for_shared_chars` (Task 2).
- Empty selection + empty buffer no-ops → `test_correct_noops_when_nothing_to_correct` (Task 8).
- Shift+letter doesn't false-trigger → `test_other_key_between_taps_resets_sequence` (Task 3).
- Idle timeout actually clears stale buffer → `test_idle_timeout_clears_buffer` (Task 4).
- Missing `wl-paste`/`wtype` fails gracefully → `test_returns_empty_string_when_wl_paste_missing` (Task 6), `test_type_text_swallows_missing_wtype` (Task 7).
