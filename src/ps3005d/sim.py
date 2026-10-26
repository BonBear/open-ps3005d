"""In-memory simulated PS3005D speaking the same wire protocol as the real unit.

The output drives a purely resistive load (``load_ohms``; ``math.inf`` = open
terminals). Used by the test suite and for running the GUI/MCP server offline.
"""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, field

from ps3005d.protocol import I_MAX, MEMORY_SLOTS, V_MAX

IDN = "VELLEMAN PS3005D V2.0 (SIMULATED)"

_SET = re.compile(r"^(VSET1|ISET1):([0-9.]+)$")
_SLOT = re.compile(r"^(SAV|RCL)([0-9])$")
_FLAG = re.compile(r"^(OUT|OCP|OVP|BEEP)([01])$")
_FLAG_ATTR = {"OUT": "output", "OCP": "ocp", "OVP": "ovp", "BEEP": "beep"}


@dataclass
class SimState:
    vset: float = 0.0
    iset: float = 0.0
    output: bool = False
    ocp: bool = False
    ovp: bool = False
    beep: bool = True
    load_ohms: float = math.inf
    # Memory last recalled; SAV writes here whatever slot number it is given.
    active_memory: int = 1
    # Firmware quirk: OVP0 while OCP is on leaves the STATUS OVP bit set until OCP0.
    ovp_bit_stuck: bool = False
    memory: dict[int, tuple[float, float]] = field(
        default_factory=lambda: dict.fromkeys(MEMORY_SLOTS, (0.0, 0.0))
    )

    def operating_point(self) -> tuple[float, float, bool]:
        """Return (volts, amps, constant_voltage) at the output terminals."""
        if not self.output:
            return 0.0, 0.0, True
        if math.isinf(self.load_ohms):
            return self.vset, 0.0, True
        if self.iset * self.load_ohms < self.vset:
            v = self.iset * self.load_ohms
            return v, self.iset, False
        return self.vset, self.vset / self.load_ohms, True


class SimulatedTransport:
    def __init__(self, state: SimState | None = None) -> None:
        self.state = state or SimState()
        self.log: list[str] = []
        self._lock = threading.Lock()

    def write(self, cmd: str) -> None:
        with self._lock:
            self.log.append(cmd)
            self._execute(cmd)

    def query(self, cmd: str, size: int | None = None) -> bytes:
        with self._lock:
            self.log.append(cmd)
            reply = self._answer(cmd).encode("latin-1")  # STATUS? is a raw byte, may be >= 0x80
            return reply[:size] if size is not None else reply

    def close(self) -> None:
        pass

    def _execute(self, cmd: str) -> None:
        s = self.state
        if m := _SET.match(cmd):
            value = float(m.group(2))
            if m.group(1) == "VSET1":
                s.vset = min(value, V_MAX)
            else:
                s.iset = min(value, I_MAX)
        elif m := _FLAG.match(cmd):
            name, on = m.group(1), m.group(2) == "1"
            if name == "OVP" and not on and s.ovp and s.ocp:
                s.ovp_bit_stuck = True
            elif (name == "OVP" and on) or (name == "OCP" and not on):
                s.ovp_bit_stuck = False
            setattr(s, _FLAG_ATTR[name], on)
        elif m := _SLOT.match(cmd):
            slot = int(m.group(2))
            if slot not in MEMORY_SLOTS:
                return
            if m.group(1) == "SAV":
                # Real firmware quirk (verified): the slot number is ignored.
                s.memory[s.active_memory] = (s.vset, s.iset)
            else:
                s.vset, s.iset = s.memory[slot]
                s.active_memory = slot
                s.output = False  # manual: recalling a memory switches the output off

    def _answer(self, cmd: str) -> str:
        s = self.state
        v, i, cv = s.operating_point()
        if cmd == "*IDN?":
            return IDN
        if cmd == "VSET1?":
            return f"{s.vset:05.2f}"
        if cmd == "ISET1?":
            return f"{s.iset:05.3f}M"  # the real firmware appends a junk byte here
        if cmd == "VOUT1?":
            return f"{v:05.2f}"
        if cmd == "IOUT1?":
            return f"{i:05.3f}"
        if cmd == "STATUS?":
            b = int(cv) | (s.ocp << 5) | (s.output << 6) | ((s.ovp or s.ovp_bit_stuck) << 7)
            return chr(b)
        return ""
