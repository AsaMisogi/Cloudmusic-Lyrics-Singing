"""原生桌面歌词与通知区域。播放时钟由 Bridge 提供，不依赖隐藏网页的动画帧。"""

import bisect
import re
import subprocess
import sys
import time
from pathlib import Path
from PySide6.QtCore import Qt, QPoint, QPointF, QTimer, QRectF
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QSystemTrayIcon,
    QMenu,
    QColorDialog,
    QGraphicsBlurEffect,
    QGraphicsScene,
)
from PySide6.QtGui import QFont, QPainter, QColor, QCursor, QPen, QPixmap
from .karaoke import DesktopClock, LyricInk, sung_ranges
from .ruby_ink import RubyInk, lyric_cells
from .profile import read_map, write_map

DEFAULT = dict(
    enabled=False,
    pinned=False,
    topmost=True,
    shadow=False,
    tray=True,
    reading=True,
    translation=True,
    roman=False,
    original=True,
    ink="#ffffff",
    note="#a9d8ff",
    trans="#f4dba9",
    paper="#192331",
    size=31,
    align="center",
    width=650,
    opacity=0,
    highlight="#ffcd68",
)
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"


def startup(enabled=None):
    """只管理当前用户的固定 Run 项。命令从本机路径生成，不执行备份中的路径。"""
    import winreg

    if enabled is None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN) as key:
                return bool(winreg.QueryValueEx(key, "Utatomo")[0])
        except FileNotFoundError:
            return False
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN) as key:
        if enabled:
            args = (
                [sys.executable]
                if getattr(sys, "frozen", False)
                else [
                    str(Path(sys.executable).with_name("pythonw.exe")),
                    str(Path(__file__).resolve().parents[1] / "main.py"),
                ]
            )
            winreg.SetValueEx(
                key, "Utatomo", 0, winreg.REG_SZ, subprocess.list2cmdline(args)
            )
        else:
            try:
                winreg.DeleteValue(key, "Utatomo")
            except FileNotFoundError:
                pass


class MainWindow(QMainWindow):
    def closeEvent(self, event):
        desk = getattr(self, "desktop", None)
        if (
            desk
            and desk.opts["tray"]
            and desk.tray.isVisible()
            and QSystemTrayIcon.isSystemTrayAvailable()
        ):
            event.ignore()
            self.hide()
        else:
            event.accept()
            QApplication.quit()


class UnlockButton(QPushButton):
    """唯一不穿透的小窗口。父浮窗始终穿透；露锁时也不影响歌词下方的其他控件。"""

    def __init__(self, overlay):
        super().__init__(overlay)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("解锁桌面歌词")
        self.setToolTip("点击解锁，恢复拖动")
        self.clicked.connect(lambda: overlay.desktop.change("pinned", False))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#aca6bb"), 1))
        p.setBrush(QColor("#524862" if self.underMouse() else "#35323e"))
        p.drawRoundedRect(QRectF(1, 1, 30, 30), 9, 9)
        p.setPen(QPen(QColor("#fffaff"), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(12, 7.5, 8, 9), 0, 180 * 16)
        p.drawLine(12, 12, 12, 15)
        p.drawLine(20, 12, 20, 15)
        p.drawRoundedRect(QRectF(9.5, 14, 13, 10), 2, 2)
        p.drawLine(16, 18, 16, 20)


def visible_at(overlay, local):
    """穿透窗口无法接收 enter。比较命中窗口和浮窗的原生 Z 序，
    避免鼠标实际停在遮挡它的窗口上时弹出解锁键（尤其是关闭置顶后）。
    坐标以窗口的物理原点换算，而不是把多屏的全局逻辑坐标直接乘 DPI。"""
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    hwnd = wintypes.HWND(int(overlay.winId()))
    rect = wintypes.RECT()
    if not u.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    scale = overlay.devicePixelRatioF()
    point = wintypes.POINT(rect.left + round(local.x() * scale), rect.top + round(local.y() * scale))
    u.WindowFromPoint.restype = u.GetAncestor.restype = u.GetWindow.restype = wintypes.HWND
    hit = u.WindowFromPoint(point)
    root = u.GetAncestor(wintypes.HWND(hit), 2) if hit else None  # GA_ROOT
    if overlay.unlock.isVisible() and root == int(overlay.unlock.winId()):
        return True
    # 从实际命中的窗口向上寻找浮窗；通常只隔着少量窗口。未命中时不显示。
    while root:
        if root == hwnd.value:
            return True
        root = u.GetWindow(wintypes.HWND(root), 3)  # GW_HWNDPREV
    return False


class Overlay(QWidget):
    def __init__(self, desktop):
        super().__init__(
            None,
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus,
        )
        self.desktop = desktop
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("咏伴 · 桌面歌词")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        # 工具条预留一行高度，悬停显隐不推移歌词或改变拖动命中区域。
        self.bar = QWidget()
        self.bar.setObjectName("captionTools")
        self.bar.setAttribute(Qt.WA_StyledBackground)
        bar = QHBoxLayout(self.bar)
        bar.setContentsMargins(4, 2, 4, 2)
        bar.setSpacing(2)
        for title, callback in [
            ("字号 −", lambda: self.resize_type(-2)),
            ("字号 ＋", lambda: self.resize_type(2)),
            ("钉住", lambda: desktop.change("pinned", True)),
            ("隐藏", lambda: desktop.change("enabled", False)),
        ]:
            button = QPushButton(title)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(
                {
                    "钉住": "固定位置并穿透鼠标；悬停三秒可解锁",
                    "隐藏": "隐藏桌面歌词，播放继续",
                }.get(title, title)
            )
            button.clicked.connect(callback)
            bar.addWidget(button)
        self.bar.setStyleSheet(
            "#captionTools{background:#26252d;border:1px solid #484651;border-radius:8px}"
            "QPushButton{background:transparent;color:#f4f2fc;border:0;border-radius:5px;padding:3px 10px} QPushButton:hover{background:#474050;color:white} QPushButton:pressed{background:#5a5269}"
        )
        holder = QWidget()
        holder.setFixedHeight(30)
        h = QHBoxLayout(holder)
        h.setContentsMargins(0, 0, 0, 0)
        h.addStretch()
        h.addWidget(self.bar)
        h.addStretch()
        outer.addWidget(holder)
        self.bar.hide()
        self.labels = [LyricInk(), RubyInk(), LyricInk()]
        for label in self.labels:
            outer.addWidget(label)
        outer.setSpacing(0)
        outer.setContentsMargins(10, 0, 10, 12)
        screen = QApplication.primaryScreen().availableGeometry()
        self.setFixedWidth(min(desktop.opts["width"], screen.width()))
        self.move(screen.center().x() - self.width() // 2, screen.bottom() - 200)
        point = desktop.opts.get("position")
        if (
            isinstance(point, list)
            and len(point) == 2
            and all(type(x) == int and abs(x) < 100000 for x in point)
        ):
            candidate = QPoint(*point)
            if QApplication.screenAt(candidate):
                self.move(candidate)
        self.drag = None
        self.width_drag = None
        self.setMouseTracking(True)

        self.shadow_layer = None
        self.unlock = UnlockButton(self)
        self.hover_since = None
        self.hover_timer = QTimer(self)
        self.hover_timer.setInterval(100)
        self.hover_timer.timeout.connect(self.poll_unlock)

    def ink_rects(self):
        """复用原文、上标与译文的实际排版边界；两侧空白不是歌词的悬停区。"""
        for label in self.labels:
            if not label.isHidden():
                for rect in getattr(label, "ink_bounds", ()):
                    yield rect.translated(label.pos())

    def reset_unlock(self):
        self.hover_since = None
        self.unlock.hide()

    def sync_unlock(self):
        if self.isVisible() and self.desktop.opts["pinned"]:
            if not self.hover_timer.isActive():
                self.hover_timer.start()
        else:
            self.hover_timer.stop()
            self.reset_unlock()

    def hideEvent(self, event):
        self.hover_timer.stop()
        self.reset_unlock()
        super().hideEvent(event)

    def poll_unlock(self, cursor=None, now=None):
        # 不装全局鼠标钩子。仅浮窗已显示且钉住时低频取样，停播时同样可以解锁。
        cursor = QCursor.pos() if cursor is None else cursor
        now = time.monotonic() if now is None else now
        local = self.mapFromGlobal(cursor)
        shown = self.unlock.isVisible()
        in_badge = shown and self.unlock.geometry().adjusted(-5, -2, 5, 2).contains(cursor)
        if not (in_badge or any(r.adjusted(-5, -4, 5, 4).contains(local) for r in self.ink_rects())):
            self.reset_unlock()
            return
        if not visible_at(self, local):
            self.reset_unlock()
        elif self.hover_since is None:
            self.hover_since = now
        elif not shown and now - self.hover_since >= 3:
            # 锁放在指针侧边而不是正下方；不会截走原本准备点到下层窗口的那一次点击。
            x = local.x() + 4 if local.x() + 36 <= self.width() else local.x() - 36
            y = max(0, min(self.height() - 32, local.y() - 16))
            self.unlock.move(self.mapToGlobal(QPoint(x, y)))
            self.unlock.show()

    def shadow_pixmap(self):
        """将多行字组下的羽化底影缓存为一层；逐字着色不重新生成阴影。"""
        if self.shadow_layer is None:
            scale = self.devicePixelRatioF()
            mask = QPixmap(round(self.width() * scale), round(self.height() * scale))
            mask.setDevicePixelRatio(scale)
            mask.fill(Qt.transparent)
            p = QPainter(mask)
            for label in self.labels:
                if label.isHidden() or not label.cache_key:
                    continue
                if isinstance(label, RubyInk):
                    p.drawPixmap(label.pos(), label.base)
                else:
                    label.layout_text.draw(p, QPointF(label.pos()))
            # 取文本轮廓而非标签矩形：亮壁纸上也不会出现一块方形黑底。
            p.setCompositionMode(QPainter.CompositionMode_SourceIn)
            p.fillRect(self.rect(), QColor("#10121a"))
            p.end()
            scene = QGraphicsScene()
            scene.setSceneRect(QRectF(self.rect()))
            item = scene.addPixmap(mask)
            blur = QGraphicsBlurEffect()
            blur.setBlurRadius(10 * scale)
            item.setGraphicsEffect(blur)
            item.setPos(0, 3)
            self.shadow_layer = QPixmap(mask.size())
            self.shadow_layer.setDevicePixelRatio(scale)
            self.shadow_layer.fill(Qt.transparent)
            p = QPainter(self.shadow_layer)
            # 两次叠加提高浅色桌面上的可读性，仍保留字间和句尾的透明区。
            for _ in range(2):
                scene.render(p, QRectF(self.rect()), scene.sceneRect())
            p.end()
        return self.shadow_layer

    def resize_type(self, delta):
        self.desktop.change("size", min(56, max(18, self.desktop.opts["size"] + delta)))

    def enterEvent(self, event):
        self.bar.setVisible(not self.desktop.opts["pinned"])
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.bar.hide()
        super().leaveEvent(event)

    def contextMenuEvent(self, event):
        if self.desktop.opts["pinned"]:
            return
        menu = QMenu(self)
        menu.addAction("放大歌词", lambda: self.resize_type(2))
        menu.addAction("缩小歌词", lambda: self.resize_type(-2))
        for title, delta in [("加宽浮窗", 80), ("收窄浮窗", -80)]:
            menu.addAction(
                title,
                lambda checked=False, d=delta: self.desktop.change(
                    "width", max(320, min(1600, self.width() + d))
                ),
            )
        menu.addSeparator()
        for title, key in [
            ("显示原文", "original"),
            ("显示注音", "reading"),
            ("显示译文", "translation"),
            ("使用罗马音", "roman"),
            ("歌词底部阴影", "shadow"),
            ("窗口置顶", "topmost"),
        ]:
            item = menu.addAction(title)
            item.setCheckable(True)
            item.setChecked(self.desktop.opts[key])
            if (
                key in ("original", "reading", "translation")
                and self.desktop.opts[key]
                and sum(
                    self.desktop.opts[k] for k in ("original", "reading", "translation")
                )
                == 1
            ):
                item.setEnabled(False)
            item.triggered.connect(
                lambda checked, k=key: self.desktop.change(k, checked)
            )

        def choose_color():
            color = QColorDialog.getColor(
                QColor(self.desktop.opts["highlight"]), self, "已唱颜色"
            )
            if color.isValid():
                self.desktop.change("highlight", color.name())

        align_menu = menu.addMenu("歌词对齐")
        for key, title in [("center", "居中"), ("left", "居左"), ("right", "居右")]:
            item = align_menu.addAction(title)
            item.setCheckable(True)
            item.setChecked(self.desktop.opts["align"] == key)
            item.triggered.connect(
                lambda checked, k=key: self.desktop.change("align", k)
            )
        menu.addAction("更改已唱颜色…", choose_color)
        menu.addSeparator()
        menu.addAction("钉住并穿透鼠标", lambda: self.desktop.change("pinned", True))
        menu.addAction("隐藏桌面歌词", lambda: self.desktop.change("enabled", False))
        menu.exec(event.globalPos())

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta and not self.desktop.opts["pinned"]:
            self.resize_type(2 if delta > 0 else -2)
            event.accept()

    def paintEvent(self, event):
        # 分层窗口的完全透明像素在 Windows 会透过鼠标；未锁定用 1/255 的底保持可拖动。
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(self.desktop.opts["paper"])
        color.setAlpha(
            max(
                0 if self.desktop.opts["pinned"] else 1,
                round(self.desktop.opts["opacity"] * 2.55),
            )
        )
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(self.rect(), 10, 10)
        if self.desktop.opts["shadow"]:
            p.drawPixmap(0, 0, self.shadow_pixmap())

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if e.position().x() >= self.width() - 12:
                self.width_drag = (e.globalPosition().x(), self.width())
            else:
                self.drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self.width_drag is not None:
            start, width = self.width_drag
            self.setFixedWidth(
                max(320, min(1600, round(width + e.globalPosition().x() - start)))
            )
            self.desktop.last = None
            self.desktop.tick()
            return
        self.setCursor(
            Qt.SizeHorCursor
            if e.position().x() >= self.width() - 12
            else Qt.OpenHandCursor
        )
        if self.drag is not None:
            self.move(e.globalPosition().toPoint() - self.drag)

    def mouseReleaseEvent(self, e):
        if self.width_drag is not None:
            self.width_drag = None
            self.desktop.change("width", self.width())
        if self.drag is not None:
            self.drag = None
            self.desktop.change("position", [self.x(), self.y()])


def selected_content(line, o):
    """统一判断并排版当前勾选的内容；只有空白的时间标记不算一句歌词。"""
    cells, unaligned = lyric_cells(line, o["roman"])
    # 原文打开时，假名紧贴对应汉字；仅注音模式和没有对应断点的手写读音仍可独立阅读。
    notes_only = ""
    if o["reading"]:
        if not o["original"]:
            manual = line.get("segments", {}).get("roman" if o["roman"] else "kana")
            tokens = line.get("cantoneseTokens", line.get("tokens", []))
            readings = [
                (
                    t.get("romaji")
                    if o["roman"] and t.get("language") == "ja"
                    else None
                )
                or t.get("reading")
                or (t["text"] if t.get("language") == "ja" else "")
                for t in tokens
            ]
            notes_only = manual or " ".join(filter(None, readings))
        else:
            notes_only = unaligned
    if not o["reading"]:
        cells = [(base, "") for base, _ in cells]
    if not o["original"]:
        cells = []
    trans = line.get("translation", "") if o["translation"] else ""
    if not any((base + note).strip() for base, note in cells):
        cells = []
    return cells, notes_only.strip(), trans.strip()


def desktop_line(lines, index, options):
    """按歌曲时间轴向前找，而非记住屏幕上一帧：倒拖、跳播、换歌都不会串句。"""
    if 0 <= index < len(lines):
        for candidate in range(index, -1, -1):
            content = selected_content(lines[candidate], options)
            if any(content):
                return candidate, content
    return index, ([], "", "")


class Desktop:
    def __init__(self, bridge, path, testing=False):
        self.bridge, self.path = bridge, path
        self.opts = {**DEFAULT, **read_map(path)}
        self.overlay = Overlay(self)
        self.last = None
        self.lines = None
        self.manual = 0
        self.clock = DesktopClock()
        self.sample = None
        self.progress_key = None
        # 浮窗有自己的呈现节拍，隐藏主窗口不会节流它；停播、纯文本和关闭时不开高频定时器。
        self.animation = QTimer(self.overlay)
        self.animation.setTimerType(Qt.PreciseTimer)
        self.animation.timeout.connect(self.tick)
        self.tray = QSystemTrayIcon(QApplication.windowIcon(), bridge.window)
        self.menu = QMenu(bridge.window)
        self.menu.addAction("打开咏伴", self.restore)
        # 每次展开都描述下一次动作，不让用户猜“显示 / 隐藏”究竟会执行哪一个。
        # 使用系统菜单的字体、行高和调色板，不把网页主题强塞进 Windows 通知区。
        self.visibility_action = self.menu.addAction(
            "显示桌面歌词", lambda: self.change("enabled", not self.opts["enabled"])
        )
        self.pin_action = self.menu.addAction(
            "钉住桌面歌词", lambda: self.change("pinned", not self.opts["pinned"])
        )
        self.menu.aboutToShow.connect(self.refresh_tray)
        self.menu.addSeparator()
        self.menu.addAction("退出咏伴", QApplication.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.setToolTip("咏伴 · 歌词练唱")
        self.tray.activated.connect(
            lambda reason: (
                self.restore()
                if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
                else None
            )
        )
        if not testing:
            self.tray.show()
        self.apply()

    def refresh_tray(self):
        self.visibility_action.setText(
            "隐藏桌面歌词" if self.opts["enabled"] else "显示桌面歌词"
        )
        self.pin_action.setText(
            "解锁桌面歌词" if self.opts["pinned"] else "钉住桌面歌词"
        )
        self.pin_action.setEnabled(self.opts["enabled"])

    def restore(self):
        w = self.bridge.window
        w.showNormal()
        w.raise_()
        w.activateWindow()

    def change(self, key, value):
        if key == "startup":
            startup(value)
        else:
            if key in DEFAULT:
                default = DEFAULT[key]
                if type(value) != type(default) or (
                    isinstance(default, str)
                    and key != "align"
                    and not re.fullmatch("#[0-9a-fA-F]{6}", value)
                ):
                    raise ValueError("无效的桌面歌词设置。")
                if key == "align" and value not in ("center", "left", "right"):
                    raise ValueError("未知对齐方式。")
                if key == "width" and not 320 <= value <= 1600:
                    raise ValueError("浮窗宽度范围为 320–1600。")
                if key == "opacity" and not 0 <= value <= 100:
                    raise ValueError("底色浓度范围为 0–100。")
                if key == "size" and not 18 <= value <= 56:
                    raise ValueError("字号范围为 18–56。")
            elif key != "position":
                raise ValueError("未知设置。")
            opts = {**self.opts, key: value}
            if not any(opts[k] for k in ("reading", "translation", "original")):
                raise ValueError("请至少保留一种显示内容。")
            write_map(self.path, opts)
            self.opts = opts
            self.apply()
        self.report()

    def report(self):
        self.bridge.send("desktop", dict(self.opts, startup=startup()))

    def apply(self):
        o = self.opts
        w = self.overlay
        screen = QApplication.screenAt(w.pos()) or QApplication.primaryScreen()
        w.setFixedWidth(min(o["width"], screen.availableGeometry().width()))
        # 一次更新窗口标志；Qt 重建窗口时暂时隐藏，保留原屏位置与不抢焦点属性。
        flags = w.windowFlags()
        for flag, enabled in ((Qt.WindowTransparentForInput, o["pinned"]), (Qt.WindowStaysOnTopHint, o["topmost"])):
            flags = (flags | flag) if enabled else (flags & ~flag)
        if flags != w.windowFlags():
            pos = w.pos()
            w.setWindowFlags(flags)
            w.move(pos)
        w.unlock.setWindowFlag(Qt.WindowStaysOnTopHint, o["topmost"])
        if o["pinned"]:
            w.bar.hide()
        w.update()
        self.last = None
        if not o["enabled"]:
            self.animation.stop()
        w.setVisible(o["enabled"])
        w.sync_unlock()
        self.tick()

    def tick(self):
        if not self.opts["enabled"]:
            return
        b = self.bridge
        lines = b.lines
        if lines is not self.lines:
            self.lines = lines
            self.starts = [l["start"] for l in lines]
            self.manual = 0
            self.last = None
        if b.mode == "local":
            now = time.monotonic() * 1000
            playing = b.player.isPlaying()
            self.clock.update(
                dict(
                    position=b.player.position(),
                    rate=b.player.playbackRate(),
                    duration=b.player.duration(),
                    playing=playing,
                    connected=True,
                    identity=("local", b.generation),
                ),
                now,
            )
            position = self.clock.read(now)
            self.sample = None
        else:
            playing = bool(
                b.cloud_state.get("playing") and b.cloud_state.get("hasTimeline", True)
            )
            if self.sample is not b.cloud_state:
                self.sample = b.cloud_state
                self.clock.update(self.sample, b.cloud_sample_time * 1000)
            position = self.clock.read(time.monotonic() * 1000)
        idx = (
            bisect.bisect_right(self.starts, (position or 0) - b.lyric_offset) - 1
            if self.starts and self.starts[0] is not None
            else self.manual
        )
        pos = (position or 0) - b.lyric_offset
        o = self.opts
        screen = self.overlay.screen()
        if playing and self.starts and self.starts[0] is not None and o["original"]:
            interval = max(1, round(1000 / max(1, screen.refreshRate() or 60)))
            if not self.animation.isActive() or interval != self.animation.interval():
                self.animation.start(interval)
        elif self.animation.isActive():
            self.animation.stop()
        layout_key = (idx, self.overlay.devicePixelRatioF())
        same_layout = self.last == layout_key
        if not same_layout:
            self.display_index, (cells, notes_only, trans) = desktop_line(lines, idx, o)
        idx = self.display_index
        line = lines[idx] if 0 <= idx < len(lines) else {}
        end = (
            line.get("end")
            or (self.starts[idx + 1] if 0 <= idx < len(lines) - 1 else None)
            or (
                b.player.duration()
                if b.mode == "local"
                else b.cloud_state.get("duration")
            )
            or line.get("start")
            or 0
        )
        if same_layout:
            self.progress(line, pos, end)
            return
        self.last = layout_key
        self.progress_key = None
        if not (cells or trans or notes_only):
            cells = [("等待歌词" if not line else "此句无所选内容", "")]
        width = self.overlay.width() - 20
        for index, (text, color, ratio) in enumerate(
            [(notes_only, "note", 0.60), ("", "ink", 1), (trans, "trans", 0.60)]
        ):
            label = self.overlay.labels[index]
            visible = bool(cells) if index == 1 else bool(text)
            label.setVisible(visible)
            if not visible:
                continue
            font = QFont("Microsoft YaHei UI")
            font.setPixelSize(round(o["size"] * ratio))
            font.setWeight(QFont.DemiBold if index == 1 else QFont.Medium)
            if index == 1:
                # breaks 是源码点；每个较早的斜线在显示串里另占一个位置。
                separators = {cut + n for n, cut in enumerate(line.get("breaks", []))} if o["original"] else set()
                label.prepare_cells(
                    cells, font, width, o["ink"], o["highlight"], o["note"], o["align"], separators
                )
            else:
                manual_note = index == 0 and line.get("segments", {}).get("roman" if o["roman"] else "kana")
                separators = {i for i, c in enumerate(text) if c == "/"} if manual_note else set()
                label.prepare(text, font, width, o[color], o["highlight"], o["align"], separators)
        self.overlay.adjustSize()
        self.overlay.layout().activate()
        self.overlay.shadow_layer = None
        self.overlay.update()
        self.progress(line, pos, end)

    def progress(self, line, pos, end):
        if not line or not self.opts["original"]:
            return
        key = (pos, end)
        if key == self.progress_key:
            return
        self.progress_key = key
        # 合并相邻已唱区间。正常播放通常只需一个裁切矩形；真正的词间空隙仍分别着色。
        ranges = []
        for a, b in sung_ranges(line, pos, end):
            if b <= a:
                continue
            if ranges and a == ranges[-1][1]:
                ranges[-1] = (ranges[-1][0], b)
            else:
                ranges.append((a, b))
        # 斜线是练习标记，不占原音轨的时间。将源字符范围投影到加过分隔符的显示串。
        cuts = line.get("breaks", [])
        if cuts:
            ranges = [
                (a + bisect.bisect_right(cuts, a), b + bisect.bisect_left(cuts, b))
                for a, b in ranges
                if b > a
            ]
        self.overlay.labels[1].set_ranges(ranges)
