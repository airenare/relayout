"""Hyprland glue: instance discovery, hyprctl, the event socket, and a cached
view of the active keyboard layout.

The daemon runs as a systemd user service, which may not have
HYPRLAND_INSTANCE_SIGNATURE in its environment, so the live instance is
discovered from $XDG_RUNTIME_DIR/hypr when the variable is missing.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import time
from pathlib import Path

from relayout.keymap import LayoutPair
from relayout.layout_resolver import resolve_active_layout

logger = logging.getLogger(__name__)


def _runtime_hypr_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "hypr"


def _alive(sock_path: Path) -> bool:
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(0.3)
    try:
        s.connect(str(sock_path))
        return True
    except OSError:
        return False
    finally:
        s.close()


def find_signature() -> str | None:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig:
        return sig
    base = _runtime_hypr_dir()
    try:
        dirs = sorted(
            (d for d in base.iterdir() if (d / ".socket2.sock").exists()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    for d in dirs:
        if _alive(d / ".socket.sock"):
            return d.name
    return None


def event_socket_path() -> Path | None:
    sig = find_signature()
    return _runtime_hypr_dir() / sig / ".socket2.sock" if sig else None


def hyprctl(*args: str, timeout: float = 1.0) -> str:
    env = dict(os.environ)
    sig = find_signature()
    if sig:
        env["HYPRLAND_INSTANCE_SIGNATURE"] = sig
    try:
        out = subprocess.run(
            ["hyprctl", *args], capture_output=True, text=True, timeout=timeout, env=env
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("hyprctl %s failed: %s", " ".join(args), exc)
        return ""
    return out.stdout


def hyprctl_json(*args: str) -> dict:
    try:
        data = json.loads(hyprctl(*args, "-j"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def session_locked(monitors: list | None = None) -> bool:
    """True while the compositor holds a session lock (Omarchy's lock screen).

    Hyprland reports no lock state directly; like Omarchy's own helper, treat
    LOCK in a monitor's solitaryBlockedBy as locked.
    """
    if monitors is None:
        try:
            monitors = json.loads(hyprctl("monitors", "-j"))
        except json.JSONDecodeError:
            return False
    if not isinstance(monitors, list):
        return False
    return any(
        isinstance(m, dict) and "LOCK" in (m.get("solitaryBlockedBy") or [])
        for m in monitors
    )


class CachedLock:
    """session_locked() behind a short cache: it forks hyprctl."""

    def __init__(self, ttl_s: float = 1.0, probe=session_locked):
        self._ttl_s = ttl_s
        self._probe = probe
        self._value = False
        self._at = float("-inf")

    def __call__(self) -> bool:
        now = time.monotonic()
        if now - self._at > self._ttl_s:
            self._value = bool(self._probe())
            self._at = now
        return self._value


def active_window_class() -> str:
    return str(hyprctl_json("activewindow").get("class", ""))


def layout_index(devices: dict, layout: str) -> int | None:
    """Index of ``layout`` in the main keyboard's layout list, if present."""
    keyboards = devices.get("keyboards")
    if not isinstance(keyboards, list) or not keyboards:
        return None
    kb = next((k for k in keyboards if isinstance(k, dict) and k.get("main")), keyboards[0])
    codes = [c.strip() for c in str(kb.get("layout", "")).split(",")]
    return codes.index(layout) if layout in codes else None


class HyprLayout:
    """Active layout of the pair, cached; invalidated by compositor events."""

    FALLBACK_TTL_S = 0.5  # while the event socket is not connected
    EVENT_TTL_S = 60.0

    def __init__(self, pair: LayoutPair):
        self.pair = pair
        self.events_connected = False
        self._layout: str | None = None
        self._at = 0.0

    def get(self) -> str:
        ttl = self.EVENT_TTL_S if self.events_connected else self.FALLBACK_TTL_S
        now = time.monotonic()
        if self._layout is None or now - self._at > ttl:
            self._layout = resolve_active_layout(hyprctl_json("devices"), self.pair)
            self._at = now
        return self._layout

    def invalidate(self) -> None:
        self._layout = None

    def switch(self, layout: str) -> None:
        """Make ``layout`` the active one on all keyboards."""
        index = layout_index(hyprctl_json("devices"), layout)
        if index is None:
            logger.warning("layout %r is not configured in Hyprland", layout)
            return
        hyprctl("switchxkblayout", "all", str(index))
        self._layout = layout
        self._at = time.monotonic()
