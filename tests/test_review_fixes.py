"""Fixes from the marketplace security review."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from relayout import inject
from relayout.daemon import NOTIFY_KEPT, NOTIFY_LEARNED

from .test_autocorrect import detector, make, pair, type_text, word_and_space  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


# --- manual corrections obey suppression ------------------------------------

def typed_ghbdtn(buf, pair):
    type_text(buf, pair, "us", "ghbdtn")


def test_hotkey_does_nothing_in_an_excluded_app(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    d.set_app("keepassxc")        # excluded by default in make()
    typed_ghbdtn(buf, pair)
    assert d.correct() is False
    assert fx.calls == []


def test_hotkey_does_nothing_on_the_lock_screen(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path, locked=lambda: True)
    typed_ghbdtn(buf, pair)
    assert d.correct() is False
    assert fx.calls == []


def test_hotkey_does_nothing_over_an_excluded_layer(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path, exclude_layers=("omarchy-polkit",))
    d.set_layer("omarchy-polkit", True)
    typed_ghbdtn(buf, pair)
    assert d.correct() is False and fx.calls == []


def test_cli_flip_reports_when_it_did_not_apply(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    d.set_app("keepassxc")
    typed_ghbdtn(buf, pair)
    assert d.handle_command("flip").startswith("error:")
    assert fx.calls == []


def test_hotkey_still_works_elsewhere(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    typed_ghbdtn(buf, pair)
    assert d.correct() is True
    assert ("switch", "ru") in fx.calls


# --- a correction never lands in another window -------------------------------

def test_stale_focus_serial_drops_an_auto_correction(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    started = d.focus_serial
    d.set_window("0xabc")                        # focus moved while it was pending
    assert d.auto_correct(chunk, spaces, 0.0, started) is False
    assert fx.calls == []


def test_stale_focus_serial_drops_the_hotkey(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    typed_ghbdtn(buf, pair)
    started = d.focus_serial
    d.set_app("firefox")
    assert d.correct(started) is False and fx.calls == []


def test_layer_surfaces_count_as_a_focus_change(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    before = d.focus_serial
    d.set_layer("rofi", True)
    assert d.focus_serial != before


def test_live_probe_catches_a_focus_change_whose_event_is_late(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path, window_probe=lambda: "0xbbb")
    d.set_window("aaa")                          # what the events told us
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    assert d.auto_correct(chunk, spaces, 0.0, d.focus_serial) is False
    assert fx.calls == []


def test_same_window_proceeds(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path, window_probe=lambda: "0xAAA")
    d.set_window("aaa")                          # address formats are normalised
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    assert d.auto_correct(chunk, spaces, 0.0, d.focus_serial) is True


def test_changing_window_forgets_the_typed_word_and_the_undo(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    d.set_window("aaa")
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    d.auto_correct(chunk, spaces)
    assert d.last is not None
    d.set_window("bbb")
    assert d.last is None and buf.last_word() == ([], 0)


# --- focus stays bound through every input stage ------------------------------

def _drifting(pair, detector, tmp_path, stage):
    """A daemon whose focus moves to another window right after ``stage``."""
    win = {"now": "0xaaa"}
    d, buf, fx = make(pair, detector, tmp_path, window_probe=lambda: win["now"])
    d.set_window("0xaaa")
    orig = getattr(fx, stage)

    def hooked(*a, **k):
        r = orig(*a, **k)
        win["now"] = "0xbbb"
        return r

    setattr(fx, stage, hooked)
    return d, buf, fx


def test_focus_change_after_backspaces_stops_the_typing(pair, detector, tmp_path):
    d, buf, fx = _drifting(pair, detector, tmp_path, "send_backspaces")
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    assert d.auto_correct(chunk, spaces, 0.0, d.focus_serial) is False
    assert [c[0] for c in fx.calls] == ["bs"]          # no text, no switch
    assert d.last is None                              # nothing to undo later


def test_focus_change_after_typing_stops_the_layout_switch(pair, detector, tmp_path):
    d, buf, fx = _drifting(pair, detector, tmp_path, "type_text")
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    d.auto_correct(chunk, spaces, 0.0, d.focus_serial)
    assert ("switch", "ru") not in fx.calls


def test_replay_stages_are_each_guarded(pair, detector, tmp_path):
    win = {"now": "0xaaa"}
    log = []

    class Replayer:
        def backspaces(self, n):
            log.append("bs")
            win["now"] = "0xbbb"        # focus leaves while backspaces go out

        def replay(self, entries, spaces):
            log.append("replay")

    d, buf, fx = make(pair, detector, tmp_path, window_probe=lambda: win["now"],
                      replayer=Replayer())
    d.set_window("0xaaa")
    chunk, spaces = word_and_space(buf, pair, "us", "ghbdtn")
    d.auto_correct(chunk, spaces, 0.0, d.focus_serial)
    assert log == ["bs"] and ("switch", "ru") not in fx.calls


def test_toggle_also_stops_when_focus_moves(pair, detector, tmp_path):
    win = {"now": "0xaaa"}
    d, buf, fx = make(pair, detector, tmp_path, window_probe=lambda: win["now"])
    d.set_window("0xaaa")
    typed_ghbdtn(buf, pair)
    assert d.correct() is True
    win["now"] = "0xbbb"
    before = list(fx.calls)
    assert d.correct() is False                # window moved: nothing is sent
    assert fx.calls == before


# --- typed text never goes through process arguments --------------------------

def test_wtype_gets_the_text_on_stdin(monkeypatch):
    seen = {}

    def fake_run(args, **kw):
        seen["args"], seen["input"] = args, kw.get("input")

    monkeypatch.setattr(inject.subprocess, "run", fake_run)
    inject.type_text("секрет пароль")
    assert seen["args"] == ["wtype", "-"]
    assert seen["input"] == "секрет пароль".encode()
    assert "секрет" not in " ".join(seen["args"])


def test_notifications_never_contain_typed_text(pair, detector, tmp_path):
    sent = []
    d, buf, fx = make(pair, detector, tmp_path, notify=sent.append)
    for _ in range(2):
        buf.clear()
        d.last = None
        type_text(buf, pair, "ru", "туче")
        d.correct()
    assert sent == [NOTIFY_LEARNED]
    for word in ("next", "туче"):
        assert all(word not in m for m in sent)


def test_keep_notification_is_generic_too(pair, detector, tmp_path):
    sent = []
    d, buf, fx = make(pair, detector, tmp_path, notify=sent.append)
    d.store.words["ща"] = "ru"
    for _ in range(2):
        buf.clear()
        d.last = None
        type_text(buf, pair, "ru", "ща")
        d.correct()
    assert sent == [NOTIFY_KEPT]


# --- the widget runs only the installed CLI -----------------------------------

def test_widget_never_runs_relayout_from_path():
    qml = (ROOT / "BarWidget.qml").read_text()
    assert 'command: ["relayout"' not in qml
    assert '"relayout", "subscribe"' not in qml
    assert "root.cli" in qml and ".local/share/relayout/.venv/bin/relayout" in qml


def test_widget_sends_rule_words_on_stdin_not_argv():
    qml = (ROOT / "BarWidget.qml").read_text()
    assert 'root.run(["rules"' not in qml
    assert "runPrivate(" in qml and '"--stdin"' in qml


def test_cli_stdin_mode_reads_the_command_from_stdin(monkeypatch, tmp_path):
    import io
    import socket as _socket
    from relayout import ctl

    sent = []

    class FakeSock:
        def connect(self, p): pass
        def sendall(self, b): sent.append(b)
        def makefile(self, *a, **k): return io.StringIO("ok\n")

    monkeypatch.setattr(ctl.socket, "socket", lambda *a: FakeSock())
    monkeypatch.setattr(ctl.sys, "stdin", io.StringIO("rules add секрет ru\n"))
    assert ctl.main(["--stdin"]) == 0
    assert sent == ["rules add секрет ru\n".encode()]


def test_installer_builds_in_staging_before_touching_the_live_runtime():
    text = (ROOT / "scripts" / "install.sh").read_text()
    stage_pip = text.index('"${PIP[@]}" install --quiet --no-deps --no-build-isolation --no-index')
    smoke = text.index('smoke "$STAGE"')
    swap = text.index('mv -T "$STAGE" "$INSTALL_DIR"')
    assert stage_pip < smoke < swap
    assert 'venv --clear "$INSTALL_DIR' not in text       # never clears the live venv
    assert text.index("rsync") < swap                      # code copied to staging only
    assert 'rsync -a --exclude ".venv" --exclude ".git" --exclude "__pycache__" \\\n    --exclude "*.egg-info" --exclude "state.json" "$SRC/" "$STAGE/"' in text


# --- installer: ownership checks without following links ----------------------

pytestmark_install = pytest.mark.skipif(
    shutil.which("rsync") is None, reason="install.sh needs rsync"
)


def install_check(home, *args):
    env = {**os.environ, "RELAYOUT_HOME": str(home)}
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / "install.sh"), "--check", *args],
        env=env, capture_output=True, text=True,
    )


def paths(home):
    base = Path(home)
    return (
        base / ".local/share/relayout",
        base / ".config/systemd/user/relayout.service",
        base / ".local/bin/relayout",
    )


@pytestmark_install
def test_clean_home_passes(tmp_path):
    assert install_check(tmp_path).returncode == 0


@pytestmark_install
def test_foreign_command_is_refused_then_forced(tmp_path):
    _, _, cmd = paths(tmp_path)
    cmd.parent.mkdir(parents=True)
    cmd.write_text("not ours")
    r = install_check(tmp_path)
    assert r.returncode == 1 and "refusing to overwrite" in r.stderr
    assert install_check(tmp_path, "--force").returncode == 0


@pytestmark_install
def test_symlinked_service_is_refused_even_if_target_has_the_marker(tmp_path):
    _, svc, _ = paths(tmp_path)
    svc.parent.mkdir(parents=True)
    target = tmp_path / "elsewhere.service"
    target.write_text("# managed-by: relayout (scripts/install.sh)\n[Unit]\n")
    svc.symlink_to(target)
    r = install_check(tmp_path)
    assert r.returncode == 1 and "refusing to overwrite" in r.stderr


@pytestmark_install
def test_command_link_to_something_else_is_refused(tmp_path):
    _, _, cmd = paths(tmp_path)
    cmd.parent.mkdir(parents=True)
    cmd.symlink_to("/usr/bin/true")
    assert install_check(tmp_path).returncode == 1


@pytestmark_install
def test_own_command_link_and_unit_are_accepted(tmp_path):
    inst, svc, cmd = paths(tmp_path)
    (inst / ".venv/bin").mkdir(parents=True)
    (inst / "pyproject.toml").write_text('[project]\nname = "relayout"\n')
    svc.parent.mkdir(parents=True)
    svc.write_text("# managed-by: relayout (scripts/install.sh)\n")
    cmd.parent.mkdir(parents=True)
    cmd.symlink_to(inst / ".venv/bin/relayout")
    assert install_check(tmp_path).returncode == 0


@pytestmark_install
def test_legacy_unit_without_marker_is_still_ours(tmp_path):
    _, svc, _ = paths(tmp_path)
    svc.parent.mkdir(parents=True)
    svc.write_text("[Service]\nExecStart=%h/.local/share/relayout/.venv/bin/relayoutd\n")
    assert install_check(tmp_path).returncode == 0


@pytestmark_install
def test_symlinked_install_dir_is_never_installed_through(tmp_path):
    inst, _, _ = paths(tmp_path)
    inst.parent.mkdir(parents=True)
    target = tmp_path / "other"
    target.mkdir()
    inst.symlink_to(target)
    for extra in ((), ("--force",)):
        r = install_check(tmp_path, *extra)
        assert r.returncode == 1 and "symlink" in r.stderr
