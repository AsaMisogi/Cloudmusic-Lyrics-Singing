"""0.4.0 真实桥接验收：本地切歌、历史、歌单、粤拼修正与偏好恢复。

使用临时数据和离线 WebEngine profile；QMediaPlayer 真正播放但静音。
网易云、文件选择框、在线元数据用固定替身，不影响用户的客户端或收藏。
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utatomo import app as runtime
from utatomo.library import LibraryStore, local_track, cloud_track
from PySide6.QtCore import QEvent, QTimer, QUrl, Qt
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow


def main():
    output = ROOT / "output"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as directory, \
            patch.object(runtime, "DATA", Path(directory) / "data"), \
            patch.object(runtime, "CloudMedia"), \
            patch.object(runtime.QFileDialog, "getOpenFileNames") as picker:
        root = Path(directory)
        first, second, imported = [root / name for name in ("粤语练唱.wav", "晨光练唱.wav", "新添加的音轨.wav")]
        for path in (first, second, imported):
            shutil.copy2(ROOT / "samples/practice.wav", path)
        first.with_suffix(".lrc").write_text("[00:00]我會唱歌\n[00:05]一起看天空\n[00:10]Hello 我愛音樂", encoding="utf-8")
        picker.return_value = ([str(imported)], "音频")
        app = QApplication([])
        window = QMainWindow()
        if "--headless" in sys.argv:
            window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        window.resize(1280, 820)
        view = QWebEngineView(window)
        window.setCentralWidget(view)
        profile = QWebEngineProfile(view)
        page = runtime.LocalPage(profile, view)
        view.setPage(page)
        bridge = runtime.Bridge(window)
        bridge.audio.setVolume(0)
        bridge.update_started = True
        bridge.client_settings.confirmed = True
        first_track, second_track = local_track(first), local_track(second)
        bridge.library.add([first_track, second_track, cloud_track({"songId": "123", "title": "云端示例", "artist": "测试"})])
        bridge.services.song_detail = lambda song_id: {"songId": song_id, "title": "新增网易云曲目", "artist": "离线测试", "duration": 40000}
        channel = QWebChannel(page)
        channel.registerObject("backend", bridge)
        page.setWebChannel(channel)
        window.show()
        finished = False
        reload_started = False

        def start(ok):
            if not ok:
                app.exit(2)
                return
            if reload_started:
                QTimer.singleShot(500, lambda: page.runJavaScript("""
                    (() => {
                      const checks=JSON.parse(sessionStorage.getItem('feature-checks') || '[]');
                      checks.push({check:'界面重载恢复本机字体偏好', passed:state.lyricFont==='Microsoft YaHei' && $('lyricFont').value==='Microsoft YaHei'});
                      checks.push({check:'界面重载恢复粤拼偏好与已修正歌词', passed:
                        state.cantonese && $('cantoneseToggle').checked &&
                        state.lines[0]?.cantoneseTokens?.[0].reading==='ngo5' &&
                        lyricRows[0]?.querySelector('rt')?.textContent==='ngo5'});
                      window.__featureResult={checks,errors:window.__errors};
                    })();
                """))
                return
            inputs = {"first": first_track["key"], "second": second_track["key"]}
            script = "window.featureInputs=" + json.dumps(inputs) + ";\n" + (ROOT / "scripts/verify_features.js").read_text(encoding="utf-8")
            QTimer.singleShot(400, lambda: page.runJavaScript(script))

        def poll():
            page.runJavaScript("JSON.stringify(window.__featureResult || null)", report)
            page.runJavaScript("window.__featureCapture || ''", capture)
            page.runJavaScript("!!window.__featureReadyToReload", reload_once)

        def reload_once(ready):
            nonlocal reload_started
            if ready and not reload_started:
                reload_started = True
                view.reload()

        def capture(name):
            if name in {"cantonese", "collection", "recent"}:
                view.grab().save(str(output / f"features-{name}.png"))

        def report(raw):
            nonlocal finished
            if finished or not raw or raw == "null":
                return
            finished = True
            timer.stop()
            result = json.loads(raw)
            result["checks"].append({"check": "真实本地播放器有播放过并保存两条历史", "passed":
                bridge.library.query({"view": "recent", "source": "local"})["total"] == 2})
            # 关闭连接再重开数据库，确认不依赖界面内存；原音频仍在。
            bridge.library.close()
            bridge.library = LibraryStore(runtime.DATA)
            playlists = bridge.library.query({})["playlists"]
            result["checks"].append({"check": "重开曲库保留收藏、歌单与历史且不删除音频", "passed": bool(
                bridge.library.query({"view": "favorites"})["total"] >= 4
                and playlists and playlists[0]["name"] == "每天一首 · 已改名"
                and first.is_file() and second.is_file())})
            (output / "features-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
            app.exit(0 if all(item["passed"] for item in result["checks"]) and not result["errors"] else 1)

        def timeout():
            if not finished:
                print("真实功能验收超时。", flush=True)
                app.exit(2)

        timer = QTimer()
        timer.timeout.connect(poll)
        timer.start(100)
        page.loadFinished.connect(start)
        view.setUrl(QUrl.fromLocalFile(str(ROOT / "web/index.html")))
        QTimer.singleShot(30000, timeout)
        result = app.exec()
        bridge.close()
        # QMediaPlayer 即使 stop 仍持有当前文件；销毁后才清理临时测试音轨。
        bridge.player.setSource(QUrl())
        bridge.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        window.close()
        return result


if __name__ == "__main__":
    raise SystemExit(main())
