"""真实 WebChannel、原生窗口及临时用户资料的端到端验收，不操作网易云或系统启动项。"""

import json
import ctypes
import os
import sys
import tempfile
import time
from ctypes import wintypes
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QUrl, Qt, QTimer, QPoint
from PySide6.QtGui import QIcon, QContextMenuEvent, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMenu, QPushButton
from utatomo import app as runtime
from utatomo.desktop import MainWindow, Desktop
from utatomo.profile import export_backup, stage_backup, apply_pending, read_map
from utatomo.library import LibraryStore, cloud_track


def run():
    app = QApplication([])
    app.setWindowIcon(QIcon(str(ROOT / "assets/icon.ico")))

    def wait(predicate):
        until = time.monotonic() + 10
        while time.monotonic() < until:
            app.processEvents()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("等待界面响应超时")

    with (
        tempfile.TemporaryDirectory() as folder,
        patch.object(runtime, "CloudMedia"),
        ExitStack() as cleanup,
    ):
        data = Path(folder) / "data"
        data.mkdir()
        runtime.DATA = data
        window = MainWindow()
        window.setWindowTitle("咏伴 · Utatomo")
        window.resize(960, 700)
        view = QWebEngineView(window)
        view.setPage(runtime.LocalPage(view))
        window.setCentralWidget(view)
        bridge = runtime.Bridge(window)
        cleanup.callback(bridge.close)
        bridge.update_started = True
        bridge.client_settings.confirmed = True
        desk = Desktop(bridge, data / "desktop.json")
        window.desktop = bridge.desktop = desk
        channel = QWebChannel(view.page())
        channel.registerObject("backend", bridge)
        view.page().setWebChannel(channel)

        def js(code):
            result = []
            view.page().runJavaScript(code, 0, result.append)
            wait(lambda: bool(result))
            return result[0]

        view.setUrl(QUrl.fromLocalFile(str(ROOT / "web/index.html")))
        window.show()
        wait(lambda: bridge.ready)
        if sys.getwindowsversion().build >= 22000:
            from frame_capture import grab_frame

            # 首屏和真实标题栏一起留档。只等应用自己的窗口画完，不抓取系统桌面。
            def first_frame():
                frame, mid = grab_frame(window)
                if frame.pixelColor(frame.width() // 2, mid).name() != "#17181d":
                    return False
                # loadFinished / DOM 可见并不等于 WebEngine 合成帧已提交。检测真实连接按钮的底色后才截图。
                pos = json.loads(
                    js("""(()=>{const r=$('connectCloud').getBoundingClientRect();
                    return JSON.stringify([r.left+6,r.top+r.height/2,devicePixelRatio]);})()""")
                )
                x, y, scale = pos
                left = (frame.width() - round(view.width() * scale)) // 2
                color = frame.pixelColor(
                    left + round(x * scale), mid * 2 + round(y * scale)
                ).getRgb()[:3]
                # Chromium 合成时可能经显示器 ICC 转换；容许单通道舍入，仍排除未绘制的黑色首帧。
                if max(abs(a - b) for a, b in zip(color, (196, 175, 255))) > 3:
                    return False
                frame.save(str(ROOT / "output/welcome-native.png"))
                return True

            try:
                wait(first_frame)
            except AssertionError:
                frame, mid = grab_frame(window)
                frame.save(str(ROOT / "output/first-frame-debug.png"))
                print(
                    "首屏实际颜色",
                    frame.pixelColor(frame.width() // 2, mid).name(),
                    js(
                        "JSON.stringify([devicePixelRatio, getComputedStyle($('connectCloud')).backgroundColor, $('connectCloud').getBoundingClientRect().toJSON()])"
                    ),
                    flush=True,
                )
                raise
        js("$('importMenu').click()")
        assert js("$('importPopover').matches(':popover-open')")
        js(
            "$('pasteOpen').click();$('pasteText').value='[00:00]青空（そら）\\n[00:05]君と歩く\\n[00:10]朝の光を追いかけて';$('pasteForm').requestSubmit()"
        )
        wait(lambda: len(bridge.lines) == 3)
        wait(lambda: js("state.lines.length===3"))
        assert (
            bridge.lines[0]["text"] == "青空"
            and bridge.lines[0]["tokens"][0]["reading"] == "そら"
        )
        # 关闭按钮位于滚动容器外；从页尾同样能命中它。
        js(
            "$('moreButton').click(); document.querySelector('.pref-body').scrollTop=10000"
        )
        assert js(
            "(()=>{const b=document.querySelector('#toolsDialog .close-dialog'),r=b.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===b})()"
        )
        js(
            "document.querySelector('#toolsDialog .close-dialog').click();lyricRows[0].querySelector('.edit-line').click()"
        )
        wait(lambda: js("$('segmentDialog').open"))
        assert js(
            "$('segmentOriginal').value==='青空' && $('segmentKana').value==='そら'"
        )
        js(
            "$('segmentOriginal').focus();$('segmentOriginal').setSelectionRange(1,1);$('insertCut').click()"
        )
        assert js("$('segmentOriginal').value==='青/空'")
        js(
            "$('segmentKana').value='そ/ら';$('segmentRoman').value='so/ra';$('segmentForm').requestSubmit()"
        )
        wait(
            lambda: js(
                "document.querySelector('.segment-strip')?.textContent==='そ / ら'"
            )
        )
        js("$('toolsDialog').close();$('desktopQuick').click()")
        wait(lambda: desk.overlay.isVisible())
        bridge.cloud_state = {"position": 0}
        desk.tick()
        assert js("JSON.stringify([...lyricRows[0].querySelectorAll('.token-base')].map(b=>[+b.dataset.start,+b.dataset.end]))")== "[[0,1],[1,2]]"
        assert not desk.overlay.labels[0].isVisible()
        assert desk.overlay.labels[1].cache_key[0] == (
            ("青", "そ"),
            ("/", ""),
            ("空", "ら"),
        )
        desk.change("original", False)
        assert (
            desk.overlay.labels[0].text() == "そ/ら"
            and desk.overlay.labels[0].isVisible()
        )
        desk.change("original", True)
        assert desk.overlay.labels[1].text() == "青/空"
        assert desk.overlay.labels[1].boxes[1][1] == [0, 3]  # 单个断点对应加宽后的三个排版游标。
        assert js("parseFloat(getComputedStyle(document.querySelector('.breath'),'::before').paddingLeft) >= 6")

        # 真实抓取同一句在两个时间点的像素：只看是否换句无法发现 0.5 的静态歌词问题。
        def painted():
            image = desk.overlay.labels[1].grab().toImage()
            return sum(
                image.pixelColor(x, y).name() == desk.opts["highlight"]
                for y in range(0, image.height(), 2)
                for x in range(0, image.width(), 2)
            )

        before = painted()
        bridge.cloud_state = {"position": 3500}
        desk.tick()
        assert painted() > before + 10, "同句已唱颜色没有前进"
        assert js("document.querySelector('.breath')!==null")
        bridge.cloud_state = {"position": 5000}
        desk.tick()
        assert desk.overlay.labels[1].text() == "君と歩く"
        # 使用真实工作线程解析混合汉字与送假名。比较两端的上标边界，而不是只比整句文本。
        bridge.lines[2]["translation"] = (
            "追逐清晨的阳光"  # 与篇幅较短的显式注音、无译文行共存。
        )
        bridge.cloud_state = {"position": 11000, "duration": 15000}
        desk.tick()
        actual = desk.overlay.labels[1].cache_key[0]
        assert list(actual) == [
            tuple(x)
            for x in json.loads(
                js(
                    """JSON.stringify([...lyricRows[2].querySelectorAll('.token-base')].map(b=>[b.textContent,b.closest('ruby')?.querySelector('rt')?.textContent||'']))"""
                )
            )
        ]
        assert ("朝", "あさ") in actual
        assert (
            desk.overlay.labels[2].isVisible()
            and desk.overlay.labels[2].text() == "追逐清晨的阳光"
        )
        desk.overlay.bar.hide()
        assert desk.opts["topmost"] and not desk.opts["shadow"]
        shadow_off = desk.overlay.grab().toImage()
        js("document.querySelector('[data-desk=shadow]').click()")
        wait(lambda: desk.opts["shadow"] and js("$('deskSwatch').classList.contains('has-shadow')"))
        shadow_on = desk.overlay.grab().toImage()
        # 同一窗口的透明留白出现半透明底影，但左右边缘没有铺成整块背景。
        def gains(x, y):
            return shadow_on.pixelColor(x,y).alpha() - shadow_off.pixelColor(x,y).alpha()
        assert max(gains(x,y) for x in range(4, shadow_on.width(), 4) for y in range(6, shadow_on.height(), 4)) > 50
        assert gains(2, shadow_on.height()//2) == 0
        desk.overlay.grab().save(str(ROOT / "output/desktop-shadow081.png"))
        bridge.cloud_state.update(playing=True, connected=True)
        desk.tick()
        assert desk.animation.isActive() and desk.animation.interval() == round(
            1000 / desk.overlay.screen().refreshRate()
        )
        bridge.cloud_state.update(playing=False)
        desk.tick()
        assert not desk.animation.isActive()
        original_width, original_size = desk.opts["width"], desk.opts["size"]
        desk.change("width", 320)
        desk.change("size", 48)
        ink = desk.overlay.labels[1]
        assert len({round(point.y()) for _, _, _, point in ink.boxes}) >= 2
        assert all(
            0 <= point.x() < ink.width() and 0 <= point.y() < ink.height()
            for _, _, _, point in ink.boxes
        )
        desk.change("width", original_width)
        desk.change("size", original_size)
        # 音量操作经 WebChannel 改变真实 QAudioOutput；隔离用例不改变任何正在运行的网易云会话。
        js("window.backend.action('mode',JSON.stringify('local'))")
        wait(lambda: bridge.mode == "local")
        js("$('volumeButton').click()")
        wait(lambda: js("!$('mixerSlider').disabled"))
        js(
            "$('mixerSlider').value=37;$('mixerSlider').dispatchEvent(new Event('change'))"
        )
        wait(lambda: abs(bridge.audio.volume() - 0.37) < 0.001)
        wait(lambda: js("$('volume').value==='37'"))
        js(
            "$('playerVolumePanel').hidePopover();window.backend.action('mode',JSON.stringify('cloud'))"
        )
        wait(lambda: bridge.mode == "cloud" and len(bridge.lines) == 3)
        js("$('moreButton').click();document.querySelector('[data-pref=desktop]').click()")
        wait(lambda: not js("document.getAnimations().some(a=>a.playState==='running')"))
        view.grab().save(str(ROOT / "output/desktop-settings081.png"))
        js("$('toolsDialog').close()")
        # 从右键菜单确认功能存在，点击悬停工具实际调整字号。
        observed = []

        def inspect_menu():
            menu = QApplication.activePopupWidget()
            if isinstance(menu, QMenu):
                observed.extend(action.text() for action in menu.actions())
                menu.close()

        QTimer.singleShot(80, inspect_menu)
        desk.overlay.contextMenuEvent(
            QContextMenuEvent(
                QContextMenuEvent.Mouse,
                QPoint(50, 40),
                desk.overlay.mapToGlobal(QPoint(50, 40)),
            )
        )
        assert {"窗口置顶", "歌词底部阴影", "钉住并穿透鼠标", "隐藏桌面歌词", "更改已唱颜色…"} <= set(observed)
        # 默认居中，三次点击依次切换居左、居右、居中；桌面端与网页不各存一份。
        assert desk.opts["align"] == "center"
        for align in ["left", "right", "center"]:
            js("$('alignment').click()")
            wait(
                lambda: (
                    desk.opts["align"] == align
                    and js("document.body.dataset.align") == align
                )
            )
            assert (
                js(
                    "getComputedStyle(lyricRows[0].querySelector('.lyric-original')).textAlign"
                )
                == align
            )
            assert desk.overlay.labels[1].cache_key[-1] == align
            assert read_map(data / "desktop.json")["align"] == align
        size = desk.opts["size"]
        next(
            b
            for b in desk.overlay.bar.findChildren(QPushButton)
            if b.text() == "字号 ＋"
        ).click()
        assert desk.opts["size"] == size + 2
        desk.change("ink", "#ffe69a")
        desk.overlay.grab().save(str(ROOT / "output/desktop-060.png"))
        # 在同一点检查 Windows 实际命中的 HWND，不只检查 Qt 属性值。
        user32 = ctypes.windll.user32
        hit = user32.WindowFromPoint
        hit.argtypes = [wintypes.POINT]
        hit.restype = wintypes.HWND
        handle = int(desk.overlay.winId())
        rect = wintypes.RECT()
        user32.GetWindowRect(handle, ctypes.byref(rect))
        point = wintypes.POINT(
            (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
        )
        assert hit(point) == handle, "未锁定时未命中浮窗"
        pos = desk.overlay.pos()
        def native_topmost():
            return bool(user32.GetWindowLongW(wintypes.HWND(int(desk.overlay.winId())), -20) & 8)
        assert native_topmost()
        js("document.querySelector('[data-desk=topmost]').click();$('pinQuick').click()")
        wait(lambda: not desk.opts["topmost"] and desk.opts["pinned"])
        assert not native_topmost() and desk.overlay.pos()==pos and desk.overlay.hover_timer.isActive()
        # 用自己的普通窗口模拟歌词被盖住：此时悬停不应把解锁键抬到别的窗口上。
        over = desk.overlay.mapToGlobal(next(desk.overlay.ink_rects()).center().toPoint())
        cover = QPushButton("遮挡测试")
        cover.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        cover.setAttribute(Qt.WA_ShowWithoutActivating)
        cover.setGeometry(over.x()-45, over.y()-25, 90, 50)
        cover.show()
        app.processEvents()
        desk.overlay.poll_unlock(over, 1)
        desk.overlay.poll_unlock(over, 4.1)
        assert desk.overlay.hover_since is None and not desk.overlay.unlock.isVisible()
        cover.close()
        js("document.querySelector('[data-desk=topmost]').click()")
        wait(lambda: desk.opts["topmost"] and native_topmost())
        assert hit(point) != int(desk.overlay.winId()), "鼠标仍命中已钉住的窗口"
        # 用同一个时钟入口驱动悬停，不移动用户的真实鼠标。仍通过系统 HWND 命中验证穿透。
        w = desk.overlay
        w.hover_timer.stop()
        over = w.mapToGlobal(next(w.ink_rects()).center().toPoint())
        w.poll_unlock(over, 0)
        w.poll_unlock(over, 2.99)
        assert not w.unlock.isVisible()
        w.poll_unlock(w.mapToGlobal(QPoint(-2,-2)), 2.995)
        w.poll_unlock(over, 3)
        assert not w.unlock.isVisible()
        w.poll_unlock(over, 6.01)
        app.processEvents()
        assert w.unlock.isVisible()
        badge = int(w.unlock.winId())
        rect = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(badge), ctypes.byref(rect))
        assert hit(wintypes.POINT((rect.left+rect.right)//2,(rect.top+rect.bottom)//2)) == badge
        assert hit(wintypes.POINT(rect.left-5,(rect.top+rect.bottom)//2)) not in (badge,int(w.winId()))
        # 两个原生窗口分别取像素，按真实位置合成，不截取用户桌面。
        proof = w.grab()
        painter = QPainter(proof)
        painter.drawPixmap(w.mapFromGlobal(w.unlock.pos()), w.unlock.grab())
        painter.end()
        proof.save(str(ROOT / "output/desktop-unlock081.png"))
        QTest.mouseClick(w.unlock, Qt.LeftButton)
        wait(lambda: not desk.opts["pinned"] and js("!$('pinQuick').checked"))
        assert not w.unlock.isVisible() and not w.hover_timer.isActive()
        js("$('pinQuick').click()")
        wait(lambda: desk.opts["pinned"] and js("document.querySelector('#pref-desktop [data-desk=pinned]').checked"))
        window.close()
        app.processEvents()
        assert not window.isVisible() and desk.overlay.isVisible()
        desk.restore()
        assert window.isVisible()
        desk.menu.popup(window.mapToGlobal(QPoint(40, 60)))
        wait(lambda: desk.menu.isVisible())
        assert [a.text() for a in desk.menu.actions() if not a.isSeparator()] == [
            "打开咏伴",
            "隐藏桌面歌词",
            "解锁桌面歌词",
            "退出咏伴",
        ]
        desk.menu.grab().save(str(ROOT / "output/tray-060.png"))
        desk.menu.hide()
        desk.visibility_action.trigger()
        assert not w.unlock.isVisible() and not w.hover_timer.isActive()
        desk.refresh_tray()
        assert (
            desk.visibility_action.text() == "显示桌面歌词"
            and not desk.pin_action.isEnabled()
        )
        desk.visibility_action.trigger()
        # 预设与自定义亮暗色板必须各自保留，切换不能重建当前歌词行。
        assert js("Theme.snapshot().id==='studio' && Theme.snapshot().mode==='dark'")
        js(
            "$('moreButton').click();document.querySelector('[data-pref=theme]').click();window.savedRow=lyricRows[0]"
        )
        for pair in ["studio", "tide", "amber"]:
            js(
                f"$('themePreset').value='{pair}';$('themePreset').dispatchEvent(new Event('change'))"
            )
            for scheme in ["dark", "light"]:
                js(f"document.querySelector('[data-scheme-choice={scheme}]').click()")
                assert js(
                    f"document.documentElement.dataset.scheme==='{scheme}' && Theme.snapshot().id==='{pair}'"
                )
                if sys.getwindowsversion().build >= 22000:
                    # CAPTION_COLOR 是只写属性；直接取系统绘好的非客户区像素，不用 CSS 值代替验证。
                    expected = js(
                        "document.documentElement.style.getPropertyValue('--paper')"
                    )

                    def caption_matches():
                        frame, caption_mid = grab_frame(window)
                        return (
                            frame.pixelColor(frame.width() // 2, caption_mid).name()
                            == expected
                        )

                    wait(caption_matches)
        js(
            "$('theme-accent').value='#714740';$('theme-accent').dispatchEvent(new Event('input'))"
        )
        js(
            "document.querySelector('[data-scheme-choice=dark]').click();$('theme-accent').value='#f3bd83';$('theme-accent').dispatchEvent(new Event('input'))"
        )
        js("document.querySelector('[data-scheme-choice=light]').click()")
        assert js(
            "$('theme-accent').value==='#714740' && window.savedRow===lyricRows[0]"
        )
        # 等待短过渡结束再截图，避免把旧外观到新外观之间的过渡色留在文档里。
        wait(
            lambda: not js("document.getAnimations().some(a=>a.playState==='running')")
        )
        view.grab().save(str(ROOT / "output/theme-light.png"))
        if sys.getwindowsversion().build >= 22000:
            frame, _ = grab_frame(window)
            frame.save(str(ROOT / "output/theme-native-frame.png"))
        profile = json.loads(js("localStorage.getItem('utatomo-display')"))
        assert profile["theme"]["custom"]["dark"][2] == "#f3bd83"
        js("$('toolsDialog').close()")
        track = cloud_track({"id": "123", "title": "示例", "artist": "作者"})
        playlist = bridge.library.create_playlist("练唱")
        bridge.library.add([track], playlist)
        bridge.library.favorite(track["key"], True)
        bridge.library.played(track)
        backup = Path(folder) / "backup.zip"
        export_backup(backup, data, bridge.library.db, {**profile, "size": 42})
        other = Path(folder) / "restore"
        other.mkdir()
        stage_backup(backup, other)
        apply_pending(other)
        assert read_map(other / "restored-display.json")["theme"] == profile["theme"]
        assert read_map(other / "desktop.json")["shadow"] and read_map(other / "desktop.json")["topmost"]
        restored = LibraryStore(other)
        assert restored.db.execute("select count(*) from tracks").fetchone()[0] == 1
        assert (
            restored.db.execute("SELECT favorite,lastPlayed FROM tracks").fetchone()[0]
            == 1
        )
        assert (
            restored.db.execute("SELECT lastPlayed FROM tracks").fetchone()[0]
            is not None
        )
        assert (
            restored.db.execute(
                "SELECT trackKey FROM playlist_tracks WHERE playlistId=?", (playlist,)
            ).fetchone()[0]
            == track["key"]
        )
        restored.close()
        assert (
            read_map(other / "restored-display.json")["size"] == 42
            and read_map(other / "desktop.json")["pinned"]
        )
        assert (
            list(read_map(other / "practice.json")["segments"].values())[0]["roman"]
            == "so/ra"
        )
        assert next(iter(read_map(other / "practice.json")["imports"].values()))[0][
            "text"
        ].startswith("[00:00]青空")
        js("lyricRows[1].querySelector('.edit-line').click()")
        wait(lambda: js("$('segmentDialog').open"))
        assert js("$('segmentLine').value==='1'")
        js("$('segmentOriginal').value='君と歌う';$('segmentForm').requestSubmit()")
        wait(lambda: bridge.lines[1]["text"] == "君と歌う")
        bridge._select_version(bridge.selected_version)
        wait(
            lambda: (
                js("state.lines[1]?.text==='君と歌う'")
                and bridge.lines[1]["text"] == "君と歌う"
            )
        )
        js("lyricRows[1].querySelector('.edit-line').click()")
        wait(lambda: js("$('segmentDialog').open"))
        js("$('resetSentence').click();$('segmentForm').requestSubmit()")
        wait(lambda: bridge.lines[1]["text"] == "君と歩く")
        assert js("JSON.stringify(window.__errors)") == "[]"
        desk.overlay.hide()
        desk.tray.hide()
        print(
            "PASS: paste, inline kana, segments, playback, Win32 hit-test, tray, backup/restore",
            flush=True,
        )


if __name__ == "__main__":
    run()
    os._exit(0)
