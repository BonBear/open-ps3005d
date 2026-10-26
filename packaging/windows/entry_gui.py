"""PyInstaller entry point: ps3005d-gui.exe (windowed, no console)."""

import os
import sys

# A windowed exe has no console: sys.stdout/sys.stderr are None, and libraries that
# write to them (logging, uvicorn) would fail. Send that output nowhere instead.
for name in ("stdout", "stderr"):
    if getattr(sys, name) is None:
        setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115

from ps3005d.gui.app import main  # noqa: E402

raise SystemExit(main())
