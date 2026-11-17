"""Runs everything: control socket, Hyprland event watcher, keyboard listener."""
from __future__ import annotations

import asyncio
import logging

from relayout import hypr, input_listener
from relayout.control import ControlServer

logger = logging.getLogger(__name__)


async def watch_hyprland(daemon, lookup: hypr.HyprLayout) -> None:
    """Follow the compositor's event socket; reconnect if it drops."""
    while True:
        path = hypr.event_socket_path()
        try:
            if path is None:
                raise OSError("no running Hyprland instance")
            reader, writer = await asyncio.open_unix_connection(str(path))
        except OSError as exc:
            lookup.events_connected = False
            logger.debug("hyprland events unavailable: %s", exc)
            await asyncio.sleep(3)
            continue
        lookup.events_connected = True
        lookup.invalidate()
        daemon.set_app(hypr.active_window_class())
        try:
            while line := await reader.readline():
                name, _, data = line.decode("utf-8", "replace").rstrip("\n").partition(">>")
                if name == "activewindow":
                    daemon.set_app(data.split(",", 1)[0])
                elif name == "openlayer":
                    daemon.set_layer(data, True)
                elif name == "closelayer":
                    daemon.set_layer(data, False)
                elif name == "activelayout":
                    lookup.invalidate()
                    daemon.buffer.clear()
                    daemon.on_change()
        except (ConnectionError, OSError):
            pass
        finally:
            lookup.events_connected = False
            writer.close()
        await asyncio.sleep(1)


async def run(daemon, lookup, hotkey) -> None:
    server = await ControlServer(daemon).start()
    watcher = asyncio.create_task(watch_hyprland(daemon, lookup))
    try:
        await input_listener.run(daemon, lookup, hotkey)
    finally:
        watcher.cancel()
        server.close()
