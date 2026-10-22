"""Entry point of ``deskisle-cli.exe`` (console program, no Qt).

    deskisle-cli list | help <command> | <command> --key value … | mcp

From a source checkout the same thing is ``python main.py --cli …`` (or
``python main.py --mcp`` for the MCP server).
"""

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deskisle.agent.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
