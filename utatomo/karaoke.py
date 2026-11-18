"""桌面歌词的排版与进度。时钟只改变裁切区域；同一句的字形、换行不随播放重排。"""

from bisect import bisect_right
from math import exp

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
    QTextLayout,
    QTextOption,
    QTextCharFormat,
)
from PySide6.QtWidgets import QLabel


def sung_ranges(line, position, end):
    """返回原文字符坐标上的已唱区间。原始逐词停顿和重叠不被拉平；无时间文本不估算。"""
    if line.get("start") is None:
        return []

    def fraction(start, stop):
        return max(0, min(1, (position - start) / max(1, stop - start)))

    if line.get("timing") == "word" and line.get("words"):
        result, cursor = [], 0
        for word in line["words"]:
            length = len(word["text"])
            result.append(
                (
                    cursor,
                    cursor + length * fraction(word["start"], word.get("end") or end),
                )
            )
            cursor += length
        return result
    return [(0, len(line["text"]) * fraction(line["start"], end))]


class DesktopClock:
    """与网页 PlaybackClock 相同的采样和收敛规则；量化时间重复上报时不倒退。"""

    def __init__(self):
        self.raw = None
        self.identity = None
        self.position = self.sampled = self.error = self.duration = 0
        self.rate = 1
        self.playing = False

    def read(self, now):
        elapsed = min(1500, max(0, now - self.sampled)) if self.playing else 0
        horizon = max(600, abs(self.error) * 4 / self.rate)
        return max(
            0,
            min(
                self.duration or float("inf"),
                self.position
                + elapsed * self.rate
                + self.error * (1 - exp(-elapsed / horizon)),
            ),
        )

    def update(self, sample, now):
        raw = sample.get("position") or 0
        rate = sample.get("rate") or 1
        playing = bool(sample.get("playing") and sample.get("connected"))
        predicted = self.read(now)
        changed = self.identity != sample.get("identity")
        jump = (
            changed
            or self.raw is None
            or (not playing and not self.playing and raw != self.raw)
            or (
                raw != self.raw
                and (abs(raw - predicted) > 1500 or raw < self.raw - 350)
            )
        )
        if jump or self.playing != playing or self.rate != rate or raw != self.raw:
            self.position = raw if jump else predicted
            self.sampled = now
            self.error = 0 if jump or not playing else raw - predicted
        self.raw, self.identity, self.rate, self.playing, self.duration = (
            raw,
            sample.get("identity"),
            rate,
            playing,
            sample.get("duration") or 0,
        )


def spaced_phrase(text, separators, start=0):
    """只在手动断点两侧留半字宽。保留「显示码点 → 排版 UTF-16 游标」，
    因此补充平面汉字、斜线留白都不会令后续逐字时间错位。"""
    shaped, units = [], [0]
    for index, char in enumerate(text, start):
        piece = "\u2002/\u2002" if char == "/" and index in separators else char
        shaped.append(piece)
        units.append(units[-1] + (2 if ord(char) > 0xFFFF else len(piece)))
    return "".join(shaped), units


class LyricInk(QLabel):
    """用同一 QTextLayout 绘制描边、未唱、已唱三层，保留 Qt 的字体回退与折行。"""

    def __init__(self):
        super().__init__()
        self.cache_key = None
        self.ranges = []
        self.fill = QColor("#ffce70")
        self.ink = QColor("white")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def prepare(self, text, font, width, ink, fill, align, separators=()):
        self.ink, self.fill = QColor(ink), QColor(fill)
        key = (text, font.toString(), width, tuple(separators), align)
        if key == self.cache_key:
            self.update()
            return
        self.cache_key = key
        self.setText(text)
        shaped, self.units = spaced_phrase(text, separators)
        self.layout_text = QTextLayout(shaped, font)
        options = QTextOption()
        options.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.layout_text.setTextOption(options)
        self.layout_text.beginLayout()
        self.ink_bounds = []
        y = 2
        while True:
            row = self.layout_text.createLine()
            if not row.isValid():
                break
            row.setLineWidth(width - 8)
            gap = width - row.naturalTextWidth()
            row.setPosition(
                QPointF(
                    4 if align == "left" else gap - 4 if align == "right" else gap / 2,
                    y,
                )
            )
            self.ink_bounds.append(row.naturalTextRect())
            y += row.height()
        self.layout_text.endLayout()
        self.setFixedHeight(round(y) + 3)
        self.update()

    def set_ranges(self, ranges):
        if ranges != self.ranges:
            self.ranges = ranges
            self.update()

    def paintEvent(self, event):
        if not self.cache_key:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        fr = QTextLayout.FormatRange()
        fr.start = 0
        fr.length = self.units[-1]
        fr.format = QTextCharFormat()
        fr.format.setTextOutline(
            QPen(QColor(21, 30, 44, 225), 3.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        self.layout_text.draw(p, QPointF(), [fr])
        p.setPen(self.ink)
        self.layout_text.draw(p, QPointF())
        if not self.ranges:
            return
        from PySide6.QtGui import QPainterPath

        clip = QPainterPath()
        for i in range(self.layout_text.lineCount()):
            row = self.layout_text.lineAt(i)
            left = bisect_right(self.units, row.textStart()) - 1
            right = bisect_right(self.units, row.textStart() + row.textLength()) - 1

            def x_at(pos):
                whole = int(pos)
                x = row.cursorToX(self.units[whole])[0]
                if pos != whole and whole < right:
                    x += (row.cursorToX(self.units[whole + 1])[0] - x) * (pos - whole)
                return x

            for a, b in self.ranges:
                a, b = max(a, left), min(b, right)
                if a < b:
                    x, y = x_at(a), x_at(b)
                    clip.addRect(QRectF(min(x, y), row.y(), abs(y - x), row.height()))
        p.setClipPath(clip)
        p.setPen(self.fill)
        self.layout_text.draw(p, QPointF())
