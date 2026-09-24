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
