"""``deskisle-cli`` - drive a running DeskIsle from scripts and AI agents.

    deskisle-cli list                       commands (``--json`` for schemas)
    deskisle-cli help island.create         arguments of one command
    deskisle-cli island.create --kind widget --widget clock
    deskisle-cli island.update --uid 3f2a… --json '{"width": 420}'
    deskisle-cli mcp                        Model Context Protocol server (stdio)

Global options: ``--demo`` (talk to the demo instance), ``--data-dir PATH``,
``--timeout SECONDS``, ``--raw`` (print the whole response).  Exit codes:
0 ok, 1 command error, 2 usage error, 3 DeskIsle not running.
"""

from __future__ import annotations

import json
import sys

from .. import __version__
from .client import AgentUnavailable, running_without_agent, send
from .schema import BY_NAME, COMMANDS, from_mcp_name, input_schema

USAGE = __doc__


def _out(text: str, stream=None) -> None:
    stream = stream or sys.stdout
    if stream is None:
        return
    try:
        try:
            stream.write(text + "\n")
        except UnicodeEncodeError:
            stream.buffer.write((text + "\n").encode("utf-8"))
        stream.flush()
    except BrokenPipeError:
        pass


def convert(kind: str, raw: str):
    if kind == "integer":
        return int(raw)
    if kind == "number":
        return float(raw)
    if kind == "boolean":
        lowered = raw.strip().lower()
        if lowered in ("1", "true", "yes", "on", "y"):
            return True
        if lowered in ("0", "false", "no", "off", "n"):
            return False
        raise ValueError("expected true/false, got {0!r}".format(raw))
    if kind in ("object", "array"):
        value = json.loads(raw)
        if kind == "array" and not isinstance(value, list):
            value = [value]
        return value
    return raw


def parse_arguments(name: str, tokens: list[str]) -> dict:
    spec = BY_NAME[name]
    args: dict = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--json":
            if i + 1 >= len(tokens):
                raise ValueError("--json needs a JSON object")
            extra = json.loads(tokens[i + 1])
            if not isinstance(extra, dict):
                raise ValueError("--json must be an object")
            args.update(extra)
            i += 2
            continue
        if not token.startswith("--"):
            raise ValueError("unexpected argument {0!r}".format(token))
        key = token[2:].replace("-", "_")
        if "=" in key:
            key, value = key.split("=", 1)
            tokens.insert(i + 1, value)
        prop = spec["params"].get(key)
        if prop is None:
            raise ValueError("unknown option --{0} (allowed: {1})".format(
                key, ", ".join("--" + p for p in spec["params"]) or "none"))
        kind = prop.get("type", "string")
        has_value = i + 1 < len(tokens) and not tokens[i + 1].startswith("--")
        if kind == "boolean" and not has_value:
            args[key] = True
            i += 1
            continue
        if not has_value:
            raise ValueError("--{0} needs a value".format(key))
        value = tokens[i + 1]
        if kind == "array" and not value.lstrip().startswith("["):
            args.setdefault(key, []).append(value)
        else:
            args[key] = convert(kind, value)
        i += 2
    return args


def describe(name: str) -> str:
    spec = BY_NAME[name]
    lines = ["{0}  -  {1}{2}".format(name, spec["title"], "  (asks the user first)" if spec["destructive"] else ""),
             "", spec["description"], ""]
    for key, prop in spec["params"].items():
        flag = "--" + key + (" (required)" if key in spec["required"] else "")
        kind = prop.get("type", "string")
        enum = " [{0}]".format("|".join(prop["enum"])) if "enum" in prop else ""
        lines.append("  {0:<24} {1}{2}  {3}".format(flag, kind, enum, prop.get("description", "")))
    if not spec["params"]:
        lines.append("  (no arguments)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    demo = False
    data_dir = None
    timeout = None
    raw = False
    rest: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--demo" and not rest:
            demo = True
        elif token == "--data-dir" and not rest and i + 1 < len(argv):
            data_dir = argv[i + 1]
            i += 1
        elif token == "--timeout" and not rest and i + 1 < len(argv):
            timeout = float(argv[i + 1])
            i += 1
        elif token == "--raw" and not rest:
            raw = True
        else:
            rest.append(token)
        i += 1
    if not rest or rest[0] in ("-h", "--help"):
        _out(USAGE.strip())
        return 0 if rest else 2
    command, tokens = rest[0], rest[1:]
    if command in ("--version", "version"):
        _out("deskisle-cli {0}".format(__version__))
        return 0
    if command == "mcp":
        from .mcp import serve

        return serve(data_dir=data_dir, demo=demo)
    if command == "list":
        if "--json" in tokens:
            _out(json.dumps([{"name": s["name"], "title": s["title"], "description": s["description"],
                              "destructive": s["destructive"], "input_schema": input_schema(s)} for s in COMMANDS],
                            ensure_ascii=False, indent=1))
        else:
            width = max(len(s["name"]) for s in COMMANDS)
            for spec in COMMANDS:
                mark = " !" if spec["destructive"] else "  "
                _out("{0:<{1}}{2} {3}".format(spec["name"], width, mark, spec["title"]))
            _out("\n! = asks the user on the desktop before it runs.  deskisle-cli help <command> for arguments.")
        return 0
    if command == "help":
        if not tokens:
            _out(USAGE.strip())
            return 0
        name = from_mcp_name(tokens[0])
        if name not in BY_NAME:
            _out("unknown command {0!r}; see deskisle-cli list".format(tokens[0]), sys.stderr)
            return 2
        _out(describe(name))
        return 0
    name = from_mcp_name(command)
    if name not in BY_NAME:
        _out("unknown command {0!r}; see deskisle-cli list".format(command), sys.stderr)
        return 2
    try:
        args = parse_arguments(name, tokens)
    except (ValueError, json.JSONDecodeError) as exc:
        _out("error: {0}\n\n{1}".format(exc, describe(name)), sys.stderr)
        return 2
    try:
        response = send({"cmd": name, "args": args}, timeout=timeout, data_dir=data_dir, demo=demo)
    except AgentUnavailable as exc:
        if running_without_agent(data_dir, demo):
            _out("DeskIsle is running, but its AI interface is off: turn on 设置 → AI 与扩展 → 允许 AI 助手控制桌屿.",
                 sys.stderr)
        else:
            _out("DeskIsle is not running ({0}).".format(exc), sys.stderr)
        return 3
    except TimeoutError as exc:
        _out("error: {0}".format(exc), sys.stderr)
        return 1
    if raw:
        _out(json.dumps(response, ensure_ascii=False, indent=1))
        return 0 if response.get("ok") else 1
    if response.get("ok"):
        _out(json.dumps(response.get("result"), ensure_ascii=False, indent=1))
        return 0
    error = response.get("error") or {}
    _out("error [{0}]: {1}".format(error.get("code", "error"), error.get("message", "")), sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
