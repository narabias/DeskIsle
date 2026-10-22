"""Local agent server: JSON lines over a per-user named pipe (QLocalServer).

Only the current Windows user can connect (``UserAccessOption``); nothing
listens on the network.  Every request runs on the Qt thread through
:class:`deskisle.agent.commands.Commands`.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .. import __version__
from . import PROTOCOL_VERSION
from .client import pipe_name
from .commands import Commands

log = logging.getLogger("deskisle.agent")
MAX_LINE = 8 * 1024 * 1024


def _json_default(value):
    try:
        from PySide6.QtGui import QColor

        if isinstance(value, QColor):
            return value.name()
    except ImportError:
        pass
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, tuple)):
        return list(value)
    return str(value)


class _Connection(QObject):
    def __init__(self, socket: QLocalSocket, server: "AgentServer") -> None:
        super().__init__(server)
        self.socket = socket
        self.server = server
        self.buffer = b""
        self.alive = True
        socket.setParent(self)
        socket.readyRead.connect(self._read)
        socket.disconnected.connect(self._gone)

    def _read(self) -> None:
        self.buffer += bytes(self.socket.readAll().data())
        if len(self.buffer) > MAX_LINE and b"\n" not in self.buffer:
            self._send({"id": None, "ok": False, "error": {"code": "too_large", "message": "request too large"}})
            self.socket.disconnectFromServer()
            return
        while b"\n" in self.buffer:
            line, _sep, self.buffer = self.buffer.partition(b"\n")
            if line.strip():
                self._request(line)

    def _request(self, line: bytes) -> None:
        try:
            message = json.loads(line.decode("utf-8"))
            if not isinstance(message, dict):
                raise ValueError("request must be an object")
        except (UnicodeDecodeError, ValueError) as exc:
            self._send({"id": None, "ok": False, "error": {"code": "bad_json", "message": str(exc)}})
            return
        rid = message.get("id")
        cmd = str(message.get("cmd") or message.get("command") or "")
        args = message.get("args")
        log.info("agent: %s", cmd)
        self.server.commands.handle(cmd, args if args is not None else {},
                                    lambda ok, payload: self._reply(rid, ok, payload))

    def _reply(self, rid, ok: bool, payload) -> None:
        self._send({"id": rid, "ok": bool(ok), ("result" if ok else "error"): payload})

    def _send(self, message: dict) -> None:
        if not self.alive:
            return
        try:
            data = json.dumps(message, ensure_ascii=False, default=_json_default) + "\n"
        except (TypeError, ValueError) as exc:
            data = json.dumps({"id": message.get("id"), "ok": False,
                               "error": {"code": "internal", "message": "unserialisable result: {0}".format(exc)}})
            data += "\n"
        self.socket.write(data.encode("utf-8"))
        self.socket.flush()

    def _gone(self) -> None:
        self.alive = False
        self.server.forget(self)
        self.deleteLater()


class AgentServer(QObject):
    def __init__(self, app, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self.commands = Commands(app, self)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self.error = ""
        self._connections: list[_Connection] = []

    @property
    def name(self) -> str:
        return pipe_name(bool(getattr(self.app, "demo", False)))

    def listen(self) -> bool:
        name = self.name
        if not self.server.listen(name):
            # A stale socket file after a crash (Unix) - the instance lock already
            # guarantees that no other DeskIsle of this user is running.
            QLocalServer.removeServer(name)
            if not self.server.listen(name):
                self.error = self.server.errorString()
                return False
        self.error = ""
        self._write_info()
        log.info("agent pipe listening on %s", self.full_name())
        return True

    def _info_path(self) -> Path:
        return Path(self.app.root) / "agent.json"

    def _write_info(self) -> None:
        try:
            path = self._info_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"pipe": self.full_name(), "name": self.name, "pid": os.getpid(),
                                        "version": __version__, "protocol": PROTOCOL_VERSION}, indent=2),
                            encoding="utf-8")
        except OSError:
            log.exception("could not write agent.json")

    def full_name(self) -> str:
        return self.server.fullServerName() if self.server.isListening() else ""

    def is_listening(self) -> bool:
        return self.server.isListening()

    def _accept(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is not None:
                self._connections.append(_Connection(socket, self))

    def forget(self, connection: _Connection) -> None:
        if connection in self._connections:
            self._connections.remove(connection)

    def close(self) -> None:
        for connection in list(self._connections):
            connection.alive = False
            connection.socket.abort()
        self._connections.clear()
        self.server.close()
        try:
            path = self._info_path()
            if path.is_file() and json.loads(path.read_text(encoding="utf-8")).get("pid") == os.getpid():
                path.unlink()
        except (OSError, ValueError):
            pass


__all__ = ["AgentServer"]
