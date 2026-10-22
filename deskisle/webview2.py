"""Microsoft Edge WebView2 bound with ctypes — no extra Python packages.

HTML-animation and pinned-web-page islands embed the WebView2 runtime that
ships with Windows 10/11 (the evergreen Edge engine: H.264/AAC video, modern
web APIs, its own sign-in storage).  Only what DeskIsle needs is bound and
every method is called through its vtable slot.  Slot numbers come from
``WebView2.idl`` of SDK 1.0.4258.31; COM interfaces only ever grow at the
end, so the slots stay valid for every newer runtime.  Newer interfaces such
as ``ICoreWebView2_11`` are queried at run time and skipped when absent.

The module is Qt-free.  Tests give :class:`Runtime` a fake loader and drive
fake COM objects built with ``CFUNCTYPE``, so the call flow is checked on
any platform.
"""

from __future__ import annotations

import ctypes
import logging
import os
import struct
import sys
import sysconfig
import tempfile
import uuid
from ctypes import (POINTER, Structure, byref, c_double, c_int32, c_int64, c_ssize_t, c_ubyte, c_uint32,
                    c_void_p, c_wchar_p)
from pathlib import Path
from types import SimpleNamespace

log = logging.getLogger("deskisle.webview2")

IS_WINDOWS = sys.platform == "win32"
FUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
HRESULT = c_int32
BOOL = c_int32
ULONG = c_uint32


def _signed(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value & 0x80000000 else value


S_OK = 0
S_FALSE = 1
E_NOTIMPL = _signed(0x80004001)
E_NOINTERFACE = _signed(0x80004002)
E_POINTER = _signed(0x80004003)
E_FAIL = _signed(0x80004005)
E_ACCESSDENIED = _signed(0x80070005)
E_FILE_NOT_FOUND = _signed(0x80070002)
E_INVALID_STATE = _signed(0x8007139F)
RPC_E_CHANGED_MODE = _signed(0x80010106)

SDK_VERSION = "1.0.4258.31"
RUNTIME_DOWNLOAD_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
PRIVATE_PROFILE = "DeskIsleHTML"

RESOURCE_CONTEXT_ALL = 0
PERMISSION_DENY = 2
DOWNLOAD_IN_PROGRESS, DOWNLOAD_INTERRUPTED, DOWNLOAD_COMPLETED = 0, 1, 2
PROCESS_BROWSER_EXITED, PROCESS_RENDER_EXITED, PROCESS_RENDER_UNRESPONSIVE = 0, 1, 2
MOVE_FOCUS_PROGRAMMATIC = 0

IID = {
    "IUnknown": "00000000-0000-0000-c000-000000000046",
    "Environment10": "ee0eb9df-6f12-46ce-b53f-3f47b9c928e0",
    "Controller2": "c979903e-d4ca-4228-92eb-47ee3fa96eab",
    "Controller4": "97d418d5-a426-4e49-a151-e1a10f327d9e",
    "WebView2_3": "a0d6df20-3b92-416d-aa0c-437a9c727857",
    "WebView2_4": "20d02d59-6df2-42dc-bd06-f98a694b1302",
    "WebView2_11": "0be78e56-c193-4051-b943-23b460c08bdb",
    "WebView2_19": "6921f954-79b0-437f-a997-c85811897c68",
    # Handler interfaces implemented by DeskIsle.
    "EnvironmentCompleted": "4e8a3389-c9d8-4bd2-b6b5-124fee6cc14d",
    "ControllerCompleted": "6c4819f3-c9b7-4260-8127-c9f5bde7f68c",
    "NavigationStarting": "9adbe429-f36d-432b-9ddc-f8881fbd76e3",
    "ContentLoading": "364471e7-f2be-4910-bdba-d72077d51c4b",
    "NavigationCompleted": "d33a35bf-1c49-4f98-93ab-006e0533fe1c",
    "SourceChanged": "3c067f9f-5388-4772-8b48-79f7ef1ab37c",
    "HistoryChanged": "c79a420c-efd9-4058-9295-3e8b4bcab645",
    "DocumentTitleChanged": "f5f2b923-953e-4042-9f95-f3a118e1afd4",
    "NewWindowRequested": "d4c185fe-c81c-4989-97af-2d3fa7ab5651",
    "WebResourceRequested": "ab00b74c-15f1-4646-80e8-e76341d25d71",
    "PermissionRequested": "15e1c6a3-c72a-4df3-91d7-d097fbec6bfd",
    "DownloadStarting": "efedc989-c396-41ca-83f7-07f845a55724",
    "DownloadStateChanged": "81336594-7ede-4ba9-bf71-acf0a95b58dd",
    "ContextMenuRequested": "04d3fe1d-ab87-42fb-a898-da241d35b63c",
    "ProcessFailed": "79e0aea4-990b-42d9-aa1d-0fcc2e5bc7f1",
    "AddScriptCompleted": "b99369f3-9b11-47b5-bc6f-8e7895fcea17",
    "ZoomFactorChanged": "b52d71d6-c4df-4543-a90c-64a3e60f38cb",
    "TrySuspendCompleted": "00f206a7-9d17-4605-91f6-4e8e4de192e3",
    "FocusChanged": "05ea24bd-6452-4926-9014-4b82b498135d",
    "WebMessageReceived": "57213f19-00e6-49fa-8e07-898ea01ecbd2",
    # Composition (visual) hosting, see engine/webhost.py.
    "Controller": "4d00c0d1-9434-4eb6-8078-8697a560334f",
    "Environment3": "80a22ae3-be7c-4ce2-afe1-5a50056cdeeb",
    "CompositionController": "3df9b733-b9ae-4a15-86b4-eb9ee9826469",
    "CompositionControllerCompleted": "02fab84b-1428-4fb7-ad45-1b2e64736184",
    "CursorChanged": "9da43ccc-26e1-4dad-b56c-d8961c94c571",
}


class Slot:
    """Absolute vtable slots (IUnknown occupies 0-2)."""

    # ICoreWebView2Environment / Environment10 / ControllerOptions
    ENV_CREATE_CONTROLLER = 3
    ENV_CREATE_RESPONSE = 4
    ENV_BROWSER_VERSION = 5
    ENV10_CREATE_OPTIONS = 20
    ENV10_CREATE_CONTROLLER_WITH_OPTIONS = 21
    OPTIONS_PUT_PROFILE_NAME = 4
    OPTIONS_PUT_IN_PRIVATE = 6
    # ICoreWebView2Controller / Controller2 / Controller4
    CTRL_PUT_IS_VISIBLE = 4
    CTRL_PUT_BOUNDS = 6
    CTRL_GET_ZOOM = 7
    CTRL_PUT_ZOOM = 8
    CTRL_ADD_ZOOM_CHANGED = 9
    CTRL_MOVE_FOCUS = 12
    CTRL_ADD_GOT_FOCUS = 15
    CTRL_NOTIFY_PARENT_MOVED = 23
    CTRL_CLOSE = 24
    CTRL_GET_WEBVIEW = 25
    CTRL2_PUT_BACKGROUND = 27
    CTRL4_PUT_ALLOW_EXTERNAL_DROP = 37
    # ICoreWebView2 and later
    WV_GET_SETTINGS = 3
    WV_GET_SOURCE = 4
    WV_NAVIGATE = 5
    WV_NAVIGATE_TO_STRING = 6
    WV_ADD_NAVIGATION_STARTING = 7
    WV_ADD_CONTENT_LOADING = 9
    WV_ADD_SOURCE_CHANGED = 11
    WV_ADD_HISTORY_CHANGED = 13
    WV_ADD_NAVIGATION_COMPLETED = 15
    WV_ADD_PERMISSION_REQUESTED = 23
    WV_ADD_PROCESS_FAILED = 25
    WV_ADD_SCRIPT_ON_DOCUMENT_CREATED = 27
    WV_RELOAD = 31
    WV_POST_WEB_MESSAGE_AS_JSON = 32
    WV_ADD_WEB_MESSAGE_RECEIVED = 34
    WV_GET_CAN_GO_BACK = 38
    WV_GET_CAN_GO_FORWARD = 39
    WV_GO_BACK = 40
    WV_GO_FORWARD = 41
    WV_STOP = 43
    WV_ADD_NEW_WINDOW_REQUESTED = 44
    WV_ADD_TITLE_CHANGED = 46
    WV_GET_TITLE = 48
    WV_ADD_WEB_RESOURCE_REQUESTED = 55
    WV_ADD_WEB_RESOURCE_FILTER = 57
    WV3_TRY_SUSPEND = 68
    WV3_RESUME = 69
    WV19_PUT_MEMORY_TARGET = 120   # ICoreWebView2_19::put_MemoryUsageTargetLevel (0 normal, 1 low)
    WV4_ADD_DOWNLOAD_STARTING = 75
    WV11_ADD_CONTEXT_MENU_REQUESTED = 100
    # ICoreWebView2Settings
    SET_PUT_SCRIPT_DIALOGS = 8
    SET_PUT_STATUS_BAR = 10
    SET_PUT_DEVTOOLS = 12
    SET_PUT_CONTEXT_MENUS = 14
    SET_PUT_ZOOM_CONTROL = 18
    # Event arguments
    NAV_STARTING_GET_URI = 3
    NAV_COMPLETED_GET_IS_SUCCESS = 3
    NAV_COMPLETED_GET_ERROR = 4
    NEW_WINDOW_GET_URI = 3
    NEW_WINDOW_PUT_HANDLED = 6
    RESOURCE_ARGS_GET_REQUEST = 3
    RESOURCE_ARGS_PUT_RESPONSE = 5
    RESOURCE_REQUEST_GET_URI = 3
    PERMISSION_PUT_STATE = 7
    DOWNLOAD_ARGS_GET_OPERATION = 3
    DOWNLOAD_ADD_STATE_CHANGED = 7
    DOWNLOAD_GET_PATH = 15
    DOWNLOAD_GET_STATE = 16
    CONTEXT_MENU_PUT_HANDLED = 8
    PROCESS_FAILED_GET_KIND = 3
    WEB_MESSAGE_GET_JSON = 4
    # ICoreWebView2Environment3 / Environment10 (composition controllers)
    ENV3_CREATE_COMPOSITION_CONTROLLER = 9
    ENV10_CREATE_COMPOSITION_CONTROLLER_WITH_OPTIONS = 22
    # ICoreWebView2CompositionController
    COMP_PUT_ROOT_VISUAL_TARGET = 4
    COMP_SEND_MOUSE_INPUT = 5
    COMP_GET_SYSTEM_CURSOR_ID = 8
    COMP_ADD_CURSOR_CHANGED = 9


class RECT(Structure):
    _fields_ = [("left", c_int32), ("top", c_int32), ("right", c_int32), ("bottom", c_int32)]


class COLOR(Structure):
    """``COREWEBVIEW2_COLOR`` (passed by value)."""

    _fields_ = [("A", c_ubyte), ("R", c_ubyte), ("G", c_ubyte), ("B", c_ubyte)]


# COM plumbing -----------------------------------------------------------------
_guids: dict = {}
_prototypes: dict = {}
_free = None


def guid(iid: str):
    value = _guids.get(iid)
    if value is None:
        value = _guids[iid] = (c_ubyte * 16).from_buffer_copy(uuid.UUID(iid).bytes_le)
    return value


def vcall(ptr: int, slot: int, argtypes: tuple = (), *args, restype=HRESULT):
    """Call method ``slot`` of the COM interface pointer ``ptr``."""
    if not ptr:
        return E_POINTER
    key = (restype, argtypes)
    prototype = _prototypes.get(key)
    if prototype is None:
        prototype = _prototypes[key] = FUNCTYPE(restype, c_void_p, *argtypes)
    vtable = ctypes.cast(c_void_p(ptr), POINTER(POINTER(c_void_p))).contents
    return prototype(vtable[slot])(ptr, *args)


def set_string_free(function) -> None:
    """Replace ``CoTaskMemFree`` (tests)."""
    global _free
    _free = function


def free_string(ptr: int) -> None:
    global _free
    if _free is None:
        if IS_WINDOWS:
            function = ctypes.WinDLL("ole32").CoTaskMemFree
            function.argtypes = [c_void_p]
            function.restype = None
            _free = function
        else:
            _free = lambda _ptr: None  # noqa: E731 - fakes keep their own buffers
    _free(ptr)


class Com:
    """A COM interface pointer.

    ``release()`` drops the one reference this wrapper owns.  Wrappers around
    borrowed pointers (event senders and arguments) are simply never released.
    """

    __slots__ = ("ptr",)

    def __init__(self, ptr=0, *, add_ref: bool = False) -> None:
        self.ptr = int(ptr or 0)
        if add_ref and self.ptr:
            vcall(self.ptr, 1, restype=ULONG)

    def __bool__(self) -> bool:
        return bool(self.ptr)

    def call(self, slot: int, argtypes=(), *args) -> int:
        return vcall(self.ptr, slot, tuple(argtypes), *args)

    def release(self) -> None:
        ptr, self.ptr = self.ptr, 0
        if ptr:
            try:
                vcall(ptr, 2, restype=ULONG)
            except OSError:  # a runtime that is already gone
                pass

    def query(self, iid: str) -> "Com | None":
        out = c_void_p()
        hr = self.call(0, (c_void_p, POINTER(c_void_p)), ctypes.addressof(guid(iid)), byref(out))
        return Com(out.value) if hr >= 0 and out.value else None

    def get_object(self, slot: int) -> "Com | None":
        out = c_void_p()
        hr = self.call(slot, (POINTER(c_void_p),), byref(out))
        return Com(out.value) if hr >= 0 and out.value else None

    def get_bool(self, slot: int, default: bool = False) -> bool:
        out = BOOL(1 if default else 0)
        hr = self.call(slot, (POINTER(BOOL),), byref(out))
        return bool(out.value) if hr >= 0 else default

    def get_int(self, slot: int, default: int = 0) -> int:
        out = c_int32(default)
        hr = self.call(slot, (POINTER(c_int32),), byref(out))
        return int(out.value) if hr >= 0 else default

    def get_double(self, slot: int, default: float = 0.0) -> float:
        out = c_double(default)
        hr = self.call(slot, (POINTER(c_double),), byref(out))
        return float(out.value) if hr >= 0 else default

    def get_string(self, slot: int) -> str:
        out = c_void_p()
        hr = self.call(slot, (POINTER(c_void_p),), byref(out))
        if hr < 0 or not out.value:
            return ""
        try:
            return ctypes.wstring_at(out.value)
        finally:
            free_string(out.value)

    def put_bool(self, slot: int, value) -> int:
        return self.call(slot, (BOOL,), 1 if value else 0)

    def put_int(self, slot: int, value: int) -> int:
        return self.call(slot, (c_int32,), int(value))

    def put_double(self, slot: int, value: float) -> int:
        return self.call(slot, (c_double,), float(value))

    def put_string(self, slot: int, value: str) -> int:
        return self.call(slot, (c_wchar_p,), value)


# Python-implemented handler objects ---------------------------------------------
_IUNKNOWN = uuid.UUID(IID["IUnknown"]).bytes_le
SIGNATURES = {
    "objects": (c_void_p, c_void_p),  # (sender, args)
    "hr_object": (HRESULT, c_void_p),  # (errorCode, result)
    "hr_string": (HRESULT, c_wchar_p),
    "hr_bool": (HRESULT, BOOL),
}
_thunks: dict = {}


class Handler:
    """A Python COM object implementing one WebView2 ``…Handler`` interface.

    All handlers share the same native thunks (QueryInterface, AddRef,
    Release and one Invoke per signature).  They are created once and never
    freed, so a handler released from inside its own callback stays safe.
    """

    live: dict = {}
    _retired: list = []

    def __init__(self, iid: str, callback, signature: str = "objects") -> None:
        Handler._retired.clear()
        query, add_ref, release, invoke = _thunk_addresses(signature)
        self.iid = uuid.UUID(iid).bytes_le
        self.callback = callback
        self.refs = 1
        self.invocations = 0
        self._vtable = (c_void_p * 4)(query, add_ref, release, invoke)
        self._object = (c_void_p * 1)(ctypes.addressof(self._vtable))
        self.ptr = ctypes.addressof(self._object)
        Handler.live[self.ptr] = self

    def release(self) -> int:
        return _handler_release(self.ptr)


def _handler_query(this, riid, out):
    if not out:
        return E_POINTER
    out[0] = None
    handler = Handler.live.get(this or 0)
    if handler is None or not riid:
        return E_NOINTERFACE
    wanted = ctypes.string_at(riid, 16)
    if wanted != _IUNKNOWN and wanted != handler.iid:
        return E_NOINTERFACE
    handler.refs += 1
    out[0] = this
    return S_OK


def _handler_add_ref(this):
    handler = Handler.live.get(this or 0)
    if handler is None:
        return 1
    handler.refs += 1
    return handler.refs


def _handler_release(this):
    handler = Handler.live.get(this or 0)
    if handler is None:
        return 0
    handler.refs -= 1
    if handler.refs > 0:
        return handler.refs
    del Handler.live[this]
    handler.callback = None
    Handler._retired.append(handler)  # memory goes once no native code can run it
    return 0


def _handler_invoke(this, first, second):
    handler = Handler.live.get(this or 0)
    callback = handler.callback if handler is not None else None
    if callback is None:
        return S_OK
    handler.invocations += 1
    try:
        callback(first, second)
    except Exception:  # never let an exception unwind into the runtime
        log.exception("WebView2 callback failed")
    return S_OK


def _thunk_addresses(signature: str) -> tuple:
    if "query" not in _thunks:
        _thunks["query"] = FUNCTYPE(HRESULT, c_void_p, c_void_p, POINTER(c_void_p))(_handler_query)
        _thunks["add_ref"] = FUNCTYPE(ULONG, c_void_p)(_handler_add_ref)
        _thunks["release"] = FUNCTYPE(ULONG, c_void_p)(_handler_release)
    key = "invoke:" + signature
    if key not in _thunks:
        _thunks[key] = FUNCTYPE(HRESULT, c_void_p, *SIGNATURES[signature])(_handler_invoke)
    return tuple(ctypes.cast(_thunks[name], c_void_p).value for name in ("query", "add_ref", "release", key))


def subscribe(source, slot: int, name: str, callback, signature: str = "objects") -> bool:
    """``add_<Event>(handler, &token)``; the source keeps the handler alive."""
    if not source:
        return False
    handler = Handler(IID[name], callback, signature)
    token = c_int64()
    try:
        hr = source.call(slot, (c_void_p, POINTER(c_int64)), handler.ptr, byref(token))
    finally:
        handler.release()
    return hr >= 0


def describe(hr: int) -> str:
    known = {
        E_FILE_NOT_FOUND: "未找到 WebView2 运行时",
        E_ACCESSDENIED: "无法写入网页数据文件夹",
        E_INVALID_STATE: "网页数据文件夹正被其他程序以不同设置使用",
        RPC_E_CHANGED_MODE: "COM 线程模式不兼容",
    }
    return known.get(hr, "HRESULT 0x{0:08X}".format(hr & 0xFFFFFFFF))


# Loader and the shared environment --------------------------------------------------
def loader_arch() -> str:
    """Architecture of this *process* (an x64 build may run on ARM64)."""
    if struct.calcsize("P") == 4:
        return "x86"
    build = sysconfig.get_platform().lower()
    return "arm64" if ("arm64" in build or "aarch64" in build) else "x64"


def loader_path() -> Path:
    override = os.environ.get("DESKISLE_WEBVIEW2_LOADER")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "assets" / "webview2" / loader_arch() / "WebView2Loader.dll"


def default_data_folder() -> str:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return str(Path(base) / "DeskIsle" / "WebView2")


def disabled_by_environment() -> bool:
    return (os.environ.get("DESKISLE_DISABLE_WEBVIEW2") == "1"
            or os.environ.get("DESKISLE_DISABLE_WEBENGINE") == "1")


class WindowsLoader:
    """The two exports of ``WebView2Loader.dll`` DeskIsle uses."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise OSError("WebView2Loader.dll not found: {0}".format(self.path))
        dll = ctypes.WinDLL(str(self.path))
        self._create = dll.CreateCoreWebView2EnvironmentWithOptions
        self._create.restype = HRESULT
        self._create.argtypes = [c_wchar_p, c_wchar_p, c_void_p, c_void_p]
        self._version = dll.GetAvailableCoreWebView2BrowserVersionString
        self._version.restype = HRESULT
        self._version.argtypes = [c_wchar_p, POINTER(c_void_p)]
        self._co_initialize = ctypes.WinDLL("ole32").CoInitializeEx
        self._co_initialize.restype = HRESULT
        self._co_initialize.argtypes = [c_void_p, c_uint32]
        self._dll = dll

    def browser_version(self) -> tuple:
        out = c_void_p()
        hr = self._version(None, byref(out))
        text = ""
        if out.value:
            try:
                text = ctypes.wstring_at(out.value)
            finally:
                free_string(out.value)
        return hr, text

    def create_environment(self, user_data_folder: str, handler: int) -> int:
        return self._create(None, user_data_folder or None, None, handler)

    def initialize_com(self) -> int:
        return self._co_initialize(None, 0x2)  # COINIT_APARTMENTTHREADED


class Runtime:
    """Finds the runtime once and shares one environment per process."""

    def __init__(self, loader_factory=None) -> None:
        self._loader_factory = loader_factory
        self.loader = None
        self.checked = False
        self.status = "unknown"  # ok | unsupported | no-loader | no-runtime
        self.detail = ""
        self.version = ""
        self.data_folder = ""
        self.environment: Com | None = None
        self.env_state = "idle"  # idle | creating | ready | failed
        self.env_error = 0
        self._waiters: list = []

    def probe(self) -> bool:
        if self.checked:
            return self.status == "ok"
        self.checked = True
        if self._loader_factory is None and not IS_WINDOWS:
            self.status = "unsupported"
            return False
        try:
            factory = self._loader_factory or (lambda: WindowsLoader(loader_path()))
            self.loader = factory()
        except (OSError, AttributeError, ValueError) as exc:
            self.status, self.detail = "no-loader", str(exc)
            return False
        try:
            hr, version = self.loader.browser_version()
        except OSError as exc:
            hr, version, self.detail = E_FAIL, "", str(exc)
        if hr < 0 or not version:
            self.status = "no-runtime"
            self.detail = self.detail or describe(hr if hr < 0 else E_FILE_NOT_FOUND)
            return False
        self.version, self.status = version, "ok"
        return True

    def available(self) -> bool:
        return not disabled_by_environment() and self.probe()

    def state(self) -> str:
        """``disabled`` / ``unsupported`` / ``no-loader`` / ``no-runtime`` / ``failed`` / ``ok``."""
        if disabled_by_environment():
            return "disabled"
        if not self.probe():
            return self.status
        return "failed" if self.env_state == "failed" else "ok"

    def request_environment(self, callback) -> None:
        """``callback(environment_or_None, hresult)``, now or once it exists."""
        if self.env_state == "ready" and self.environment:
            callback(self.environment, S_OK)
            return
        if self.env_state == "failed":
            callback(None, self.env_error)
            return
        self._waiters.append(callback)
        if self.env_state == "idle":
            self._create_environment()

    def _create_environment(self) -> None:
        if not self.available():
            self._environment_failed(E_FILE_NOT_FOUND if self.status == "no-runtime" else E_FAIL)
            return
        self.env_state = "creating"
        try:
            hr = self.loader.initialize_com()
        except (OSError, AttributeError):
            hr = S_OK
        if hr == RPC_E_CHANGED_MODE:
            self.detail = describe(hr)
            self._environment_failed(hr)
            return
        folder = self.data_folder or default_data_folder()
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        handler = Handler(IID["EnvironmentCompleted"], self._environment_created, "hr_object")
        try:
            hr = self.loader.create_environment(folder, handler.ptr)
        except OSError as exc:
            hr, self.detail = E_FAIL, str(exc)
        finally:
            handler.release()
        if hr < 0 and self.env_state == "creating":
            self._environment_failed(hr)

    def _environment_created(self, hr, environment) -> None:
        if self.env_state != "creating":
            return
        if hr < 0 or not environment:
            self._environment_failed(hr if hr < 0 else E_FAIL)
            return
        self.environment = Com(environment, add_ref=True)
        self.env_state = "ready"
        version = self.environment.get_string(Slot.ENV_BROWSER_VERSION)
        if version:
            self.version = version
        self._flush(self.environment, S_OK)

    def _environment_failed(self, hr: int) -> None:
        self.env_state = "failed"
        self.env_error = hr
        if not self.detail:
            self.detail = describe(hr)
        self._flush(None, hr)

    def _flush(self, environment, hr: int) -> None:
        waiters, self._waiters = self._waiters, []
        for callback in waiters:
            try:
                callback(environment, hr)
            except Exception:
                log.exception("WebView2 environment callback failed")

    def reset(self) -> None:
        """Forget the environment (its browser process ended) or a failure."""
        if self.environment is not None:
            self.environment.release()
        self.environment = None
        self.env_state = "idle"
        self.env_error = 0
        if self.status != "ok":
            self.checked = False
            self.detail = ""

    def shutdown(self) -> None:
        self._waiters.clear()
        if self.environment is not None:
            self.environment.release()
        self.environment = None
        if self.env_state != "failed":
            self.env_state = "idle"


_runtime: Runtime | None = None


def runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = Runtime()
    return _runtime


def install_runtime(value: Runtime | None) -> Runtime | None:
    """Swap the process-wide runtime (tests); returns the previous one."""
    global _runtime
    previous, _runtime = _runtime, value
    return previous


# One WebView2 instance -------------------------------------------------------------
DEFAULT_SETTINGS = {
    "context_menus": True,  # Edge's own context menu
    "custom_context_menu": False,  # raise on_context_menu instead (ICoreWebView2_11)
    "status_bar": True,
    "zoom_control": True,
    "devtools": False,
    "script_dialogs": True,
    "external_drop": False,
}
_CALLBACKS = ("on_ready", "on_failed", "on_title", "on_source", "on_history", "on_navigation_starting",
              "on_content_loading", "on_navigation_completed", "on_new_window", "on_context_menu",
              "on_download_finished", "on_process_failed", "on_zoom", "on_message", "on_focus")


class Browser:
    """One WebView2 controller inside the native window ``hwnd``.

    Everything asked for before the controller exists (bounds, zoom, the
    first navigation …) is remembered and applied once it is ready.  Assign
    the ``on_*`` callbacks, then call :meth:`start`.
    """

    def __init__(self, hwnd: int, *, private: bool = False, settings: dict | None = None,
                 network_filter=None, runtime_: Runtime | None = None) -> None:
        self.hwnd = int(hwnd)
        self.private = bool(private)
        self.settings = dict(DEFAULT_SETTINGS, **(settings or {}))
        self.network_filter = network_filter  # callable(uri) -> True to block
        self.runtime = runtime_ or runtime()
        self.state = "new"  # new | pending | ready | failed | closed
        self.error = 0
        self.environment: Com | None = None
        self.controller: Com | None = None
        self.webview: Com | None = None
        self.custom_menu = False
        self._bounds = (0, 0)
        self._visible = True
        self._zoom = 1.0
        self._background: tuple | None = None
        self._pending: tuple | None = None
        self._scripts: list = []
        self._downloads: list = []
        for name in _CALLBACKS:
            setattr(self, name, None)

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def start(self) -> None:
        if self.state == "new":
            self.state = "pending"
            self.runtime.request_environment(self._environment_ready)

    # Creation ---------------------------------------------------------------
    def _environment_ready(self, environment, hr: int) -> None:
        if self.state != "pending":
            return
        if environment is None:
            self._fail(hr if hr < 0 else E_FAIL)
            return
        self.environment = Com(environment.ptr, add_ref=True)
        handler = Handler(IID["ControllerCompleted"], self._controller_created, "hr_object")
        try:
            hr = self._create_controller(handler.ptr)
        except OSError:
            hr = E_FAIL
        finally:
            handler.release()
        if hr < 0:
            self._fail(hr)

    def _create_controller(self, handler: int) -> int:
        environment = self.environment
        if self.private:
            environment10 = environment.query(IID["Environment10"])
            if environment10 is not None:
                try:
                    options = environment10.get_object(Slot.ENV10_CREATE_OPTIONS)
                    if options is not None:
                        try:
                            options.put_string(Slot.OPTIONS_PUT_PROFILE_NAME, PRIVATE_PROFILE)
                            options.put_bool(Slot.OPTIONS_PUT_IN_PRIVATE, True)
                            return environment10.call(Slot.ENV10_CREATE_CONTROLLER_WITH_OPTIONS,
                                                      (c_void_p, c_void_p, c_void_p),
                                                      self.hwnd, options.ptr, handler)
                        finally:
                            options.release()
                finally:
                    environment10.release()
        return environment.call(Slot.ENV_CREATE_CONTROLLER, (c_void_p, c_void_p), self.hwnd, handler)

    def _controller_created(self, hr, controller) -> None:
        if self.state != "pending":
            if hr >= 0 and controller:  # closed while waiting: dispose of it
                late = Com(controller, add_ref=True)
                late.call(Slot.CTRL_CLOSE)
                late.release()
            return
        if hr < 0 or not controller:
            self._fail(hr if hr < 0 else E_FAIL)
            return
        self._adopt(Com(controller, add_ref=True))

    def _adopt(self, controller: "Com") -> None:
        """Finish creation with an owned ICoreWebView2Controller reference."""
        self.controller = controller
        self.webview = self.controller.get_object(Slot.CTRL_GET_WEBVIEW)
        if self.webview is None:
            self._fail(E_NOINTERFACE)
            return
        try:
            self._configure()
        except OSError:
            log.exception("WebView2 configuration failed")
        self.state = "ready"
        self._apply_pending()
        if self.on_ready is not None:
            self.on_ready()

    def _configure(self) -> None:
        options, webview, controller = self.settings, self.webview, self.controller
        settings = webview.get_object(Slot.WV_GET_SETTINGS)
        if options["custom_context_menu"]:
            webview11 = webview.query(IID["WebView2_11"])
            if webview11 is not None:
                self.custom_menu = subscribe(webview11, Slot.WV11_ADD_CONTEXT_MENU_REQUESTED,
                                             "ContextMenuRequested", self._context_menu)
                webview11.release()
        if settings is not None:
            menus = options["context_menus"] and (self.custom_menu or not options["custom_context_menu"])
            settings.put_bool(Slot.SET_PUT_SCRIPT_DIALOGS, options["script_dialogs"])
            settings.put_bool(Slot.SET_PUT_STATUS_BAR, options["status_bar"])
            settings.put_bool(Slot.SET_PUT_DEVTOOLS, options["devtools"])
            settings.put_bool(Slot.SET_PUT_CONTEXT_MENUS, menus)
            settings.put_bool(Slot.SET_PUT_ZOOM_CONTROL, options["zoom_control"])
            settings.release()
        subscribe(webview, Slot.WV_ADD_TITLE_CHANGED, "DocumentTitleChanged", self._title_changed)
        subscribe(webview, Slot.WV_ADD_SOURCE_CHANGED, "SourceChanged", self._source_changed)
        subscribe(webview, Slot.WV_ADD_HISTORY_CHANGED, "HistoryChanged", self._history_changed)
        subscribe(webview, Slot.WV_ADD_NAVIGATION_STARTING, "NavigationStarting", self._navigation_starting)
        subscribe(webview, Slot.WV_ADD_CONTENT_LOADING, "ContentLoading", self._content_loading)
        subscribe(webview, Slot.WV_ADD_NAVIGATION_COMPLETED, "NavigationCompleted", self._navigation_completed)
        subscribe(webview, Slot.WV_ADD_NEW_WINDOW_REQUESTED, "NewWindowRequested", self._new_window)
        subscribe(webview, Slot.WV_ADD_PERMISSION_REQUESTED, "PermissionRequested", self._permission)
        subscribe(webview, Slot.WV_ADD_PROCESS_FAILED, "ProcessFailed", self._process_failed)
        subscribe(controller, Slot.CTRL_ADD_ZOOM_CHANGED, "ZoomFactorChanged", self._zoom_changed)
        subscribe(controller, Slot.CTRL_ADD_GOT_FOCUS, "FocusChanged", self._got_focus)
        subscribe(webview, Slot.WV_ADD_WEB_MESSAGE_RECEIVED, "WebMessageReceived", self._web_message)
        if self.network_filter is not None:
            webview.call(Slot.WV_ADD_WEB_RESOURCE_FILTER, (c_wchar_p, c_int32), "*", RESOURCE_CONTEXT_ALL)
            subscribe(webview, Slot.WV_ADD_WEB_RESOURCE_REQUESTED, "WebResourceRequested",
                      self._resource_requested)
        webview4 = webview.query(IID["WebView2_4"])
        if webview4 is not None:
            subscribe(webview4, Slot.WV4_ADD_DOWNLOAD_STARTING, "DownloadStarting", self._download_starting)
            webview4.release()
        if not options["external_drop"]:
            controller4 = controller.query(IID["Controller4"])
            if controller4 is not None:
                controller4.put_bool(Slot.CTRL4_PUT_ALLOW_EXTERNAL_DROP, False)
                controller4.release()
        for script in self._scripts:
            self._add_script_now(script)

    def _apply_pending(self) -> None:
        self._push_bounds()
        self.controller.put_bool(Slot.CTRL_PUT_IS_VISIBLE, self._visible)
        if abs(self._zoom - 1.0) > 1e-3:
            self.controller.put_double(Slot.CTRL_PUT_ZOOM, self._zoom)
        if self._background is not None:
            self._push_background()
        pending, self._pending = self._pending, None
        if pending is not None:
            self._navigate_now(*pending)

    def _fail(self, hr: int) -> None:
        if self.state in ("failed", "closed"):
            return
        callback = self.on_failed
        self.close()
        self.state, self.error = "failed", hr
        if callback is not None:
            callback(hr)

    # Events -------------------------------------------------------------------
    def _title_changed(self, _sender, _args) -> None:
        if self.ready and self.on_title is not None:
            self.on_title(self.title())

    def _source_changed(self, _sender, _args) -> None:
        if self.ready and self.on_source is not None:
            self.on_source(self.source())

    def _history_changed(self, _sender, _args) -> None:
        if self.ready and self.on_history is not None:
            self.on_history(self.can_go_back(), self.can_go_forward())

    def _navigation_starting(self, _sender, args) -> None:
        if self.ready and self.on_navigation_starting is not None:
            self.on_navigation_starting(Com(args).get_string(Slot.NAV_STARTING_GET_URI))

    def _content_loading(self, _sender, _args) -> None:
        if self.ready and self.on_content_loading is not None:
            self.on_content_loading()

    def _navigation_completed(self, _sender, args) -> None:
        if not self.ready:
            return
        event = Com(args)
        ok = event.get_bool(Slot.NAV_COMPLETED_GET_IS_SUCCESS, True)
        status = event.get_int(Slot.NAV_COMPLETED_GET_ERROR, 0)
        if self.on_navigation_completed is not None:
            self.on_navigation_completed(ok, status)

    def _new_window(self, _sender, args) -> None:
        event = Com(args)
        uri = event.get_string(Slot.NEW_WINDOW_GET_URI)
        event.put_bool(Slot.NEW_WINDOW_PUT_HANDLED, True)  # never open WebView2 popups
        if self.ready and self.on_new_window is not None:
            self.on_new_window(uri)

    def _permission(self, _sender, args) -> None:
        Com(args).put_int(Slot.PERMISSION_PUT_STATE, PERMISSION_DENY)

    def _process_failed(self, _sender, args) -> None:
        kind = Com(args).get_int(Slot.PROCESS_FAILED_GET_KIND, -1)
        if kind == PROCESS_BROWSER_EXITED and self.environment is not None:
            shared = self.runtime.environment
            if shared is not None and shared.ptr == self.environment.ptr:
                self.runtime.reset()
        if self.ready and self.on_process_failed is not None:
            self.on_process_failed(kind)

    def _got_focus(self, _sender, _args) -> None:
        # The page took the focus (a click into a windowed page): the host makes the layer
        # window activatable so the keyboard reaches it.
        if self.on_focus is not None:
            self.on_focus()

    def _zoom_changed(self, _sender, _args) -> None:
        if not self.ready:
            return
        self._zoom = self.controller.get_double(Slot.CTRL_GET_ZOOM, self._zoom)
        if self.on_zoom is not None:
            self.on_zoom(self._zoom)

    def _web_message(self, _sender, args) -> None:
        """``window.chrome.webview.postMessage(...)`` from the page (JSON text)."""
        if self.ready and self.on_message is not None:
            self.on_message(Com(args).get_string(Slot.WEB_MESSAGE_GET_JSON))

    def post_json(self, text: str) -> None:
        """Deliver a JSON message to the page (``chrome.webview`` "message" event)."""
        if self.ready:
            self.webview.put_string(Slot.WV_POST_WEB_MESSAGE_AS_JSON, text)

    def _context_menu(self, _sender, args) -> None:
        if self.ready and self.on_context_menu is not None and self.on_context_menu():
            Com(args).put_bool(Slot.CONTEXT_MENU_PUT_HANDLED, True)

    def _resource_requested(self, _sender, args) -> None:
        if not self.ready or self.network_filter is None:
            return
        event = Com(args)
        request = event.get_object(Slot.RESOURCE_ARGS_GET_REQUEST)
        if request is None:
            return
        try:
            uri = request.get_string(Slot.RESOURCE_REQUEST_GET_URI)
        finally:
            request.release()
        if not self.network_filter(uri):
            return
        out = c_void_p()
        hr = self.environment.call(Slot.ENV_CREATE_RESPONSE,
                                   (c_void_p, c_int32, c_wchar_p, c_wchar_p, POINTER(c_void_p)),
                                   None, 403, "Blocked by DeskIsle", "Content-Type: text/plain", byref(out))
        if hr >= 0 and out.value:
            response = Com(out.value)
            event.call(Slot.RESOURCE_ARGS_PUT_RESPONSE, (c_void_p,), response.ptr)
            response.release()

    def _download_starting(self, _sender, args) -> None:
        operation = Com(args).get_object(Slot.DOWNLOAD_ARGS_GET_OPERATION)
        if operation is None:
            return
        self._downloads.append(operation)
        subscribe(operation, Slot.DOWNLOAD_ADD_STATE_CHANGED, "DownloadStateChanged",
                  lambda _sender, _args, op=operation: self._download_state(op))

    def _download_state(self, operation: Com) -> None:
        if not operation:
            return
        state = operation.get_int(Slot.DOWNLOAD_GET_STATE, DOWNLOAD_IN_PROGRESS)
        if state == DOWNLOAD_IN_PROGRESS:
            return
        path = operation.get_string(Slot.DOWNLOAD_GET_PATH)
        if operation in self._downloads:  # finished or interrupted: let it go
            self._downloads.remove(operation)
            operation.release()
        if state == DOWNLOAD_COMPLETED and path and self.on_download_finished is not None:
            self.on_download_finished(path)

    # Commands -------------------------------------------------------------------
    def navigate(self, url: str) -> None:
        self._navigate("url", url)

    def navigate_to_string(self, html: str) -> None:
        self._navigate("html", html)

    def _navigate(self, kind: str, value: str) -> None:
        if self.ready:
            self._navigate_now(kind, value)
        elif self.state in ("new", "pending"):
            self._pending = (kind, value)

    def _navigate_now(self, kind: str, value: str) -> None:
        slot = Slot.WV_NAVIGATE if kind == "url" else Slot.WV_NAVIGATE_TO_STRING
        hr = self.webview.put_string(slot, value)
        if hr < 0:
            log.warning("WebView2 navigation failed: %s", describe(hr))

    def reload(self) -> None:
        if self.ready:
            self.webview.call(Slot.WV_RELOAD)

    def stop(self) -> None:
        if self.ready:
            self.webview.call(Slot.WV_STOP)

    def go_back(self) -> None:
        if self.ready:
            self.webview.call(Slot.WV_GO_BACK)

    def go_forward(self) -> None:
        if self.ready:
            self.webview.call(Slot.WV_GO_FORWARD)

    def source(self) -> str:
        return self.webview.get_string(Slot.WV_GET_SOURCE) if self.ready else ""

    def title(self) -> str:
        return self.webview.get_string(Slot.WV_GET_TITLE) if self.ready else ""

    def can_go_back(self) -> bool:
        return self.ready and self.webview.get_bool(Slot.WV_GET_CAN_GO_BACK)

    def can_go_forward(self) -> bool:
        return self.ready and self.webview.get_bool(Slot.WV_GET_CAN_GO_FORWARD)

    def add_script(self, script: str) -> None:
        """Run ``script`` at the start of every document (before page script)."""
        self._scripts.append(script)
        if self.ready:
            self._add_script_now(script)

    def _add_script_now(self, script: str) -> None:
        handler = Handler(IID["AddScriptCompleted"], None, "hr_string")
        try:
            self.webview.call(Slot.WV_ADD_SCRIPT_ON_DOCUMENT_CREATED, (c_wchar_p, c_void_p), script, handler.ptr)
        finally:
            handler.release()

    def set_bounds(self, width: int, height: int) -> None:
        self._bounds = (max(0, int(width)), max(0, int(height)))
        if self.ready:
            self._push_bounds()

    def _push_bounds(self) -> None:
        width, height = self._bounds
        self.controller.call(Slot.CTRL_PUT_BOUNDS, (RECT,), RECT(0, 0, width, height))

    def set_visible(self, visible: bool) -> None:
        changed = bool(visible) != self._visible
        self._visible = bool(visible)
        if self.ready:
            self.controller.put_bool(Slot.CTRL_PUT_IS_VISIBLE, self._visible)
            if changed:
                self.set_memory_low(not self._visible)

    def set_memory_low(self, low: bool) -> None:
        """Hidden pages ask the browser processes to trim memory (ICoreWebView2_19, runtime 114+)."""
        if not self.ready:
            return
        webview19 = self.webview.query(IID["WebView2_19"])
        if webview19 is not None:
            webview19.call(Slot.WV19_PUT_MEMORY_TARGET, (c_int32,), 1 if low else 0)
            webview19.release()

    def set_zoom(self, factor: float) -> None:
        self._zoom = max(0.25, min(5.0, float(factor)))
        if self.ready:
            self.controller.put_double(Slot.CTRL_PUT_ZOOM, self._zoom)

    def zoom(self) -> float:
        return self._zoom

    def set_background(self, alpha: int, red: int, green: int, blue: int) -> None:
        """Page background before the page paints; alpha 0 = transparent."""
        self._background = (int(alpha), int(red), int(green), int(blue))
        if self.ready:
            self._push_background()

    def _push_background(self) -> None:
        controller2 = self.controller.query(IID["Controller2"])
        if controller2 is not None:
            controller2.call(Slot.CTRL2_PUT_BACKGROUND, (COLOR,), COLOR(*self._background))
            controller2.release()

    def notify_moved(self) -> None:
        """The host window moved (keeps popups and IME windows in place)."""
        if self.ready:
            self.controller.call(Slot.CTRL_NOTIFY_PARENT_MOVED)

    def focus(self) -> None:
        if self.ready:
            self.controller.call(Slot.CTRL_MOVE_FOCUS, (c_int32,), MOVE_FOCUS_PROGRAMMATIC)

    def suspend(self) -> None:
        """Freeze script and timers of a hidden page (ICoreWebView2_3)."""
        if not self.ready:
            return
        webview3 = self.webview.query(IID["WebView2_3"])
        if webview3 is not None:
            handler = Handler(IID["TrySuspendCompleted"], None, "hr_bool")
            try:
                webview3.call(Slot.WV3_TRY_SUSPEND, (c_void_p,), handler.ptr)
            finally:
                handler.release()
                webview3.release()

    def resume(self) -> None:
        if not self.ready:
            return
        webview3 = self.webview.query(IID["WebView2_3"])
        if webview3 is not None:
            webview3.call(Slot.WV3_RESUME)
            webview3.release()

    def close(self) -> None:
        if self.state == "closed":
            return
        self.state = "closed"
        for name in _CALLBACKS:
            setattr(self, name, None)
        for operation in self._downloads:
            operation.release()
        self._downloads.clear()
        webview, controller, environment = self.webview, self.controller, self.environment
        self.webview = self.controller = self.environment = None
        if controller is not None:
            try:
                controller.call(Slot.CTRL_CLOSE)
            except OSError:
                pass
        if webview is not None:
            webview.release()
        if controller is not None:
            controller.release()
        if environment is not None:
            environment.release()


# Native helpers for the host window -------------------------------------------------
class _BitmapInfo(Structure):
    _fields_ = [("biSize", c_uint32), ("biWidth", c_int32), ("biHeight", c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", c_uint32), ("biSizeImage", c_uint32),
                ("biXPelsPerMeter", c_int32), ("biYPelsPerMeter", c_int32), ("biClrUsed", c_uint32),
                ("biClrImportant", c_uint32), ("bmiColors", c_uint32 * 3)]


_win32 = None
_GWL_STYLE = -16
_GWLP_HWNDPARENT = -8
_WS_CLIPCHILDREN = 0x02000000
_GW_HWNDPREV = 3
_SWP_FLAGS = 0x0001 | 0x0002 | 0x0010 | 0x0200  # NOSIZE | NOMOVE | NOACTIVATE | NOOWNERZORDER


def _win():
    global _win32
    if _win32 is None:
        user32, gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
        handle = c_void_p
        wide = struct.calcsize("P") == 8

        def bind(dll, name, restype, *argtypes):
            function = getattr(dll, name)
            function.restype = restype
            function.argtypes = list(argtypes)
            return function

        ns = SimpleNamespace()
        ns.GetClientRect = bind(user32, "GetClientRect", BOOL, handle, POINTER(RECT))
        ns.GetWindow = bind(user32, "GetWindow", handle, handle, c_uint32)
        ns.SetWindowPos = bind(user32, "SetWindowPos", BOOL, handle, handle, c_int32, c_int32, c_int32, c_int32,
                               c_uint32)
        ns.GetWindowLong = bind(user32, "GetWindowLongPtrW" if wide else "GetWindowLongW", c_ssize_t, handle,
                                c_int32)
        ns.SetWindowLong = bind(user32, "SetWindowLongPtrW" if wide else "SetWindowLongW", c_ssize_t, handle,
                                c_int32, c_ssize_t)
        ns.PrintWindow = bind(user32, "PrintWindow", BOOL, handle, handle, c_uint32)
        ns.GetDC = bind(user32, "GetDC", handle, handle)
        ns.ReleaseDC = bind(user32, "ReleaseDC", c_int32, handle, handle)
        ns.CreateCompatibleDC = bind(gdi32, "CreateCompatibleDC", handle, handle)
        ns.CreateDIBSection = bind(gdi32, "CreateDIBSection", handle, handle, c_void_p, c_uint32,
                                   POINTER(c_void_p), handle, c_uint32)
        ns.SelectObject = bind(gdi32, "SelectObject", handle, handle, handle)
        ns.DeleteObject = bind(gdi32, "DeleteObject", BOOL, handle)
        ns.DeleteDC = bind(gdi32, "DeleteDC", BOOL, handle)
        try:
            ns.DwmSetWindowAttribute = bind(ctypes.WinDLL("dwmapi"), "DwmSetWindowAttribute", HRESULT, handle,
                                            c_uint32, c_void_p, c_uint32)
        except (OSError, AttributeError):
            ns.DwmSetWindowAttribute = None
        _win32 = ns
    return _win32


def client_size(hwnd: int) -> tuple | None:
    """Client size of ``hwnd`` in physical pixels."""
    if not IS_WINDOWS or not hwnd:
        return None
    rect = RECT()
    if not _win().GetClientRect(hwnd, byref(rect)):
        return None
    return rect.right - rect.left, rect.bottom - rect.top


def capture_window(hwnd: int) -> tuple | None:
    """``(width, height, BGRX bytes)`` of ``hwnd``, GPU-composited content included."""
    size = client_size(hwnd)
    if not size or size[0] < 2 or size[1] < 2:
        return None
    width, height = size
    win = _win()
    screen = win.GetDC(None)
    memory = win.CreateCompatibleDC(screen)
    info = _BitmapInfo(biSize=40, biWidth=width, biHeight=-height, biPlanes=1, biBitCount=32)
    bits = c_void_p()
    bitmap = win.CreateDIBSection(screen, byref(info), 0, byref(bits), None, 0)
    try:
        if not memory or not bitmap or not bits.value:
            return None
        previous = win.SelectObject(memory, bitmap)
        ok = win.PrintWindow(hwnd, memory, 0x1 | 0x2)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT
        win.SelectObject(memory, previous)
        if not ok:
            return None
        return width, height, ctypes.string_at(bits.value, width * height * 4)
    finally:
        if bitmap:
            win.DeleteObject(bitmap)
        if memory:
            win.DeleteDC(memory)
        if screen:
            win.ReleaseDC(None, screen)


def ensure_owner(hwnd: int, owner: int) -> None:
    """Make ``owner`` own ``hwnd``: it then always stays just above it."""
    if not IS_WINDOWS or not hwnd or not owner:
        return
    win = _win()
    if int(win.GetWindowLong(hwnd, _GWLP_HWNDPARENT) or 0) != int(owner):
        win.SetWindowLong(hwnd, _GWLP_HWNDPARENT, int(owner))


def place_above(hwnd: int, owner: int) -> None:
    """Put ``hwnd`` directly above ``owner`` in the Z order, without activating."""
    if not IS_WINDOWS or not hwnd or not owner:
        return
    win = _win()
    above = win.GetWindow(owner, _GW_HWNDPREV)
    if above and int(above) == int(hwnd):
        return
    win.SetWindowPos(hwnd, above or None, 0, 0, 0, 0, _SWP_FLAGS)


def set_clip_children(hwnd: int, enabled: bool) -> None:
    """Transparent pages need the host's own pixels underneath the page."""
    if not IS_WINDOWS or not hwnd:
        return
    win = _win()
    style = int(win.GetWindowLong(hwnd, _GWL_STYLE) or 0)
    wanted = style | _WS_CLIPCHILDREN if enabled else style & ~_WS_CLIPCHILDREN
    if wanted != style:
        win.SetWindowLong(hwnd, _GWL_STYLE, wanted)


def round_corners(hwnd: int) -> None:
    """Small rounded corners without a border (Windows 11; ignored before)."""
    if not IS_WINDOWS or not hwnd:
        return
    set_attribute = _win().DwmSetWindowAttribute
    if set_attribute is None:
        return
    corner = c_int32(3)  # DWMWCP_ROUNDSMALL
    set_attribute(hwnd, 33, byref(corner), 4)  # DWMWA_WINDOW_CORNER_PREFERENCE
    border = c_uint32(0xFFFFFFFE)  # DWMWA_COLOR_NONE
    set_attribute(hwnd, 34, byref(border), 4)  # DWMWA_BORDER_COLOR


__all__ = [
    "Browser",
    "Com",
    "Handler",
    "Runtime",
    "RUNTIME_DOWNLOAD_URL",
    "capture_window",
    "client_size",
    "describe",
    "ensure_owner",
    "install_runtime",
    "loader_path",
    "place_above",
    "round_corners",
    "runtime",
    "set_clip_children",
]
