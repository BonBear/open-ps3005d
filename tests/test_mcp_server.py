import json
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
import pytest
from mcp.client import Client

from ps3005d.controller import Controller, Limits
from ps3005d.device import PowerSupply
from ps3005d.mcp_server import build_server
from ps3005d.sim import SimState, SimulatedTransport


@pytest.fixture(autouse=True)
def no_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ps3005d.controller.SETTLE_S", 0.0)


@pytest.fixture
def sim() -> SimulatedTransport:
    return SimulatedTransport(SimState(load_ohms=100.0))


def _run(
    sim: SimulatedTransport,
    body: Callable[[Client], Awaitable[None]],
    allow_memory_write: bool = False,
) -> None:
    ctl = Controller(lambda: PowerSupply(sim), Limits(max_volts=12, max_amps=1))

    async def go() -> None:
        async with Client(build_server(ctl, allow_memory_write=allow_memory_write)) as client:
            await body(client)

    anyio.run(go)


def _text(result: Any) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


def test_tools_listed(sim: SimulatedTransport) -> None:
    async def body(client: Client) -> None:
        names = {t.name for t in (await client.list_tools()).tools}
        assert {"get_status", "set_voltage_current", "set_output", "sweep_voltage"} <= names

    _run(sim, body)


def test_call_flow_and_limit_error_reaches_agent(sim: SimulatedTransport) -> None:
    async def body(client: Client) -> None:
        r = await client.call_tool("set_voltage_current", {"volts": 5, "amps": 0.5})
        assert not r.is_error
        r = await client.call_tool("set_output", {"on": True})
        assert not r.is_error
        assert json.loads(_text(r))["measured"]["amps"] == 0.05

        r = await client.call_tool("set_voltage_current", {"volts": 20})
        assert r.is_error
        assert "allowed range" in _text(r)

    _run(sim, body)
    assert sim.state.vset == 5.0
    assert sim.state.output


def test_store_memory_only_when_allowed(sim: SimulatedTransport) -> None:
    async def names(client: Client) -> None:
        found = {t.name for t in (await client.list_tools()).tools}
        assert ("store_memory" in found) == allowed

    allowed = False
    _run(sim, names)
    allowed = True
    _run(sim, names, allow_memory_write=True)
