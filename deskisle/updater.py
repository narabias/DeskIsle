"""Update checks against the GitHub releases of ``narabias/DeskIsle``.

Network use is deliberately small and explicit:

* one JSON request to the GitHub Releases API (automatic at most about once a
  day, or when the user clicks “检查更新”), and
* the installer download, only after the user clicks “下载并安装”.

No user data is sent beyond ordinary HTTP headers.  The installer is verified
against the SHA-256 published with the release before it is started, and the
user's layout, rules and preferences (``%LOCALAPPDATA%\\DeskIsle``) live outside
the install directory, so updating never rewrites them.  A layout snapshot is
still saved right before the installer starts, as an extra safety net.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxyFactory, QNetworkReply, QNetworkRequest

from . import __version__

REPO = "narabias/DeskIsle"
API_LATEST = "https://api.github.com/repos/{0}/releases/latest".format(REPO)
RELEASES_PAGE = "https://github.com/{0}/releases".format(REPO)
ASSET_PATTERN = re.compile(r"^DeskIsle-Setup-(?P<version>[0-9A-Za-z.+-]+)-x64\.exe$", re.IGNORECASE)
ALLOWED_HOSTS = frozenset({
    "github.com",
    "api.github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
})
CHECK_INTERVAL_SECONDS = 20 * 3600
STARTUP_DELAY_MS = 15_000
REQUEST_TIMEOUT_MS = 15_000
DOWNLOAD_STALL_TIMEOUT_MS = 60_000
MAX_INSTALLER_BYTES = 700 * 1024 * 1024
STATE_FILENAME = "update.json"
INSTALLER_ARGS = (
    "/SILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/SP-",
    "/CLOSEAPPLICATIONS",
    "/DESKISLERELAUNCH=1",
)
_SHA256 = re.compile(r"\b([0-9a-fA-F]{64})\b")


# Versions -------------------------------------------------------------------
def parse_version(text: str) -> tuple[tuple[int, ...], int, str]:
    """Sortable key for tags such as ``v1.2.0`` or ``1.3.0-beta.2``.

    A final release sorts after its pre-releases (``1.3.0 > 1.3.0-beta``).
    """
    value = str(text or "").strip()
    if value[:1] in ("v", "V"):
        value = value[1:]
    value = value.split("+", 1)[0]
    main, _sep, pre = value.partition("-")
    numbers: list[int] = []
    for part in main.split("."):
        digits = re.match(r"\d+", part)
        numbers.append(int(digits.group(0)) if digits else 0)
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers[:6]), (0 if pre else 1), pre.lower()


def is_newer(candidate: str, current: str = __version__) -> bool:
    if not str(candidate or "").strip():
        return False
    return parse_version(candidate) > parse_version(current)


def display_version(text: str) -> str:
    value = str(text or "").strip()
    return value[1:] if value[:1] in ("v", "V") else value


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    title: str = ""
    notes: str = ""
    page_url: str = RELEASES_PAGE
    published_at: str = ""
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    sha256: str = ""
    sha256_url: str = ""

    @property
    def has_installer(self) -> bool:
        return bool(self.asset_name and self.asset_url)

    @property
    def size_text(self) -> str:
        if self.asset_size <= 0:
            return ""
        return "{0:.1f} MB".format(self.asset_size / (1024 * 1024))

    @property
    def published_text(self) -> str:
        return (self.published_at or "").replace("T", " ").replace("Z", "")[:16]


def _host_allowed(url: str | QUrl) -> bool:
    qurl = url if isinstance(url, QUrl) else QUrl(str(url))
    return qurl.scheme() == "https" and qurl.host().lower() in ALLOWED_HOSTS


def parse_release(payload: Mapping[str, Any]) -> ReleaseInfo:
    """Turn a GitHub ``releases/latest`` JSON object into :class:`ReleaseInfo`."""
    if not isinstance(payload, Mapping):
        raise ValueError("发布信息格式不正确。")
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("发布信息中缺少版本号。")
    release = ReleaseInfo(
        version=display_version(tag),
        tag=tag,
        title=str(payload.get("name") or tag),
        notes=str(payload.get("body") or "").strip(),
        page_url=str(payload.get("html_url") or RELEASES_PAGE),
        published_at=str(payload.get("published_at") or ""),
    )
    if not _host_allowed(release.page_url):
        release.page_url = RELEASES_PAGE
    assets = payload.get("assets") or []
    installer = None
    # Only accept the installer built for this tag: installing a different
    # version would make the same update reappear forever.
    wanted = parse_version(release.version)
    for asset in assets:
        if not isinstance(asset, Mapping):
            continue
        match = ASSET_PATTERN.match(str(asset.get("name") or ""))
        if match and parse_version(match.group("version")) == wanted:
            installer = asset
            break
    if installer is not None:
        name = str(installer.get("name") or "")
        url = str(installer.get("browser_download_url") or "")
        if _host_allowed(url):
            release.asset_name = name
            release.asset_url = url
            try:
                release.asset_size = int(installer.get("size") or 0)
            except (TypeError, ValueError):
                release.asset_size = 0
            digest = str(installer.get("digest") or "")
            if digest.lower().startswith("sha256:"):
                candidate = digest.split(":", 1)[1].strip()
                if _SHA256.fullmatch(candidate):
                    release.sha256 = candidate.lower()
            for asset in assets:
                if isinstance(asset, Mapping) and str(asset.get("name") or "").lower() == name.lower() + ".sha256":
                    sha_url = str(asset.get("browser_download_url") or "")
                    if _host_allowed(sha_url):
                        release.sha256_url = sha_url
                    break
    return release


def parse_sha256_file(text: str) -> str:
    match = _SHA256.search(text or "")
    return match.group(1).lower() if match else ""


def can_self_install() -> bool:
    """Only the packaged Windows build can replace itself with the installer."""
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


def download_directory() -> Path:
    return Path(tempfile.gettempdir()) / "DeskIsle-Update"


def launch_installer(path: str | os.PathLike[str]) -> bool:
    """Start the verified installer detached from this process."""
    installer = str(path)
    if os.name != "nt" or not os.path.isfile(installer):
        return False
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen([installer, *INSTALLER_ARGS], creationflags=flags, close_fds=True,
                         cwd=str(Path(installer).parent))
        return True
    except OSError:
        pass
    try:
        # ShellExecute handles installers that ask for elevation.
        os.startfile(installer, arguments=" ".join(INSTALLER_ARGS))  # type: ignore[attr-defined]
        return True
    except (OSError, AttributeError, TypeError):
        return False


# Manager --------------------------------------------------------------------
class UpdateManager(QObject):
    """Checks GitHub for a newer release and downloads the installer."""

    check_started = Signal()
    check_finished = Signal(object, bool, bool)  # release, newer, manual
    check_failed = Signal(str, bool)  # message, manual
    download_progress = Signal(object, object)  # received, total (python ints; may exceed 2 GB)
    download_finished = Signal(str)
    download_failed = Signal(str)

    def __init__(self, data_root: str | os.PathLike[str] | None = None, parent: QObject | None = None,
                 current_version: str = __version__) -> None:
        super().__init__(parent)
        self.current_version = current_version
        self.data_root = Path(data_root) if data_root else None
        self.latest: ReleaseInfo | None = None
        self.latest_is_newer = False
        self._network: QNetworkAccessManager | None = None
        self._check_reply: QNetworkReply | None = None
        self._check_manual = False
        self._download_reply: QNetworkReply | None = None
        self._download_file = None
        self._download_hash = None
        self._download_target: Path | None = None
        self._download_release: ReleaseInfo | None = None
        self._received = 0
        self.state = self._load_state()

    # Persistence ------------------------------------------------------------
    @property
    def state_path(self) -> Path | None:
        return self.data_root / STATE_FILENAME if self.data_root else None

    def _load_state(self) -> dict:
        path = self.state_path
        if path is None:
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        path = self.state_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, path)
        except OSError:
            pass

    @property
    def skipped_version(self) -> str:
        return str(self.state.get("skipped_version") or "")

    def skip_version(self, version: str) -> None:
        self.state["skipped_version"] = display_version(version)
        self._save_state()

    def should_notify(self, release: ReleaseInfo) -> bool:
        """True once per new version for automatic (background) checks."""
        version = display_version(release.version)
        if not is_newer(version, self.current_version):
            return False
        if version == self.skipped_version:
            return False
        return version != str(self.state.get("notified_version") or "")

    def mark_notified(self, release: ReleaseInfo) -> None:
        self.state["notified_version"] = display_version(release.version)
        self._save_state()

    @property
    def last_check(self) -> float:
        try:
            return float(self.state.get("last_check") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def last_check_text(self) -> str:
        stamp = self.last_check
        if stamp <= 0:
            return "尚未检查"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp))

    def auto_check_due(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        last = self.last_check
        return last <= 0 or last > now + 3600 or now - last >= CHECK_INTERVAL_SECONDS

    # Network ----------------------------------------------------------------
    def _manager(self) -> QNetworkAccessManager:
        if self._network is None:
            QNetworkProxyFactory.setUseSystemConfiguration(True)
            self._network = QNetworkAccessManager(self)
        return self._network

    def _request(self, url: str, accept: str = "application/vnd.github+json") -> QNetworkRequest:
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", "DeskIsle/{0}".format(self.current_version).encode("ascii", "ignore"))
        request.setRawHeader(b"Accept", accept.encode("ascii"))
        if "api.github.com" in url:
            request.setRawHeader(b"X-GitHub-Api-Version", b"2022-11-28")
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.UserVerifiedRedirectPolicy)
        request.setTransferTimeout(REQUEST_TIMEOUT_MS)
        return request

    def _guard_redirects(self, reply: QNetworkReply) -> None:
        def redirected(url: QUrl, reply=reply) -> None:
            if _host_allowed(url):
                reply.redirectAllowed.emit()
            else:
                reply.abort()

        reply.redirected.connect(redirected)

    @property
    def is_checking(self) -> bool:
        return self._check_reply is not None

    @property
    def is_downloading(self) -> bool:
        return self._download_reply is not None

    def maybe_auto_check(self) -> bool:
        if self.is_checking or not self.auto_check_due():
            return False
        self.check(manual=False)
        return True

    def check(self, manual: bool = True) -> None:
        if self._check_reply is not None:
            self._check_manual = self._check_manual or manual
            return
        self._check_manual = manual
        reply = self._manager().get(self._request(API_LATEST))
        self._guard_redirects(reply)
        self._check_reply = reply
        reply.finished.connect(lambda reply=reply: self._check_done(reply))
        self.check_started.emit()

    @staticmethod
    def _http_status(reply: QNetworkReply) -> int:
        value = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _error_message(self, reply: QNetworkReply) -> str:
        status = self._http_status(reply)
        if status in (403, 429):
            remaining = bytes(reply.rawHeader(b"X-RateLimit-Remaining") or b"").decode("ascii", "ignore")
            if remaining == "0" or status == 429:
                return "GitHub 接口请求次数暂时用完，请稍后再试。"
            return "GitHub 拒绝了这次请求（HTTP {0}）。".format(status)
        if status == 404:
            return "仓库 {0} 目前还没有正式发布的版本。".format(REPO)
        if status >= 500:
            return "GitHub 暂时不可用（HTTP {0}），请稍后再试。".format(status)
        error = reply.error()
        if error == QNetworkReply.NetworkError.OperationCanceledError:
            return "连接超时或已取消，请检查网络后重试。"
        if error in (QNetworkReply.NetworkError.HostNotFoundError, QNetworkReply.NetworkError.UnknownNetworkError):
            return "无法连接到 GitHub，请检查网络或代理设置。"
        if error == QNetworkReply.NetworkError.SslHandshakeFailedError:
            return "与 GitHub 的安全连接失败，请检查系统时间或代理设置。"
        text = reply.errorString() or "未知错误"
        return "检查更新失败：{0}".format(text)

    def _check_done(self, reply: QNetworkReply) -> None:
        if reply is not self._check_reply:
            reply.deleteLater()
            return
        self._check_reply = None
        manual = self._check_manual
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.check_failed.emit(self._error_message(reply), manual)
                return
            try:
                payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
                release = parse_release(payload)
            except (ValueError, UnicodeError) as exc:
                self.check_failed.emit("无法解析 GitHub 返回的发布信息：{0}".format(exc), manual)
                return
            self.state["last_check"] = time.time()
            self.state["latest_version"] = release.version
            self._save_state()
            self.latest = release
            self.latest_is_newer = is_newer(release.version, self.current_version)
            self.check_finished.emit(release, self.latest_is_newer, manual)
        finally:
            reply.deleteLater()

    # Download ---------------------------------------------------------------
    def cached_installer(self, release: ReleaseInfo) -> Path | None:
        if not release.sha256 or not release.asset_name:
            return None
        path = download_directory() / release.asset_name
        if path.is_file() and _file_sha256(path) == release.sha256:
            return path
        return None

    def download(self, release: ReleaseInfo) -> None:
        if self.is_downloading:
            return
        if not release.has_installer:
            self.download_failed.emit("这个版本没有提供 Windows 安装包，请在浏览器中查看发布页面。")
            return
        if not ASSET_PATTERN.match(release.asset_name) or not _host_allowed(release.asset_url):
            self.download_failed.emit("安装包地址不受信任，已拒绝下载。")
            return
        if release.asset_size > MAX_INSTALLER_BYTES:
            self.download_failed.emit("安装包大小异常，已拒绝下载。")
            return
        self._download_release = release
        if not release.sha256:
            if release.sha256_url:
                self._fetch_checksum(release)
                return
            self._download_release = None
            self.download_failed.emit("该版本没有发布 SHA-256 校验值，为了安全已拒绝自动安装。请在浏览器中手动下载。")
            return
        self._start_download(release)

    def _fetch_checksum(self, release: ReleaseInfo) -> None:
        reply = self._manager().get(self._request(release.sha256_url, "application/octet-stream"))
        self._guard_redirects(reply)
        self._download_reply = reply

        def done(reply=reply) -> None:
            self._download_reply = None
            try:
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    self._download_release = None
                    self.download_failed.emit("无法获取安装包校验值：" + self._error_message(reply))
                    return
                digest = parse_sha256_file(bytes(reply.read(4096)).decode("utf-8", "ignore"))
                if not digest:
                    self._download_release = None
                    self.download_failed.emit("安装包校验文件格式不正确，已拒绝安装。")
                    return
                release.sha256 = digest
                self._start_download(release)
            finally:
                reply.deleteLater()

        reply.finished.connect(done)

    def _start_download(self, release: ReleaseInfo) -> None:
        cached = self.cached_installer(release)
        if cached is not None:
            self._download_release = None
            self.download_progress.emit(release.asset_size or 1, release.asset_size or 1)
            self.download_finished.emit(str(cached))
            return
        folder = download_directory()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob("DeskIsle-Setup-*"):
                try:
                    old.unlink()
                except OSError:
                    pass
            target = folder / release.asset_name
            part = target.with_name(target.name + ".part")
            self._download_file = open(part, "wb")
        except OSError as exc:
            self._download_release = None
            self.download_failed.emit("无法写入临时文件：{0}".format(exc))
            return
        self._download_target = target
        self._download_hash = hashlib.sha256()
        self._received = 0
        request = self._request(release.asset_url, "application/octet-stream")
        request.setTransferTimeout(DOWNLOAD_STALL_TIMEOUT_MS)
        reply = self._manager().get(request)
        self._guard_redirects(reply)
        self._download_reply = reply
        reply.readyRead.connect(lambda reply=reply: self._download_chunk(reply))
        reply.downloadProgress.connect(lambda received, total: self.download_progress.emit(
            int(received), int(total if total > 0 else release.asset_size)))
        reply.finished.connect(lambda reply=reply: self._download_done(reply))

    def _download_chunk(self, reply: QNetworkReply) -> None:
        if reply is not self._download_reply or self._download_file is None:
            return
        data = bytes(reply.readAll())
        if not data:
            return
        self._received += len(data)
        if self._received > MAX_INSTALLER_BYTES:
            reply.abort()
            return
        try:
            self._download_file.write(data)
        except OSError:
            reply.abort()
            return
        self._download_hash.update(data)

    def _close_download_file(self) -> None:
        if self._download_file is not None:
            try:
                self._download_file.close()
            except OSError:
                pass
        self._download_file = None

    def _discard_partial(self) -> None:
        if self._download_target is not None:
            part = self._download_target.with_name(self._download_target.name + ".part")
            try:
                part.unlink()
            except OSError:
                pass

    def _download_done(self, reply: QNetworkReply) -> None:
        if reply is not self._download_reply:
            reply.deleteLater()
            return
        self._download_chunk(reply)
        self._download_reply = None
        release = self._download_release
        self._download_release = None
        self._close_download_file()
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._discard_partial()
                if reply.error() == QNetworkReply.NetworkError.OperationCanceledError and self._cancelled:
                    self.download_failed.emit("已取消下载。")
                else:
                    self.download_failed.emit("下载失败：" + self._error_message(reply))
                return
            digest = self._download_hash.hexdigest() if self._download_hash is not None else ""
            if release is None or not release.sha256 or digest != release.sha256:
                self._discard_partial()
                self.download_failed.emit("安装包校验失败（SHA-256 不一致），文件已删除。请稍后重试。")
                return
            target = self._download_target
            part = target.with_name(target.name + ".part")
            try:
                os.replace(part, target)
            except OSError as exc:
                self._discard_partial()
                self.download_failed.emit("无法保存安装包：{0}".format(exc))
                return
            self.download_finished.emit(str(target))
        finally:
            self._cancelled = False
            reply.deleteLater()

    _cancelled = False

    def cancel_download(self) -> None:
        if self._download_reply is not None:
            self._cancelled = True
            self._download_reply.abort()

    def shutdown(self) -> None:
        for reply in (self._check_reply, self._download_reply):
            if reply is not None:
                try:
                    reply.abort()
                except RuntimeError:
                    pass
        self._close_download_file()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


__all__ = [
    "API_LATEST",
    "RELEASES_PAGE",
    "REPO",
    "ReleaseInfo",
    "UpdateManager",
    "can_self_install",
    "display_version",
    "is_newer",
    "launch_installer",
    "parse_release",
    "parse_sha256_file",
    "parse_version",
]
