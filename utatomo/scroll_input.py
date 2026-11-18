"""校准 Windows WebEngine 的滚动输入；滚动本身仍由 Chromium 执行。

便携版 Qt 6.10.3 的 WebEventFactory 在 Windows 按每系统行 20 CSS 像素换算角度，
并不读取 pixelDelta。桌面 Chromium 则按每系统行 100/3 CSS 像素换算。
在渲染控件入口转换单位，歌词、设置、词典与曲库即可共用原生滚动、命中和边界。
"""

import sys

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QGuiApplication, QWheelEvent
from PySide6.QtWebEngineWidgets import QWebEngineView


QT_LINE_PX = 20
BROWSER_LINE_PX = 100 / 3
NOTCH = 120  # Windows WHEEL_DELTA；Qt 的 angleDelta 采用相同刻度。


class _WheelUnits(QObject):
    """只处理网页自己的滚轮消息，不改系统设置，不接管滑块和原生浮窗。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.forwarding = False
        self.engine_lines = None
        self.scale_key = None
        self.fraction = (0.0, 0.0)

    def eventFilter(self, receiver, event):
        if event.type() != QEvent.Wheel or self.forwarding:
            return False

        # 与 Qt 首次处理滚轮时缓存的行数一致；只换算输入的单位，不对速度做二次插值。
        lines = QGuiApplication.styleHints().wheelScrollLines()
        if self.engine_lines is None:
            self.engine_lines = lines
        if (
            self.engine_lines <= 0
            or lines < 0
            or event.modifiers() != Qt.NoModifier
            or event.buttons() != Qt.NoButton
        ):
            return False

        angle, pixels = event.angleDelta(), event.pixelDelta()
        if event.phase() in (Qt.ScrollBegin, Qt.ScrollEnd):
            self.fraction = (0.0, 0.0)
        if not pixels.isNull():
            # 像素输入本身已有距离，不放大、不按整刻度取整。不乘 DPR：网页和 Qt
            # 控件使用逻辑坐标。在常见的「每次三行」设置下，每个像素对应两个角度单位。
            factor = NOTCH / (QT_LINE_PX * self.engine_lines)
            source = pixels
        elif angle.y() and not angle.x() and event.phase() == Qt.NoScrollPhase:
            # 无像素信息的纵向滚轮按系统行数走。保留高分辨率鼠标的小刻度、合并刻度与反向，
            # 不用 Linux/macOS 的滚动策略替代 Windows；横向、组合键与手势沿用引擎行为。
            factor = BROWSER_LINE_PX * lines / (QT_LINE_PX * self.engine_lines)
            source = angle
        else:
            return False
        # Qt 的角度是整数。把不足一个单位的余数带给下一次事件：120 次微刻度
        # 与一个完整刻度走同样的总距离，而不是每次四舍五入后越滚越偏。
        key = (not pixels.isNull(), factor)
        if key != self.scale_key:
            self.scale_key = key
            self.fraction = (0.0, 0.0)
        x = source.x() * factor + self.fraction[0]
        y = source.y() * factor + self.fraction[1]
        converted = QPoint(round(x), round(y))
        self.fraction = (x - converted.x(), y - converted.y())
        if converted == angle:
            return False

        adjusted = QWheelEvent(
            event.position(),
            event.globalPosition(),
            pixels,
            converted,
            event.buttons(),
            event.modifiers(),
            event.phase(),
            event.inverted(),
            event.source(),
            event.pointingDevice(),
        )
        adjusted.setTimestamp(event.timestamp())
        self.forwarding = True
        try:
            QCoreApplication.sendEvent(receiver, adjusted)
        finally:
            self.forwarding = False
        event.setAccepted(adjusted.isAccepted())
        return True


class PracticeWebView(QWebEngineView):
    """输入发给 WebEngine 的焦点代理，而非外层 view；只给当前网页渲染控件安装过滤器。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        if sys.platform == "win32":
            self._wheel_units = _WheelUnits(self)
            # 页面更换或重载时 Qt 可能更换代理；同一个对象重复安装仍只保留一个过滤器。
            self.loadStarted.connect(self._bind_wheel)
            self.loadFinished.connect(self._bind_wheel)

    def _bind_wheel(self):
        receiver = self.focusProxy()
        if receiver is not None:
            receiver.installEventFilter(self._wheel_units)
