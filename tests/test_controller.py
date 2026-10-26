import pytest

from ps3005d.controller import Controller, LimitError, Limits
from ps3005d.device import PowerSupply
from ps3005d.sequence import Step
from ps3005d.sim import SimState, SimulatedTransport


@pytest.fixture
def sim() -> SimulatedTransport:
    return SimulatedTransport(SimState(load_ohms=10.0))


@pytest.fixture
def ctl(sim: SimulatedTransport) -> Controller:
    return Controller(lambda: PowerSupply(sim), Limits(max_volts=12, max_amps=1))


@pytest.fixture(autouse=True)
def no_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ps3005d.controller.SETTLE_S", 0.0)
    monkeypatch.setattr("ps3005d.device.SAVE_SETTLE_S", 0.0)


def test_limits_cannot_exceed_hardware() -> None:
    with pytest.raises(ValueError):
        Limits(max_volts=31, max_amps=1)


def test_setpoints_above_limits_rejected(ctl: Controller, sim: SimulatedTransport) -> None:
    with pytest.raises(LimitError):
        ctl.set_setpoints(12.5, None)
    with pytest.raises(LimitError):
        ctl.set_setpoints(None, 1.5)
    assert sim.state.vset == 0.0


def test_set_and_enable_output(ctl: Controller) -> None:
    st = ctl.set_setpoints(5, 0.2)
    assert not st["output_on"]
    st = ctl.set_output(True)
    assert st["output_on"]
    assert st["mode"] == "CC"
    assert st["measured"] == {"volts": 2.0, "amps": 0.2, "watts": 0.4}


def test_output_refused_when_setpoints_from_panel_exceed_limits(
    ctl: Controller, sim: SimulatedTransport
) -> None:
    sim.state.vset = 24.0  # e.g. set on the front panel or recalled from memory
    with pytest.raises(LimitError):
        ctl.set_output(True)
    assert not sim.state.output


def test_recall_warns_about_out_of_limit_memory(ctl: Controller, sim: SimulatedTransport) -> None:
    sim.state.memory[3] = (30.0, 3.0)
    st = ctl.recall_memory(3)
    assert "warning" in st
    assert not st["output_on"]


def test_store_memory_checks_limits(ctl: Controller, sim: SimulatedTransport) -> None:
    with pytest.raises(LimitError):
        ctl.store_memory(5, 20, 0.5)
    ctl.store_memory(5, 9, 0.5)
    assert sim.state.memory[5] == (9.0, 0.5)


def test_measure_stats(ctl: Controller) -> None:
    ctl.set_setpoints(5, 1)
    ctl.set_output(True)
    r = ctl.measure(3, 0)
    assert len(r["samples"]) == 3
    assert r["stats"]["volts"]["mean"] == 5.0


def test_measure_duration_limited(ctl: Controller) -> None:
    with pytest.raises(LimitError):
        ctl.measure(1000, 1.0)


def test_sweep(ctl: Controller, sim: SimulatedTransport) -> None:
    r = ctl.sweep_voltage(0, 4, 1, 0.25, 0, False)
    assert [pt["set_volts"] for pt in r["points"]] == [0, 1, 2, 3, 4]
    assert [pt["amps"] for pt in r["points"]] == [0, 0.1, 0.2, 0.25, 0.25]
    assert [pt["cc_mode"] for pt in r["points"]] == [False, False, False, True, True]
    assert not sim.state.output


def test_sweep_descending_and_limits(ctl: Controller) -> None:
    r = ctl.sweep_voltage(3, 1, 0.5, 0.5, 0, False)
    assert [pt["set_volts"] for pt in r["points"]] == [3, 2.5, 2, 1.5, 1]
    with pytest.raises(LimitError):
        ctl.sweep_voltage(0, 15, 1, 0.5, 0, False)


def test_sweep_aborts_on_trip(sim: SimulatedTransport) -> None:
    class TripAt3V(SimulatedTransport):
        def write(self, cmd: str) -> None:
            super().write(cmd)
            if cmd == "VSET1:03.00":
                self.state.output = False

    trip = TripAt3V(sim.state)
    ctl = Controller(lambda: PowerSupply(trip), Limits(12, 1))
    r = ctl.sweep_voltage(0, 5, 1, 1, 0, True)
    assert "warning" in r
    assert len(r["points"]) == 4
    assert not trip.state.output


def test_release_switches_output_off_and_reopens(ctl: Controller, sim: SimulatedTransport) -> None:
    ctl.set_setpoints(5, 0.5)
    ctl.set_output(True)
    ctl.release()
    assert not sim.state.output
    assert ctl.status()["setpoint"]["volts"] == 5.0


def test_run_sequence(ctl: Controller, sim: SimulatedTransport) -> None:
    steps = [Step(5, 1, 0.5), Step(2, 0.1, 0.5)]
    r = ctl.run_sequence(steps, 2, False, 0.2)
    assert [(row["round"], row["step"]) for row in r["steps"]] == [(1, 1), (1, 2), (2, 1), (2, 2)]
    first, second = r["steps"][0], r["steps"][1]
    assert first["measured"]["volts"]["max"] == 5.0 and not first["entered_cc"]
    assert second["measured"]["amps"]["max"] == 0.1 and second["entered_cc"]  # 10 ohm load
    assert 1.9 < r["elapsed_s"] < 3.0
    assert not sim.state.output


def test_run_sequence_checks_limits_and_duration(ctl: Controller, sim: SimulatedTransport) -> None:
    with pytest.raises(ValueError, match="step 2"):
        ctl.run_sequence([Step(5, 0.5, 1), Step(15, 0.5, 1)], 1, False, 0.5)
    with pytest.raises(LimitError):
        ctl.run_sequence([Step(5, 0.5, 200)], 2, False, 0.5)
    assert sim.log == []


def test_run_sequence_aborts_on_trip(sim: SimulatedTransport) -> None:
    class TripAt9V(SimulatedTransport):
        def write(self, cmd: str) -> None:
            super().write(cmd)
            if cmd == "VSET1:09.00":
                self.state.output = False

    t = TripAt9V(sim.state)
    ctl = Controller(lambda: PowerSupply(t), Limits(12, 1))
    r = ctl.run_sequence([Step(5, 1, 0.5), Step(9, 1, 0.5), Step(3, 1, 0.5)], 1, True, 0.2)
    assert "step 2" in r["warning"]
    assert len(r["steps"]) == 2
    assert not t.state.output
