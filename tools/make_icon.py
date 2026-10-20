"""Génère assets/icon.ico (toutes les tailles Windows) à partir de assets/logo.svg.

À relancer seulement si le logo change :  .venv\\Scripts\\python.exe tools\\make_icon.py
"""
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
HERE = Path(__file__).resolve().parent.parent / "assets"


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def main() -> int:
    QGuiApplication(sys.argv)
    renderer = QSvgRenderer(str(HERE / "logo.svg"))
    if not renderer.isValid():
        print("logo.svg illisible")
        return 1
    images = [(s, render_png(renderer, s)) for s in SIZES]
    # Format ICO : en-tête, une entrée par taille, puis les images PNG (accepté depuis Windows Vista)
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for size, png in images:
        dim = 0 if size >= 256 else size
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    out += b"".join(png for _, png in images)
    (HERE / "icon.ico").write_bytes(out)
    print(f"icon.ico : {len(images)} tailles, {len(out) // 1024} Ko")
    return 0


if __name__ == "__main__":
    sys.exit(main())
