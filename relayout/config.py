"""Loads ~/.config/relayout/config.toml, merged over built-in defaults."""
import tomllib
from pathlib import Path

DEFAULT_CONFIG = {
    "layouts": {"pair": ["us", "ru"]},
    "hotkey": {"key": "KEY_LEFTSHIFT", "taps": 2, "window_ms": 400},
    "buffer": {"max_len": 500, "idle_timeout_s": 10.0},
    "output": {
        # How a correction is retyped: "uinput" replays the same physical keys
        # on a virtual keyboard (works in any app), "wtype" injects text via
        # the Wayland virtual-keyboard protocol, "auto" = uinput if available.
        "method": "auto",
    },
    "auto": {
        # Correct the last word automatically when you press Space.
        "enabled": True,
        # Log-probability lead (nats) the other layout needs to win.
        "threshold": 4.0,
        # Manual flips of the same word (or undos of an auto-correction)
        # before relayout remembers it for good.
        "learn_threshold": 2,
        "notify": True,
        # Window classes, as in `hyprctl activewindow`.
        "exclude_apps": [
            "org.keepassxc.KeePassXC", "1Password", "Bitwarden",
            "gcr-prompter", "pinentry-qt", "pinentry-gtk",
        ],
        # Shell popups (layer-shell namespaces), e.g. the polkit prompt.
        "exclude_layers": ["omarchy-polkit"],
    },
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
