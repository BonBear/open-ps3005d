"""Device worker: owns the PowerSupply in a background QThread.

The GUI thread never talks to the serial port. It requests operations through
signals connected to the worker's slots (queued across threads) and receives
results through the worker's signals. A QTimer in the worker thread polls
measurements.

Memories: the firmware switches the output off on every RCL, and storing a slot
needs an RCL (SAV writes the active memory). To never interrupt a running output,
the worker caches M1-M5 (read on connect while the output is off, kept up to date
by stores) and

* recalls a cached slot by setting its voltage/current directly (no RCL),
* queues stores requested while the output is on and writes them as soon as the
  output is off.

The cache is valid because the front panel is locked while the PC is connected.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ps3005d import sequence as seq
from ps3005d.device import DeviceError, PowerSupply
from ps3005d.gui.i18n import tr
from ps3005d.protocol import MEMORY_SLOTS, Mode
from ps3005d.sequence import Step
from ps3005d.sim import SimState, SimulatedTransport

# Read the setpoints back every N polls.
SETPOINT_EVERY = 10
RECALL_SETTLE_S = 0.3

# memory_slot states
SAVED = "saved"
PENDING = "pending"  # queued until the output is off
FAILED = "failed"  # values reverted to the last known content

# sequence_finished reasons
SEQ_DONE = "done"
SEQ_STOPPED = "stopped"  # by the user (output switched off)
SEQ_TRIPPED = "tripped"  # output went off by itself (OVP/OCP)
SEQ_ERROR = "error"


@dataclass(frozen=True)
class Sample:
    t: float  # seconds since connect
    volts: float
    amps: float
    output_on: bool
    mode: Mode | None  # None while the output is off
    ocp_on: bool
    ovp_on: bool

    @property
    def watts(self) -> float:
        return self.volts * self.amps


class DeviceWorker(QObject):
    connected = Signal(str)  # identity
    disconnected = Signal()
    sample = Signal(object)  # Sample
    setpoints = Signal(float, float)
    memories = Signal(object)  # dict[int, tuple[float, float]]
    memory_slot = Signal(int, float, float, str)  # slot, volts, amps, state
    sequence_progress = Signal(int, int, float)  # step index, round index, seconds left in step
    sequence_finished = Signal(str)  # SEQ_* reason
    error = Signal(str)

    def __init__(self, sim_state: SimState | None = None) -> None:
        super().__init__()
        self._sim_state = sim_state
        self._ps: PowerSupply | None = None
        self._timer: QTimer | None = None
        self._interval_ms = 250
        self._t0 = 0.0
        self._polls = 0
        self._output_on = False
        self._mem: dict[int, tuple[float, float]] = {}
        self._pending: dict[int, tuple[float, float]] = {}
        self._sp = [0.0, 0.0]  # last known setpoints (volts, amps)
        # Running sequence: steps, repeat (0 = forever), leave output on, start, position.
        self._seq: list[Step] | None = None
        self._seq_repeat = 1
        self._seq_leave_on = False
        self._seq_t0 = 0.0
        self._seq_pos = (0, 0)
        self._seq_timer: QTimer | None = None

    # -- helpers ----------------------------------------------------------

    def _run(self, fn: Callable[[], object]) -> bool:
        """Call ``fn`` if connected, reporting errors. Returns False on failure."""
        if self._ps is None:
            self.error.emit(tr("not connected"))
            return False
        try:
            fn()
        except Exception as exc:
            self.error.emit(str(exc))
            if isinstance(exc, OSError):
                self.disconnect_device()
            return False
        return True

    def current_supply(self) -> PowerSupply:
        """For the GUI-hosted MCP server, which shares this connection (any thread)."""
        ps = self._ps
        if ps is None:
            raise DeviceError("the GUI is not connected to the supply")
        return ps

    def _dev(self) -> PowerSupply:
        assert self._ps is not None
        return self._ps

    def _emit_setpoints(self) -> None:
        ps = self._dev()
        self._sp = [ps.voltage_setpoint(), ps.current_setpoint()]
        self.setpoints.emit(*self._sp)

    def _read_memories(self) -> None:
        ps = self._dev()
        v0, i0 = ps.voltage_setpoint(), ps.current_setpoint()
        try:
            for slot in MEMORY_SLOTS:
                ps.recall(slot)
                time.sleep(RECALL_SETTLE_S)
                self._mem[slot] = (ps.voltage_setpoint(), ps.current_setpoint())
        finally:
            ps.set_voltage(v0)
            ps.set_current(i0)
        self.memories.emit(dict(self._mem))

    def _store_now(self, slot: int, volts: float, amps: float) -> None:
        try:
            self._dev().store_memory(slot, volts, amps)
        except Exception as exc:
            old = self._mem.get(slot, (float("nan"), float("nan")))
            self.memory_slot.emit(slot, old[0], old[1], FAILED)
            self.error.emit(tr("storing M{slot} failed: {error}", slot=slot, error=exc))
            if isinstance(exc, OSError):
                raise
            return
        self._mem[slot] = (volts, amps)
        self.memory_slot.emit(slot, volts, amps, SAVED)

    def _flush_pending(self) -> None:
        while self._pending:
            slot, (v, i) = next(iter(self._pending.items()))
            del self._pending[slot]
            self._store_now(slot, v, i)

    # -- connection -------------------------------------------------------

    @Slot(str, bool)
    def connect_device(self, port: str, sim: bool) -> None:
        self.disconnect_device()
        self._mem.clear()
        self._pending.clear()
        try:
            if sim:
                state = self._sim_state or SimState(load_ohms=10.0)
                self._sim_state = state
                self._ps = PowerSupply(SimulatedTransport(state))
            else:
                self._ps = PowerSupply.open(port)
            identity = self._ps.identify()
            self._output_on = self._ps.status().output_on
            if not self._output_on:
                self._read_memories()
            self._emit_setpoints()
        except Exception as exc:
            self.error.emit(tr("connect failed: {error}", error=exc))
            if self._ps is not None:
                self._ps.close(output_off=False)
            self._ps = None
            return
        self._t0 = time.monotonic()
        self._polls = 0
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.poll)
        self._timer.start(self._interval_ms)
        self.connected.emit(identity)
        self.poll()

    @Slot(bool)
    def disconnect_device(self, output_off: bool = False) -> None:
        if self._timer is not None:
            self._timer.stop()
        if self._seq is not None:
            self._end_sequence(SEQ_STOPPED, switch_off=False)  # output_off below decides
        ps = self._ps
        if ps is None:
            return
        try:
            if output_off:
                ps.output(False)
                self._flush_pending()
            elif self._pending:
                slots = ", ".join(f"M{s}" for s in sorted(self._pending))
                self.error.emit(tr("{slots} not stored: output was still on", slots=slots))
            ps.close(output_off=output_off)
        except Exception as exc:
            self.error.emit(str(exc))
        self._ps = None
        self._pending.clear()
        self.disconnected.emit()

    @Slot(int)
    def set_interval(self, ms: int) -> None:
        self._interval_ms = ms
        if self._timer is not None and self._timer.isActive():
            self._timer.start(ms)

    # -- polling ----------------------------------------------------------

    @Slot()
    def poll(self) -> None:
        def read() -> None:
            ps = self._dev()
            m = ps.measure()
            st = ps.status()
            self._output_on = st.output_on
            self.sample.emit(
                Sample(
                    t=time.monotonic() - self._t0,
                    volts=m.volts,
                    amps=m.amps,
                    output_on=st.output_on,
                    mode=st.mode if st.output_on else None,
                    ocp_on=st.ocp_on,
                    ovp_on=st.ovp_on,
                )
            )
            self._polls += 1
            if self._polls % SETPOINT_EVERY == 0:
                self._emit_setpoints()
            if self._seq is not None:
                if not st.output_on and time.monotonic() - self._seq_t0 > 0.5:
                    self._end_sequence(SEQ_TRIPPED, switch_off=False)
                else:
                    self._emit_seq_progress()
            if self._pending and not st.output_on:
                self._flush_pending()

        if self._ps is not None:
            self._run(read)

    # -- control ----------------------------------------------------------

    @Slot(float)
    def set_voltage(self, volts: float) -> None:
        if self._run(lambda: self._dev().set_voltage(volts)):
            self._sp[0] = volts
            self.setpoints.emit(*self._sp)

    @Slot(float)
    def set_current(self, amps: float) -> None:
        if self._run(lambda: self._dev().set_current(amps)):
            self._sp[1] = amps
            self.setpoints.emit(*self._sp)

    @Slot(bool)
    def set_output(self, on: bool) -> None:
        if not on and self._seq is not None:
            self._end_sequence(SEQ_STOPPED, switch_off=False)
        if self._run(lambda: self._dev().output(on)):
            self.poll()

    @Slot(bool)
    def set_ocp(self, on: bool) -> None:
        if self._run(lambda: self._dev().ocp(on)):
            self.poll()

    @Slot(bool)
    def set_ovp(self, on: bool) -> None:
        if self._run(lambda: self._dev().ovp(on)):
            self.poll()

    # -- memories ---------------------------------------------------------

    @Slot(int)
    def recall(self, slot: int) -> None:
        def recall() -> None:
            ps = self._dev()
            if slot in self._mem:
                # No RCL: it would switch the output off.
                v, i = self._mem[slot]
                ps.set_current(i)
                ps.set_voltage(v)
            elif not ps.status().output_on:
                ps.recall(slot)
                time.sleep(RECALL_SETTLE_S)
                self._mem[slot] = (ps.voltage_setpoint(), ps.current_setpoint())
                self.memory_slot.emit(slot, *self._mem[slot], SAVED)
            else:
                raise RuntimeError(
                    tr(
                        "M{slot} is unknown; switch the output off and read the memories first",
                        slot=slot,
                    )
                )
            self._emit_setpoints()

        if self._run(recall):
            self.poll()

    @Slot(int, float, float)
    def store(self, slot: int, volts: float, amps: float) -> None:
        def store() -> None:
            if self._dev().status().output_on:
                self._pending[slot] = (volts, amps)
                self.memory_slot.emit(slot, volts, amps, PENDING)
            else:
                self._store_now(slot, volts, amps)

        self._run(store)

    @Slot()
    def refresh_setpoints(self) -> None:
        """Re-read the setpoints now (e.g. after the AI changed them)."""
        if self._ps is not None:
            self._run(self._emit_setpoints)

    @Slot(int, float, float)
    def note_memory(self, slot: int, volts: float, amps: float) -> None:
        """Someone else (the AI) stored a memory; keep the cache right."""
        self._mem[slot] = (volts, amps)
        self.memory_slot.emit(slot, volts, amps, SAVED)

    @Slot()
    def read_memories(self) -> None:
        """Read M1-M5 by recalling each. Refused while the output is on (RCL turns it off)."""

        def read() -> None:
            if self._dev().status().output_on:
                raise RuntimeError(tr("switch the output off before reading memories"))
            self._read_memories()

        self._run(read)

    # -- sequences --------------------------------------------------------

    @Slot(object, int, bool)
    def start_sequence(self, steps: list[Step], repeat: int, leave_on: bool) -> None:
        """Run ``steps`` ``repeat`` times (0 = until stopped); switches the output on."""
        try:
            seq.validate(steps)
        except ValueError as exc:
            self.error.emit(str(exc))
            self.sequence_finished.emit(SEQ_ERROR)
            return
        self._seq = list(steps)
        self._seq_repeat = repeat
        self._seq_leave_on = leave_on
        self._seq_t0 = time.monotonic()
        self._seq_pos = (0, 0)
        first = self._seq[0]

        def begin() -> None:
            ps = self._dev()
            ps.set_current(first.amps)
            ps.set_voltage(first.volts)
            ps.output(True)
            self._sp = [first.volts, first.amps]
            self.setpoints.emit(*self._sp)

        if not self._run(begin):
            self._end_sequence(SEQ_ERROR, switch_off=True)
            return
        if self._seq_timer is None:
            self._seq_timer = QTimer(self)
            self._seq_timer.setSingleShot(True)
            self._seq_timer.timeout.connect(self._sequence_tick)
        self._emit_seq_progress()
        self._schedule_next_step()

    @Slot()
    def stop_sequence(self) -> None:
        if self._seq is not None:
            self._end_sequence(SEQ_STOPPED, switch_off=True)

    def _elapsed(self) -> float:
        return time.monotonic() - self._seq_t0

    def _schedule_next_step(self) -> None:
        assert self._seq is not None and self._seq_timer is not None
        boundary = seq.next_boundary(self._seq, self._seq_repeat, self._elapsed())
        if boundary is None:
            self._end_sequence(SEQ_DONE, switch_off=not self._seq_leave_on)
            return
        self._seq_timer.start(max(int((boundary - self._elapsed()) * 1000) + 5, 0))

    def _sequence_tick(self) -> None:
        if self._seq is None:
            return
        pos = seq.position(self._seq, self._seq_repeat, self._elapsed())
        if pos is None:
            self._end_sequence(SEQ_DONE, switch_off=not self._seq_leave_on)
            return
        index, rnd, _ = pos
        if (index, rnd) != self._seq_pos:
            step = self._seq[index]

            def apply() -> None:
                ps = self._dev()
                ps.set_current(step.amps)
                ps.set_voltage(step.volts)
                self._sp = [step.volts, step.amps]
                self.setpoints.emit(*self._sp)

            if not self._run(apply):
                self._end_sequence(SEQ_ERROR, switch_off=True)
                return
            self._seq_pos = (index, rnd)
            self._emit_seq_progress()
        self._schedule_next_step()

    def _emit_seq_progress(self) -> None:
        assert self._seq is not None
        pos = seq.position(self._seq, self._seq_repeat, self._elapsed())
        if pos is not None:
            index, rnd, left = pos
            self.sequence_progress.emit(index, rnd, left)

    def _end_sequence(self, reason: str, *, switch_off: bool) -> None:
        self._seq = None
        if self._seq_timer is not None:
            self._seq_timer.stop()
        if switch_off and self._ps is not None:
            self._run(lambda: self._dev().output(False))
        self.sequence_finished.emit(reason)
