"""Sequence tab: edit a step table, run it, show progress."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSettings, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ps3005d import sequence as seq
from ps3005d.gui.i18n import tr
from ps3005d.protocol import I_MAX, V_MAX
from ps3005d.sequence import Step

SETTINGS_SEQUENCE = "sequence"
DEFAULT_STEPS = [Step(5.0, 0.5, 10.0), Step(12.0, 0.5, 10.0)]
# column -> (minimum, maximum, decimals)
COLUMNS = ((0.0, V_MAX, 2), (0.0, I_MAX, 3), (seq.MIN_STEP_S, 24 * 3600.0, 1))
CURRENT_ROW_COLOR = QColor(42, 127, 212, 60)


def format_duration(seconds: float) -> str:
    s = round(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    parts = [f"{h} h"] if h else []
    if m or h:
        parts.append(f"{m} min")
    parts.append(f"{s} s")
    return " ".join(parts)


class _NumberDelegate(QStyledItemDelegate):
    """Spin-box editors limited to each column's valid range."""

    def createEditor(
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        lo, hi, decimals = COLUMNS[index.column()]
        editor = QDoubleSpinBox(parent)
        editor.setRange(lo, hi)
        editor.setDecimals(decimals)
        return editor

    def displayText(self, value: object, locale: object) -> str:
        return f"{float(value):g}" if isinstance(value, float) else str(value)


class SequencePanel(QWidget):
    start_requested = Signal(object, int, bool)  # steps, repeat (0 = forever), leave output on
    stop_requested = Signal()

    def __init__(self, settings: QSettings) -> None:
        super().__init__()
        self._settings = settings
        self._running = False
        self._connected = False
        self._highlight: int | None = None

        self.table = QTableWidget(0, 3)
        self.table.setItemDelegate(_NumberDelegate(self.table))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(self._table_changed)

        self.add_btn = QPushButton()
        self.add_btn.clicked.connect(self._add_step)
        self.remove_btn = QPushButton()
        self.remove_btn.clicked.connect(self._remove_steps)
        self.open_btn = QPushButton()
        self.open_btn.clicked.connect(self._open)
        self.save_btn = QPushButton()
        self.save_btn.clicked.connect(self._save)
        edit_row = QHBoxLayout()
        for b in (self.add_btn, self.remove_btn, self.open_btn, self.save_btn):
            edit_row.addWidget(b)

        self.rounds_label = QLabel()
        self.rounds = QSpinBox()
        self.rounds.setRange(0, 100000)
        self.rounds.setSpecialValueText("∞")
        self.rounds.setValue(1)
        self.rounds.valueChanged.connect(self._update_total)
        self.leave_on = QCheckBox()
        opts = QHBoxLayout()
        opts.addWidget(self.rounds_label)
        opts.addWidget(self.rounds)
        opts.addSpacing(12)
        opts.addWidget(self.leave_on, 1)

        self.total_label = QLabel()
        self.start_btn = QPushButton()
        self.start_btn.setMinimumHeight(36)
        self.start_btn.clicked.connect(self._start_clicked)
        self.stop_btn = QPushButton()
        self.stop_btn.setMinimumHeight(36)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        run_row = QHBoxLayout()
        run_row.addWidget(self.start_btn, 1)
        run_row.addWidget(self.stop_btn, 1)
        self.progress_label = QLabel()

        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        layout.addLayout(edit_row)
        layout.addLayout(opts)
        layout.addWidget(self.total_label)
        layout.addLayout(run_row)
        layout.addWidget(self.progress_label)

        saved = str(self._settings.value(SETTINGS_SEQUENCE, "") or "")
        try:
            steps = seq.loads(saved) or DEFAULT_STEPS
        except ValueError:
            steps = DEFAULT_STEPS
        self.set_steps(steps)
        self._update_buttons()

    # -- table ------------------------------------------------------------

    def _item(self, row: int, col: int) -> QTableWidgetItem:
        item = self.table.item(row, col)
        assert item is not None  # every cell is created in _append_row
        return item

    def steps(self) -> list[Step]:
        out = []
        for row in range(self.table.rowCount()):
            values = [float(self._item(row, c).data(Qt.ItemDataRole.EditRole)) for c in range(3)]
            out.append(Step(*values))
        return out

    def set_steps(self, steps: list[Step]) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for step in steps:
            self._append_row(step)
        self.table.blockSignals(False)
        self._table_changed()

    def _append_row(self, step: Step) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, value in enumerate((step.volts, step.amps, step.seconds)):
            lo, hi, _ = COLUMNS[col]
            item = QTableWidgetItem()
            item.setData(Qt.ItemDataRole.EditRole, float(min(max(value, lo), hi)))
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, col, item)

    def _add_step(self) -> None:
        steps = self.steps()
        self.table.blockSignals(True)
        self._append_row(steps[-1] if steps else DEFAULT_STEPS[0])
        self.table.blockSignals(False)
        self._table_changed()

    def _remove_steps(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and self.table.rowCount():
            rows = [self.table.rowCount() - 1]
        for row in rows:
            self.table.removeRow(row)
        self._table_changed()

    def _table_changed(self, *_: object) -> None:
        self._settings.setValue(SETTINGS_SEQUENCE, seq.dumps(self.steps()))
        self._update_total()
        self._update_buttons()

    def _update_total(self) -> None:
        cycle = format_duration(seq.total_seconds(self.steps()))
        rounds = self.rounds.value()
        if rounds == 0:
            self.total_label.setText(tr("Total: {time} per round, until stopped", time=cycle))
        else:
            total = format_duration(seq.total_seconds(self.steps()) * rounds)
            self.total_label.setText(tr("Total: {time}", time=total))

    # -- files ------------------------------------------------------------

    def _open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Open sequence"), "", tr("Sequence files (*.csv *.ini *.txt)")
        )
        if path:
            try:
                self.set_steps(seq.load(Path(path)))
            except (OSError, ValueError) as exc:
                self.progress_label.setText(tr("Error: {message}", message=exc))

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Save sequence"), "sequence.csv", tr("Sequence files (*.csv *.ini *.txt)")
        )
        if path:
            seq.save(Path(path), self.steps())

    # -- running ----------------------------------------------------------

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._update_buttons()

    def set_running(self, running: bool) -> None:
        self._running = running
        if not running:
            self._set_highlight(None)
        self._update_buttons()

    def _update_buttons(self) -> None:
        editable = not self._running
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.AllEditTriggers
            if editable
            else QAbstractItemView.EditTrigger.NoEditTriggers
        )
        for w in (self.add_btn, self.remove_btn, self.open_btn, self.rounds, self.leave_on):
            w.setEnabled(editable)
        self.start_btn.setEnabled(
            self._connected and not self._running and self.table.rowCount() > 0
        )
        self.stop_btn.setEnabled(self._running)

    def _start_clicked(self) -> None:
        self.start_requested.emit(self.steps(), self.rounds.value(), self.leave_on.isChecked())

    def show_progress(self, index: int, rnd: int, left: float) -> None:
        steps = self.table.rowCount()
        rounds = self.rounds.value()
        self.progress_label.setText(
            tr(
                "Step {step}/{steps} · round {round}/{rounds} · {left} s left",
                step=index + 1,
                steps=steps,
                round=rnd + 1,
                rounds=rounds if rounds else "∞",
                left=f"{left:.0f}",
            )
        )
        self._set_highlight(index)

    def show_message(self, text: str) -> None:
        self.progress_label.setText(text)

    def _set_highlight(self, row: int | None) -> None:
        if row == self._highlight:
            return
        for r in (self._highlight, row):
            if r is None or r >= self.table.rowCount():
                continue
            brush = QBrush(CURRENT_ROW_COLOR) if r == row else QBrush()
            for c in range(3):
                self._item(r, c).setBackground(brush)
        self._highlight = row
        if row is not None:
            self.table.scrollToItem(self._item(row, 0))

    def retranslate(self) -> None:
        self.table.setHorizontalHeaderLabels(
            [tr("Voltage (V)"), tr("Current limit (A)"), tr("Time (s)")]
        )
        self.add_btn.setText(tr("Add step"))
        self.remove_btn.setText(tr("Remove step"))
        self.open_btn.setText(tr("Open…"))
        self.save_btn.setText(tr("Save…"))
        self.rounds_label.setText(tr("Rounds:"))
        self.leave_on.setText(tr("Leave output on after the last step"))
        self.start_btn.setText(tr("Start (switches the output on)"))
        self.stop_btn.setText(tr("Stop (output off)"))
        self._update_total()
        if not self._running:
            self.progress_label.setText(tr("Not running"))
