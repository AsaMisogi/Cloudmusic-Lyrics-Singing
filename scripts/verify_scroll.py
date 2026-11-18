"""从 Qt 的输入入口验收 WebEngine 滚动。--profile 在可见窗口采样并保存原始位移。

每次使用临时网页资料和内存歌词，不碰网易云、不移动系统指针。采样依据真正改变
scrollTop 的 scroll 事件；既不是空 rAF 次数，也不把它当成显示器实际呈现的帧数。
"""

import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utatomo import __version__
from utatomo.app import LocalPage, PracticeWebView
from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication


def delay(ms):
    """让 Qt 事件循环正常派发输入与合成，不用 sleep 或周期性 Python 轮询采样。"""
    loop, timer = QEventLoop(), QTimer()
    timer.setTimerType(Qt.PreciseTimer)
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(ms)
    loop.exec()


def verify(profile=False):
    app = QApplication([])
    view = PracticeWebView()
    view.setWindowTitle("咏伴 · 滚动验收")
    view.setAttribute(Qt.WA_ShowWithoutActivating)
    view.setAttribute(Qt.WA_DontShowOnScreen, not profile)
    view.resize(960, 700)
    page = LocalPage(QWebEngineProfile(view), view)
    view.setPage(page)

    def js(code):
        loop, result = QEventLoop(), []

        def received(value):
            result.append(value)
            loop.quit()

        page.runJavaScript(code, 0, received)
        loop.exec()
        return result[0]

    loaded = QEventLoop()
    page.loadFinished.connect(loaded.quit)
    view.setUrl(QUrl.fromLocalFile(str(ROOT / "web/index.html")))
    view.show()
    loaded.exec()
    hz = view.screen().refreshRate()

    js(
        "onEvent('displayInfo',"
        + json.dumps(
            {
                "refreshRate": hz,
                "unlimited": os.environ.get("UTATOMO_SYSTEM_VSYNC") != "1",
            }
        )
        + ")"
    )
    js("""onEvent('mode',{mode:'local'});onEvent('lyrics',{source:'离线滚动验收',
        lines:Array.from({length:180},(_,i)=>({text:'朝の光を追いかけて',translation:'追逐清晨的阳光',
        tokens:[{text:'朝',reading:'あさ'},{text:'の'},{text:'光',reading:'ひかり'},
        {text:'を'},{text:'追',reading:'お'},{text:'いかけて'}],start:i*4000,end:(i+1)*4000,words:[]}))});
        window.steps=[];window.wheels=[];
        lyricViewport.addEventListener('scroll',()=>steps.push([performance.timeOrigin+performance.now(),lyricViewport.scrollTop]),{passive:true});
        lyricViewport.addEventListener('wheel',e=>wheels.push(e.deltaY),{passive:true});""")
    target = view.focusProxy()
    left, top, right, h, rail = json.loads(
        js("""(()=>{
        const v=lyricViewport,r=v.getBoundingClientRect();
        return JSON.stringify([r.left,r.top,r.right,v.clientHeight,v.offsetWidth-v.clientWidth]);
    })()""")
    )
    inside = QPointF(left + 80, top + 80)

    def wheel(angle=0, pixel=0, phase=Qt.NoScrollPhase, point=inside):
        event = QWheelEvent(
            point,
            target.mapToGlobal(point),
            QPoint(0, pixel),
            QPoint(0, angle),
            Qt.NoButton,
            Qt.NoModifier,
            phase,
            False,
        )
        app.sendEvent(target, event)

    def mouse(kind, pos, changed, held):
        app.sendEvent(
            target,
            QMouseEvent(
                kind, pos, target.mapToGlobal(pos), changed, held, Qt.NoModifier
            ),
        )

    def offset():
        return js("lyricViewport.scrollTop")

    traces = {}
    notch = app.wheelScrollLines() * 100 / 3
    assert notch > 0, "请在启用了按行滚动的测试环境运行此验收。"
    for playing in [False, True]:
        js(
            "updatePlayback({position:0,duration:720000,canSeek:true,playing:"
            + str(playing).lower()
            + "})"
        )
        delay(500)
        js("lyricViewport.scrollTop=1800")
        delay(50)
        initial = offset()
        js("steps.length=wheels.length=0")
        wheel(-120)
        delay(400)
        assert abs(offset() - initial - notch) <= 1, (initial, offset(), notch)
        assert js(
            "state.resumeFollowAt===Infinity && new Set(steps.map(s=>s[1])).size>1"
        )
        wheel(120)
        delay(400)
        assert abs(offset() - initial) <= 1
        js("steps.length=wheels.length=0")
        inputs = []
        for i in range(18):
            inputs.append(time.time_ns() / 1e6)
            wheel(-120 if i < 12 else 120)
            delay(45)
        delay(320)
        rows, events = json.loads(js("JSON.stringify([steps,wheels])"))
        assert (
            abs(sum(events) - 6 * notch) < 1
            and rows[-1][1] < max(y for _, y in rows) - notch
        )
        reverse = next(
            t - inputs[12]
            for (t, y), (_, z) in zip(rows[1:], rows)
            if t >= inputs[12] and y < z
        )
        gaps = sorted(t - s for (t, _), (s, _) in zip(rows[1:], rows))
        summary = {
            "firstMs": round(rows[0][0] - inputs[0], 1),
            "reverseMs": round(reverse, 1),
            "medianGapMs": round(statistics.median(gaps), 1),
            "p95GapMs": round(gaps[math.ceil(0.95 * len(gaps)) - 1], 1),
        }
        label = "播放" if playing else "暂停"
        traces[label] = {"inputs": inputs, "positions": rows, "summary": summary}
        print(label, summary)

    # 微刻度的分数余量不能积成额外距离。完整的像素手势应走其上报值，而非按系统行数二次放大。
    initial = offset()
    for _ in range(24):
        wheel(-5)
        delay(3)
    delay(350)
    assert abs(offset() - initial - notch) <= 1
    initial = offset()
    wheel(phase=Qt.ScrollBegin)
    for _ in range(10):
        wheel(pixel=-5, phase=Qt.ScrollUpdate)
        delay(10)
    wheel(phase=Qt.ScrollEnd)
    delay(350)
    assert abs(offset() - initial - 50) <= 1

    # 在轨道中点拖滑块，排除不同主题的箭头、滑块最短长度造成的轨道误点。
    js("$('resumeAfterBrowse').click();$('followButton').click()")
    delay(650)
    js(
        "lyricViewport.scrollTop=(lyricViewport.scrollHeight-lyricViewport.clientHeight)/2"
    )
    delay(100)
    initial = offset()
    start = QPointF(right - rail / 2, top + h / 2)
    mouse(QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
    delay(30)
    js("steps.length=0")
    inputs = []
    for i in range(1, 21):
        inputs.append(time.time_ns() / 1e6)
        mouse(QEvent.MouseMove, start + QPointF(0, 3 * i), Qt.NoButton, Qt.LeftButton)
        delay(10)
    delay(80)
    held = offset()
    rows = json.loads(js("JSON.stringify(steps)"))
    assert held > initial + h and len(set(y for _, y in rows)) > 2
    traces["拖动"] = {"inputs": inputs, "positions": rows}
    release_pos = start + QPointF(0, 60)
    if profile:
        # scroll 事件也在页面主线程：它卡住时，光看 JS 序列分不出「没画」和「还没通知」。
        # 给测试页制造一次有截止时间的长任务，直接取 Qt 窗口像素，检查字和滑块都已移动。
        before = view.grab().toImage()
        js("""setTimeout(()=>{window.stallStart=performance.timeOrigin+performance.now();
            const until=performance.now()+420;while(performance.now()<until){}
            window.stallEnd=performance.timeOrigin+performance.now();},40)""")
        delay(75)
        sent = time.time_ns() / 1e6
        for i in range(1, 9):
            mouse(
                QEvent.MouseMove,
                release_pos + QPointF(0, 5 * i),
                Qt.NoButton,
                Qt.LeftButton,
            )
            delay(10)
        delay(40)
        during = view.grab().toImage()
        captured = time.time_ns() / 1e6
        delay(360)
        assert js("stallStart") <= sent < captured < js("stallEnd")
        dpr = before.devicePixelRatio()

        def thumb_center(image):
            # 隔离资料使用默认深色主题；轨道中只有亮色滑块，排除两端箭头。
            ys = [
                y / dpr
                for y in range(round((top + 40) * dpr), round((top + h - 40) * dpr))
                if image.pixelColor(round(start.x() * dpr), y).red() > 80
            ]
            return (min(ys) + max(ys)) / 2

        origin, current, settled = (
            thumb_center(im) for im in (before, during, view.grab().toImage())
        )
        moved = current - origin
        changed = sum(
            before.pixel(x, y) != during.pixel(x, y)
            for x in range(round((left + 30) * dpr), round((right - 40) * dpr), 9)
            for y in range(round((top + 10) * dpr), round((top + h - 10) * dpr), 9)
        )
        # 上一段仍在拖动，before 可能是迟一个输入采样的前缓冲。与同一终点
        # 松开前的稳定画面对照，而不是用上一帧的延迟给本段位移加减几个像素。
        assert (
            abs(current - settled) <= 1
            and abs(current - (release_pos.y() + 40)) <= 2
            and changed > 20
        ), (origin, current, settled, release_pos.y() + 40, changed)
        traces["主线程繁忙时的拖动"] = {
            "pointerDelta": 40,
            "thumbDelta": moved,
            "changedLyricSamples": changed,
        }
        release_pos += QPointF(0, 40)
        held = offset()
    # 手还按着，但四秒内不再移动；强制跨句以检测自动跟随是否抢位置。
    delay(4050)
    js("updatePlayback({position:24000,duration:720000,canSeek:true,playing:true})")
    delay(100)
    assert abs(offset() - held) <= 1 and js("state.scrollTarget===null"), (
        "按住滑块时被拉回当前句"
    )
    mouse(QEvent.MouseButtonRelease, release_pos, Qt.LeftButton, Qt.NoButton)
    delay(45)
    assert js(
        "Number.isFinite(state.resumeFollowAt) && state.resumeFollowAt>performance.now() && !pointerOnScrollbar"
    )
    js("$('resumeAfterBrowse').click()")

    # 同一个输入入口也必须按实际命中滚动弹窗，不能把指令固定发给歌词视口。
    js("$('moreButton').click();document.querySelector('[data-pref=desktop]').click()")
    delay(200)
    x, y, limit = json.loads(
        js("""(()=>{const v=document.querySelector('.pref-body'),r=v.getBoundingClientRect();
        return JSON.stringify([r.left+50,r.top+30,v.scrollHeight-v.clientHeight]);})()""")
    )
    assert limit > 0
    wheel(-120, point=QPointF(x, y))
    delay(360)
    assert (
        js("document.querySelector('.pref-body').scrollTop") > 0
        and abs(offset() - held) <= 1
    )
    assert js("window.__errors.length") == 0
    if profile:
        dest = ROOT / "output" / "scroll-profile.json"
        dest.parent.mkdir(exist_ok=True)
        dest.write_text(
            json.dumps(
                {
                    "version": __version__,
                    "screenHz": hz,
                    "dpr": view.devicePixelRatioF(),
                    "linesPerNotch": app.wheelScrollLines(),
                    "traces": traces,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf8",
        )
        print(dest)
    print(
        f"PASS: 每格 {notch:g} CSS px；播放、暂停、反向、微刻度、像素手势、按住滑块及弹窗滚动。"
    )


if __name__ == "__main__":
    verify("--profile" in sys.argv)
