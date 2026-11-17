"""Unix-socket control server (one line in, one line out) for the CLI and widget."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path


def socket_path() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "relayout.sock"


class ControlServer:
    def __init__(self, daemon, path: Path | None = None):
        self.daemon = daemon
        self.path = path or socket_path()
        self._subscribers: set[asyncio.StreamWriter] = set()
        daemon.on_change = self.publish

    def publish(self) -> None:
        line = (self.daemon.handle_command("status") + "\n").encode()
        for writer in list(self._subscribers):
            try:
                writer.write(line)
            except (ConnectionError, RuntimeError):
                self._subscribers.discard(writer)

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=2.0)
            line = raw.decode("utf-8", "replace").strip()
            if line == "subscribe":
                self._subscribers.add(writer)
                self.publish()
                await reader.read()  # until the client disconnects
                return
            writer.write((self.daemon.handle_command(line) + "\n").encode())
            await writer.drain()
        except (asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            self._subscribers.discard(writer)
            writer.close()

    async def start(self) -> asyncio.AbstractServer:
        if self.path.exists():
            # Refuse to start twice; clear the socket only if nobody answers.
            try:
                _, w = await asyncio.open_unix_connection(str(self.path))
                w.close()
                raise RuntimeError(f"relayout is already running ({self.path})")
            except (ConnectionRefusedError, FileNotFoundError):
                self.path.unlink(missing_ok=True)
        old = os.umask(0o177)
        try:
            return await asyncio.start_unix_server(self._client, str(self.path))
        finally:
            os.umask(old)
