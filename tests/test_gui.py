"""Offscreen GUI tests against the simulator (skipped if PySide6 is not installed)."""

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from ps3005d.gui.main_window import SIM_PORT, MainWindow
from ps3005d.sim import SimState


def pump(ms: int) -> None:
    """Run the event loop for ``ms`` (QTest.qWait keeps the GIL and starves the worker)."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_until(cond: Callable[[], bool], timeout_ms: int = 3000) -> None:
    waited = 0
    while not cond():
        assert waited < timeout_ms, "timed out"
        pump(20)
        waited += 20


@pytest.fixture(scope="module")
def app(tmp_path_factory: pytest.TempPathFactory) -> QApplication:
    # Keep the language setting out of the user's real config.
    QSettings.setPath(
        QSettings.Format.NativeFormat,
        QSettings.Scope.UserScope,
        str(tmp_path_factory.mktemp("settings")),
    )
    return QApplication.instance() or QApplication([])  # type: ignore[return-value]


@pytest.fixture
def sim() -> SimState:
    return SimState(load_ohms=10.0)


@pytest.fixture
def win(app: QApplication, sim: SimState) -> Iterator[MainWindow]:
    w = MainWindow(port=SIM_PORT, sim_state=sim, language="en")
    w.interval.setValue(100)
    w.show()
    w.connect_btn.click()
    wait_until(lambda: w.identity.text() != "")
    yield w
    w.close()


def test_connect_shows_identity(win: MainWindow) -> None:
    assert "SIMULATED" in win.identity.text()
    assert win.output_btn.isEnabled()


def test_setpoints_apply_immediately_output_and_plot(win: MainWindow, sim: SimState) -> None:
    # Current first, then voltage: the first edit must not be lost.
    win.i_spin.setValue(1.0)
    win.v_spin.setValue(5.0)
    wait_until(lambda: sim.vset == 5.0 and sim.iset == 1.0)
    assert not sim.output  # applying setpoints never enables the output

    win.output_btn.click()
    wait_until(lambda: "ON" in win.output_btn.text())
    assert sim.output
    wait_until(lambda: "5.00 V" in win.v_label.text() and win.mode_label.text() == "CV")
    wait_until(lambda: len(win._t) > 3)
    win._update_plots()
    _xs, ys = win.curves["amps"].getData()
    assert ys is not None and ys[-1] == pytest.approx(0.5)

    win.output_btn.click()
    wait_until(lambda: not sim.output)


@pytest.fixture
def yes(win: MainWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win, "_ask_store", lambda question: True)


def test_memories_read_on_connect(app: QApplication) -> None:
    sim = SimState(load_ohms=10.0)
    sim.memory[2] = (12.0, 0.25)
    w = MainWindow(port=SIM_PORT, sim_state=sim, language="en")
    w.connect_btn.click()
    wait_until(lambda: w.mem_labels[2].text() == "12.00 V / 0.250 A")
    w.close()


def test_ocp_ovp_checkboxes(win: MainWindow, sim: SimState) -> None:
    win.ocp_box.click()
    wait_until(lambda: sim.ocp)
    win.ovp_box.click()
    wait_until(lambda: sim.ovp)
    pump(600)  # several polls: the boxes must stay checked
    assert win.ocp_box.isChecked() and win.ovp_box.isChecked()
    win.ocp_box.click()
    wait_until(lambda: not sim.ocp)


def test_ovp_unchecks_while_ocp_on(win: MainWindow, sim: SimState) -> None:
    win.ovp_box.click()
    win.ocp_box.click()
    wait_until(lambda: sim.ovp and sim.ocp)
    win.ovp_box.click()
    wait_until(lambda: not sim.ovp)
    pump(2000)  # past the click hold: status polls must not re-check the box
    assert not win.ovp_box.isChecked()
    assert win.ocp_box.isChecked()


def test_max_values_and_reset(win: MainWindow, sim: SimState) -> None:
    win.req_voltage.emit(5.0)
    win.req_current.emit(1.0)
    win.req_output.emit(True)
    wait_until(lambda: win._max["volts"] == 5.0)
    assert win.max_labels["amps"].text() == "0.500 A"
    win.req_voltage.emit(2.0)
    wait_until(lambda: "2.00 V" in win.v_label.text())
    assert win._max["volts"] == 5.0  # the peak stays
    win.max_reset_btn.click()
    wait_until(lambda: win._max["volts"] == 2.0)


def test_store_dialog_dont_show_again(
    win: MainWindow, sim: SimState, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = []

    def fake_ask(question: str) -> bool:
        asked.append(question)
        win.confirm_store_action.setChecked(False)  # as if "Don't show again" was ticked
        return True

    monkeypatch.setattr(win, "_ask_store", fake_ask)
    win.confirm_store_action.setChecked(True)
    win._store_clicked(1)
    win._store_clicked(2)
    assert len(asked) == 1
    wait_until(lambda: sim.memory[2] == (win.v_spin.value(), win.i_spin.value()), 5000)
    win.confirm_store_action.setChecked(True)  # re-enable via the Settings menu


def test_recall_keeps_output_on(win: MainWindow, sim: SimState) -> None:
    sim.memory[3] = (3.3, 0.2)
    win.read_mem_btn.click()
    wait_until(lambda: win.mem_labels[3].text() == "3.30 V / 0.200 A")
    win.req_voltage.emit(5.0)
    win.req_current.emit(1.0)
    win.req_output.emit(True)
    wait_until(lambda: win._output_on)
    win._recall_clicked(3)
    wait_until(lambda: (sim.vset, sim.iset) == (3.3, 0.2))
    pump(300)
    assert sim.output  # a firmware RCL would have switched it off
    assert win.v_spin.value() == 3.3


def test_store_with_output_off_updates_label_and_device(
    win: MainWindow, sim: SimState, yes: None
) -> None:
    win.v_spin.setValue(3.3)
    win.i_spin.setValue(0.1)
    win._store_clicked(4)
    assert "3.30 V / 0.100 A" in win.mem_labels[4].text()  # immediately
    wait_until(lambda: sim.memory[4] == (3.3, 0.1), 5000)
    wait_until(lambda: win.mem_labels[4].text() == "3.30 V / 0.100 A")


def test_store_with_output_on_is_deferred(win: MainWindow, sim: SimState, yes: None) -> None:
    win.req_voltage.emit(5.0)
    win.req_current.emit(1.0)
    win.req_output.emit(True)
    wait_until(lambda: win._output_on)
    win.v_spin.set_quietly(7.0)
    win.i_spin.set_quietly(0.7)
    win._store_clicked(5)
    wait_until(lambda: "saved when output is turned off" in win.mem_labels[5].text())
    pump(400)
    assert sim.output  # never interrupted
    assert sim.memory[5] == (0.0, 0.0)
    win.req_output.emit(False)
    wait_until(lambda: sim.memory[5] == (7.0, 0.7), 5000)
    wait_until(lambda: win.mem_labels[5].text() == "7.00 V / 0.700 A")
    assert not sim.output


def test_readback_does_not_overwrite_recent_edit(win: MainWindow) -> None:
    win.i_spin.setValue(0.333)
    win._on_setpoints(1.0, 0.111)  # stale read-back arriving right after the edit
    assert win.i_spin.value() == 0.333


def test_export_csv(win: MainWindow, tmp_path: Path) -> None:
    wait_until(lambda: len(win._t) > 2)
    out = tmp_path / "s.csv"
    win.export_csv(out)
    lines = out.read_text().splitlines()
    assert lines[0] == "t_s,volts,amps,watts"
    assert len(lines) > 2


def test_close_switches_output_off(app: QApplication, sim: SimState) -> None:
    w = MainWindow(port=SIM_PORT, sim_state=sim, language="en")
    w.connect_btn.click()
    wait_until(lambda: w.identity.text() != "")
    w.req_output.emit(True)
    wait_until(lambda: sim.output)
    w.close()
    assert not sim.output


def test_switch_language_while_connected(win: MainWindow, sim: SimState) -> None:
    win.req_output.emit(True)
    wait_until(lambda: win._output_on)
    win.v_spin.set_quietly(7.0)
    win._mem[5] = (7.0, 0.7)
    win._on_memory_slot(5, 7.0, 0.7, "pending")

    win.set_language("sv")
    assert win.connect_btn.text() == "Koppla från"
    assert win.output_btn.text() == "Utgång PÅ"
    assert win.language_menu.title() == "&Språk"
    assert "sparas när utgången stängs av" in win.mem_labels[5].text()
    assert win.window_box.itemText(4) == "Allt"

    win.set_language("de")
    assert win.ocp_box.text().startswith("OCP (Ausgang")
    assert "beim Ausschalten" in win.mem_labels[5].text()
    assert sim.output  # switching language does not touch the device

    win.set_language("en")
    assert win.connect_btn.text() == "Disconnect"
