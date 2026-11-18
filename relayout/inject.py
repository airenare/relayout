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
    """Type ``text``. It goes to wtype on stdin ("-"), never as an argument:
    process arguments are readable by other local users (`ps`, /proc)."""
    if not text:
        return
    try:
        subprocess.run(["wtype", "-"], input=text.encode("utf-8"), check=False)
    except FileNotFoundError:
        pass
