"""AI (MCP) tab: serve the MCP tools over local HTTP through the GUI's own connection.

The serial port has a single owner, so instead of running ``ps3005d-mcp`` next to
the GUI, the GUI hosts the same tools on ``http://127.0.0.1:<port>/mcp``. Clients
need the bearer key shown here. The operator's limits (max V / A / duration) are set
in this tab; an AI client cannot change them.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSettings, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ps3005d.controller import Controller, Limits
from ps3005d.device import PowerSupply
from ps3005d.gui.i18n import tr
from ps3005d.mcp_http import DEFAULT_PORT, HttpMcpServer, new_key, url
from ps3005d.mcp_server import build_server
from ps3005d.protocol import I_MAX, V_MAX

KEY_ENABLED = "ai/enabled"
KEY_PORT = "ai/port"
KEY_MAX_V = "ai/max_volts"
KEY_MAX_A = "ai/max_amps"
KEY_MAX_MIN = "ai/max_duration_min"
KEY_MEMORY = "ai/allow_memory_write"
KEY_SECRET = "ai/key"


def _setting(settings: QSettings, key: str, default: float) -> float:
    try:
        return float(settings.value(key, default))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _flag(settings: QSettings, key: str, default: bool) -> bool:
    return str(settings.value(key, default)).lower() == "true"


class AiPanel(QWidget):
    # Emitted from server threads; Qt queues them to the GUI thread.
    activity = Signal(str)  # tool name, "" when idle
    memory_stored = Signal(int, float, float)
    server_state = Signal(bool)  # serving or not

    def __init__(
        self,
        settings: QSettings,
        supply: Callable[[], PowerSupply],
        blocked: Callable[[], str | None],
    ) -> None:
        super().__init__()
        self._settings = settings
        self._server = HttpMcpServer()
        self._error = ""
        self._started_with: tuple[int, bool, str] | None = None  # port, memory writes, key
        key = str(settings.value(KEY_SECRET, "") or "")
        if not key:
            key = new_key()
            settings.setValue(KEY_SECRET, key)
        self._key = key
        self._ctl = Controller(supply, self._limits_from_settings(), owns_port=False)
        self._blocked = blocked

        self.enable = QCheckBox()
        self.enable.setChecked(_flag(settings, KEY_ENABLED, False))
        self.enable.toggled.connect(self._enable_toggled)

        self.limits_group = QGroupBox()
        form = QFormLayout(self.limits_group)
        self.max_v = QDoubleSpinBox()
        self.max_v.setRange(0.1, V_MAX)
        self.max_v.setDecimals(2)
        self.max_v.setSuffix(" V")
        self.max_v.setValue(self._ctl.limits.max_volts)
        self.max_a = QDoubleSpinBox()
        self.max_a.setRange(0.001, I_MAX)
        self.max_a.setDecimals(3)
        self.max_a.setSuffix(" A")
        self.max_a.setValue(self._ctl.limits.max_amps)
        self.max_min = QSpinBox()
        self.max_min.setRange(1, 24 * 60)
        self.max_min.setSuffix(" min")
        self.max_min.setValue(round(self._ctl.limits.max_duration_s / 60))
        for spin in (self.max_v, self.max_a, self.max_min):
            spin.valueChanged.connect(self._limits_changed)
        self.max_v_label, self.max_a_label, self.max_min_label = QLabel(), QLabel(), QLabel()
        form.addRow(self.max_v_label, self.max_v)
        form.addRow(self.max_a_label, self.max_a)
        form.addRow(self.max_min_label, self.max_min)
        self.allow_memory = QCheckBox()
        self.allow_memory.setChecked(_flag(settings, KEY_MEMORY, False))
        self.allow_memory.toggled.connect(self._restart_setting_changed)
        form.addRow(self.allow_memory)

        self.conn_group = QGroupBox()
        conn = QFormLayout(self.conn_group)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(_setting(settings, KEY_PORT, DEFAULT_PORT)))
        self.port.valueChanged.connect(self._restart_setting_changed)
        self.port_label = QLabel()
        conn.addRow(self.port_label, self.port)
        self.key_edit = QLineEdit(self._key)
        self.key_edit.setReadOnly(True)
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_key = QPushButton()
        self.show_key.setCheckable(True)
        self.show_key.toggled.connect(
            lambda on: self.key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.show_key)
        self.key_label = QLabel()
        conn.addRow(self.key_label, key_row)
        self.copy_key = QPushButton()
        self.copy_key.clicked.connect(lambda: self._copy(self._key))
        self.copy_cmd = QPushButton()
        self.copy_cmd.clicked.connect(lambda: self._copy(self.claude_command()))
        self.new_key_btn = QPushButton()
        self.new_key_btn.clicked.connect(self._new_key)
        buttons = QHBoxLayout()
        for b in (self.copy_key, self.copy_cmd, self.new_key_btn):
            buttons.addWidget(b)
        conn.addRow(buttons)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.activity_label = QLabel()

        layout = QVBoxLayout(self)
        layout.addWidget(self.enable)
        layout.addWidget(self.limits_group)
        layout.addWidget(self.conn_group)
        layout.addWidget(self.status_label)
        layout.addWidget(self.activity_label)
        layout.addStretch(1)

        self.activity.connect(self._show_activity)
        if self.enable.isChecked():
            self._start()

    # -- server -----------------------------------------------------------

    def _limits_from_settings(self) -> Limits:
        return Limits(
            max_volts=min(_setting(self._settings, KEY_MAX_V, 12.0), V_MAX),
            max_amps=min(_setting(self._settings, KEY_MAX_A, 1.0), I_MAX),
            max_duration_s=_setting(self._settings, KEY_MAX_MIN, 5.0) * 60,
        )

    @property
    def serving(self) -> bool:
        return self._server.running

    @property
    def endpoint(self) -> str:
        """The address actually served (the port field may differ until restarted)."""
        return url(self._server.port if self.serving else self.port.value())

    def claude_command(self) -> str:
        return (
            f"claude mcp add --transport http ps3005d {self.endpoint} "
            f'--header "Authorization: Bearer {self._key}"'
        )

    def _config(self) -> tuple[int, bool, str]:
        return self.port.value(), self.allow_memory.isChecked(), self._key

    def _start(self) -> None:
        self._error = ""
        self._started_with = self._config()
        mcp = build_server(
            self._ctl,
            allow_memory_write=self.allow_memory.isChecked(),
            on_activity=lambda name: self.activity.emit(name or ""),
            blocked=self._blocked,
            on_memory_stored=self.memory_stored.emit,
        )
        try:
            self._server.start(mcp, self.port.value(), self._key)
        except OSError as exc:
            self._error = str(exc)
        self._update_status()
        self.server_state.emit(self.serving)

    def _stop(self) -> None:
        self._server.stop()
        self._update_status()
        self.server_state.emit(False)

    def shutdown(self) -> None:
        self._server.stop(timeout_s=2.0)

    def _enable_toggled(self, on: bool) -> None:
        self._settings.setValue(KEY_ENABLED, on)
        if on:
            self._start()
        else:
            self._stop()

    def _restart_setting_changed(self) -> None:
        self._settings.setValue(KEY_PORT, self.port.value())
        self._settings.setValue(KEY_MEMORY, self.allow_memory.isChecked())
        if self.enable.isChecked() and (self._config() != self._started_with or self._error):
            self._start()

    def _limits_changed(self) -> None:
        self._settings.setValue(KEY_MAX_V, self.max_v.value())
        self._settings.setValue(KEY_MAX_A, self.max_a.value())
        self._settings.setValue(KEY_MAX_MIN, self.max_min.value())
        # Takes effect for the next tool call; no restart needed.
        self._ctl.limits = Limits(
            self.max_v.value(), self.max_a.value(), self.max_min.value() * 60.0
        )

    def _new_key(self) -> None:
        self._key = new_key()
        self._settings.setValue(KEY_SECRET, self._key)
        self.key_edit.setText(self._key)
        if self.enable.isChecked():
            self._start()  # old key stops working at once

    def _copy(self, text: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    # -- display ----------------------------------------------------------

    def _update_status(self) -> None:
        if self._error:
            self.status_label.setText(tr("Error: {message}", message=self._error))
        elif self.serving:
            self.status_label.setText(tr("Listening on {url}", url=self.endpoint))
        else:
            self.status_label.setText(tr("Off"))

    def _show_activity(self, name: str) -> None:
        self.activity_label.setText(tr("Running: {tool}", tool=name) if name else "")

    def retranslate(self) -> None:
        self.enable.setText(tr("Allow AI control (MCP server)"))
        self.limits_group.setTitle(tr("Limits for the AI"))
        self.max_v_label.setText(tr("Max voltage"))
        self.max_a_label.setText(tr("Max current"))
        self.max_min_label.setText(tr("Max duration per call"))
        self.allow_memory.setText(tr("Allow the AI to overwrite memories M1-M5"))
        self.conn_group.setTitle(tr("Connection"))
        self.port_label.setText(tr("Port"))
        self.key_label.setText(tr("Key"))
        self.show_key.setText(tr("Show"))
        self.copy_key.setText(tr("Copy key"))
        self.copy_cmd.setText(tr("Copy Claude Code command"))
        self.new_key_btn.setText(tr("New key"))
        self._update_status()
