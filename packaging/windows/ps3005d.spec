# PyInstaller spec: one folder "open-ps3005d" with three programs sharing one runtime.
#
#   ps3005d-gui.exe   desktop app (windowed, no console)
#   ps3005d.exe       command line
#   ps3005d-mcp.exe   MCP server over stdio (console)
#
# Build from the repository root (on Windows for .exe files):
#   pyinstaller packaging/windows/ps3005d.spec --noconfirm
# The same spec also builds on Linux, which is handy for checking hidden imports.

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent.parent  # noqa: F821 - SPECPATH is set by PyInstaller
HERE = ROOT / "packaging" / "windows"
VERSION = re.search(
    r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M
).group(1)
WINDOWS = sys.platform == "win32"

# uvicorn loads its protocol/loop implementations by name.
HIDDEN = collect_submodules("uvicorn") + collect_submodules("ps3005d")
DATAS = collect_data_files("ps3005d") + copy_metadata("mcp") + copy_metadata("ps3005d")
# Qt modules neither we nor pyqtgraph use (pyqtgraph needs QtSvg, QtOpenGLWidgets, QtTest).
EXCLUDES = [
    "tkinter",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
    "PySide6.QtSql",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
]


def version_file() -> str | None:
    if not WINDOWS:
        return None
    nums = [int(x) for x in re.findall(r"\d+", VERSION)[:3]] + [0, 0, 0]
    v = tuple(nums[:4])
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'open-ps3005d'),
      StringStruct('FileDescription', 'Control for the Velleman PS3005D power supply'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('ProductName', 'open-ps3005d'),
      StringStruct('ProductVersion', '{VERSION}'),
      StringStruct('LegalCopyright', 'MIT License, (c) 2026 Bjorn Sjolen'),
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
"""
    path = Path(workpath) / "version_info.txt"  # noqa: F821 - set by PyInstaller
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


VERSION_FILE = version_file()
ICON = str(HERE / "ps3005d.ico") if WINDOWS else None


def program(script: str, name: str, console: bool):
    a = Analysis(  # noqa: F821
        [str(HERE / script)],
        pathex=[str(ROOT / "src")],
        hiddenimports=HIDDEN,
        datas=DATAS,
        excludes=EXCLUDES,
    )
    pyz = PYZ(a.pure)  # noqa: F821
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        console=console,
        icon=ICON,
        version=VERSION_FILE,
        upx=False,
    )
    return exe, a


gui, a_gui = program("entry_gui.py", "ps3005d-gui", console=False)
cli, a_cli = program("entry_cli.py", "ps3005d", console=True)
mcp, a_mcp = program("entry_mcp.py", "ps3005d-mcp", console=True)

coll = COLLECT(  # noqa: F821
    gui, a_gui.binaries, a_gui.datas,
    cli, a_cli.binaries, a_cli.datas,
    mcp, a_mcp.binaries, a_mcp.datas,
    name="open-ps3005d",
    upx=False,
)
