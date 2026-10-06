"""由可维护的 SVG 生成 Windows 多尺寸 ICO，无需额外图像依赖。

ICO 中使用 Windows 10 / 11 支持的 PNG 图层，包含任务栏常用尺寸与
256px 资源管理器预览。PNG 保留透明度；小图分别渲染，避免只嵌大图。
"""

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
SIZES = (16, 24, 32, 48, 64, 128, 256)


def create_icon():
    renderer = QSvgRenderer(str(ROOT / "assets/icon.svg"))
    if not renderer.isValid():
        raise ValueError("图标 SVG 无效。")
    layers = []
    for size in SIZES:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise ValueError("图标 PNG 渲染失败。")
        layers.append(bytes(buffer.data()))
    # ICONDIR 后紧跟每个 ICONDIRENTRY；尺寸 256 在 ICO 头中记为 0。
    offset = 6 + 16 * len(layers)
    entries = []
    for size, png in zip(SIZES, layers):
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset))
        offset += len(png)
    destination = ROOT / "assets/icon.ico"
    destination.write_bytes(struct.pack("<HHH", 0, 1, len(layers)) + b"".join(entries) + b"".join(layers))
    print(f"Icon: {destination}")


if __name__ == "__main__":
    create_icon()
