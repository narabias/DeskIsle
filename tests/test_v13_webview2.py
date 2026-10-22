"""WebView2 web islands: the ctypes binding against fake COM objects.

The fakes below are real native COM objects -- vtables of ctypes callbacks --
so ``deskisle/webview2.py`` runs exactly the pointer plumbing, reference
counting and event callbacks it runs against Microsoft Edge WebView2, on any
platform and without the runtime installed.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import tempfile
import unittest
import uuid
from ctypes import POINTER, c_double, c_int32, c_int64, c_void_p, c_wchar_p
from pathlib import Path
from unittest import mock

from deskisle import webview2  # noqa: E402
from deskisle.webview2 import (  # noqa: E402
    BOOL,
    COLOR,
    DOWNLOAD_COMPLETED,
    DOWNLOAD_IN_PROGRESS,
    E_ACCESSDENIED,
    E_FILE_NOT_FOUND,
    E_NOINTERFACE,
    E_NOTIMPL,
    HRESULT,
    IID,
    PERMISSION_DENY,
    PRIVATE_PROFILE,
    PROCESS_BROWSER_EXITED,
    PROCESS_RENDER_EXITED,
    RECT,
    RUNTIME_DOWNLOAD_URL,
    S_OK,
    ULONG,
    Browser,
    Handler,
    Runtime,
    Slot,
    vcall,
)

SLOTS = 112
VERSION = "131.0.2903.70"
_IUNKNOWN = uuid.UUID(IID["IUnknown"]).bytes_le
_buffers: list = []  # strings handed out by the fakes (the binding never frees them here)
ERRORS: list = []  # exceptions raised inside fake COM methods


def _iid(name: str) -> bytes:
    return uuid.UUID(IID[name]).bytes_le


def _plain(value):
    if isinstance(value, RECT):
        return (value.left, value.top, value.right, value.bottom)
    if isinstance(value, COLOR):
        return (value.A, value.R, value.G, value.B)
    return value


class FakeCom:
    """A native COM object whose methods are Python callables."""

    def __init__(self, name: str, *interfaces: str) -> None:
        self.name = name
        self.refs = 1  # owned by the test
        self.iids = {_IUNKNOWN} | {_iid(interface) for interface in interfaces}
        self.calls: list = []
        self.values: dict = {}
        self.handlers: dict = {}
        self._natives: list = []
        self._vtable = (c_void_p * SLOTS)()
        self._object = (c_void_p * 1)(ctypes.addressof(self._vtable))
        self.ptr = ctypes.addressof(self._object)
        for slot in range(3, SLOTS):
            self.define(slot, (), lambda: E_NOTIMPL, record=False)
        self.define(0, (c_void_p, POINTER(c_void_p)), self._query, record=False)
        self.define(1, (), self._add_ref, restype=ULONG, record=False)
        self.define(2, (), self._release, restype=ULONG, record=False)

    # Plumbing ------------------------------------------------------------
    def define(self, slot: int, argtypes: tuple, function, restype=HRESULT, record: bool = True) -> "FakeCom":
        def thunk(_this, *args):
            try:
                if record:
                    self.calls.append((slot,) + tuple(_plain(arg) for arg in args))
                result = function(*args)
            except Exception as exc:  # surfaced by the tests' tearDown
                ERRORS.append("{0}[{1}]: {2!r}".format(self.name, slot, exc))
                return -1
            return S_OK if result is None else result

        native = webview2.FUNCTYPE(restype, c_void_p, *argtypes)(thunk)
        self._natives.append(native)
        self._vtable[slot] = ctypes.cast(native, c_void_p).value
        return self

    def _query(self, riid, out):
        if ctypes.string_at(riid, 16) in self.iids:
            self.refs += 1
            out[0] = self.ptr
            return S_OK
        out[0] = None
        return E_NOINTERFACE

    def _add_ref(self):
        self.refs += 1
        return self.refs

    def _release(self):
        self.refs -= 1
        return max(0, self.refs)

    # Method builders -------------------------------------------------------
    def setter(self, slot: int, ctype, name: str) -> "FakeCom":
        return self.define(slot, (ctype,), lambda value: self.values.__setitem__(name, _plain(value)))

    def action(self, slot: int, name: str) -> "FakeCom":
        return self.define(slot, (), lambda: self.values.__setitem__(name, self.values.get(name, 0) + 1))

    def getter_value(self, slot: int, ctype, source) -> "FakeCom":
        def get(out):
            out[0] = source()
        return self.define(slot, (POINTER(ctype),), get)

    def getter_string(self, slot: int, source) -> "FakeCom":
        def get(out):
            text = source()
            if text is None:
                out[0] = None
                return
            buffer = ctypes.create_unicode_buffer(text)
            _buffers.append(buffer)
            out[0] = ctypes.addressof(buffer)
        return self.define(slot, (POINTER(c_void_p),), get)

    def getter_object(self, slot: int, target: "FakeCom") -> "FakeCom":
        def get(out):
            target.refs += 1  # COM getters hand out a new reference
            out[0] = target.ptr
        return self.define(slot, (POINTER(c_void_p),), get)

    def event(self, slot: int) -> "FakeCom":
        def add(handler, token):
            vcall(handler, 1, restype=ULONG)  # an event source keeps its handlers
            self.handlers.setdefault(slot, []).append(handler)
            token[0] = len(self.handlers[slot])
        return self.define(slot, (c_void_p, POINTER(c_int64)), add)

    def fire(self, slot: int, args: "FakeCom | None" = None) -> int:
        handlers = list(self.handlers.get(slot, ()))
        for handler in handlers:
            vcall(handler, 3, (c_void_p, c_void_p), self.ptr, args.ptr if args is not None else None)
        return len(handlers)

    def drop_handlers(self) -> None:
        """What the runtime does when the object goes away."""
        for handlers in self.handlers.values():
            for handler in handlers:
                vcall(handler, 2, restype=ULONG)
        self.handlers.clear()


WEBVIEW_EVENTS = (Slot.WV_ADD_NAVIGATION_STARTING, Slot.WV_ADD_CONTENT_LOADING, Slot.WV_ADD_SOURCE_CHANGED,
                  Slot.WV_ADD_HISTORY_CHANGED, Slot.WV_ADD_NAVIGATION_COMPLETED, Slot.WV_ADD_PERMISSION_REQUESTED,
                  Slot.WV_ADD_PROCESS_FAILED, Slot.WV_ADD_NEW_WINDOW_REQUESTED, Slot.WV_ADD_TITLE_CHANGED,
                  Slot.WV_ADD_WEB_RESOURCE_REQUESTED, Slot.WV4_ADD_DOWNLOAD_STARTING,
                  Slot.WV11_ADD_CONTEXT_MENU_REQUESTED)


class FakeWorld:
    """Environment, controller, webview and settings of one fake runtime."""

    def __init__(self, *, environment10: bool = True) -> None:
        self.version = VERSION
        self.title = "Fake page"
        self.source = "about:blank"
        self.back = False
        self.forward = False
        self.zoom = 1.0
        self.requests: list = []  # pending controller creations
        self.responses: list = []
        self.environment = FakeCom("environment", *(("Environment10",) if environment10 else ()))
        self.options = FakeCom("options")
        self.controller = FakeCom("controller", "Controller2", "Controller4")
        self.webview = FakeCom("webview", "WebView2_3", "WebView2_4", "WebView2_11")
        self.settings = FakeCom("settings")

        env = self.environment
        env.define(Slot.ENV_CREATE_CONTROLLER, (c_void_p, c_void_p),
                   lambda hwnd, handler: self._request("plain", hwnd, handler))
        env.define(Slot.ENV_CREATE_RESPONSE, (c_void_p, c_int32, c_wchar_p, c_wchar_p, POINTER(c_void_p)),
                   self._create_response)
        env.getter_string(Slot.ENV_BROWSER_VERSION, lambda: self.version)
        if environment10:
            env.getter_object(Slot.ENV10_CREATE_OPTIONS, self.options)
            env.define(Slot.ENV10_CREATE_CONTROLLER_WITH_OPTIONS, (c_void_p, c_void_p, c_void_p),
                       lambda hwnd, options, handler: self._request("options", hwnd, handler))
        self.options.setter(Slot.OPTIONS_PUT_PROFILE_NAME, c_wchar_p, "profile")
        self.options.setter(Slot.OPTIONS_PUT_IN_PRIVATE, BOOL, "private")

        ctl = self.controller
        ctl.setter(Slot.CTRL_PUT_IS_VISIBLE, BOOL, "visible")
        ctl.setter(Slot.CTRL_PUT_BOUNDS, RECT, "bounds")
        ctl.getter_value(Slot.CTRL_GET_ZOOM, c_double, lambda: self.zoom)
        ctl.setter(Slot.CTRL_PUT_ZOOM, c_double, "zoom")
        ctl.event(Slot.CTRL_ADD_ZOOM_CHANGED)
        ctl.setter(Slot.CTRL_MOVE_FOCUS, c_int32, "focus")
        ctl.action(Slot.CTRL_NOTIFY_PARENT_MOVED, "moved")
        ctl.action(Slot.CTRL_CLOSE, "closed")
        ctl.getter_object(Slot.CTRL_GET_WEBVIEW, self.webview)
        ctl.setter(Slot.CTRL2_PUT_BACKGROUND, COLOR, "background")
        ctl.setter(Slot.CTRL4_PUT_ALLOW_EXTERNAL_DROP, BOOL, "external_drop")

        wv = self.webview
        wv.getter_object(Slot.WV_GET_SETTINGS, self.settings)
        wv.getter_string(Slot.WV_GET_SOURCE, lambda: self.source)
        wv.setter(Slot.WV_NAVIGATE, c_wchar_p, "navigate")
        wv.setter(Slot.WV_NAVIGATE_TO_STRING, c_wchar_p, "html")
        for slot in WEBVIEW_EVENTS:
            wv.event(slot)
        wv.define(Slot.WV_ADD_SCRIPT_ON_DOCUMENT_CREATED, (c_wchar_p, c_void_p), self._add_script)
        for slot, name in ((Slot.WV_RELOAD, "reload"), (Slot.WV_GO_BACK, "back"), (Slot.WV_GO_FORWARD, "forward"),
                           (Slot.WV_STOP, "stop"), (Slot.WV3_RESUME, "resume")):
            wv.action(slot, name)
        wv.getter_value(Slot.WV_GET_CAN_GO_BACK, BOOL, lambda: int(self.back))
        wv.getter_value(Slot.WV_GET_CAN_GO_FORWARD, BOOL, lambda: int(self.forward))
        wv.getter_string(Slot.WV_GET_TITLE, lambda: self.title)
        wv.define(Slot.WV_ADD_WEB_RESOURCE_FILTER, (c_wchar_p, c_int32),
                  lambda uri, context: wv.values.__setitem__("filter", (uri, context)))
        wv.define(Slot.WV3_TRY_SUSPEND, (c_void_p,), self._try_suspend)

        for slot, name in ((Slot.SET_PUT_SCRIPT_DIALOGS, "script_dialogs"), (Slot.SET_PUT_STATUS_BAR, "status_bar"),
                           (Slot.SET_PUT_DEVTOOLS, "devtools"), (Slot.SET_PUT_CONTEXT_MENUS, "context_menus"),
                           (Slot.SET_PUT_ZOOM_CONTROL, "zoom_control")):
            self.settings.setter(slot, BOOL, name)

    def objects(self) -> tuple:
        return (self.environment, self.options, self.controller, self.webview, self.settings)

    def _request(self, kind: str, hwnd, handler) -> None:
        vcall(handler, 1, restype=ULONG)
        self.requests.append((kind, hwnd, handler))

    def complete_controller(self, hr: int = S_OK, controller: FakeCom | None = None) -> str:
        kind, _hwnd, handler = self.requests.pop(0)
        target = controller if controller is not None else (self.controller if hr >= 0 else None)
        vcall(handler, 3, (HRESULT, c_void_p), hr, target.ptr if target is not None else None)
        vcall(handler, 2, restype=ULONG)
        return kind

    def _create_response(self, _stream, status, reason, headers, out) -> None:
        response = FakeCom("response")
        self.responses.append((status, reason, headers, response))
        out[0] = response.ptr  # the caller owns this reference

    def _add_script(self, script, handler) -> None:
        self.webview.values.setdefault("scripts", []).append(script)
        vcall(handler, 3, (HRESULT, c_wchar_p), S_OK, "script-1")

    def _try_suspend(self, handler) -> None:
        self.webview.values["suspend"] = self.webview.values.get("suspend", 0) + 1
        vcall(handler, 3, (HRESULT, BOOL), S_OK, 1)

    def release_everything(self) -> None:
        for fake in self.objects():
            fake.drop_handlers()


class FakeLoader:
    """Stands in for ``WebView2Loader.dll``."""

    def __init__(self, world: FakeWorld, hr: int = S_OK) -> None:
        self.world = world
        self.hr = hr
        self.folders: list = []
        self.handlers: list = []
        self.com_initialized = 0

    def browser_version(self) -> tuple:
        return self.hr, (self.world.version if self.hr >= 0 else "")

    def initialize_com(self) -> int:
        self.com_initialized += 1
        return S_OK

    def create_environment(self, folder: str, handler: int) -> int:
        vcall(handler, 1, restype=ULONG)
        self.folders.append(folder)
        self.handlers.append(handler)
        return S_OK

    def complete(self, hr: int = S_OK) -> None:
        handler = self.handlers.pop(0)
        environment = self.world.environment if hr >= 0 else None
        vcall(handler, 3, (HRESULT, c_void_p), hr, environment.ptr if environment is not None else None)
        vcall(handler, 2, restype=ULONG)


def args_object(name: str, **getters) -> FakeCom:
    """Event arguments: ``uri=…`` / ``success=…`` / ``status=…`` / ``kind=…``."""
    fake = FakeCom(name)
    for key, value in getters.items():
        if key == "uri":
            fake.getter_string(3, lambda value=value: value)
        elif key == "success":
            fake.getter_value(Slot.NAV_COMPLETED_GET_IS_SUCCESS, BOOL, lambda value=value: int(value))
        elif key == "status":
            fake.getter_value(Slot.NAV_COMPLETED_GET_ERROR, c_int32, lambda value=value: value)
        elif key == "kind":
            fake.getter_value(Slot.PROCESS_FAILED_GET_KIND, c_int32, lambda value=value: value)
    return fake


class _FakeRuntimeCase(unittest.TestCase):
    def setUp(self) -> None:
        ERRORS.clear()
        self._environ = mock.patch.dict(os.environ)
        self._environ.start()
        for name in ("DESKISLE_DISABLE_WEBENGINE", "DESKISLE_DISABLE_WEBVIEW2"):
            os.environ.pop(name, None)
        webview2.set_string_free(lambda _ptr: None)  # the fakes keep their own buffers
        self.root = Path(tempfile.mkdtemp(prefix="deskisle-wv2-"))
        self.world = FakeWorld()
        self.loader = FakeLoader(self.world)
        self.runtime = Runtime(loader_factory=lambda: self.loader)
        self.runtime.data_folder = str(self.root / "WebView2")
        self.handlers_before = len(Handler.live)

    def tearDown(self) -> None:
        self.runtime.shutdown()
        webview2.set_string_free(None)
        self._environ.stop()
        shutil.rmtree(self.root, ignore_errors=True)
        self.assertEqual(ERRORS, [])

    def ready_browser(self, **options) -> Browser:
        browser = Browser(0x1234, runtime_=self.runtime, **options)
        events = self.events = []
        browser.on_ready = lambda: events.append(("ready",))
        browser.on_failed = lambda hr: events.append(("failed", hr))
        browser.start()
        if self.runtime.env_state == "creating":
            self.loader.complete()
        self.world.complete_controller()
        self.assertTrue(browser.ready)
        return browser


class HandlerTests(_FakeRuntimeCase):
    def test_handler_reference_counting_and_query_interface(self) -> None:
        calls = []
        handler = Handler(IID["NavigationCompleted"], lambda sender, args: calls.append((sender, args)))
        out = c_void_p()
        hr = vcall(handler.ptr, 0, (c_void_p, POINTER(c_void_p)),
                   ctypes.addressof(webview2.guid(IID["NavigationCompleted"])), ctypes.byref(out))
        self.assertEqual((hr, out.value, handler.refs), (S_OK, handler.ptr, 2))
        hr = vcall(handler.ptr, 0, (c_void_p, POINTER(c_void_p)),
                   ctypes.addressof(webview2.guid(IID["IUnknown"])), ctypes.byref(out))
        self.assertEqual((hr, handler.refs), (S_OK, 3))
        hr = vcall(handler.ptr, 0, (c_void_p, POINTER(c_void_p)),
                   ctypes.addressof(webview2.guid(IID["SourceChanged"])), ctypes.byref(out))
        self.assertEqual((hr, out.value), (E_NOINTERFACE, None))
        vcall(handler.ptr, 3, (c_void_p, c_void_p), 11, 22)
        self.assertEqual(calls, [(11, 22)])
        for expected in (2, 1, 0):
            self.assertEqual(vcall(handler.ptr, 2, restype=ULONG), expected)
        self.assertNotIn(handler.ptr, Handler.live)
        # A late call after the last release is ignored instead of crashing.
        self.assertEqual(vcall(handler.ptr, 3, (c_void_p, c_void_p), 1, 2), S_OK)
        self.assertEqual(calls, [(11, 22)])

    def test_exceptions_never_unwind_into_the_runtime(self) -> None:
        def broken(_sender, _args):
            raise RuntimeError("boom")

        handler = Handler(IID["SourceChanged"], broken)
        with self.assertLogs("deskisle.webview2", level="ERROR"):
            self.assertEqual(vcall(handler.ptr, 3, (c_void_p, c_void_p), None, None), S_OK)
        handler.release()

    def test_completion_handler_signatures(self) -> None:
        seen = []
        for signature, argtypes, value in (("hr_object", (HRESULT, c_void_p), 0x55),
                                           ("hr_string", (HRESULT, c_wchar_p), "id-7"),
                                           ("hr_bool", (HRESULT, BOOL), 1)):
            handler = Handler(IID["EnvironmentCompleted"], lambda hr, result: seen.append((hr, result)), signature)
            vcall(handler.ptr, 3, argtypes, E_ACCESSDENIED, value)
            handler.release()
        self.assertEqual(seen, [(E_ACCESSDENIED, 0x55), (E_ACCESSDENIED, "id-7"), (E_ACCESSDENIED, 1)])


class RuntimeTests(_FakeRuntimeCase):
    def test_states(self) -> None:
        self.assertEqual(self.runtime.state(), "ok")
        self.assertEqual(self.runtime.version, VERSION)
        os.environ["DESKISLE_DISABLE_WEBVIEW2"] = "1"
        self.assertEqual(self.runtime.state(), "disabled")
        self.assertFalse(self.runtime.available())
        del os.environ["DESKISLE_DISABLE_WEBVIEW2"]

        def missing():
            raise OSError("WebView2Loader.dll not found")

        self.assertEqual(Runtime(loader_factory=missing).state(), "no-loader")
        no_runtime = Runtime(loader_factory=lambda: FakeLoader(self.world, hr=E_FILE_NOT_FOUND))
        self.assertEqual(no_runtime.state(), "no-runtime")
        self.assertIn("未找到", no_runtime.detail)
        if os.name != "nt":
            self.assertEqual(Runtime().state(), "unsupported")

    def test_one_shared_environment_in_the_data_folder(self) -> None:
        results = []
        self.runtime.request_environment(lambda env, hr: results.append((env, hr)))
        self.runtime.request_environment(lambda env, hr: results.append((env, hr)))
        self.assertEqual(self.runtime.env_state, "creating")
        self.assertEqual(self.loader.folders, [str(self.root / "WebView2")])
        self.assertTrue((self.root / "WebView2").is_dir())
        self.assertEqual(self.loader.com_initialized, 1)
        self.loader.complete()
        self.assertEqual(self.runtime.env_state, "ready")
        self.assertEqual([hr for _env, hr in results], [S_OK, S_OK])
        self.assertEqual({env.ptr for env, _hr in results}, {self.world.environment.ptr})
        self.assertEqual(self.world.environment.refs, 2)  # test + runtime
        self.runtime.request_environment(lambda env, hr: results.append((env, hr)))
        self.assertEqual(len(results), 3)  # served at once
        self.runtime.shutdown()
        self.assertEqual(self.world.environment.refs, 1)

    def test_failed_environment(self) -> None:
        browser = Browser(1, runtime_=self.runtime)
        failures = []
        browser.on_failed = failures.append
        browser.start()
        self.loader.complete(E_ACCESSDENIED)
        self.assertEqual(failures, [E_ACCESSDENIED])
        self.assertEqual(browser.state, "failed")
        self.assertEqual(self.runtime.state(), "failed")
        self.assertIn("无法写入", self.runtime.detail)
        self.runtime.reset()
        self.assertEqual(self.runtime.state(), "ok")


class BrowserTests(_FakeRuntimeCase):
    def test_settings_pending_state_and_subscriptions(self) -> None:
        browser = Browser(0x1234, runtime_=self.runtime, settings={"status_bar": False})
        ready = []
        browser.on_ready = lambda: ready.append(True)
        browser.set_bounds(300, 200)
        browser.set_zoom(1.25)
        browser.set_visible(False)
        browser.navigate("https://example.com/")
        browser.add_script("window.answer = 42;")
        browser.start()
        self.loader.complete()
        self.assertEqual(self.world.complete_controller(), "plain")
        self.assertEqual(ready, [True])
        controller, webview, settings = self.world.controller, self.world.webview, self.world.settings
        self.assertEqual(controller.values["bounds"], (0, 0, 300, 200))
        self.assertEqual(controller.values["zoom"], 1.25)
        self.assertEqual(controller.values["visible"], 0)
        self.assertEqual(controller.values["external_drop"], 0)
        self.assertEqual(webview.values["navigate"], "https://example.com/")
        self.assertEqual(webview.values["scripts"], ["window.answer = 42;"])
        self.assertEqual(settings.values, {"script_dialogs": 1, "status_bar": 0, "devtools": 0,
                                           "context_menus": 1, "zoom_control": 1})
        for slot in WEBVIEW_EVENTS:
            if slot in (Slot.WV_ADD_WEB_RESOURCE_REQUESTED, Slot.WV11_ADD_CONTEXT_MENU_REQUESTED):
                self.assertNotIn(slot, webview.handlers)  # no network filter / Edge's own menu
            else:
                self.assertEqual(len(webview.handlers[slot]), 1, slot)
        self.assertEqual(len(controller.handlers[Slot.CTRL_ADD_ZOOM_CHANGED]), 1)
        self.assertNotIn("filter", webview.values)
        # Settings / QueryInterface results were released again.
        self.assertEqual((settings.refs, webview.refs, controller.refs), (1, 2, 2))

        browser.set_bounds(640, 480)
        browser.notify_moved()
        browser.focus()
        browser.reload()
        browser.go_back()
        browser.go_forward()
        browser.stop()
        self.assertEqual(controller.values["bounds"], (0, 0, 640, 480))
        self.assertEqual((controller.values["moved"], controller.values["focus"]), (1, 0))
        self.assertEqual([webview.values[name] for name in ("reload", "back", "forward", "stop")], [1, 1, 1, 1])
        self.world.title, self.world.source, self.world.back = "标题", "https://example.com/a", True
        self.assertEqual((browser.title(), browser.source()), ("标题", "https://example.com/a"))
        self.assertEqual((browser.can_go_back(), browser.can_go_forward()), (True, False))

        browser.close()
        self.assertEqual(controller.values["closed"], 1)
        self.assertEqual((webview.refs, controller.refs, self.world.environment.refs), (1, 1, 2))
        self.world.release_everything()
        self.assertEqual(len(Handler.live), self.handlers_before)

    def test_private_profile_and_transparent_background(self) -> None:
        browser = Browser(7, runtime_=self.runtime, private=True)
        browser.set_background(0, 0, 0, 0)
        browser.start()
        self.loader.complete()
        self.assertEqual(self.world.complete_controller(), "options")
        self.assertEqual(self.world.options.values, {"profile": PRIVATE_PROFILE, "private": 1})
        self.assertEqual(self.world.options.refs, 1)
        self.assertEqual(self.world.controller.values["background"], (0, 0, 0, 0))
        browser.close()

    def test_private_falls_back_without_environment10(self) -> None:
        self.world = FakeWorld(environment10=False)
        self.loader.world = self.world
        browser = Browser(7, runtime_=self.runtime, private=True)
        browser.start()
        self.loader.complete()
        self.assertEqual(self.world.complete_controller(), "plain")
        self.assertTrue(browser.ready)
        browser.close()

    def test_network_filter_answers_403(self) -> None:
        browser = self.ready_browser(private=True, network_filter=lambda uri: uri.startswith("https:"))
        webview = self.world.webview
        self.assertEqual(webview.values["filter"], ("*", webview2.RESOURCE_CONTEXT_ALL))
        for uri, blocked in (("https://tracker.example/x.js", True), ("file:///C:/anim/index.html", False)):
            request = args_object("request", uri=uri)
            event = FakeCom("resource args").getter_object(Slot.RESOURCE_ARGS_GET_REQUEST, request)
            event.setter(Slot.RESOURCE_ARGS_PUT_RESPONSE, c_void_p, "response")
            webview.fire(Slot.WV_ADD_WEB_RESOURCE_REQUESTED, event)
            self.assertEqual(request.refs, 1)
            self.assertEqual("response" in event.values, blocked, uri)
        status, reason, _headers, response = self.world.responses[0]
        self.assertEqual((status, reason, len(self.world.responses)), (403, "Blocked by DeskIsle", 1))
        self.assertEqual(response.refs, 0)  # the fake args do not keep it; the binding released its own
        browser.close()

    def test_events_reach_the_callbacks(self) -> None:
        browser = self.ready_browser(settings={"custom_context_menu": True})
        seen = []
        browser.on_title = lambda title: seen.append(("title", title))
        browser.on_source = lambda url: seen.append(("source", url))
        browser.on_history = lambda back, forward: seen.append(("history", back, forward))
        browser.on_navigation_starting = lambda uri: seen.append(("starting", uri))
        browser.on_content_loading = lambda: seen.append(("loading",))
        browser.on_navigation_completed = lambda ok, status: seen.append(("completed", ok, status))
        browser.on_new_window = lambda uri: seen.append(("new window", uri))
        browser.on_context_menu = lambda: seen.append(("menu",)) or True
        browser.on_zoom = lambda factor: seen.append(("zoom", factor))
        browser.on_process_failed = lambda kind: seen.append(("process", kind))
        webview, controller = self.world.webview, self.world.controller
        self.assertEqual(self.world.settings.values["context_menus"], 1)  # custom menu replaces Edge's

        self.world.title, self.world.source, self.world.back = "B 站", "https://www.bilibili.com/", True
        webview.fire(Slot.WV_ADD_TITLE_CHANGED)
        webview.fire(Slot.WV_ADD_SOURCE_CHANGED)
        webview.fire(Slot.WV_ADD_HISTORY_CHANGED)
        webview.fire(Slot.WV_ADD_NAVIGATION_STARTING, args_object("starting", uri="https://www.bilibili.com/"))
        webview.fire(Slot.WV_ADD_CONTENT_LOADING)
        webview.fire(Slot.WV_ADD_NAVIGATION_COMPLETED, args_object("completed", success=False, status=7))
        popup = args_object("new window", uri="https://passport.example/")
        popup.setter(Slot.NEW_WINDOW_PUT_HANDLED, BOOL, "handled")
        webview.fire(Slot.WV_ADD_NEW_WINDOW_REQUESTED, popup)
        permission = FakeCom("permission").setter(Slot.PERMISSION_PUT_STATE, c_int32, "state")
        webview.fire(Slot.WV_ADD_PERMISSION_REQUESTED, permission)
        menu = FakeCom("menu").setter(Slot.CONTEXT_MENU_PUT_HANDLED, BOOL, "handled")
        webview.fire(Slot.WV11_ADD_CONTEXT_MENU_REQUESTED, menu)
        self.world.zoom = 1.5
        controller.fire(Slot.CTRL_ADD_ZOOM_CHANGED)
        webview.fire(Slot.WV_ADD_PROCESS_FAILED, args_object("render", kind=PROCESS_RENDER_EXITED))

        self.assertEqual(seen, [
            ("title", "B 站"),
            ("source", "https://www.bilibili.com/"),
            ("history", True, False),
            ("starting", "https://www.bilibili.com/"),
            ("loading",),
            ("completed", False, 7),
            ("new window", "https://passport.example/"),
            ("menu",),
            ("zoom", 1.5),
            ("process", PROCESS_RENDER_EXITED),
        ])
        self.assertEqual(popup.values["handled"], 1)  # never a WebView2 popup window
        self.assertEqual(permission.values["state"], PERMISSION_DENY)
        self.assertEqual(menu.values["handled"], 1)
        self.assertEqual(browser.zoom(), 1.5)
        self.assertEqual(self.runtime.env_state, "ready")

        # The browser process ended: the shared environment has to be rebuilt.
        webview.fire(Slot.WV_ADD_PROCESS_FAILED, args_object("browser", kind=PROCESS_BROWSER_EXITED))
        self.assertEqual(seen[-1], ("process", PROCESS_BROWSER_EXITED))
        self.assertEqual(self.runtime.env_state, "idle")
        self.assertIsNone(self.runtime.environment)
        browser.close()

    def test_download_finished(self) -> None:
        browser = self.ready_browser()
        finished = []
        browser.on_download_finished = finished.append
        state = [DOWNLOAD_IN_PROGRESS]
        operation = FakeCom("download").event(Slot.DOWNLOAD_ADD_STATE_CHANGED)
        operation.getter_string(Slot.DOWNLOAD_GET_PATH, lambda: r"C:\Users\Julia\Downloads\a.zip")
        operation.getter_value(Slot.DOWNLOAD_GET_STATE, c_int32, lambda: state[0])
        starting = FakeCom("download args").getter_object(Slot.DOWNLOAD_ARGS_GET_OPERATION, operation)
        self.world.webview.fire(Slot.WV4_ADD_DOWNLOAD_STARTING, starting)
        self.assertEqual(operation.refs, 2)
        operation.fire(Slot.DOWNLOAD_ADD_STATE_CHANGED)
        self.assertEqual(finished, [])
        state[0] = DOWNLOAD_COMPLETED
        operation.fire(Slot.DOWNLOAD_ADD_STATE_CHANGED)
        self.assertEqual(finished, [r"C:\Users\Julia\Downloads\a.zip"])
        self.assertEqual(operation.refs, 1)
        operation.drop_handlers()
        browser.close()

    def test_suspend_and_resume(self) -> None:
        browser = self.ready_browser()
        browser.suspend()
        browser.resume()
        self.assertEqual((self.world.webview.values["suspend"], self.world.webview.values["resume"]), (1, 1))
        self.assertEqual(self.world.webview.refs, 2)
        browser.close()

    def test_close_before_the_controller_exists(self) -> None:
        browser = Browser(3, runtime_=self.runtime)
        browser.navigate("https://example.com/")
        browser.start()
        self.loader.complete()
        browser.close()
        self.world.complete_controller()  # arrives late: closed right away
        self.assertEqual(self.world.controller.values["closed"], 1)
        self.assertEqual(self.world.controller.refs, 1)
        self.assertNotIn("navigate", self.world.webview.values)
        self.assertEqual(self.world.environment.refs, 2)

    def test_controller_failure(self) -> None:
        browser = Browser(3, runtime_=self.runtime)
        failures = []
        browser.on_failed = failures.append
        browser.start()
        self.loader.complete()
        self.world.complete_controller(E_ACCESSDENIED)
        self.assertEqual((failures, browser.state), ([E_ACCESSDENIED], "failed"))
        self.assertEqual(self.world.environment.refs, 2)

    def test_loader_is_bundled_for_every_architecture(self) -> None:
        assets = Path(webview2.__file__).resolve().parent / "assets" / "webview2"
        for arch in ("x64", "x86", "arm64"):
            self.assertTrue((assets / arch / "WebView2Loader.dll").is_file(), arch)
        self.assertTrue((assets / "LICENSE.txt").is_file())
        self.assertIn(webview2.loader_arch(), ("x64", "x86", "arm64"))
        os.environ["DESKISLE_WEBVIEW2_LOADER"] = str(self.root / "custom.dll")
        self.assertEqual(webview2.loader_path(), self.root / "custom.dll")


if __name__ == "__main__":
    unittest.main()
