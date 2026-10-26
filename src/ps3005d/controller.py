"""Safety-limited, thread-safe facade over :class:`PowerSupply` for remote/automated use.

This is what the MCP server exposes. Compared to the raw driver it adds:

* operator-configured limits (``Limits``) below the hardware maximum that callers
  cannot raise; every setpoint, stored memory and output-enable is checked against them,
* one lock around every operation, so multi-step tools (sweeps) never interleave,
* lazy port opening and an explicit ``release`` so other programs can take the port,
* results as plain dicts (JSON-serializable).
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ps3005d import protocol as p
from ps3005d import sequence as seq
from ps3005d.device import PowerSupply
from ps3005d.sequence import Step

# Time for the output to settle after a change before it is measured.
SETTLE_S = 0.3


class LimitError(ValueError):
    pass


@dataclass(frozen=True)
class Limits:
    max_volts: float = p.V_MAX
    max_amps: float = p.I_MAX
    # Upper bound on how long a single sweep/measure call may run.
    max_duration_s: float = 300.0

    def __post_init__(self) -> None:
        if not 0 < self.max_volts <= p.V_MAX:
            raise ValueError(f"max_volts must be in (0, {p.V_MAX}]")
        if not 0 < self.max_amps <= p.I_MAX:
            raise ValueError(f"max_amps must be in (0, {p.I_MAX}]")

    def check(self, volts: float | None = None, amps: float | None = None) -> None:
        if volts is not None and not 0 <= volts <= self.max_volts:
            raise LimitError(f"{volts} V outside the allowed range 0..{self.max_volts} V")
        if amps is not None and not 0 <= amps <= self.max_amps:
            raise LimitError(f"{amps} A outside the allowed range 0..{self.max_amps} A")


class Controller:
    def __init__(
        self,
        open_supply: Callable[[], PowerSupply],
        limits: Limits,
        *,
        owns_port: bool = True,
    ) -> None:
        """``owns_port=False``: the supply belongs to a host (the GUI), which opened it and
        keeps it open; ``open_supply`` is then called for every operation and ``release``
        only switches the output off."""
        self._open_supply = open_supply
        self.limits = limits
        self._owns_port = owns_port
        self._ps: PowerSupply | None = None
        self._lock = threading.RLock()

    # -- connection -------------------------------------------------------

    def _dev(self) -> PowerSupply:
        if not self._owns_port:
            return self._open_supply()  # the host's current connection
        if self._ps is None:
            self._ps = self._open_supply()
        return self._ps

    def release(self) -> dict[str, Any]:
        """Switch the output off and close the port (shared port: output off only)."""
        with self._lock:
            if not self._owns_port:
                self._dev().output(False)
                return {"connected": True, "output_on": False}
            if self._ps is not None:
                try:
                    self._ps.close(output_off=True)
                finally:
                    self._ps = None
            return {"connected": False, "output_on": False}

    # -- queries ----------------------------------------------------------

    def info(self) -> dict[str, Any]:
        with self._lock:
            return {
                "identity": self._dev().identify(),
                "hardware_max": {"volts": p.V_MAX, "amps": p.I_MAX},
                "limits": {
                    "max_volts": self.limits.max_volts,
                    "max_amps": self.limits.max_amps,
                    "max_duration_s": self.limits.max_duration_s,
                },
                "memory_slots": list(p.MEMORY_SLOTS),
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            ps = self._dev()
            st = ps.status()
            m = ps.measure()
            return {
                "output_on": st.output_on,
                # The mode bit is only meaningful while the output is on.
                "mode": st.mode.value if st.output_on else None,
                "ocp_enabled": st.ocp_on,
                "ovp_enabled": st.ovp_on,
                "setpoint": {"volts": ps.voltage_setpoint(), "amps": ps.current_setpoint()},
                "measured": {"volts": m.volts, "amps": m.amps, "watts": round(m.watts, 4)},
            }

    # -- control ----------------------------------------------------------

    def set_setpoints(self, volts: float | None, amps: float | None) -> dict[str, Any]:
        if volts is None and amps is None:
            raise ValueError("give volts and/or amps")
        self.limits.check(volts, amps)
        with self._lock:
            ps = self._dev()
            # Lower the current limit first so a voltage increase never sees the old limit.
            if amps is not None:
                ps.set_current(amps)
            if volts is not None:
                ps.set_voltage(volts)
            time.sleep(SETTLE_S if ps.status().output_on else 0)
            return self.status()

    def _check_active_setpoints(self, ps: PowerSupply) -> None:
        # Setpoints may have come from a memory recall or the front panel.
        v, i = ps.voltage_setpoint(), ps.current_setpoint()
        try:
            self.limits.check(v, i)
        except LimitError as exc:
            raise LimitError(
                f"active setpoints {v} V / {i} A exceed the limits; lower them first ({exc})"
            ) from None

    def set_output(self, on: bool) -> dict[str, Any]:
        with self._lock:
            ps = self._dev()
            if on:
                self._check_active_setpoints(ps)
            ps.output(on)
            time.sleep(SETTLE_S)
            return self.status()

    def set_protection(self, ocp: bool | None, ovp: bool | None) -> dict[str, Any]:
        with self._lock:
            ps = self._dev()
            if ocp is not None:
                ps.ocp(ocp)
            if ovp is not None:
                ps.ovp(ovp)
            return self.status()

    def recall_memory(self, slot: int) -> dict[str, Any]:
        with self._lock:
            ps = self._dev()
            ps.recall(slot)
            time.sleep(SETTLE_S)
            result = self.status()
            try:
                self._check_active_setpoints(ps)
            except LimitError as exc:
                result["warning"] = f"{exc}; the output cannot be enabled with these values"
            return result

    def store_memory(self, slot: int, volts: float, amps: float) -> dict[str, Any]:
        self.limits.check(volts, amps)
        with self._lock:
            self._dev().store_memory(slot, volts, amps)
            return {"slot": slot, "volts": volts, "amps": amps, "status": self.status()}

    # -- measurement ------------------------------------------------------

    def _check_duration(self, seconds: float) -> None:
        if seconds > self.limits.max_duration_s:
            raise LimitError(
                f"operation would take ~{seconds:.0f} s, limit is {self.limits.max_duration_s} s"
            )

    def measure(self, samples: int, interval_s: float) -> dict[str, Any]:
        if samples < 1 or interval_s < 0:
            raise ValueError("samples must be >= 1 and interval_s >= 0")
        self._check_duration((samples - 1) * interval_s)
        with self._lock:
            ps = self._dev()
            output_was_on = ps.status().output_on
            rows: list[dict[str, float]] = []
            t0 = time.monotonic()
            for n in range(samples):
                if n:
                    time.sleep(interval_s)
                m = ps.measure()
                rows.append(
                    {
                        "t_s": round(time.monotonic() - t0, 3),
                        "volts": m.volts,
                        "amps": m.amps,
                        "watts": round(m.watts, 4),
                    }
                )
            result: dict[str, Any] = {"samples": rows, "stats": _stats(rows)}
            if output_was_on and not ps.status().output_on:
                result["warning"] = "output switched off during measurement (OVP/OCP trip?)"
            return result

    def sweep_voltage(
        self,
        start_volts: float,
        stop_volts: float,
        step_volts: float,
        current_limit_amps: float,
        dwell_s: float,
        leave_output_on: bool,
    ) -> dict[str, Any]:
        """Step the voltage from start to stop and measure at each step (I-V curve)."""
        if step_volts <= 0:
            raise ValueError("step_volts must be > 0")
        if dwell_s < 0:
            raise ValueError("dwell_s must be >= 0")
        self.limits.check(start_volts, current_limit_amps)
        self.limits.check(stop_volts)
        n = math.floor(abs(stop_volts - start_volts) / step_volts + 1e-9) + 1
        if n > 1000:
            raise LimitError(f"{n} steps; at most 1000 allowed")
        self._check_duration(n * (dwell_s + 0.2))
        direction = 1 if stop_volts >= start_volts else -1
        points = [round(start_volts + direction * k * step_volts, 2) for k in range(n)]

        with self._lock:
            ps = self._dev()
            rows: list[dict[str, Any]] = []
            aborted: str | None = None
            try:
                ps.set_current(current_limit_amps)
                ps.set_voltage(points[0])
                ps.output(True)
                time.sleep(SETTLE_S)
                for v in points:
                    ps.set_voltage(v)
                    time.sleep(dwell_s)
                    m = ps.measure()
                    st = ps.status()
                    rows.append(
                        {
                            "set_volts": v,
                            "volts": m.volts,
                            "amps": m.amps,
                            "watts": round(m.watts, 4),
                            "cc_mode": st.output_on and st.mode is p.Mode.CC,
                        }
                    )
                    if not st.output_on:
                        aborted = f"output switched off at {v} V (OVP/OCP trip?)"
                        break
            finally:
                if not leave_output_on or aborted:
                    ps.output(False)
            result: dict[str, Any] = {"points": rows, "status": self.status()}
            if aborted:
                result["warning"] = aborted
            return result

    def run_sequence(
        self,
        steps: list[Step],
        repeat: int,
        leave_output_on: bool,
        sample_interval_s: float,
    ) -> dict[str, Any]:
        """Switch the output on and run the steps ``repeat`` times, measuring during each.

        Steps start at absolute times (no drift from command latency). The output is
        switched off at the end unless ``leave_output_on``, and always on a trip.
        """
        if repeat < 1:
            raise ValueError("repeat must be >= 1")
        if sample_interval_s < 0.2:
            raise ValueError("sample_interval_s must be >= 0.2")
        seq.validate(steps, max_volts=self.limits.max_volts, max_amps=self.limits.max_amps)
        self._check_duration(seq.total_seconds(steps) * repeat)

        with self._lock:
            ps = self._dev()
            ovp_on = ps.status().ovp_on
            rows: list[dict[str, Any]] = []
            aborted: str | None = None
            t0 = time.monotonic()
            deadline = t0
            try:
                for rnd in range(repeat):
                    for n, step in enumerate(steps):
                        ps.set_current(step.amps)
                        ps.set_voltage(step.volts)
                        if rnd == 0 and n == 0:
                            ps.output(True)
                        deadline += step.seconds
                        samples: list[dict[str, float]] = []
                        cc = False
                        while True:
                            time.sleep(min(sample_interval_s, max(deadline - time.monotonic(), 0)))
                            m = ps.measure()
                            st = ps.status()
                            samples.append({"volts": m.volts, "amps": m.amps, "watts": m.watts})
                            cc = cc or (st.output_on and st.mode is p.Mode.CC)
                            if not st.output_on:
                                aborted = (
                                    f"output switched off in step {n + 1}, round {rnd + 1} "
                                    + (
                                        "(OVP is on: this supply often trips OVP when the "
                                        "voltage setpoint changes; disable it with "
                                        "set_protection(ovp=false) for sequences)"
                                        if ovp_on
                                        else "(OCP trip?)"
                                    )
                                )
                                break
                            if time.monotonic() >= deadline:
                                break
                        rows.append(
                            {
                                "step": n + 1,
                                "round": rnd + 1,
                                "set_volts": step.volts,
                                "set_amps": step.amps,
                                "seconds": step.seconds,
                                "measured": _stats(samples),
                                "entered_cc": cc,
                            }
                        )
                        if aborted:
                            break
                    if aborted:
                        break
            finally:
                if not leave_output_on or aborted:
                    ps.output(False)
            result: dict[str, Any] = {
                "steps": rows,
                "ovp_enabled": ovp_on,
                "elapsed_s": round(time.monotonic() - t0, 2),
                "status": self.status(),
            }
            if aborted:
                result["warning"] = aborted
            return result


def _stats(rows: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for key in ("volts", "amps", "watts"):
        values = [r[key] for r in rows]
        out[key] = {
            "min": min(values),
            "max": max(values),
            "mean": round(sum(values) / len(values), 4),
        }
    return out
