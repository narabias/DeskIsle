"""Shared bits of the widget services."""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import Property, QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

log = logging.getLogger("deskisle.services")
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36 DeskIsle/2.0")


class NullService(QObject):
    """Placeholder when a back-end failed to load (its widget shows a hint)."""

    changed = Signal()

    def __init__(self, name: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = name

    available = Property(bool, lambda self: False, constant=True)
    name = Property(str, lambda self: self._name, constant=True)


class Http(QObject):
    """Tiny async JSON GET helper on top of QNetworkAccessManager."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._pending: set = set()

    def get_json(self, url: str, callback, timeout_ms: int = 12000, headers: dict | None = None) -> None:
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
        request.setRawHeader(b"Accept", b"application/json")
        for key, value in (headers or {}).items():
            request.setRawHeader(key.encode(), str(value).encode())
        request.setTransferTimeout(timeout_ms)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        reply = self._manager.get(request)
        self._pending.add(reply)

        def done(reply=reply) -> None:
            self._pending.discard(reply)
            data, error = None, ""
            if reply.error() != QNetworkReply.NetworkError.NoError:
                error = reply.errorString() or "网络错误"
            else:
                try:
                    data = json.loads(bytes(reply.readAll()).decode("utf-8", "replace"))
                except ValueError:
                    error = "返回的数据无法解析"
            reply.deleteLater()
            try:
                callback(data, error)
            except Exception:
                log.exception("http callback")

        reply.finished.connect(done)

    def abort_all(self) -> None:
        for reply in list(self._pending):
            try:
                reply.abort()
            except RuntimeError:
                pass
        self._pending.clear()


__all__ = ["Http", "NullService", "USER_AGENT"]
