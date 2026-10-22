"""Model Context Protocol server over stdio (``DeskIsle.exe --mcp`` / ``deskisle-cli mcp``).

Pure Python: the bridge does not import Qt, it forwards every ``tools/call`` to
the running DeskIsle through the agent pipe (and starts DeskIsle when needed).
Messages are newline-delimited JSON-RPC 2.0 on stdin / stdout; logs go to
stderr.  Requests are served on worker threads so that ``ping`` keeps working
while a destructive tool waits for the user's confirmation.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
from pathlib import Path

from .. import __version__
from . import PROTOCOL_VERSION
from .client import AgentUnavailable, ensure_running, running_without_agent, send
from .schema import COMMANDS, from_mcp_name, input_schema, mcp_name

SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")
READ_ONLY = {"app.info", "schema", "confirm.status", "desk.state", "monitor.list", "page.list", "island.list",
             "island.get", "island.items", "item.loose", "web.status", "widget.types", "todo.list", "media.status",
             "weather.status", "clock.info", "search.query", "prefs.get", "theme.get", "custom.status",
             "custom.widget_read", "snapshot.list", "rules.list"}
GUIDE = Path(__file__).with_name("GUIDE.md")
INSTRUCTIONS = (
    "DeskIsle (桌屿) organises the Windows desktop into glass 'islands' (file islands, web pages, widgets) "
    "on per-monitor presets. Start with app_info or desk_state. Geometry is in board pixels (see monitor_list). "
    "Destructive tools (deletes, restores, quit) show a confirmation card on the user's desktop and wait for the "
    "answer; status=pending means the user has not answered yet - poll confirm_status. Use dry_run=true to "
    "preview them. Verify visual changes with app_screenshot. Custom widgets and theme tokens live in the custom "
    "folder (custom_status, custom_widget_create, theme_tokens); the accent colour always follows the wallpaper. "
    "Resource deskisle://guide has the full guide.")
MAX_IMAGE = 3 * 1024 * 1024
AGENT_OFF_HINT = "the switch 设置 → AI 与扩展 → 允许 AI 助手控制桌屿 must be on."
AGENT_OFF = ("DeskIsle (桌屿) is running, but its AI interface is switched off. Ask the user to turn on "
             "设置 → AI 与扩展 → 允许 AI 助手控制桌屿, then try again.")


def tool_list() -> list[dict]:
    tools = []
    for spec in COMMANDS:
        description = spec["description"]
        if spec["destructive"]:
            description += " Asks the user on the desktop before it runs (see confirm_status)."
        tools.append({"name": mcp_name(spec["name"]), "title": spec["title"], "description": description,
                      "inputSchema": input_schema(spec),
                      "annotations": {"title": spec["title"], "readOnlyHint": spec["name"] in READ_ONLY,
                                      "destructiveHint": bool(spec["destructive"]), "openWorldHint": False}})
    return tools


class Bridge:
    def __init__(self, data_dir=None, demo: bool = False, autostart: bool = True, out=None) -> None:
        self.data_dir = data_dir
        self.demo = demo
        self.autostart = autostart and not os.environ.get("DESKISLE_MCP_NO_START")
        self.out = out or sys.stdout.buffer
        self.lock = threading.Lock()
        self.protocol = SUPPORTED[0]

    # Transport ----------------------------------------------------------------------------------------
    def write(self, message: dict) -> None:
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self.lock:
            self.out.write(data)
            self.out.flush()

    def result(self, rid, value) -> None:
        self.write({"jsonrpc": "2.0", "id": rid, "result": value})

    def error(self, rid, code: int, message: str) -> None:
        self.write({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})

    def serve(self, stream=None) -> int:
        stream = stream or sys.stdin.buffer
        for raw in stream:
            raw = raw.strip()
            if not raw:
                continue
            try:
                message = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self.error(None, -32700, "parse error")
                continue
            batch = message if isinstance(message, list) else [message]
            for item in batch:
                if isinstance(item, dict):
                    self.dispatch(item)
        return 0

    def dispatch(self, message: dict) -> None:
        method = message.get("method")
        rid = message.get("id")
        if method is None:
            return                      # a response to something we never asked
        if rid is None:
            return                      # notifications: initialized, cancelled, ...
        if method == "tools/call":
            threading.Thread(target=self._safe, args=(rid, method, message.get("params") or {}),
                             daemon=True).start()
        else:
            self._safe(rid, method, message.get("params") or {})

    def _safe(self, rid, method: str, params: dict) -> None:
        try:
            self.handle(rid, method, params)
        except Exception as exc:  # noqa: BLE001
            self.error(rid, -32603, "{0}: {1}".format(type(exc).__name__, exc))

    # Methods -------------------------------------------------------------------------------------------
    def handle(self, rid, method: str, params: dict) -> None:
        if method == "initialize":
            wanted = str(params.get("protocolVersion") or "")
            self.protocol = wanted if wanted in SUPPORTED else SUPPORTED[0]
            self.result(rid, {"protocolVersion": self.protocol,
                              "capabilities": {"tools": {"listChanged": False}, "resources": {}},
                              "serverInfo": {"name": "deskisle", "title": "桌屿 DeskIsle", "version": __version__},
                              "instructions": INSTRUCTIONS})
        elif method == "ping":
            self.result(rid, {})
        elif method == "tools/list":
            self.result(rid, {"tools": tool_list()})
        elif method == "tools/call":
            self.result(rid, self.call_tool(str(params.get("name", "")), params.get("arguments") or {}))
        elif method == "resources/list":
            self.result(rid, {"resources": [{"uri": "deskisle://guide", "name": "guide", "title": "DeskIsle agent guide",
                                             "mimeType": "text/markdown"}]})
        elif method == "resources/read":
            if params.get("uri") != "deskisle://guide":
                self.error(rid, -32002, "resource not found")
                return
            text = GUIDE.read_text(encoding="utf-8") if GUIDE.is_file() else INSTRUCTIONS
            self.result(rid, {"contents": [{"uri": "deskisle://guide", "mimeType": "text/markdown", "text": text}]})
        elif method in ("prompts/list",):
            self.result(rid, {"prompts": []})
        else:
            self.error(rid, -32601, "method not found: {0}".format(method))

    def _send(self, name: str, arguments: dict) -> dict:
        return send({"cmd": name, "args": arguments}, data_dir=self.data_dir, demo=self.demo)

    def call_tool(self, tool: str, arguments: dict) -> dict:
        name = from_mcp_name(tool)
        try:
            response = self._send(name, arguments)
        except AgentUnavailable:
            if running_without_agent(self.data_dir, self.demo):
                return self.text(AGENT_OFF, True)
            if not (self.autostart and ensure_running(demo=self.demo, data_dir=self.data_dir)):
                return self.text("DeskIsle (桌屿) is not running and could not be started. Ask the user to start "
                                 "DeskIsle; " + AGENT_OFF_HINT, True)
            try:
                response = self._send(name, arguments)
            except AgentUnavailable as exc:
                return self.text("DeskIsle (桌屿) started but did not answer: {0}".format(exc), True)
        except TimeoutError as exc:
            return self.text(str(exc), True)
        if not response.get("ok"):
            error = response.get("error") or {}
            return self.text(json.dumps(error, ensure_ascii=False, indent=1), True)
        result = response.get("result")
        content = [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}]
        if name == "app.screenshot" and isinstance(result, dict):
            for path in (result.get("paths") or [])[:2]:
                try:
                    data = Path(path).read_bytes()
                except OSError:
                    continue
                if len(data) <= MAX_IMAGE:
                    content.append({"type": "image", "mimeType": "image/png",
                                    "data": base64.b64encode(data).decode("ascii")})
        return {"content": content, "isError": False}

    @staticmethod
    def text(message: str, is_error: bool = False) -> dict:
        return {"content": [{"type": "text", "text": message}], "isError": is_error}


def serve(data_dir=None, demo: bool = False, autostart: bool = True) -> int:
    """Entry point of ``--mcp``."""
    try:
        sys.stderr.write("DeskIsle MCP bridge {0} (protocol {1})\n".format(__version__, PROTOCOL_VERSION))
    except (AttributeError, OSError):
        pass
    return Bridge(data_dir=data_dir, demo=demo, autostart=autostart).serve()


__all__ = ["Bridge", "serve", "tool_list"]
