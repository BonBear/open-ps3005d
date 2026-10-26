"""Entry point for the desktop GUI: ``ps3005d-gui [--port PORT | --sim]``."""

from __future__ import annotations

import argparse
import os
import socket
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ps3005d.gui import i18n
from ps3005d.gui.i18n import LANGUAGES
from ps3005d.gui.main_window import SIM_PORT, MainWindow

PORT_ENV = "PS3005D_PORT"
ICON = Path(__file__).with_name("icon.png")


def _make_app() -> QApplication:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv[:1])
    app.setApplicationName("PS3005D")
    app.setWindowIcon(QIcon(str(ICON)))
    return app


def self_test(report: Path) -> int:
    """Start the GUI against the simulator and check the parts a frozen build can lose
    (Qt plugins and translations, the MCP HTTP server). Writes a report; 0 = all ok.

    Used by the Windows build, whose GUI exe has no console. Uses temporary settings.
    """
    lines: list[str] = []
    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        lines.append(f"{'OK  ' if passed else 'FAIL'} {name}{': ' + detail if detail else ''}")

    def pump(ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    try:
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
        app = _make_app()
        check("window icon", not app.windowIcon().isNull())
        for code in ("sv", "de"):
            i18n.set_language(code)
            check(f"Qt translation {code}", i18n._qt_translator is not None)
        win = MainWindow(port=SIM_PORT, language="en")
        win.show()
        win.connect_btn.click()
        deadline = time.monotonic() + 10
        while not win.identity.text() and time.monotonic() < deadline:
            pump(50)
        check("connect to simulator", "SIMULATED" in win.identity.text(), win.identity.text())
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = int(s.getsockname()[1])
        win.ai_panel.port.setValue(port)
        win.ai_panel.enable.setChecked(True)
        check("MCP HTTP server", win.ai_panel.serving, win.ai_panel.endpoint)
        try:
            urllib.request.urlopen(urllib.request.Request(win.ai_panel.endpoint, data=b"{}"))
            status = 200
        except urllib.error.HTTPError as exc:
            status = exc.code
        check("MCP key required", status == 401, f"HTTP {status} without key")
        win.ai_panel.enable.setChecked(False)
        win.close()
    except Exception:
        check("exception", False, traceback.format_exc())
    lines.append("RESULT " + ("OK" if ok else "FAILED"))
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ps3005d-gui", description=__doc__)
    parser.add_argument("--port", default=os.environ.get(PORT_ENV))
    parser.add_argument("--sim", action="store_true", help="preselect the simulator")
    parser.add_argument("--connect", action="store_true", help="connect on startup")
    parser.add_argument(
        "--lang", choices=list(LANGUAGES), help="UI language (default: last used, else system)"
    )
    parser.add_argument("--self-test", metavar="REPORT", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test(args.self_test)

    app = _make_app()
    win = MainWindow(port=SIM_PORT if args.sim else args.port, language=args.lang)
    win.show()
    if args.connect:
        win.connect_btn.click()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
