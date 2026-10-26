"""Draw the app icon with Qt and write it as PNG (window icon) and ICO (Windows exe).

Run from the repository root: ``python packaging/make_icon.py``. The outputs are
committed; rerun only when changing the design.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

ROOT = Path(__file__).resolve().parent.parent
PNG_OUT = ROOT / "src" / "ps3005d" / "gui" / "icon.png"
ICO_OUT = ROOT / "packaging" / "windows" / "ps3005d.ico"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 256, size / 256)
    # Body
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1d3557"))
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 44, 44)
    # Display with a step waveform (like the graphs)
    p.setBrush(QColor("#0b1d33"))
    p.drawRoundedRect(QRectF(32, 36, 192, 112), 16, 16)
    wave = QPainterPath(QPointF(48, 128))
    for x, y in ((80, 128), (80, 80), (128, 80), (128, 104), (168, 104), (168, 60), (208, 60)):
        wave.lineTo(x, y)
    p.setPen(
        QPen(
            QColor("#4fa3ff"),
            14,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(wave)
    # Output terminals
    p.setPen(Qt.PenStyle.NoPen)
    for cx, color in ((92, "#e63946"), (164, "#111111")):
        p.setBrush(QColor("#f1faee"))
        p.drawEllipse(QPointF(cx, 194), 26, 26)
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(cx, 194), 18, 18)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data.data())


def write_ico(path: Path, images: list[bytes], sizes: tuple[int, ...]) -> None:
    """ICO with PNG-compressed entries (supported since Windows Vista)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, blob in zip(sizes, images, strict=True):
        dim = 0 if size >= 256 else size  # 0 means 256
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    path.write_bytes(header + entries + blobs)


def main() -> int:
    _app = QGuiApplication(sys.argv[:1])
    draw(256).save(str(PNG_OUT))
    write_ico(ICO_OUT, [png_bytes(draw(s)) for s in ICO_SIZES], ICO_SIZES)
    print(f"wrote {PNG_OUT.relative_to(ROOT)} and {ICO_OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
