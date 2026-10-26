"""The MCP server over HTTP with a bearer key, as hosted by the GUI."""

import json
import socket
from collections.abc import Iterator

import anyio
import httpx2
import pytest
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from ps3005d.controller import Controller, Limits
from ps3005d.device import DeviceError, PowerSupply
from ps3005d.mcp_http import HttpMcpServer, new_key, url
from ps3005d.mcp_server import build_server
from ps3005d.sim import SimState, SimulatedTransport


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(autouse=True)
def no_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ps3005d.controller.SETTLE_S", 0.0)


@pytest.fixture
def served() -> Iterator[tuple[str, str, SimState, list[str | None]]]:
    sim = SimState(load_ohms=100.0)
    ps = PowerSupply(SimulatedTransport(sim))
    ctl = Controller(lambda: ps, Limits(max_volts=12, max_amps=1), owns_port=False)
    activity: list[str | None] = []
    server = HttpMcpServer()
    key = new_key()
    port = _free_port()
    server.start(build_server(ctl, on_activity=activity.append), port, key)
    try:
        yield url(port), key, sim, activity
    finally:
        server.stop()
    assert not server.running


async def _call(endpoint: str, key: str | None, tool: str, args: dict[str, object]) -> str:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with (
        httpx2.AsyncClient(headers=headers) as http,
        Client(streamable_http_client(endpoint, http_client=http)) as client,
    ):
        r = await client.call_tool(tool, args)
        text = "".join(getattr(c, "text", "") for c in r.content)
        return ("ERROR: " if r.is_error else "") + text


def test_tools_over_http_with_key(served: tuple[str, str, SimState, list[str | None]]) -> None:
    endpoint, key, sim, activity = served
    out = anyio.run(_call, endpoint, key, "set_voltage_current", {"volts": 5, "amps": 0.5})
    assert json.loads(out)["setpoint"]["volts"] == 5.0
    assert sim.vset == 5.0
    assert activity == ["set_voltage_current", None]


def test_wrong_or_missing_key_rejected(served: tuple[str, str, SimState, list[str | None]]) -> None:
    endpoint, _, sim, _ = served
    for key in (None, "wrong"):
        with pytest.raises(Exception):  # noqa: B017 - the client surfaces the 401 its own way
            anyio.run(_call, endpoint, key, "set_output", {"on": True})
    r = httpx2.post(endpoint, json={}, headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    assert not sim.output


def test_blocked_and_shared_release() -> None:
    sim = SimState()
    ps = PowerSupply(SimulatedTransport(sim))
    ctl = Controller(lambda: ps, Limits(12, 1), owns_port=False)
    reason: list[str] = []
    server = build_server(ctl, blocked=lambda: reason[0] if reason else None)

    async def flow() -> None:
        async with Client(server) as client:
            reason.append("the GUI is running a sequence")
            r = await client.call_tool("set_output", {"on": True})
            assert r.is_error and "sequence" in "".join(getattr(c, "text", "") for c in r.content)
            r = await client.call_tool("get_status", {})
            assert not r.is_error  # reading is always allowed
            reason.clear()
            await client.call_tool("set_output", {"on": True})
            await client.call_tool("release_port", {})

    anyio.run(flow)
    assert not sim.output
    assert ps.identify()  # the host's port is still open


def test_not_connected_reported() -> None:
    def no_supply() -> PowerSupply:
        raise DeviceError("the GUI is not connected to the supply")

    ctl = Controller(no_supply, Limits(12, 1), owns_port=False)

    async def flow() -> None:
        async with Client(build_server(ctl)) as client:
            r = await client.call_tool("get_status", {})
            assert r.is_error and "not connected" in "".join(
                getattr(c, "text", "") for c in r.content
            )

    anyio.run(flow)
