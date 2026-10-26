"""Entry point for the desktop GUI: ``ps3005d-gui [--port PORT | --sim]``."""

from __future__ import annotations

import argparse
import os
import sys

from PySide6.QtWidgets import QApplication

from ps3005d.gui.i18n import LANGUAGES
from ps3005d.gui.main_window import SIM_PORT, MainWindow

PORT_ENV = "PS3005D_PORT"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ps3005d-gui", description=__doc__)
    parser.add_argument("--port", default=os.environ.get(PORT_ENV))
    parser.add_argument("--sim", action="store_true", help="preselect the simulator")
    parser.add_argument("--connect", action="store_true", help="connect on startup")
    parser.add_argument(
        "--lang", choices=list(LANGUAGES), help="UI language (default: last used, else system)"
    )
    args = parser.parse_args(argv)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("PS3005D")
    win = MainWindow(port=SIM_PORT if args.sim else args.port, language=args.lang)
    win.show()
    if args.connect:
        win.connect_btn.click()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
