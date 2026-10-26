"""High-level driver for the PS3005D on top of a :class:`~ps3005d.transport.Transport`."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from types import TracebackType

from ps3005d import protocol as p
from ps3005d.transport import SerialTransport, Transport

# Pause after SAV before reading the slot back; the firmware writes to EEPROM.
SAVE_SETTLE_S = 0.2


class DeviceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Measurement:
    volts: float
    amps: float

    @property
    def watts(self) -> float:
        return self.volts * self.amps


class PowerSupply:
    """Synchronous driver. Never switches the output on unless asked explicitly."""

    def __init__(self, transport: Transport) -> None:
        self._t = transport
        self._closed = False
        # Last OVP command sent this session (None = none sent); see status().
        self._ovp_commanded: bool | None = None

    @classmethod
    def open(cls, port: str) -> PowerSupply:
        return cls(SerialTransport(port))

    def __enter__(self) -> PowerSupply:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self, *, output_off: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if output_off:
                self.output(False)
        finally:
            self._t.close()

    def _query(self, cmd: str) -> bytes:
        size = p.REPLY_SIZE.get(cmd)
        reply = self._t.query(cmd, size)
        if not reply or (size is not None and len(reply) < size):
            raise DeviceError(f"no reply to {cmd!r} (wrong port, device off, or not a PS3005D?)")
        return reply

    def _query_float(self, cmd: str) -> float:
        return p.parse_float(self._query(cmd))

    def raw_query(self, cmd: str) -> bytes:
        """Send an unvalidated query and return the raw reply (may be empty). For debugging."""
        return self._t.query(cmd)

    def raw_write(self, cmd: str) -> None:
        """Send a raw command. For debugging; setpoints must go through set_voltage/current."""
        if cmd.upper().startswith(("VSET", "ISET")):
            raise ValueError("use set_voltage/set_current for setpoints (range-checked)")
        self._t.write(cmd)

    def identify(self) -> str:
        return self._query(p.QUERY_IDN).decode("ascii", errors="replace").strip()

    def set_voltage(self, volts: float) -> None:
        self._t.write(p.set_voltage(volts))

    def set_current(self, amps: float) -> None:
        self._t.write(p.set_current(amps))

    def voltage_setpoint(self) -> float:
        return self._query_float(p.QUERY_VSET)

    def current_setpoint(self) -> float:
        return self._query_float(p.QUERY_ISET)

    def measure(self) -> Measurement:
        return Measurement(self._query_float(p.QUERY_VOUT), self._query_float(p.QUERY_IOUT))

    def status(self) -> p.Status:
        """Decoded STATUS?, corrected for a firmware quirk (verified on hardware).

        After OVP0 while OCP is on, the OVP bit stays 1 until OCP is switched off,
        although OVP is off - also across sessions. So:

        * once this session knows the real OVP state (it sent OVP0/OVP1 or resolved
          it), a stale "on" bit is ignored;
        * the first time both bits read "on" without that knowledge, the real state is
          resolved by switching OCP off for one status read (~0.2 s) and back on. With
          the output on, the current limit still applies meanwhile (CC instead of cut-off).
        """
        st = p.parse_status(self._query(p.QUERY_STATUS))
        if st.ovp_on and st.ocp_on and self._ovp_commanded is None:
            self.ocp(False)
            try:
                actual = p.parse_status(self._query(p.QUERY_STATUS)).ovp_on
            finally:
                self.ocp(True)
            self._ovp_commanded = actual
        if self._ovp_commanded is False and st.ovp_on:
            st = replace(st, ovp_on=False)
        return st

    def output(self, on: bool) -> None:
        self._t.write(p.output(on))

    def ocp(self, on: bool) -> None:
        self._t.write(p.ocp(on))

    def ovp(self, on: bool) -> None:
        self._t.write(p.ovp(on))
        self._ovp_commanded = on

    def beep(self, on: bool) -> None:
        self._t.write(p.beep(on))

    def save(self, slot: int) -> None:
        """Store the current setpoints in memory ``slot`` (1..5). See :meth:`store_memory`."""
        self.store_memory(slot, self.voltage_setpoint(), self.current_setpoint())

    def recall(self, slot: int) -> None:
        """Load memory ``slot``. The supply switches its output off when recalling."""
        self._t.write(p.recall(slot))

    def store_memory(self, slot: int, volts: float, amps: float) -> None:
        """Program memory ``slot`` with the given values, leaving the active setpoints unchanged.

        The firmware's ``SAV<n>`` ignores n and writes the active memory (the last one
        recalled), so the slot is recalled first: RCL n, set values, SAV n. Recalling
        switches the output off; it is switched back on afterwards if it was on, but only
        if the store succeeded. The result is verified by moving the setpoints to a
        different value and recalling the slot again. One retry, then :class:`DeviceError`.

        Side effect: ``slot`` becomes the active memory.
        """
        p.save(slot)  # validate before touching the device
        p.set_voltage(volts)
        p.set_current(amps)
        was_on = self.status().output_on
        old_v, old_i = self.voltage_setpoint(), self.current_setpoint()
        sentinel = (0.0, 0.0) if (volts, amps) != (0.0, 0.0) else (1.0, 0.01)
        self.output(False)
        try:
            for _ in range(2):
                self.recall(slot)
                self.set_voltage(volts)
                self.set_current(amps)
                self._t.write(p.save(slot))
                time.sleep(SAVE_SETTLE_S)
                self.set_voltage(sentinel[0])
                self.set_current(sentinel[1])
                self.recall(slot)
                got_v, got_i = self.voltage_setpoint(), self.current_setpoint()
                if abs(got_v - volts) < 0.005 and abs(got_i - amps) < 0.0005:
                    break
            else:
                raise DeviceError(
                    f"memory M{slot} did not store {volts:.2f} V / {amps:.3f} A "
                    f"(reads back {got_v:.2f} V / {got_i:.3f} A)"
                )
        finally:
            self.set_voltage(old_v)
            self.set_current(old_i)
        if was_on:
            self.output(True)
