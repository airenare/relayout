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
