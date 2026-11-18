"""桌面练唱谱：原文和它的注音组成一个排版单元，两者一起换行。

只在句子、配色、宽度或缩放改变时排字和描边。播放帧只复制两张透明字层的
局部区域；不再反复整句描边，也不需要第二个 WebEngine 实例。
"""

import re
from bisect import bisect_left
from math import ceil

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTextCharFormat,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import QLabel

from .karaoke import spaced_phrase


def lyric_cells(line, roman=False):
    """返回 (原文, 注音) 对和无法可靠定位的手写读音。斜线是显示符号，不参与音轨时间。"""
    tokens = line.get("cantoneseTokens", line.get("tokens", []))
    segments = line.get("segments", {})
    original = segments.get("original") or line.get("text", "")
    manual = segments.get("roman" if roman else "kana", "")
    if manual:
        bases, notes = original.split("/"), manual.split("/")
        if len(bases) == len(notes) and (len(bases) > 1 or len(tokens) == 1):
            cells = []
            for i, (base, note) in enumerate(zip(bases, notes)):
                if i:
                    cells.append(("/", ""))
                cells.append((base, note))
            return cells, ""
    cells, cursor = [], 0
    cuts = line.get("breaks", [])
    for token in tokens or [{"text": line.get("text", "")}]:
        if roman and token.get("language") == "ja" and token.get("romaji"):
            parts = [{"text": token["text"], "reading": token["romaji"]}]
        else:
            parts = token.get("rubyParts") or [token]
        for part in parts:
            text = part["text"]
            note = part.get("reading", "") if not manual else ""
            stop = cursor + len(text)
            # 使用源码点位置；在已有标注内部加斜线也不会把后面的假名错配给前一个字。
            for cut in reversed(
                cuts[bisect_left(cuts, cursor) : bisect_left(cuts, stop)]
            ):
                at = cut - cursor
                if at == 0:
                    # 断点恰好在词首，留白单独排版；注音应继续居于字上而非字与斜线之间。
                    cells.append(("/", ""))
                else:
                    text = text[:at] + "/" + text[at:]
            cells.append((text, note))
            cursor = stop
    return [(base, note) for base, note in cells if base], manual


def shape(text, font, limit):
    """整组用 Qt 排字，保留字库回退、组合字符和超长单词的自然折行。"""
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    layout.setCacheEnabled(True)
    layout.beginLayout()
    width = height = 0
    while True:
        row = layout.createLine()
        if not row.isValid():
            break
        row.setLineWidth(limit)
        row.setPosition(QPointF(0, height))
        width = max(width, row.horizontalAdvance())
        height += row.height()
    layout.endLayout()
    return layout, min(width, limit), height


class RubyInk(QLabel):
    """每个字组保留原文游标到屏幕坐标的映射；重叠逐字时间仍能独立高亮。"""

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.cache_key = None
        self.ranges = []
        self.boxes = []

    def prepare_cells(self, cells, font, width, ink, highlight, note, align, separators=()):
        scale = self.devicePixelRatioF()
        key = (tuple(cells), font.toString(), width, ink, highlight, note, scale, tuple(separators), align)
        if key == self.cache_key:
            return
        self.cache_key = key
        self.setText("".join(t for t, _ in cells))
        small = QFont(font)
        small.setPixelSize(max(10, round(font.pixelSize() * 0.5)))
        small.setWeight(QFont.Medium)
        available = max(8, width - 12)
        rows, row, advance, start = [], [], 0, 0
        for base, reading in cells:
            if not base:
                continue
            # 无注音连续文本按空白划分；长词仍由 QTextLayout 安全折行。
            for text in [base] if reading else re.findall(r"\s+|\S+", base):
                shaped, units = spaced_phrase(text, separators, start)
                bl, bw, bh = shape(shaped, font, available)
                nl, nw, nh = (
                    shape(reading, small, available) if reading else (None, 0, 0)
                )
                w = max(bw, nw) + (1 if reading else 0)
                if row and advance + w > available:
                    rows.append((advance, row))
                    row, advance = [], 0
                row.append((advance, w, bl, bw, bh, nl, nw, nh, start, units))
                advance += w
                start += len(text)
        if row:
            rows.append((advance, row))
        self.boxes = []
        self.ink_bounds = []
        notes = []
        y = 3
        for rw, row in rows:
            above = max(c[7] for c in row)
            below = max(c[4] for c in row)
            left = (
                6
                if align == "left"
                else width - 6 - rw
                if align == "right"
                else (width - rw) / 2
            )
            self.ink_bounds.append(QRectF(left, y, rw, above + below))
            for x, w, bl, bw, bh, nl, nw, nh, start, units in row:
                # 基线由整行最高的注音决定，纯假名、标点不会随注音高低上下跳动。
                point = QPointF(left + x + (w - bw) / 2, y + above)
                self.boxes.append((start, units, bl, point))
                if nl:
                    notes.append((nl, QPointF(left + x + (w - nw) / 2, y + above - nh)))
            y += above + below + 3
        self.setFixedHeight(max(1, ceil(y)))
        self.base = QPixmap(ceil(width * scale), ceil(self.height() * scale))
        self.base.setDevicePixelRatio(scale)
        self.base.fill(Qt.transparent)
        self.sung = QPixmap(self.base.size())
        self.sung.setDevicePixelRatio(scale)
        self.sung.fill(Qt.transparent)
        painter = QPainter(self.base)
        painter.setRenderHint(QPainter.TextAntialiasing)

        def draw(layout, point, color, stroke):
            fr = QTextLayout.FormatRange()
            fr.start = 0
            fr.length = len(layout.text().encode("utf-16-le")) // 2
            fr.format = QTextCharFormat()
            fr.format.setTextOutline(
                QPen(
                    QColor(20, 22, 32, 225),
                    stroke,
                    Qt.SolidLine,
                    Qt.RoundCap,
                    Qt.RoundJoin,
                )
            )
            layout.draw(painter, point, [fr])
            painter.setPen(QColor(color))
            layout.draw(painter, point)

        for _, _, layout, point in self.boxes:
            draw(layout, point, ink, 2.6)
        for layout, point in notes:
            draw(layout, point, note, 1.8)
        painter.end()
        painter = QPainter(self.sung)
        painter.setPen(QColor(highlight))
        painter.setRenderHint(QPainter.TextAntialiasing)
        for _, _, layout, point in self.boxes:
            layout.draw(painter, point)
        painter.end()
        self.ranges = []
        self.update()

    def set_ranges(self, ranges):
        if ranges == self.ranges:
            return
        self.ranges = ranges
        self.update()

    def paintEvent(self, event):
        if self.cache_key is None:
            return
        p = QPainter(self)
        p.drawPixmap(0, 0, self.base)
        if not self.ranges:
            return
        clip = QPainterPath()
        for start, units, layout, point in self.boxes:
            for a, b in self.ranges:
                lo = max(0, a - start)
                hi = min(len(units) - 1, b - start)
                if lo >= hi:
                    continue
                for i in range(layout.lineCount()):
                    row = layout.lineAt(i)
                    left = bisect_left(units, row.textStart())
                    right = bisect_left(units, row.textStart() + row.textLength())
                    lower, upper = max(left, lo), min(right, hi)
                    if lower >= upper:
                        continue

                    x1, x2 = (
                        self._cursor_x(row, units, lower),
                        self._cursor_x(row, units, upper),
                    )
                    clip.addRect(
                        QRectF(
                            point.x() + min(x1, x2),
                            point.y() + row.y(),
                            abs(x2 - x1),
                            row.height(),
                        )
                    )
        p.setClipPath(clip)
        p.drawPixmap(0, 0, self.sung)

    @staticmethod
    def _cursor_x(row, units, pos):
        """Qt 字形游标给出字符边界，边界间插值使一个音节也能连续填充。"""
        k = int(pos)
        x = row.cursorToX(units[k])[0]
        return x if pos == k else x + (pos - k) * (row.cursorToX(units[k + 1])[0] - x)
