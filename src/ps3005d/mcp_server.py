"""MCP server exposing the PS3005D to AI agents (stdio transport).

Run ``ps3005d-mcp --port /dev/ttyACM0 --max-volts 12 --max-amps 1``. The limits are
set by the operator on the command line; no tool can raise them. The output is
switched off when the server exits.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable
from typing import Any, TypeVar

import serial
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from ps3005d import __version__
from ps3005d.controller import Controller, Limits
from ps3005d.device import DeviceError, PowerSupply
from ps3005d.sim import SimState, SimulatedTransport

PORT_ENV = "PS3005D_PORT"

INSTRUCTIONS = """\
Controls a Velleman PS3005D bench power supply (single channel, 0-30 V / 0-5 A) wired
to a device under test. Safety rules:
- The output is OFF unless you switch it on with set_output. Configure voltage and
  current limit first, then enable the output.
- The operator has set maximum voltage/current limits (see get_info); requests above
  them are refused. Do not try to work around them.
- In constant-voltage (CV) mode the current setpoint is the current limit; if the load
  draws more, the supply switches to constant-current (CC) mode.
- Recalling a memory switches the output off.
- Switch the output off when you are done testing.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
CONTROL = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
# Enabling the output energizes real hardware.
ENERGIZE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)


T = TypeVar("T")


def _guard(fn: Callable[[], T]) -> T:
    """Turn expected failures into ToolError so the agent sees the reason.

    The MCP SDK hides the message of any other exception from the client.
    """
    try:
        return fn()
    except (ValueError, DeviceError, OSError, serial.SerialException) as exc:
        raise ToolError(str(exc)) from exc


def build_server(ctl: Controller, *, allow_memory_write: bool = False) -> MCPServer:
    mcp = MCPServer(name="ps3005d", version=__version__, instructions=INSTRUCTIONS)

    @mcp.tool(annotations=READ_ONLY)
    def get_info() -> dict[str, Any]:
        """Identify the supply and return the operator's safety limits."""
        return _guard(lambda: ctl.info())

    @mcp.tool(annotations=READ_ONLY)
    def get_status() -> dict[str, Any]:
        """Output state, CV/CC mode, OVP/OCP flags, setpoints and measured V/I/P."""
        return _guard(lambda: ctl.status())

    @mcp.tool(annotations=CONTROL)
    def set_voltage_current(
        volts: float | None = None, amps: float | None = None
    ) -> dict[str, Any]:
        """Set the voltage setpoint and/or current limit. Does not switch the output on."""
        return _guard(lambda: ctl.set_setpoints(volts, amps))

    @mcp.tool(annotations=ENERGIZE)
    def set_output(on: bool) -> dict[str, Any]:
        """Switch the output on or off. Returns the status after the output settled."""
        return _guard(lambda: ctl.set_output(on))

    @mcp.tool(annotations=CONTROL)
    def set_protection(ocp: bool | None = None, ovp: bool | None = None) -> dict[str, Any]:
        """Enable/disable over-current (OCP) and over-voltage (OVP) protection.

        With OCP on, the supply cuts the output instead of entering CC mode when the
        current limit is reached; with OVP on, it cuts the output above the voltage setpoint.
        """
        return _guard(lambda: ctl.set_protection(ocp, ovp))

    @mcp.tool(annotations=READ_ONLY)
    def measure(samples: int = 1, interval_s: float = 0.5) -> dict[str, Any]:
        """Measure output voltage/current/power, optionally several samples with min/max/mean."""
        return _guard(lambda: ctl.measure(samples, interval_s))

    @mcp.tool(annotations=ENERGIZE)
    def sweep_voltage(
        start_volts: float,
        stop_volts: float,
        step_volts: float,
        current_limit_amps: float,
        dwell_s: float = 0.5,
        leave_output_on: bool = False,
    ) -> dict[str, Any]:
        """Switch the output on and step the voltage from start to stop, measuring at each
        step (e.g. an I-V curve or brown-out test). The output is switched off afterwards
        unless leave_output_on is true, and always if the output trips."""
        return _guard(
            lambda: ctl.sweep_voltage(
                start_volts, stop_volts, step_volts, current_limit_amps, dwell_s, leave_output_on
            )
        )

    @mcp.tool(annotations=CONTROL)
    def recall_memory(slot: int) -> dict[str, Any]:
        """Load memory M1-M5 into the active setpoints. Switches the output off."""
        return _guard(lambda: ctl.recall_memory(slot))

    if allow_memory_write:
        # Off by default: the memories belong to the bench user (front panel).
        @mcp.tool(annotations=CONTROL)
        def store_memory(slot: int, volts: float, amps: float) -> dict[str, Any]:
            """Program memory M1-M5 with voltage/current, without changing the active setpoints.
            Overwrites what the user stored in that slot."""
            return _guard(lambda: ctl.store_memory(slot, volts, amps))

    @mcp.tool(annotations=CONTROL)
    def release_port() -> dict[str, Any]:
        """Switch the output off and close the serial port so another program can use it.
        Any other tool reopens it."""
        return _guard(lambda: ctl.release())

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ps3005d-mcp", description=__doc__)
    parser.add_argument("--port", default=os.environ.get(PORT_ENV), help=f"default: ${PORT_ENV}")
    parser.add_argument("--sim", action="store_true", help="use the simulator instead")
    parser.add_argument("--sim-load-ohms", type=float, default=100.0)
    parser.add_argument("--max-volts", type=float, required=True)
    parser.add_argument("--max-amps", type=float, required=True)
    parser.add_argument("--max-duration-s", type=float, default=300.0)
    parser.add_argument(
        "--allow-memory-write",
        action="store_true",
        help="expose store_memory (may overwrite the user's front-panel memories)",
    )
    args = parser.parse_args(argv)

    if args.sim:
        sim_state = SimState(load_ohms=args.sim_load_ohms)

        def open_supply() -> PowerSupply:
            return PowerSupply(SimulatedTransport(sim_state))
    else:
        if not args.port:
            parser.error(f"--port or ${PORT_ENV} is required (or --sim)")
        port = args.port

        def open_supply() -> PowerSupply:
            return PowerSupply.open(port)

    # stdout carries the MCP protocol; logs must go to stderr.
    logging.basicConfig(level=logging.WARNING)
    ctl = Controller(open_supply, Limits(args.max_volts, args.max_amps, args.max_duration_s))
    try:
        build_server(ctl, allow_memory_write=args.allow_memory_write).run("stdio")
    finally:
        ctl.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
