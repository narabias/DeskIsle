"""Agent interfaces of DeskIsle 2.0.

* :mod:`.schema`   - every command with its JSON schema (pure Python, no Qt),
* :mod:`.commands` - the handlers, run inside the DeskIsle process,
* :mod:`.server`   - local named pipe / Unix socket, one JSON object per line,
* :mod:`.client`   - pure Python client (used by the CLI and the MCP bridge),
* :mod:`.mcp`      - Model Context Protocol server over stdio,
* :mod:`.cli`      - ``deskisle-cli`` command line.

Destructive commands (deleting islands, presets, widgets, restoring layouts,
quitting) never run directly: DeskIsle shows a confirmation card on the desktop
and the command only runs after the user accepted it.
"""

PROTOCOL_VERSION = 1
