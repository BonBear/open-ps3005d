"""Offscreen GUI tests against the simulator (skipped if PySide6 is not installed)."""

import os
import socket
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

import anyio
import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from ps3005d.gui.main_window import SIM_PORT, MainWindow
from ps3005d.gui.sequence_panel import SequencePanel
from ps3005d.sequence import Step
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


def _run_steps(win: MainWindow, steps: list[Step], rounds: int = 1, leave_on: bool = False) -> None:
    panel = win.sequence_panel
    panel.set_steps(steps)
    panel.rounds.setValue(rounds)
    panel.leave_on.setChecked(leave_on)
    panel.start_btn.click()


def test_sequence_runs_rounds_and_switches_off(win: MainWindow, sim: SimState) -> None:
    seen: list[tuple[float, float]] = []
    win.worker.setpoints.connect(lambda v, i: seen.append((round(v, 2), round(i, 3))))
    _run_steps(win, [Step(5, 1, 0.5), Step(2, 0.2, 0.5)], rounds=2)
    wait_until(lambda: sim.output)
    assert not win.v_spin.isEnabled()  # manual setpoints locked while running
    assert not win.sequence_panel.start_btn.isEnabled()
    wait_until(lambda: "finished" in win.sequence_panel.progress_label.text(), 5000)
    assert not sim.output
    assert win.v_spin.isEnabled()
    # Periodic read-backs repeat values; keep only the changes.
    changes = [sp for k, sp in enumerate(seen) if k == 0 or sp != seen[k - 1]]
    applied = [sp for sp in changes if sp in ((5.0, 1.0), (2.0, 0.2))]
    assert applied[:4] == [(5.0, 1.0), (2.0, 0.2), (5.0, 1.0), (2.0, 0.2)]


def test_sequence_stop_button(win: MainWindow, sim: SimState) -> None:
    _run_steps(win, [Step(5, 1, 30)])
    wait_until(lambda: sim.output)
    wait_until(lambda: "1/1" in win.sequence_panel.progress_label.text())
    win.sequence_panel.stop_btn.click()
    wait_until(lambda: not sim.output)
    wait_until(lambda: "stopped" in win.sequence_panel.progress_label.text())


def test_sequence_aborts_when_output_trips(win: MainWindow, sim: SimState) -> None:
    _run_steps(win, [Step(5, 1, 30)])
    wait_until(lambda: sim.output)
    pump(700)
    sim.output = False  # OCP/OVP trip on the device
    wait_until(lambda: "OVP/OCP" in win.sequence_panel.progress_label.text())
    assert win.sequence_panel.start_btn.isEnabled()


def test_sequence_leave_output_on(win: MainWindow, sim: SimState) -> None:
    _run_steps(win, [Step(3.3, 0.5, 0.5)], leave_on=True)
    wait_until(lambda: "finished" in win.sequence_panel.progress_label.text(), 3000)
    assert sim.output and sim.vset == 3.3


def test_sequence_table_is_remembered(win: MainWindow, app: QApplication) -> None:
    win.sequence_panel.set_steps([Step(1.5, 0.25, 7)])
    other = SequencePanel(win._settings)
    assert other.steps() == [Step(1.5, 0.25, 7)]


@pytest.mark.parametrize(("choice", "runs"), [("off", True), ("cancel", False)])
def test_sequence_with_ovp_on_asks(
    win: MainWindow, sim: SimState, monkeypatch: pytest.MonkeyPatch, choice: str, runs: bool
) -> None:
    win.ovp_box.click()
    wait_until(lambda: sim.ovp)
    pump(1600)  # past the click hold
    monkeypatch.setattr(win, "_ask_ovp_for_sequence", lambda: choice)
    _run_steps(win, [Step(3, 0.5, 0.5)])
    if runs:
        wait_until(lambda: sim.output)
        assert not sim.ovp  # off while the sequence runs
        wait_until(lambda: "finished" in win.sequence_panel.progress_label.text(), 3000)
        wait_until(lambda: sim.ovp)  # restored afterwards
    else:
        pump(500)
        assert not sim.output and sim.ovp


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _ai_call(win: MainWindow, tool: str, args: dict[str, object]) -> str:
    """Call a tool over HTTP from a helper thread while the GUI event loop keeps running."""
    panel = win.ai_panel
    result: list[str] = []

    async def go() -> None:
        headers = {"Authorization": f"Bearer {panel._key}"}
        async with (
            httpx2.AsyncClient(headers=headers) as http,
            Client(streamable_http_client(panel.endpoint, http_client=http)) as client,
        ):
            r = await client.call_tool(tool, args)
            text = "".join(getattr(c, "text", "") for c in r.content)
            result.append(("ERROR: " if r.is_error else "") + text)

    t = threading.Thread(target=lambda: anyio.run(go))
    t.start()
    wait_until(lambda: not t.is_alive(), 15000)
    return result[0]


@pytest.fixture
def ai(win: MainWindow) -> Iterator[MainWindow]:
    win.ai_panel.port.setValue(_free_port())
    win.ai_panel.enable.setChecked(True)
    assert win.ai_panel.serving
    yield win
    win.ai_panel.enable.setChecked(False)
    assert not win.ai_panel.serving


def test_ai_controls_supply_through_gui(ai: MainWindow, sim: SimState) -> None:
    seen: list[str] = []
    ai.ai_panel.activity.connect(seen.append)
    out = _ai_call(ai, "set_voltage_current", {"volts": 6, "amps": 0.5})
    assert not out.startswith("ERROR"), out
    assert sim.vset == 6.0
    wait_until(lambda: ai.v_spin.value() == 6.0, 5000)  # GUI follows the AI's change
    assert "set_voltage_current" in seen
    assert ai.ai_indicator.text() == "AI: on"
    out = _ai_call(ai, "set_voltage_current", {"volts": 20})
    assert "allowed range" in out  # the GUI's AI limit (12 V default)


def test_ai_blocked_during_gui_sequence(ai: MainWindow, sim: SimState) -> None:
    _run_steps(ai, [Step(3, 0.5, 30)])
    wait_until(lambda: sim.output)
    out = _ai_call(ai, "set_output", {"on": False})
    assert "running a sequence" in out
    assert sim.output
    assert not _ai_call(ai, "get_status", {}).startswith("ERROR")  # reading still works
    ai.sequence_panel.stop_btn.click()
    wait_until(lambda: not sim.output)


def test_ai_memory_store_updates_gui(ai: MainWindow, sim: SimState) -> None:
    ai.ai_panel.allow_memory.setChecked(True)  # restarts the server with store_memory
    out = _ai_call(ai, "store_memory", {"slot": 3, "volts": 4.2, "amps": 0.42})
    assert not out.startswith("ERROR"), out
    assert sim.memory[3] == (4.2, 0.42)
    wait_until(lambda: ai.mem_labels[3].text() == "4.20 V / 0.420 A", 5000)


def test_ai_release_keeps_gui_connected(ai: MainWindow, sim: SimState) -> None:
    ai.req_output.emit(True)
    wait_until(lambda: sim.output)
    _ai_call(ai, "release_port", {})
    assert not sim.output
    pump(500)
    assert ai._connected and ai.connect_btn.text() == "Disconnect"


def test_new_key_invalidates_old(ai: MainWindow) -> None:
    old = ai.ai_panel._key
    ai.ai_panel.new_key_btn.click()
    assert ai.ai_panel._key != old and ai.ai_panel.serving
    r = httpx2.post(ai.ai_panel.endpoint, json={}, headers={"Authorization": f"Bearer {old}"})
    assert r.status_code == 401
    assert ai.ai_panel._key in ai.ai_panel.claude_command()


def test_ai_port_change_restarts_and_address_matches(ai: MainWindow) -> None:
    new = _free_port()
    ai.ai_panel.port.setValue(new)
    assert ai.ai_panel.serving
    assert ai.ai_panel.endpoint.endswith(f":{new}/mcp")
    assert f":{new}/mcp" in ai.ai_panel.claude_command()
    assert not _ai_call(ai, "get_status", {}).startswith("ERROR")


def test_ai_server_starts_from_saved_setting(app: QApplication, sim: SimState) -> None:
    first = MainWindow(port=SIM_PORT, sim_state=sim, language="en")
    first.ai_panel.port.setValue(_free_port())
    first.ai_panel.enable.setChecked(True)
    port = first.ai_panel.port.value()
    first.close()  # stops the server; "enabled" and the port stay saved
    second = MainWindow(port=SIM_PORT, sim_state=sim, language="en")
    try:
        assert second.ai_panel.serving
        assert second.ai_panel.endpoint.endswith(f":{port}/mcp")
    finally:
        second.ai_panel.enable.setChecked(False)
        second.close()
