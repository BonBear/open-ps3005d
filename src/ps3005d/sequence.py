"""Step sequences: (voltage, current limit, duration) steps, optionally repeated.

Pure data and timing; no I/O to the supply. Used by the GUI worker (timer driven, so
the graphs stay live), ``Controller.run_sequence`` (MCP server) and the CLI.

File format (``.csv``)::

    volts,amps,seconds
    5.00,1.000,10
    12.00,0.500,30

The vendor app's step table (``2.ini``: whitespace-separated ``step V I seconds``
rows, no header) can be loaded too; that column order is inferred, not documented.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from ps3005d.protocol import I_MAX, V_MAX

MIN_STEP_S = 0.5  # setting V and I takes ~0.2 s on the real unit
MAX_STEPS = 1000


@dataclass(frozen=True)
class Step:
    volts: float
    amps: float
    seconds: float


def validate(steps: list[Step], *, max_volts: float = V_MAX, max_amps: float = I_MAX) -> None:
    """Raise ValueError with a step number (1-based) for the first invalid step."""
    if not steps:
        raise ValueError("the sequence has no steps")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"{len(steps)} steps; at most {MAX_STEPS} allowed")
    for n, s in enumerate(steps, 1):
        if not 0 <= s.volts <= max_volts:
            raise ValueError(f"step {n}: {s.volts} V outside 0..{max_volts} V")
        if not 0 <= s.amps <= max_amps:
            raise ValueError(f"step {n}: {s.amps} A outside 0..{max_amps} A")
        if s.seconds < MIN_STEP_S:
            raise ValueError(f"step {n}: {s.seconds} s is shorter than {MIN_STEP_S} s")


def total_seconds(steps: list[Step]) -> float:
    return sum(s.seconds for s in steps)


def position(steps: list[Step], repeat: int, elapsed: float) -> tuple[int, int, float] | None:
    """Where a run is ``elapsed`` seconds after it started.

    Returns ``(step_index, round_index, seconds_left_in_step)``, or None once finished.
    ``repeat`` = 0 means forever.
    """
    cycle = total_seconds(steps)
    rnd, t = divmod(max(elapsed, 0.0), cycle)
    if repeat and rnd >= repeat:
        return None
    for i, s in enumerate(steps):
        if t < s.seconds:
            return i, int(rnd), s.seconds - t
        t -= s.seconds
    return len(steps) - 1, int(rnd), 0.0  # float rounding at the very end of a cycle


def next_boundary(steps: list[Step], repeat: int, elapsed: float) -> float | None:
    """Elapsed time of the next step change (or of the end), None when already finished."""
    pos = position(steps, repeat, elapsed)
    return None if pos is None else elapsed + pos[2]


def dumps(steps: list[Step]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["volts", "amps", "seconds"])
    for s in steps:
        w.writerow([f"{s.volts:.2f}", f"{s.amps:.3f}", f"{s.seconds:g}"])
    return out.getvalue()


def loads(text: str) -> list[Step]:
    """Parse our CSV format or the vendor's whitespace-separated ``step V I s`` table."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    if lines[0].lower().replace(" ", "").startswith("volts,amps,seconds"):
        rows = list(csv.reader(lines[1:]))
        try:
            return [Step(float(v), float(i), float(s)) for v, i, s in rows]
        except ValueError as exc:
            raise ValueError(f"not a valid sequence file: {exc}") from None
    steps = []
    for n, ln in enumerate(lines, 1):
        parts = ln.replace(",", " ").split()
        if len(parts) != 4:
            raise ValueError(f"line {n}: expected 'step volts amps seconds', got {ln!r}")
        try:
            steps.append(Step(float(parts[1]), float(parts[2]), float(parts[3])))
        except ValueError:
            raise ValueError(f"line {n}: not numbers: {ln!r}") from None
    return steps


def load(path: Path) -> list[Step]:
    return loads(path.read_text(encoding="utf-8", errors="replace"))


def save(path: Path, steps: list[Step]) -> None:
    path.write_text(dumps(steps), encoding="utf-8")
