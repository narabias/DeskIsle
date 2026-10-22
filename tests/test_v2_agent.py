"""2.0 agent interfaces without Qt: command catalogue, CLI, MCP bridge, client helpers."""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from deskisle import __version__
from deskisle.agent import cli, client, mcp, schema

DESTRUCTIVE = {"app.quit", "page.delete", "island.delete", "island.tab_close", "todo.remove",
               "custom.widget_delete", "snapshot.restore", "layout.import"}


class SchemaTests(unittest.TestCase):
    def test_catalogue_is_consistent(self) -> None:
        names = [spec["name"] for spec in schema.COMMANDS]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(names), 60)
        for spec in schema.COMMANDS:
            self.assertRegex(spec["name"], r"^[a-z]+(\.[a-z_]+)?$")
            self.assertTrue(spec["title"] and spec["description"], spec["name"])
            for key in spec["required"]:
                self.assertIn(key, spec["params"], spec["name"])
            for key, prop in spec["params"].items():
                self.assertIn(prop.get("type"), ("string", "boolean", "integer", "number", "object", "array"),
                              "{0}.{1}".format(spec["name"], key))
                self.assertTrue(prop.get("description"), "{0}.{1}".format(spec["name"], key))
            tool = schema.mcp_name(spec["name"])
            self.assertRegex(tool, r"^[A-Za-z0-9_-]{1,64}$")
            self.assertEqual(schema.from_mcp_name(tool), spec["name"])

    def test_destructive_commands_ask_first(self) -> None:
        destructive = {spec["name"] for spec in schema.COMMANDS if spec["destructive"]}
        self.assertEqual(destructive, DESTRUCTIVE)
        for name in destructive:
            self.assertIn("wait", schema.BY_NAME[name]["params"])
            self.assertIn("dry_run", schema.BY_NAME[name]["params"])

    def test_every_command_has_a_handler(self) -> None:
        source = Path(schema.__file__).with_name("commands.py").read_text(encoding="utf-8")
        for spec in schema.COMMANDS:
            self.assertIn("def c_" + spec["name"].replace(".", "_") + "(", source, spec["name"])

    def test_every_command_is_documented_in_the_guide(self) -> None:
        guide = Path(schema.__file__).with_name("GUIDE.md").read_text(encoding="utf-8")
        missing = [spec["name"] for spec in schema.COMMANDS if "`" + spec["name"] + "`" not in guide]
        self.assertEqual(missing, [])
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        try:
            import gen_guide
        finally:
            sys.path.pop(0)
        self.assertEqual(gen_guide.main(["--check"]), 0, "run python tools/gen_guide.py")

    def test_validate_gives_actionable_messages(self) -> None:
        self.assertEqual(schema.validate("island.list", {}), [])
        self.assertEqual(schema.validate("island.list", None), [])
        self.assertTrue(schema.validate("island.explode", {})[0].startswith("unknown command"))
        self.assertEqual(schema.validate("island.list", []), ["args must be an object"])
        self.assertIn("missing required argument 'uid'", schema.validate("island.get", {}))
        self.assertIn("missing required argument 'uid'", schema.validate("island.get", {"uid": ""}))
        self.assertTrue(any("must be one of" in p for p in schema.validate("desk.visibility", {"action": "x"})))
        self.assertTrue(any("must be boolean" in p for p in schema.validate("desk.focus", {"on": "yes"})))
        self.assertTrue(any("must be integer" in p for p in schema.validate("island.update",
                                                                              {"uid": "a", "x": 1.5})))
        self.assertTrue(any("must be integer" in p for p in schema.validate("island.update",
                                                                              {"uid": "a", "x": True})))
        self.assertEqual(schema.validate("island.update", {"uid": "a", "x": None}), [])
        self.assertTrue(any("unknown argument 'bogus'" in p for p in schema.validate("island.list", {"bogus": 1})))

    def test_input_schema_is_closed(self) -> None:
        spec = schema.BY_NAME["island.create"]
        value = schema.input_schema(spec)
        self.assertEqual(value["type"], "object")
        self.assertFalse(value["additionalProperties"])
        self.assertEqual(value["required"], ["kind"])
        self.assertEqual(value["properties"]["kind"]["enum"], ["files", "web", "widget"])


class _Captured:
    def __enter__(self):
        self.out, self.err = io.StringIO(), io.StringIO()
        self._patches = [mock.patch.object(sys, "stdout", self.out), mock.patch.object(sys, "stderr", self.err)]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *_exc):
        for patch in self._patches:
            patch.stop()


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="deskisle-cli-"))
        self._env = mock.patch.dict(os.environ, {"DESKISLE_PIPE_NAME": "deskisle-none-" + os.urandom(4).hex(),
                                                 "DESKISLE_DATA_DIR": str(self.root)})
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_parse_arguments_converts_types(self) -> None:
        args = cli.parse_arguments("island.create", ["--kind", "widget", "--widget", "clock", "--x", "40",
                                                     "--config", '{"style": "analog"}'])
        self.assertEqual(args, {"kind": "widget", "widget": "clock", "x": 40, "config": {"style": "analog"}})
        args = cli.parse_arguments("island.get", ["--uid=abc", "--include-items"])
        self.assertEqual(args, {"uid": "abc", "include_items": True})
        args = cli.parse_arguments("island.update", ["--uid", "a", "--collapsed", "no", "--json", '{"width": 420}'])
        self.assertEqual(args, {"uid": "a", "collapsed": False, "width": 420})
        self.assertEqual(cli.parse_arguments("island.delete", ["--uid", "a", "--wait", "2.5"])["wait"], 2.5)

    def test_parse_arguments_rejects_mistakes(self) -> None:
        for tokens in (["--nope", "1"], ["stray"], ["--x"], ["--json", "[1]"], ["--json"]):
            with self.subTest(tokens=tokens), self.assertRaises(ValueError):
                cli.parse_arguments("island.create", list(tokens))
        with self.assertRaises(ValueError):
            cli.parse_arguments("island.update", ["--uid", "a", "--collapsed", "maybe"])

    def test_list_help_and_version(self) -> None:
        with _Captured() as cap:
            self.assertEqual(cli.main(["list"]), 0)
        self.assertIn("island.create", cap.out.getvalue())
        self.assertRegex(cap.out.getvalue(), r"island\.delete +! ")
        with _Captured() as cap:
            self.assertEqual(cli.main(["list", "--json"]), 0)
        listed = json.loads(cap.out.getvalue())
        self.assertEqual(len(listed), len(schema.COMMANDS))
        with _Captured() as cap:
            self.assertEqual(cli.main(["help", "island_create"]), 0)
        self.assertIn("--kind (required)", cap.out.getvalue())
        with _Captured() as cap:
            self.assertEqual(cli.main(["--version"]), 0)
        self.assertEqual(cap.out.getvalue().strip(), "deskisle-cli " + __version__)
        with _Captured():
            self.assertEqual(cli.main([]), 2)

    def test_usage_errors_and_not_running(self) -> None:
        with _Captured() as cap:
            self.assertEqual(cli.main(["island.explode"]), 2)
        self.assertIn("unknown command", cap.err.getvalue())
        with _Captured() as cap:
            self.assertEqual(cli.main(["island.get", "--bogus", "1"]), 2)
        self.assertIn("unknown option --bogus", cap.err.getvalue())
        with _Captured() as cap:
            self.assertEqual(cli.main(["island.list"]), 3)
        self.assertIn("not running", cap.err.getvalue())

    def test_agent_switched_off_is_reported(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            (self.root / "instance.lock").write_text("{0}\nDeskIsle\nhost\n".format(child.pid), encoding="utf-8")
            self.assertTrue(client.running_without_agent())
            self.assertFalse(client.running_without_agent(demo=True))
            with _Captured() as cap:
                self.assertEqual(cli.main(["island.list"]), 3)
            self.assertIn("允许 AI 助手控制桌屿", cap.err.getvalue())
            # ensure_running never starts a second copy next to one with the interface off
            with mock.patch.object(client.subprocess, "Popen") as popen:
                self.assertFalse(client.ensure_running(wait=0.1))
                popen.assert_not_called()
        finally:
            child.kill()
            child.wait()
        self.assertFalse(client.running_without_agent())        # the owner is gone: stale lock
        (self.root / "instance.lock").write_text("{0}\n".format(os.getpid()), encoding="utf-8")
        self.assertFalse(client.running_without_agent())        # that is us


class ClientTests(unittest.TestCase):
    def test_pipe_name_override_is_sanitised(self) -> None:
        with mock.patch.dict(os.environ, {"DESKISLE_PIPE_NAME": "a b/c\\d"}):
            self.assertEqual(client.pipe_name(), "a_b_c_d")
            self.assertEqual(client.pipe_name(demo=True), "a_b_c_d")
        with mock.patch.dict(os.environ, {"DESKISLE_PIPE_NAME": ""}):
            self.assertTrue(client.pipe_name().startswith("deskisle-"))
            self.assertTrue(client.pipe_name(demo=True).startswith("deskisle-demo-"))

    def test_discover_prefers_agent_json(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="deskisle-disc-"))
        try:
            (root / "agent.json").write_text(json.dumps({"pipe": "/tmp/somewhere", "pid": 1}), encoding="utf-8")
            self.assertEqual(client.discover(root), "/tmp/somewhere")
            (root / "agent.json").write_text("{broken", encoding="utf-8")
            self.assertTrue(client.discover(root).endswith(client.pipe_name()))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_destructive_commands_wait_for_the_user(self) -> None:
        self.assertEqual(client._timeout_for("island.list", {}, None), 30.0)
        self.assertEqual(client._timeout_for("island.delete", {}, None), 105.0)
        self.assertEqual(client._timeout_for("island.delete", {"wait": 5}, None), 20.0)
        self.assertEqual(client._timeout_for("island.delete", {"wait": 9999}, None), 315.0)
        self.assertEqual(client._timeout_for("island.delete", {}, 3.0), 3.0)

    def test_launch_info_for_source_and_packaged_builds(self) -> None:
        info = client.launch_info()
        self.assertFalse(info["packaged"])
        self.assertEqual(info["mcpArgs"][-1], "--mcp")
        self.assertTrue(info["mcpArgs"][0].endswith("main.py"))
        self.assertEqual(client.launch_info(demo=True)["mcpArgs"][-1], "--demo")
        root = Path(tempfile.mkdtemp(prefix="deskisle-li-")) / "Program Files" / "DeskIsle"
        root.mkdir(parents=True)
        try:
            exe = root / "DeskIsle.exe"
            exe.write_bytes(b"")
            portable = client.launch_info(executable=exe, frozen=True, entries=[])
            self.assertEqual(portable["mcpCommand"], str(exe))
            self.assertEqual(portable["mcpArgs"], ["--mcp"])
            self.assertTrue(portable["cli"].startswith('"'))
            (root / "deskisle-cli.exe").write_bytes(b"")
            info = client.launch_info(executable=exe, frozen=True, entries=[])
            self.assertEqual(info["mcpCommand"], str(root / "deskisle-cli.exe"))
            self.assertEqual(info["mcpArgs"], ["mcp"])
            self.assertEqual(info["cli"], '"{0}"'.format(root / "deskisle-cli.exe"))
            self.assertFalse(info["cliOnPath"])
            on_path = client.launch_info(executable=exe, frozen=True, entries=['"{0}{1}"'.format(root, os.sep)])
            self.assertEqual(on_path["cli"], "deskisle-cli")
            self.assertTrue(on_path["cliOnPath"])
            demo = client.launch_info(executable=exe, frozen=True, demo=True, entries=[str(root)])
            self.assertEqual(demo["mcpArgs"], ["--demo", "mcp"])
            self.assertEqual(demo["cli"], "deskisle-cli --demo")
        finally:
            shutil.rmtree(root.parents[1], ignore_errors=True)

    def test_folder_on_path_expands_variables(self) -> None:
        with mock.patch.dict(os.environ, {"DESKISLE_TEST_HOME": "/opt/deskisle"}):
            self.assertTrue(client.folder_on_path("/opt/deskisle", ["$DESKISLE_TEST_HOME"]))
        self.assertFalse(client.folder_on_path("/opt/deskisle", ["/opt", "", "  "]))

    @unittest.skipIf(client.IS_WINDOWS, "Unix socket transport")
    def test_request_roundtrip_over_the_socket(self) -> None:
        name = "deskisle-rt-" + os.urandom(4).hex()
        path = os.path.join(tempfile.gettempdir(), name)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)

        def serve() -> None:
            conn, _ = server.accept()
            with conn:
                data = b""
                while not data.endswith(b"\n"):
                    data += conn.recv(4096)
                request = json.loads(data)
                # an unrelated line first: the client must match the id
                reply = {"id": request["id"], "ok": True, "result": {"echo": request["cmd"], "args": request["args"]}}
                conn.sendall(b'{"id": -1, "ok": true}\n' + json.dumps(reply).encode() + b"\n")

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        try:
            with mock.patch.dict(os.environ, {"DESKISLE_PIPE_NAME": name, "DESKISLE_DATA_DIR": tempfile.gettempdir()
                                              + "/deskisle-nowhere"}):
                result = client.call("island.list", {"kind": "files"})
            self.assertEqual(result, {"echo": "island.list", "args": {"kind": "files"}})
        finally:
            worker.join(5)
            server.close()
            os.unlink(path)


class McpTests(unittest.TestCase):
    def bridge(self):
        out = io.BytesIO()
        return mcp.Bridge(autostart=False, out=out), out

    @staticmethod
    def messages(out: io.BytesIO) -> list[dict]:
        return [json.loads(line) for line in out.getvalue().decode("utf-8").splitlines() if line.strip()]

    def test_initialize_list_and_resources(self) -> None:
        bridge, out = self.bridge()
        lines = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "deskisle://guide"}},
            {"jsonrpc": "2.0", "id": 4, "method": "nope"},
            {"jsonrpc": "2.0", "id": 5, "method": "ping"},
        ]
        stream = io.BytesIO(("\n".join(json.dumps(m) for m in lines) + "\nnot json\n").encode("utf-8"))
        self.assertEqual(bridge.serve(stream), 0)
        replies = self.messages(out)
        by_id = {m.get("id"): m for m in replies}
        self.assertEqual(by_id[1]["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(by_id[1]["result"]["serverInfo"]["version"], __version__)
        tools = by_id[2]["result"]["tools"]
        self.assertEqual(len(tools), len(schema.COMMANDS))
        delete = next(t for t in tools if t["name"] == "island_delete")
        self.assertTrue(delete["annotations"]["destructiveHint"])
        self.assertIn("confirm_status", delete["description"])
        listing = next(t for t in tools if t["name"] == "island_list")
        self.assertTrue(listing["annotations"]["readOnlyHint"])
        self.assertIn("DeskIsle", by_id[3]["result"]["contents"][0]["text"])
        self.assertEqual(by_id[4]["error"]["code"], -32601)
        self.assertEqual(by_id[5]["result"], {})
        self.assertEqual(by_id[None]["error"]["code"], -32700)
        self.assertEqual(len(replies), 6)          # the notification got no answer

    def test_unknown_protocol_falls_back_to_the_newest(self) -> None:
        bridge, out = self.bridge()
        bridge.handle(1, "initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(self.messages(out)[0]["result"]["protocolVersion"], mcp.SUPPORTED[0])

    def test_read_only_list_names_real_commands(self) -> None:
        self.assertTrue(mcp.READ_ONLY <= set(schema.BY_NAME))
        self.assertFalse(mcp.READ_ONLY & DESTRUCTIVE)

    def test_tool_call_results_and_errors(self) -> None:
        bridge, _out = self.bridge()
        with mock.patch.object(bridge, "_send", return_value={"ok": True, "result": {"islands": 3}}) as send:
            result = bridge.call_tool("island_list", {"kind": "files"})
        send.assert_called_once_with("island.list", {"kind": "files"})
        self.assertFalse(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"]), {"islands": 3})
        with mock.patch.object(bridge, "_send", return_value={"ok": False, "error": {"code": "not_found"}}):
            result = bridge.call_tool("island_get", {"uid": "x"})
        self.assertTrue(result["isError"])
        self.assertIn("not_found", result["content"][0]["text"])
        with mock.patch.object(bridge, "_send", side_effect=TimeoutError("slow")):
            self.assertTrue(bridge.call_tool("island_list", {})["isError"])

    def test_screenshots_come_back_as_images(self) -> None:
        bridge, _out = self.bridge()
        folder = Path(tempfile.mkdtemp(prefix="deskisle-shot-"))
        try:
            png = folder / "layer.png"
            png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            reply = {"ok": True, "result": {"paths": [str(png), str(folder / "missing.png")]}}
            with mock.patch.object(bridge, "_send", return_value=reply):
                result = bridge.call_tool("app_screenshot", {})
            images = [c for c in result["content"] if c["type"] == "image"]
            self.assertEqual(len(images), 1)
            self.assertEqual(base64.b64decode(images[0]["data"]), png.read_bytes())
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_not_running_and_switched_off(self) -> None:
        bridge, _out = self.bridge()
        with mock.patch.object(bridge, "_send", side_effect=client.AgentUnavailable("gone")), \
                mock.patch.object(mcp, "running_without_agent", return_value=True):
            result = bridge.call_tool("island_list", {})
        self.assertTrue(result["isError"])
        self.assertIn("switched off", result["content"][0]["text"])
        with mock.patch.object(bridge, "_send", side_effect=client.AgentUnavailable("gone")), \
                mock.patch.object(mcp, "running_without_agent", return_value=False):
            result = bridge.call_tool("island_list", {})
        self.assertTrue(result["isError"])
        self.assertIn("not running", result["content"][0]["text"])


class EntryPointTests(unittest.TestCase):
    def test_cli_and_mcp_never_import_qt(self) -> None:
        code = ("import sys; sys.argv=['x','--cli','list']; import main; "
                "rc = main.main(['--cli', 'list']); "
                "assert not any(m.startswith('PySide6') for m in sys.modules), 'Qt was imported'; "
                "sys.exit(rc)")
        result = subprocess.run([sys.executable, "-c", code], cwd=str(Path(__file__).resolve().parents[1]),
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertIn(b"island.create", result.stdout)

    def test_cli_entry_script(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(root / "tools" / "cli_entry.py"), "--version"], cwd=str(root),
                                capture_output=True, timeout=60, env=dict(os.environ, PYTHONPATH=str(root)))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout.decode().strip(), "deskisle-cli " + __version__)


if __name__ == "__main__":
    unittest.main()
