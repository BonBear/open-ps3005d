"""Wire protocol for the Velleman PS3005D (Korad KA3005P-compatible command set).

Commands are plain ASCII with no terminator, sent over a USB CDC/serial port at
9600 baud 8N1. This module only builds command strings, validates setpoints and
parses replies; it performs no I/O.

The command set is the de-facto Korad/Tenma one; docs/protocol.md records which
parts have been verified on a real PS3005D.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

BAUDRATE = 9600

V_MAX = 30.0
I_MAX = 5.0
MEMORY_SLOTS = (1, 2, 3, 4, 5)


class Mode(Enum):
    CC = "CC"
    CV = "CV"


@dataclass(frozen=True)
class Status:
    """Decoded STATUS? byte."""

    mode: Mode
    output_on: bool
    ocp_on: bool
    ovp_on: bool
    raw: int


def _check_range(name: str, value: float, upper: float) -> None:
    if not 0.0 <= value <= upper:
        raise ValueError(f"{name} {value} outside 0..{upper}")


def set_voltage(volts: float) -> str:
    _check_range("voltage", volts, V_MAX)
    return f"VSET1:{volts:05.2f}"


def set_current(amps: float) -> str:
    _check_range("current", amps, I_MAX)
    return f"ISET1:{amps:05.3f}"


def output(on: bool) -> str:
    return f"OUT{int(on)}"


def ocp(on: bool) -> str:
    return f"OCP{int(on)}"


def ovp(on: bool) -> str:
    return f"OVP{int(on)}"


def beep(on: bool) -> str:
    return f"BEEP{int(on)}"


def _check_slot(slot: int) -> None:
    if slot not in MEMORY_SLOTS:
        raise ValueError(f"memory slot {slot} not in {MEMORY_SLOTS}")


def save(slot: int) -> str:
    """SAV<n>. NOTE: the PS3005D firmware ignores n and writes the *active* memory
    (the one last recalled; M1 after power-on). Use PowerSupply.store_memory."""
    _check_slot(slot)
    return f"SAV{slot}"


def recall(slot: int) -> str:
    """RCL<n>: load memory n, make it the active memory, switch the output off."""
    _check_slot(slot)
    return f"RCL{slot}"


QUERY_IDN = "*IDN?"
QUERY_STATUS = "STATUS?"
QUERY_VSET = "VSET1?"
QUERY_ISET = "ISET1?"
QUERY_VOUT = "VOUT1?"
QUERY_IOUT = "IOUT1?"

# Fixed reply lengths (verified). Reading exactly this many bytes avoids waiting for
# the line to go quiet; trailing junk (ISET1? sends "0.100M") is flushed before the
# next command. Queries not listed here have variable-length replies.
REPLY_SIZE = {
    QUERY_STATUS: 1,
    QUERY_VSET: 5,
    QUERY_ISET: 5,
    QUERY_VOUT: 5,
    QUERY_IOUT: 5,
}


def parse_float(reply: bytes) -> float:
    # Some firmware revisions append junk bytes after the number; keep the leading numeric part.
    text = reply.decode("ascii", errors="ignore").strip()
    digits = ""
    for ch in text:
        if ch.isdigit() or ch == ".":
            digits += ch
        else:
            break
    if not digits:
        raise ValueError(f"no numeric value in reply {reply!r}")
    return float(digits)


def parse_status(reply: bytes) -> Status:
    if not reply:
        raise ValueError("empty STATUS reply")
    b = reply[0]
    return Status(
        mode=Mode.CV if b & 0x01 else Mode.CC,
        output_on=bool(b & 0x40),
        ocp_on=bool(b & 0x20),
        ovp_on=bool(b & 0x80),
        raw=b,
    )
