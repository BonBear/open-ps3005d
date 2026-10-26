"""Main window: connection, setpoints, output/protection, memories and live graphs."""

from __future__ import annotations

import csv
import math
import time
from pathlib import Path
from typing import IO

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QFont, QPalette, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ps3005d.gui import i18n
from ps3005d.gui.i18n import tr
from ps3005d.gui.worker import FAILED, PENDING, DeviceWorker, Sample
from ps3005d.protocol import I_MAX, MEMORY_SLOTS, V_MAX
from ps3005d.sim import SimState
from ps3005d.transport import list_serial_ports

SIM_PORT = "Simulator"  # combo-box item data; the displayed text is translated
# (label, seconds); 0 = all data. Labels other than "All" are language-neutral.
WINDOWS_S = (("30 s", 30.0), ("1 min", 60.0), ("5 min", 300.0), ("15 min", 900.0), ("All", 0.0))
# Series colors (colorblind-safe, distinct in light and dark).
COLORS = {"volts": "#2a7fd4", "amps": "#e0731f", "watts": "#3a9a5b"}
# Smallest Y span per plot, so a flat line at 0 does not autoscale to noise.
Y_MIN_SPAN = {"volts": 1.0, "amps": 0.01, "watts": 0.01}
# Setpoint edits are sent after this pause, so holding an arrow sends one value.
SEND_DELAY_MS = 150
# After a user edit or click, device read-backs do not overwrite that control for this long.
HOLD_S = 1.5
SETTINGS_LANGUAGE = "language"
SETTINGS_CONFIRM_STORE = "confirm_store"


class SetpointSpin(QDoubleSpinBox):
    """Spin box whose value is sent to the supply immediately.

    Typed values are sent on Enter / focus-out (no keyboard tracking). The mouse wheel
    only works once the box has focus, so scrolling the window cannot change the output.
    """

    def __init__(self, maximum: float, decimals: int, suffix: str) -> None:
        super().__init__()
        self.setRange(0.0, maximum)
        self.setDecimals(decimals)
        self.setSuffix(f" {suffix}")
        self.setKeyboardTracking(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

    def is_typing(self) -> bool:
        return self.hasFocus() and self.cleanText() != self.textFromValue(self.value())

    def set_quietly(self, value: float) -> None:
        self.blockSignals(True)
        self.setValue(value)
        self.blockSignals(False)


def _fmt_va(volts: float, amps: float) -> str:
    return f"{volts:.2f} V / {amps:.3f} A"


class MainWindow(QMainWindow):
    # Requests to the worker thread.
    req_connect = Signal(str, bool)
    req_disconnect = Signal(bool)
    req_shutdown = Signal(bool)  # blocking: returns once the port is closed
    req_voltage = Signal(float)
    req_current = Signal(float)
    req_output = Signal(bool)
    req_ocp = Signal(bool)
    req_ovp = Signal(bool)
    req_recall = Signal(int)
    req_store = Signal(int, float, float)
    req_read_memories = Signal()
    req_interval = Signal(int)

    def __init__(
        self,
        port: str | None = None,
        sim_state: SimState | None = None,
        language: str | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("PS3005D")
        self._settings = QSettings("ps3005d", "ps3005d")
        saved = self._settings.value(SETTINGS_LANGUAGE)
        lang = language or (saved if saved in i18n.LANGUAGES else i18n.system_language())
        i18n.set_language(str(lang))

        self._connected = False
        self._identity = ""
        self._output_on = False
        self._t: list[float] = []
        self._v: list[float] = []
        self._i: list[float] = []
        self._paused = False
        self._log: IO[str] | None = None
        self._log_name = ""
        self._mem_buttons: list[tuple[QPushButton, QPushButton]] = []
        self._mem: dict[int, tuple[float, float]] = {}
        # slot -> (note, i.e. untranslated English key) for values not yet on the device
        self._mem_note: dict[int, str] = {}
        self._setpoints: tuple[float, float] | None = None
        # control name -> monotonic time until which device read-backs are ignored
        self._hold: dict[str, float] = {}
        # Highest measured values since connect or the last reset.
        self._max = {"volts": 0.0, "amps": 0.0, "watts": 0.0}

        self._thread = QThread(self)
        self.worker = DeviceWorker(sim_state)
        self.worker.moveToThread(self._thread)
        self._wire_worker()
        self._thread.start()

        self._build_ui()
        self._build_menu()
        self.retranslate()
        self._refresh_ports(prefer=port)

        self._redraw = QTimer(self)
        self._redraw.timeout.connect(self._update_plots)
        self._redraw.start(200)

    # -- setup ------------------------------------------------------------

    def _wire_worker(self) -> None:
        w = self.worker
        self.req_connect.connect(w.connect_device)
        self.req_disconnect.connect(w.disconnect_device)
        self.req_shutdown.connect(w.disconnect_device, Qt.ConnectionType.BlockingQueuedConnection)
        self.req_voltage.connect(w.set_voltage)
        self.req_current.connect(w.set_current)
        self.req_output.connect(w.set_output)
        self.req_ocp.connect(w.set_ocp)
        self.req_ovp.connect(w.set_ovp)
        self.req_recall.connect(w.recall)
        self.req_store.connect(w.store)
        self.req_read_memories.connect(w.read_memories)
        self.req_interval.connect(w.set_interval)
        w.connected.connect(self._on_connected)
        w.disconnected.connect(self._on_disconnected)
        w.sample.connect(self._on_sample)
        w.setpoints.connect(self._on_setpoints)
        w.memories.connect(self._on_memories)
        w.memory_slot.connect(self._on_memory_slot)
        w.error.connect(self._on_error)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.addLayout(self._build_connection_bar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self._build_readouts())
        lv.addWidget(self._build_controls())
        lv.addWidget(self._build_memories())
        lv.addStretch(1)
        splitter.addWidget(left)
        splitter.addWidget(self._build_plots())
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self._set_enabled(False)
        self.resize(1200, 720)

    def _build_menu(self) -> None:
        self.settings_menu = self.menuBar().addMenu("")
        self.confirm_store_action = QAction(self, checkable=True)
        self.confirm_store_action.setChecked(self._confirm_store())
        self.confirm_store_action.toggled.connect(
            lambda on: self._settings.setValue(SETTINGS_CONFIRM_STORE, on)
        )
        self.settings_menu.addAction(self.confirm_store_action)
        self.language_menu = self.menuBar().addMenu("")
        group = QActionGroup(self)
        for code, name in i18n.LANGUAGES.items():
            action = QAction(name, self, checkable=True)
            action.setChecked(code == i18n.current())
            action.triggered.connect(lambda _=False, c=code: self.set_language(c))
            group.addAction(action)
            self.language_menu.addAction(action)

    def _build_connection_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.port_label = QLabel()
        bar.addWidget(self.port_label)
        self.port_box = QComboBox()
        self.port_box.setMinimumWidth(260)
        bar.addWidget(self.port_box)
        self.refresh_btn = QPushButton()
        self.refresh_btn.clicked.connect(lambda: self._refresh_ports())
        bar.addWidget(self.refresh_btn)
        self.connect_btn = QPushButton()
        self.connect_btn.clicked.connect(self._toggle_connection)
        bar.addWidget(self.connect_btn)
        bar.addSpacing(20)
        self.poll_label = QLabel()
        bar.addWidget(self.poll_label)
        self.interval = QSpinBox()
        self.interval.setRange(100, 5000)
        self.interval.setSingleStep(50)
        self.interval.setValue(250)
        self.interval.setSuffix(" ms")
        self.interval.valueChanged.connect(self.req_interval.emit)
        bar.addWidget(self.interval)
        self.off_on_exit = QCheckBox()
        self.off_on_exit.setChecked(True)
        bar.addWidget(self.off_on_exit)
        bar.addStretch(1)
        self.identity = QLabel("")
        bar.addWidget(self.identity)
        return bar

    def _build_readouts(self) -> QGroupBox:
        self.output_group = QGroupBox()
        grid = QGridLayout(self.output_group)
        big = QFont()
        big.setPointSize(26)
        big.setBold(True)
        big.setStyleHint(QFont.StyleHint.Monospace)
        self.v_label = QLabel("--.-- V")
        self.i_label = QLabel("-.--- A")
        self.p_label = QLabel("--.--- W")
        for col, (lbl, key) in enumerate(
            ((self.v_label, "volts"), (self.i_label, "amps"), (self.p_label, "watts"))
        ):
            lbl.setFont(big)
            lbl.setStyleSheet(f"color: {COLORS[key]}")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(lbl, 0, col)
        self.mode_label = QLabel()
        self.mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_label.setMinimumWidth(60)
        grid.addWidget(self.mode_label, 1, 0)
        self.set_label = QLabel()
        grid.addWidget(self.set_label, 1, 1, 1, 2)
        self.max_title = QLabel()
        self.max_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.max_title, 2, 0)
        self.max_labels: dict[str, QLabel] = {}
        for key in ("volts", "amps", "watts"):
            lbl = QLabel()
            lbl.setStyleSheet(f"color: {COLORS[key]}; font-weight: bold")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.max_labels[key] = lbl
        max_row = QHBoxLayout()
        for key in ("volts", "amps", "watts"):
            max_row.addWidget(self.max_labels[key], 1)
        self.max_reset_btn = QPushButton()
        self.max_reset_btn.clicked.connect(self.reset_max)
        max_row.addWidget(self.max_reset_btn)
        grid.addLayout(max_row, 2, 1, 1, 2)
        self._render_max()
        return self.output_group

    def _build_controls(self) -> QGroupBox:
        self.control_group = QGroupBox()
        grid = QGridLayout(self.control_group)
        self.v_spin = SetpointSpin(V_MAX, 2, "V")
        self.i_spin = SetpointSpin(I_MAX, 3, "A")
        self.v_spin.setSingleStep(0.1)
        self.i_spin.setSingleStep(0.01)
        self.voltage_label = QLabel()
        self.current_label = QLabel()
        grid.addWidget(self.voltage_label, 0, 0)
        grid.addWidget(self.v_spin, 0, 1)
        grid.addWidget(self.current_label, 1, 0)
        grid.addWidget(self.i_spin, 1, 1)
        self.applied_hint = QLabel()
        self.applied_hint.setEnabled(False)
        grid.addWidget(self.applied_hint, 0, 2, 2, 1)
        self._send_timers: dict[str, QTimer] = {}
        for name, spin, signal in (
            ("volts", self.v_spin, self.req_voltage),
            ("amps", self.i_spin, self.req_current),
        ):
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(SEND_DELAY_MS)
            timer.timeout.connect(lambda sp=spin, sig=signal: sig.emit(sp.value()))
            spin.valueChanged.connect(lambda _v, n=name, t=timer: self._setpoint_edited(n, t))
            self._send_timers[name] = timer

        self.output_btn = QPushButton()
        self.output_btn.setCheckable(True)
        self.output_btn.setMinimumHeight(44)
        self.output_btn.clicked.connect(self._output_clicked)
        grid.addWidget(self.output_btn, 2, 0, 1, 3)

        self.ocp_box = QCheckBox()
        self.ovp_box = QCheckBox()
        # Not clicked.connect(signal.emit): PySide then emits without the bool argument.
        self.ocp_box.clicked.connect(lambda: self._protection_clicked("ocp"))
        self.ovp_box.clicked.connect(lambda: self._protection_clicked("ovp"))
        grid.addWidget(self.ocp_box, 3, 0, 1, 3)
        grid.addWidget(self.ovp_box, 4, 0, 1, 3)
        self._style_output(False)
        return self.control_group

    def _build_memories(self) -> QGroupBox:
        self.memory_group = QGroupBox()
        grid = QGridLayout(self.memory_group)
        self.mem_labels: dict[int, QLabel] = {}
        for row, slot in enumerate(MEMORY_SLOTS):
            grid.addWidget(QLabel(f"M{slot}"), row, 0)
            lbl = QLabel("?")
            self.mem_labels[slot] = lbl
            grid.addWidget(lbl, row, 1)
            rcl = QPushButton()
            rcl.clicked.connect(lambda _=False, s=slot: self._recall_clicked(s))
            grid.addWidget(rcl, row, 2)
            sto = QPushButton()
            sto.clicked.connect(lambda _=False, s=slot: self._store_clicked(s))
            grid.addWidget(sto, row, 3)
            self._mem_buttons.append((rcl, sto))
        self.read_mem_btn = QPushButton()
        self.read_mem_btn.clicked.connect(self.req_read_memories.emit)
        grid.addWidget(self.read_mem_btn, len(MEMORY_SLOTS), 0, 1, 4)
        return self.memory_group

    def _build_plots(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.window_label = QLabel()
        bar.addWidget(self.window_label)
        self.window_box = QComboBox()
        for label, seconds in WINDOWS_S:
            self.window_box.addItem(label, seconds)
        self.window_box.setCurrentIndex(1)
        bar.addWidget(self.window_box)
        self.pause_btn = QPushButton()
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._pause_toggled)
        bar.addWidget(self.pause_btn)
        self.clear_btn = QPushButton()
        self.clear_btn.clicked.connect(self.clear_data)
        bar.addWidget(self.clear_btn)
        self.export_btn = QPushButton()
        self.export_btn.clicked.connect(self._export_csv)
        bar.addWidget(self.export_btn)
        self.log_btn = QPushButton()
        self.log_btn.setCheckable(True)
        self.log_btn.toggled.connect(self._log_toggled)
        bar.addWidget(self.log_btn)
        bar.addStretch(1)
        v.addLayout(bar)

        # Follow the system light/dark palette instead of pyqtgraph's black default.
        pal = self.palette()
        pg.setConfigOptions(
            antialias=True,
            background=pal.color(QPalette.ColorRole.Base),
            foreground=pal.color(QPalette.ColorRole.Text),
        )
        self.plot_area = pg.GraphicsLayoutWidget()
        self.curves: dict[str, pg.PlotDataItem] = {}
        self.plots: dict[str, pg.PlotItem] = {}
        prev = None
        for row, key in enumerate(("volts", "amps", "watts")):
            p = self.plot_area.addPlot(row=row, col=0)
            p.showGrid(x=True, y=True, alpha=0.25)
            p.setMouseEnabled(x=False, y=False)
            p.hideButtons()
            self.plots[key] = p
            if prev is not None:
                p.setXLink(prev)
            self.curves[key] = p.plot(pen=pg.mkPen(COLORS[key], width=2))
            prev = p
        v.addWidget(self.plot_area, 1)
        return w

    # -- language ---------------------------------------------------------

    def set_language(self, code: str) -> None:
        i18n.set_language(code)
        self._settings.setValue(SETTINGS_LANGUAGE, code)
        self.retranslate()

    def retranslate(self) -> None:
        """Set every text from the current language and state (also after a switch)."""
        self.language_menu.setTitle(tr("&Language"))
        self.settings_menu.setTitle(tr("&Settings"))
        self.confirm_store_action.setText(tr("Confirm before storing a memory"))
        self.max_title.setText(tr("Max"))
        self.max_reset_btn.setText(tr("Reset"))
        self.max_reset_btn.setToolTip(tr("Reset the maximum values"))
        self.port_label.setText(tr("Port:"))
        self.refresh_btn.setText(tr("Refresh"))
        self.poll_label.setText(tr("Poll:"))
        self.off_on_exit.setText(tr("Output off on exit"))
        sim_idx = self.port_box.findData(SIM_PORT)
        if sim_idx >= 0:
            self.port_box.setItemText(sim_idx, tr("Simulator"))
        self.output_group.setTitle(tr("Output"))
        self.control_group.setTitle(tr("Control"))
        self.voltage_label.setText(tr("Voltage"))
        self.current_label.setText(tr("Current limit"))
        self.applied_hint.setText(tr("Applied immediately"))
        self.ocp_box.setText(tr("OCP (cut output at current limit)"))
        self.ovp_box.setText(tr("OVP (cut output above voltage)"))
        self.memory_group.setTitle(tr("Memories"))
        for rcl, sto in self._mem_buttons:
            rcl.setText(tr("Recall"))
            rcl.setToolTip(tr("Load into the setpoints (the output stays as it is)"))
            sto.setText(tr("Store"))
            sto.setToolTip(tr("Store the Voltage / Current limit fields above into this memory"))
        self.read_mem_btn.setText(tr("Read memories"))
        self.read_mem_btn.setToolTip(tr("Reads M1-M5 by recalling each; only with output off"))
        self.window_label.setText(tr("Window:"))
        self.window_box.setItemText(len(WINDOWS_S) - 1, tr("All"))
        self.clear_btn.setText(tr("Clear"))
        self.export_btn.setText(tr("Export CSV…"))
        for key, name, unit in (
            ("volts", "Voltage", "V"),
            ("amps", "Current", "A"),
            ("watts", "Power", "W"),
        ):
            self.plots[key].setLabel("left", tr(name), units=unit)
        self.plots["watts"].setLabel("bottom", tr("Time"), units="s")
        # State-dependent texts.
        self.connect_btn.setText(tr("Disconnect") if self._connected else tr("Connect"))
        self._pause_toggled(self._paused)
        self._update_log_button()
        self._style_output(self._output_on)
        if not self._output_on:
            self.mode_label.setText(tr("OFF"))
        self._update_set_label()
        for slot in MEMORY_SLOTS:
            self._render_mem(slot)
        self.statusBar().showMessage(
            tr("Connected: {identity}", identity=self._identity)
            if self._connected
            else tr("Not connected")
        )

    # -- connection -------------------------------------------------------

    def _refresh_ports(self, prefer: str | None = None) -> None:
        current = prefer or self.port_box.currentData()
        self.port_box.clear()
        for pi in list_serial_ports():
            if pi.device.startswith("/dev/ttyS") and not pi.likely_ps3005d:
                continue  # legacy UARTs; clutter on Linux
            label = f"{pi.device} — {pi.description}"
            if pi.likely_ps3005d:
                label += " (PS3005D)"
            self.port_box.addItem(label, pi.device)
        if prefer and self.port_box.findData(prefer) < 0 and prefer != SIM_PORT:
            self.port_box.addItem(prefer, prefer)
        self.port_box.addItem(tr("Simulator"), SIM_PORT)
        idx = self.port_box.findData(current)
        self.port_box.setCurrentIndex(max(idx, 0))

    def _toggle_connection(self) -> None:
        if self._connected:
            self.req_disconnect.emit(False)
        else:
            port = self.port_box.currentData()
            self.statusBar().showMessage(tr("Connecting to {port}…", port=port))
            self.req_connect.emit(port, port == SIM_PORT)

    def _set_enabled(self, on: bool) -> None:
        for w in (
            self.v_spin,
            self.i_spin,
            self.output_btn,
            self.ocp_box,
            self.ovp_box,
            self.read_mem_btn,
            *(b for pair in self._mem_buttons for b in pair),
        ):
            w.setEnabled(on)
        self.port_box.setEnabled(not on)

    def _on_connected(self, identity: str) -> None:
        self._connected = True
        self._identity = identity
        self.connect_btn.setText(tr("Disconnect"))
        self.identity.setText(identity)
        self.statusBar().showMessage(tr("Connected: {identity}", identity=identity))
        self._set_enabled(True)
        self.clear_data()
        self.reset_max()

    def _on_disconnected(self) -> None:
        self._connected = False
        self._identity = ""
        self.connect_btn.setText(tr("Connect"))
        self.identity.setText("")
        self.statusBar().showMessage(tr("Disconnected"))
        self._set_enabled(False)
        self._style_output(False)
        self.mode_label.setText(tr("OFF"))

    def _on_error(self, message: str) -> None:
        self.statusBar().showMessage(tr("Error: {message}", message=message), 10000)

    # -- device state -----------------------------------------------------

    def _on_sample(self, s: Sample) -> None:
        self.v_label.setText(f"{s.volts:6.2f} V")
        self.i_label.setText(f"{s.amps:6.3f} A")
        self.p_label.setText(f"{s.watts:7.3f} W")
        for key, value in (("volts", s.volts), ("amps", s.amps), ("watts", s.watts)):
            self._max[key] = max(self._max[key], value)
        self._render_max()
        self.mode_label.setText(s.mode.value if s.mode else tr("OFF"))
        self._style_output(s.output_on)
        if not self._held("ocp"):
            self.ocp_box.setChecked(s.ocp_on)
        if not self._held("ovp"):
            self.ovp_box.setChecked(s.ovp_on)
        self.read_mem_btn.setEnabled(not s.output_on)
        if not self._paused:
            self._t.append(s.t)
            self._v.append(s.volts)
            self._i.append(s.amps)
        if self._log is not None:
            self._log.write(
                f"{s.t:.3f},{s.volts:.2f},{s.amps:.3f},{s.watts:.4f},{int(s.output_on)}\n"
            )
            self._log.flush()

    def reset_max(self) -> None:
        self._max = dict.fromkeys(self._max, 0.0)
        self._render_max()

    def _render_max(self) -> None:
        m = self._max
        self.max_labels["volts"].setText(f"{m['volts']:.2f} V")
        self.max_labels["amps"].setText(f"{m['amps']:.3f} A")
        self.max_labels["watts"].setText(f"{m['watts']:.3f} W")

    def _held(self, name: str) -> bool:
        return time.monotonic() < self._hold.get(name, 0.0)

    def _setpoint_edited(self, name: str, timer: QTimer) -> None:
        self._hold[name] = time.monotonic() + HOLD_S
        timer.start()

    def _protection_clicked(self, name: str) -> None:
        box = self.ocp_box if name == "ocp" else self.ovp_box
        self._hold[name] = time.monotonic() + HOLD_S
        (self.req_ocp if name == "ocp" else self.req_ovp).emit(box.isChecked())

    def _on_setpoints(self, volts: float, amps: float) -> None:
        self._setpoints = (volts, amps)
        self._update_set_label()
        for name, spin, value in (("volts", self.v_spin, volts), ("amps", self.i_spin, amps)):
            if not (self._held(name) or spin.is_typing() or self._send_timers[name].isActive()):
                spin.set_quietly(value)

    def _update_set_label(self) -> None:
        if self._setpoints is None:
            self.set_label.setText(tr("Set: {volts} / {amps}", volts="--.-- V", amps="-.--- A"))
        else:
            v, i = self._setpoints
            self.set_label.setText(
                tr("Set: {volts} / {amps}", volts=f"{v:.2f} V", amps=f"{i:.3f} A")
            )

    def _on_memories(self, mem: dict[int, tuple[float, float]]) -> None:
        for slot, (v, i) in mem.items():
            self._on_memory_slot(slot, v, i, "saved")

    def _on_memory_slot(self, slot: int, volts: float, amps: float, state: str) -> None:
        if math.isnan(volts):
            self._mem.pop(slot, None)
        else:
            self._mem[slot] = (volts, amps)
        if state == PENDING:
            self._mem_note[slot] = "not saved yet – saved when output is turned off"
            self.statusBar().showMessage(
                tr(
                    "M{slot} is saved when you turn the output off "
                    "(the supply cannot store a memory while the output is on)",
                    slot=slot,
                ),
                10000,
            )
        elif state == FAILED:
            self._mem_note[slot] = "saving failed – previous value shown"
        else:
            self._mem_note.pop(slot, None)
        self._render_mem(slot)

    def _render_mem(self, slot: int) -> None:
        """Value, plus a second line when it is not (yet) what the device holds."""
        lbl = self.mem_labels[slot]
        value = _fmt_va(*self._mem[slot]) if slot in self._mem else "?"
        note = self._mem_note.get(slot)
        if note:
            lbl.setText(f"<i>{value}</i><br><small><i>{tr(note)}</i></small>")
        else:
            lbl.setText(value)

    def _style_output(self, on: bool) -> None:
        self._output_on = on
        self.output_btn.setChecked(on)
        self.output_btn.setText(tr("Output ON") if on else tr("Output OFF"))
        color = "#c62828" if on else "#555555"
        self.output_btn.setStyleSheet(
            f"QPushButton {{ background: {color}; color: white; font-weight: bold; }}"
        )
        self.mode_label.setStyleSheet(
            "font-weight: bold; color: " + ("#c62828" if on else "palette(text)")
        )

    def _output_clicked(self) -> None:
        # Keep the button showing the device's state until the worker confirms.
        want = not self._output_on
        self.output_btn.setChecked(self._output_on)
        self.req_output.emit(want)

    def _recall_clicked(self, slot: int) -> None:
        if slot in self._mem:
            # Show the recalled values right away; the worker sets them on the device.
            v, i = self._mem[slot]
            self.v_spin.set_quietly(v)
            self.i_spin.set_quietly(i)
        for name in ("volts", "amps"):
            self._hold.pop(name, None)
            self._send_timers[name].stop()
        self.req_recall.emit(slot)

    def _store_clicked(self, slot: int) -> None:
        v, i = self.v_spin.value(), self.i_spin.value()
        question = tr("Overwrite M{slot} with {values}?", slot=slot, values=_fmt_va(v, i))
        if self._output_on:
            question += "\n\n" + tr(
                "The supply can only store with the output off, "
                "so this is written when you switch the output off."
            )
        if self._confirm_store() and not self._ask_store(question):
            return
        self._mem[slot] = (v, i)
        self._mem_note[slot] = "saving…"
        self._render_mem(slot)
        self.req_store.emit(slot, v, i)

    def _confirm_store(self) -> bool:
        return str(self._settings.value(SETTINGS_CONFIRM_STORE, "true")).lower() == "true"

    def _ask_store(self, question: str) -> bool:
        box = QMessageBox(
            QMessageBox.Icon.Question,
            tr("Store memory"),
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self,
        )
        dont_ask = QCheckBox(tr("Don't show again"))
        box.setCheckBox(dont_ask)
        yes = box.exec() == QMessageBox.StandardButton.Yes
        if yes and dont_ask.isChecked():
            self.confirm_store_action.setChecked(False)  # also saves the setting
        return yes

    # -- plotting & data --------------------------------------------------

    def clear_data(self) -> None:
        self._t.clear()
        self._v.clear()
        self._i.clear()
        self._update_plots()

    def _pause_toggled(self, paused: bool) -> None:
        self._paused = paused
        self.pause_btn.setText(tr("Resume") if paused else tr("Pause"))

    def _update_plots(self) -> None:
        t = np.asarray(self._t)
        v = np.asarray(self._v)
        i = np.asarray(self._i)
        window = float(self.window_box.currentData())
        if window and len(t):
            start = int(np.searchsorted(t, t[-1] - window))
            t, v, i = t[start:], v[start:], i[start:]
        for key, data in (("volts", v), ("amps", i), ("watts", v * i)):
            self.curves[key].setData(t, data)
            top = max(float(np.max(data)) * 1.1 if len(data) else 0.0, Y_MIN_SPAN[key])
            self.plots[key].setYRange(-0.03 * top, top, padding=0)

    def _ask_csv_path(self, title: str) -> Path | None:
        path, _ = QFileDialog.getSaveFileName(self, title, "ps3005d.csv", "CSV (*.csv)")
        return Path(path) if path else None

    def _export_csv(self) -> None:
        path = self._ask_csv_path(tr("Export samples"))
        if path:
            self.export_csv(path)

    def export_csv(self, path: Path) -> None:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["t_s", "volts", "amps", "watts"])
            for t, v, i in zip(self._t, self._v, self._i, strict=True):
                w.writerow([f"{t:.3f}", f"{v:.2f}", f"{i:.3f}", f"{v * i:.4f}"])
        self.statusBar().showMessage(
            tr("Exported {count} samples to {path}", count=len(self._t), path=path), 5000
        )

    def _log_toggled(self, on: bool) -> None:
        if on:
            path = self._ask_csv_path(tr("Log samples to"))
            if not path:
                self.log_btn.setChecked(False)
                return
            self._log = path.open("w", encoding="utf-8")
            self._log.write("t_s,volts,amps,watts,output_on\n")
            self._log_name = path.name
        else:
            self._close_log()
        self._update_log_button()

    def _update_log_button(self) -> None:
        if self._log is not None:
            self.log_btn.setText(tr("Logging: {name}", name=self._log_name))
        else:
            self.log_btn.setText(tr("Log to CSV…"))

    def _close_log(self) -> None:
        if self._log is not None:
            self._log.close()
        self._log = None
        self._update_log_button()

    # -- shutdown ---------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        self._redraw.stop()
        self._close_log()
        # Runs in the worker thread; blocks until the port is closed.
        self.req_shutdown.emit(self.off_on_exit.isChecked())
        self._thread.quit()
        self._thread.wait(3000)
        super().closeEvent(event)
