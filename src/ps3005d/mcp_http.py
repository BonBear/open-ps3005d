"""Serve an MCPServer over streamable HTTP on 127.0.0.1, guarded by a bearer key.

Used by the GUI to let an AI client control the supply through the GUI's own serial
connection (the port has a single owner). Clients connect to
``http://127.0.0.1:<port>/mcp`` with ``Authorization: Bearer <key>``.
"""

from __future__ import annotations

import hmac
import json
import secrets
import threading
import time
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer

HOST = "127.0.0.1"
PATH = "/mcp"
DEFAULT_PORT = 8765


def new_key() -> str:
    return secrets.token_urlsafe(32)


def url(port: int) -> str:
    return f"http://{HOST}:{port}{PATH}"


class BearerKeyMiddleware:
    """ASGI middleware: HTTP requests need ``Authorization: Bearer <key>``."""

    def __init__(self, app: Any, key: str) -> None:
        self._app = app
        self._expected = f"Bearer {key}".encode()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            given = headers.get(b"authorization", b"")
            if not hmac.compare_digest(given, self._expected):
                body = json.dumps({"error": "missing or wrong bearer key"}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b"Bearer"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self._app(scope, receive, send)


class HttpMcpServer:
    """Runs one MCPServer with uvicorn in a daemon thread; start() / stop()."""

    def __init__(self) -> None:
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.port = 0

    @property
    def running(self) -> bool:
        return self._server is not None and self._server.started

    def start(self, mcp: MCPServer, port: int, key: str, timeout_s: float = 5.0) -> None:
        """Start serving; raises OSError if it does not come up (e.g. port in use)."""
        self.stop()
        app = BearerKeyMiddleware(mcp.streamable_http_app(host=HOST), key)
        # log_config=None: no uvicorn handlers on sys.stderr, which is None in a windowed exe.
        config = uvicorn.Config(
            app, host=HOST, port=port, log_level="warning", lifespan="on", log_config=None
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, name="mcp-http", daemon=True)
        thread.start()
        deadline = time.monotonic() + timeout_s
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                server.should_exit = True
                raise OSError(f"MCP server could not listen on {HOST}:{port} (port in use?)")
            time.sleep(0.02)
        self._server, self._thread, self.port = server, thread, port

    def stop(self, timeout_s: float = 5.0) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout_s)
        self._server = self._thread = None
