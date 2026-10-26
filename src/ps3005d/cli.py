"""Command-line control of the Velleman PS3005D."""

from __future__ import annotations

import argparse
import os
import sys
import time

from ps3005d import __version__
from ps3005d import protocol as p
from ps3005d.device import DeviceError, PowerSupply
from ps3005d.sim import SimulatedTransport
from ps3005d.transport import list_serial_ports

PORT_ENV = "PS3005D_PORT"

PROBE_QUERIES = (
    p.QUERY_IDN,
    p.QUERY_STATUS,
    p.QUERY_VSET,
    p.QUERY_ISET,
    p.QUERY_VOUT,
    p.QUERY_IOUT,
)


def _on_off(text: str) -> bool:
    if text.lower() in ("on", "1", "true"):
        return True
    if text.lower() in ("off", "0", "false"):
        return False
    raise argparse.ArgumentTypeError("expected on/off")


def _resolve_port(arg: str | None) -> str:
    if arg:
        return arg
    if env := os.environ.get(PORT_ENV):
        return env
    likely = [pi for pi in list_serial_ports() if pi.likely_ps3005d]
    if len(likely) == 1:
        return likely[0].device
    raise SystemExit(
        f"cannot pick a port automatically ({len(likely)} candidates); "
        f"use --port or set {PORT_ENV}. See `ps3005d ports`."
    )


def _open(args: argparse.Namespace) -> PowerSupply:
    if args.sim:
        return PowerSupply(SimulatedTransport())
    return PowerSupply.open(_resolve_port(args.port))


def _print_state(ps: PowerSupply) -> None:
    st = ps.status()
    m = ps.measure()
    print(f"set:     {ps.voltage_setpoint():6.2f} V  {ps.current_setpoint():6.3f} A")
    print(f"output:  {m.volts:6.2f} V  {m.amps:6.3f} A  {m.watts:7.3f} W")
    print(
        f"status:  out={'ON' if st.output_on else 'off'} mode={st.mode.value} "
        f"ocp={'on' if st.ocp_on else 'off'} ovp={'on' if st.ovp_on else 'off'} "
        f"(raw 0x{st.raw:02x} = {st.raw:08b})"
    )


def cmd_ports(_: argparse.Namespace) -> int:
    ports = list_serial_ports()
    if not ports:
        print("no serial ports found")
    for pi in ports:
        ids = f"{pi.vid:04x}:{pi.pid:04x}" if pi.vid is not None and pi.pid is not None else "-"
        mark = "  <- likely PS3005D" if pi.likely_ps3005d else ""
        print(f"{pi.device:16} {ids:10} {pi.description}{mark}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Read-only check of every query; prints raw replies so the protocol can be verified."""
    ps = _open(args)
    try:
        for q in PROBE_QUERIES:
            reply = ps.raw_query(q)
            print(f"{q:8} -> {reply!r:40} hex={reply.hex(' ') or '(no reply)'}")
    finally:
        ps.close(output_off=False)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ps = _open(args)
    try:
        print(ps.identify())
        _print_state(ps)
    finally:
        ps.close(output_off=False)
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    if args.volts is None and args.amps is None:
        raise SystemExit("give --volts and/or --amps")
    ps = _open(args)
    try:
        if args.amps is not None:
            ps.set_current(args.amps)
        if args.volts is not None:
            ps.set_voltage(args.volts)
        _print_state(ps)
    finally:
        ps.close(output_off=False)
    return 0


def cmd_switch(args: argparse.Namespace) -> int:
    ps = _open(args)
    try:
        getattr(ps, args.command)(args.state)
        _print_state(ps)
    finally:
        ps.close(output_off=False)
    return 0


def cmd_memory(args: argparse.Namespace) -> int:
    ps = _open(args)
    try:
        if args.command == "save":
            ps.save(args.slot)
        elif args.command == "recall":
            ps.recall(args.slot)
        else:
            ps.store_memory(args.slot, args.volts, args.amps)
        _print_state(ps)
    finally:
        ps.close(output_off=False)
    return 0


def cmd_raw(args: argparse.Namespace) -> int:
    ps = _open(args)
    try:
        if args.cmd.endswith("?"):
            reply = ps.raw_query(args.cmd)
            print(f"{reply!r} hex={reply.hex(' ') or '(no reply)'}")
        else:
            ps.raw_write(args.cmd)
    finally:
        ps.close(output_off=False)
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    ps = _open(args)
    out = open(args.csv, "w", encoding="utf-8") if args.csv else None  # noqa: SIM115
    try:
        if out:
            out.write("t_s,volts,amps,watts\n")
        t0 = time.monotonic()
        n = 0
        while args.count <= 0 or n < args.count:
            if n:
                time.sleep(args.interval)
            m = ps.measure()
            t = time.monotonic() - t0
            print(f"{t:8.2f} s  {m.volts:6.2f} V  {m.amps:6.3f} A  {m.watts:7.3f} W", flush=True)
            if out:
                out.write(f"{t:.3f},{m.volts:.2f},{m.amps:.3f},{m.watts:.4f}\n")
            n += 1
    except KeyboardInterrupt:
        pass
    finally:
        if out:
            out.close()
        ps.close(output_off=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ps3005d", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--port", help=f"serial port (default: ${PORT_ENV} or auto-detect)")
    parser.add_argument("--sim", action="store_true", help="use the built-in simulator")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ports", help="list serial ports").set_defaults(func=cmd_ports)
    sub.add_parser("probe", help="read-only protocol check, raw replies").set_defaults(
        func=cmd_probe
    )
    sub.add_parser("status", help="setpoints, measurement and status").set_defaults(func=cmd_status)

    s = sub.add_parser("set", help="set voltage and/or current limit")
    s.add_argument("-v", "--volts", type=float)
    s.add_argument("-i", "--amps", type=float)
    s.set_defaults(func=cmd_set)

    for name, text in (("output", "output"), ("ocp", "over-current"), ("ovp", "over-voltage")):
        s = sub.add_parser(name, help=f"switch {text} on/off")
        s.add_argument("state", type=_on_off)
        s.set_defaults(func=cmd_switch)

    for name, text in (("save", "save active setpoints to"), ("recall", "recall (output off)")):
        s = sub.add_parser(name, help=f"{text} memory slot")
        s.add_argument("slot", type=int, choices=p.MEMORY_SLOTS)
        s.set_defaults(func=cmd_memory)
    s = sub.add_parser("store", help="program memory slot with V/I without applying them")
    s.add_argument("slot", type=int, choices=p.MEMORY_SLOTS)
    s.add_argument("volts", type=float)
    s.add_argument("amps", type=float)
    s.set_defaults(func=cmd_memory)

    s = sub.add_parser("raw", help="send a raw command (queries end with '?')")
    s.add_argument("cmd")
    s.set_defaults(func=cmd_raw)

    s = sub.add_parser("monitor", help="print measurements periodically")
    s.add_argument("--interval", type=float, default=0.5)
    s.add_argument("--count", type=int, default=0, help="number of samples (0 = until Ctrl-C)")
    s.add_argument("--csv", help="also write samples to this CSV file")
    s.set_defaults(func=cmd_monitor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (DeviceError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
