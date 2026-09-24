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
