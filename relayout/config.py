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
