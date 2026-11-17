"""Console-script entrypoint (`relayoutd`): builds real objects and runs the loop."""
import asyncio
import logging

from relayout import app
from relayout.buffer import TypedTextBuffer
from relayout.config import load_config
from relayout.daemon import Daemon, notify_send
from relayout.detect import Detector, Params
from relayout.hotkey import HotkeyDetector
from relayout.hypr import CachedLock, HyprLayout
from relayout.output import KeyReplayer
from relayout.keymap import LayoutPair
from relayout.rules import Store

logger = logging.getLogger("relayout")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = load_config()
    layout_a, layout_b = config["layouts"]["pair"]
    pair = LayoutPair(layout_a, layout_b)
    auto = config["auto"]

    detector = Detector.for_layouts(
        layout_a, layout_b, Params(threshold=float(auto["threshold"]))
    )
    if detector is None:
        logger.warning(
            "no word list for %s/%s: auto-correction is unavailable, "
            "the hotkey still works (see relayout/data/README.md)",
            layout_a, layout_b,
        )

    hotkey = HotkeyDetector(
        key_name=config["hotkey"]["key"],
        taps=config["hotkey"]["taps"],
        window_ms=config["hotkey"]["window_ms"],
    )
    buffer = TypedTextBuffer(
        max_len=config["buffer"]["max_len"],
        idle_timeout_s=config["buffer"]["idle_timeout_s"],
    )
    method = config["output"]["method"]
    replayer = KeyReplayer.open() if method in ("auto", "uinput") else None
    if method == "uinput" and replayer is None:
        logger.warning("output.method = uinput but /dev/uinput is not writable; using wtype")
    logger.info("retyping with %s", "uinput key replay" if replayer else "wtype")
    lookup = HyprLayout(pair)
    store = Store(default_excluded=auto["exclude_apps"], default_auto=bool(auto["enabled"]))
    daemon = Daemon(
        pair,
        buffer,
        detector=detector,
        store=store,
        hypr=lookup,
        learn_threshold=int(auto["learn_threshold"]),
        exclude_layers=tuple(auto["exclude_layers"]),
        notify=notify_send if auto["notify"] else None,
        replayer=replayer,
        locked=CachedLock(),
    )
    asyncio.run(app.run(daemon, lookup, hotkey))


if __name__ == "__main__":
    main()
