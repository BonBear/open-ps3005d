import math

import pytest

from ps3005d.device import DeviceError, PowerSupply
from ps3005d.protocol import Mode
from ps3005d.sim import SimState, SimulatedTransport


@pytest.fixture
def sim() -> SimulatedTransport:
    return SimulatedTransport()


@pytest.fixture
def ps(sim: SimulatedTransport) -> PowerSupply:
    return PowerSupply(sim)


def test_identify(ps: PowerSupply) -> None:
    assert "PS3005D" in ps.identify()


def test_setpoints_roundtrip(ps: PowerSupply) -> None:
    ps.set_voltage(12.5)
    ps.set_current(1.25)
    assert ps.voltage_setpoint() == 12.5
    assert ps.current_setpoint() == 1.25


def test_out_of_range_never_reaches_device(ps: PowerSupply, sim: SimulatedTransport) -> None:
    with pytest.raises(ValueError):
        ps.set_voltage(31)
    with pytest.raises(ValueError):
        ps.raw_write("VSET1:31.00")
    assert sim.log == []


def test_setpoint_changes_do_not_enable_output(ps: PowerSupply) -> None:
    ps.set_voltage(5)
    ps.set_current(1)
    assert not ps.status().output_on
    assert ps.measure().volts == 0.0


def test_constant_voltage_and_current(sim: SimulatedTransport, ps: PowerSupply) -> None:
    sim.state.load_ohms = 10.0
    ps.set_voltage(5)
    ps.set_current(1)
    ps.output(True)
    m = ps.measure()
    assert (m.volts, m.amps) == (5.0, 0.5)
    assert ps.status().mode is Mode.CV

    ps.set_current(0.2)
    m = ps.measure()
    assert (m.volts, m.amps) == (2.0, 0.2)
    assert ps.status().mode is Mode.CC


def test_recall_switches_output_off(ps: PowerSupply) -> None:
    ps.set_voltage(3.3)
    ps.set_current(0.5)
    ps.save(2)
    ps.set_voltage(9)
    ps.output(True)
    ps.recall(2)
    assert ps.voltage_setpoint() == 3.3
    assert not ps.status().output_on


def test_store_memory_keeps_active_setpoints() -> None:
    sim = SimulatedTransport(SimState(load_ohms=math.inf))
    ps = PowerSupply(sim)
    ps.set_voltage(5)
    ps.set_current(1)
    ps.output(True)
    ps.store_memory(4, 24.0, 0.1)
    assert sim.state.memory[4] == (24.0, 0.1)
    assert (ps.voltage_setpoint(), ps.current_setpoint()) == (5.0, 1.0)
    assert ps.status().output_on
    # The output was off while the memory values were active.
    assert sim.log.index("OUT0") < sim.log.index("VSET1:24.00")
    assert sim.log.index("RCL4") < sim.log.index("OUT1", sim.log.index("RCL4"))


def test_close_switches_output_off(sim: SimulatedTransport) -> None:
    with PowerSupply(sim) as ps:
        ps.output(True)
    assert not sim.state.output


def test_no_reply_raises() -> None:
    class Silent(SimulatedTransport):
        def query(self, cmd: str, size: int | None = None) -> bytes:
            return b""

    with pytest.raises(DeviceError):
        PowerSupply(Silent()).identify()


def test_store_memory_retries_ignored_save() -> None:
    class DropFirstSave(SimulatedTransport):
        dropped = False

        def write(self, cmd: str) -> None:
            if cmd.startswith("SAV") and not self.dropped:
                self.dropped = True
                return
            super().write(cmd)

    sim = DropFirstSave()
    ps = PowerSupply(sim)
    ps.store_memory(5, 7.77, 0.234)
    assert sim.state.memory[5] == (7.77, 0.234)


def test_store_memory_failure_raises_and_leaves_output_off() -> None:
    class NeverSaves(SimulatedTransport):
        def write(self, cmd: str) -> None:
            if not cmd.startswith("SAV"):
                super().write(cmd)

    sim = NeverSaves()
    ps = PowerSupply(sim)
    ps.set_voltage(5)
    ps.set_current(1)
    ps.output(True)
    with pytest.raises(DeviceError):
        ps.store_memory(5, 7.77, 0.234)
    assert not sim.state.output
    assert (ps.voltage_setpoint(), ps.current_setpoint()) == (5.0, 1.0)


def test_store_memory_detects_recall_that_does_nothing() -> None:
    class IgnoresRecall(SimulatedTransport):
        def write(self, cmd: str) -> None:
            if not cmd.startswith(("SAV", "RCL")):
                super().write(cmd)

    with pytest.raises(DeviceError):
        PowerSupply(IgnoresRecall()).store_memory(5, 7.77, 0.234)


def test_sim_reproduces_sav_quirk(sim: SimulatedTransport) -> None:
    # Verified on hardware: SAV<n> writes the active (last recalled) memory, not n.
    sim.write("RCL2")
    sim.write("VSET1:12.00")
    sim.write("SAV4")
    assert sim.state.memory[2] == (12.0, 0.0)
    assert sim.state.memory[4] == (0.0, 0.0)


def test_store_memory_targets_requested_slot_only(sim: SimulatedTransport, ps: PowerSupply) -> None:
    before = dict(sim.state.memory)
    assert sim.state.active_memory == 1
    ps.store_memory(3, 9.0, 0.5)
    assert sim.state.memory[3] == (9.0, 0.5)
    assert {k: v for k, v in sim.state.memory.items() if k != 3} == {
        k: v for k, v in before.items() if k != 3
    }


def test_save_stores_current_setpoints_in_slot(sim: SimulatedTransport, ps: PowerSupply) -> None:
    ps.set_voltage(6)
    ps.set_current(0.6)
    ps.save(5)
    assert sim.state.memory[5] == (6.0, 0.6)
    assert sim.state.memory[1] == (0.0, 0.0)
    assert (ps.voltage_setpoint(), ps.current_setpoint()) == (6.0, 0.6)


def test_close_is_idempotent(sim: SimulatedTransport) -> None:
    ps = PowerSupply(sim)
    ps.close()
    ps.close()


def test_ovp_off_reported_despite_stuck_status_bit(
    sim: SimulatedTransport, ps: PowerSupply
) -> None:
    ps.ovp(True)
    ps.ocp(True)
    ps.ovp(False)
    assert sim.query("STATUS?")[0] & 0x80  # the firmware still reports OVP on
    st = ps.status()
    assert not st.ovp_on
    assert st.ocp_on


def test_ovp_status_trusted_before_any_ovp_command(
    sim: SimulatedTransport, ps: PowerSupply
) -> None:
    sim.state.ovp = True  # e.g. enabled before this session
    assert ps.status().ovp_on


def test_stuck_ovp_bit_from_earlier_session_is_resolved() -> None:
    sim = SimulatedTransport()
    sim.write("OVP1")
    sim.write("OCP1")
    sim.write("OVP0")  # earlier session: OVP really off, but the status bit is stuck
    ps = PowerSupply(sim)  # new session
    st = ps.status()
    assert not st.ovp_on
    assert st.ocp_on and sim.state.ocp  # OCP restored
    assert sim.log[-4:] == ["STATUS?", "OCP0", "STATUS?", "OCP1"]
    n = len(sim.log)
    ps.status()
    assert len(sim.log) == n + 1  # resolved once per session


def test_both_really_on_stays_on() -> None:
    sim = SimulatedTransport()
    sim.write("OVP1")
    sim.write("OCP1")
    st = PowerSupply(sim).status()
    assert st.ovp_on and st.ocp_on
    assert sim.state.ovp and sim.state.ocp
