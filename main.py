"""桌屿 DeskIsle 2.0 entry point.

    DeskIsle.exe                 start (attaches to the Windows desktop)
    DeskIsle.exe --demo          demo layout in a normal window
    DeskIsle.exe --mcp           MCP server on stdio for AI assistants
    DeskIsle.exe --cli <cmd>     control the running DeskIsle (see deskisle-cli)

``--cli``, ``--mcp`` and ``--watchdog`` never import Qt, so they start fast and
cost only a few MB.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_args(argv: list[str]) -> argparse.Namespace:
    from deskisle import __version__

    parser = argparse.ArgumentParser(prog="DeskIsle", description="桌屿 DeskIsle {0} —— Windows 桌面整理器".format(
        __version__))
    parser.add_argument("--demo", action="store_true", help="以普通窗口运行演示布局，不挂接 Windows 桌面")
    parser.add_argument("--data-dir", type=Path, help="使用其他数据目录")
    parser.add_argument("--reset", action="store_true", help="先备份，再重建默认布局")
    parser.add_argument("--verbose", action="store_true", help="在控制台输出详细日志")
    parser.add_argument("--version", action="version", version="DeskIsle " + __version__)
    parser.add_argument("--mcp", action="store_true", help="作为 MCP 服务器运行（stdio），供 AI 助手连接")
    parser.add_argument("--cli", nargs=argparse.REMAINDER, metavar="命令",
                        help="控制正在运行的桌屿，例如 --cli island.list；--cli list 查看全部命令")
    parser.add_argument("--recovered", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--watchdog", type=int, metavar="PID", help=argparse.SUPPRESS)
    parser.add_argument("--self-test", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.watchdog:
        from deskisle.agent.client import default_root
        from deskisle.watchdog import run as watchdog

        return watchdog(args.watchdog, Path(args.data_dir) if args.data_dir else default_root(False))
    if args.mcp:
        from deskisle.agent.mcp import serve

        return serve(data_dir=args.data_dir, demo=args.demo)
    if args.cli is not None:
        from deskisle.agent.cli import main as cli

        extra = (["--demo"] if args.demo else []) + (["--data-dir", str(args.data_dir)] if args.data_dir else [])
        return cli(extra + list(args.cli))
    if args.self_test:
        from deskisle.selftest import run as self_test

        return self_test(args.self_test)
    from deskisle.engine.app import run

    return run(args)


if __name__ == "__main__":
    sys.exit(main())
