"""PyInstaller entry point: ps3005d-mcp.exe (console; MCP over stdio)."""

from ps3005d.mcp_server import main

raise SystemExit(main())
