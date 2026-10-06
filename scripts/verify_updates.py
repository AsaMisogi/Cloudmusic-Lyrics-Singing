"""真实 WebChannel + 后台线程更新验收；使用临时数据、固定 Release 和假浏览器。"""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utatomo import app as runtime
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow


def main():
    output = ROOT / "output"
    output.mkdir(exist_ok=True)
    response = Mock(status_code=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.json.return_value = {"tag_name": "v0.4.0", "draft": False, "prerelease": False}
    with tempfile.TemporaryDirectory() as directory, \
            patch.object(runtime, "DATA", Path(directory)), \
            patch.object(runtime, "CloudMedia"), \
            patch("utatomo.updates.requests.get", return_value=response) as get, \
            patch.object(runtime.QDesktopServices, "openUrl", return_value=True) as browser:
        app = QApplication([])
        window = QMainWindow()
        view = QWebEngineView(window)
        window.setCentralWidget(view)
        profile = QWebEngineProfile(view)
        page = runtime.LocalPage(profile, view)
        view.setPage(page)
        bridge = runtime.Bridge(window)
        channel = QWebChannel(page)
        channel.registerObject("backend", bridge)
        page.setWebChannel(channel)
        window.resize(960, 700)
        window.show()
        checks = []

        def check(name, expression, next_step):
            def received(passed):
                checks.append({"check": name, "passed": bool(passed)})
                next_step()
            page.runJavaScript(expression, received)

        def manual_current():
            view.grab().save(str(output / "update-dialog.png"))
            response.json.return_value["tag_name"] = "v0.3.0"
            page.runJavaScript("$('laterUpdate').click(); $('toolsDialog').showModal(); $('checkUpdate').click();")
            QTimer.singleShot(300, lambda: check("手动检查经后台返回无需更新", "!$('checkUpdate').disabled && $('updateFeedback').textContent.includes('0.3.0') && !$('updateDialog').open", manual_new))

        def manual_new():
            view.grab().save(str(output / "update-settings.png"))
            response.json.return_value["tag_name"] = "v0.4.0"
            page.runJavaScript("$('checkUpdate').click();")
            QTimer.singleShot(300, lambda: check("手动新版本经 WebChannel 自动弹窗", "$('updateDialog').open && !$('toolsDialog').open", download))

        def download():
            page.runJavaScript("$('downloadUpdate').click();")
            QTimer.singleShot(100, verify_browser)

        def verify_browser():
            checks.append({"check": "下载仅打开后端固定仓库版本页", "passed": browser.call_count == 1 and browser.call_args.args[0].toString() == runtime.REPOSITORY_URL + "/releases/tag/v0.4.0"})
            response.status_code = 429
            page.runJavaScript("$('toolsDialog').showModal(); $('checkUpdate').click();")
            QTimer.singleShot(300, lambda: check("限流失败反馈可见且按钮恢复", "!$('checkUpdate').disabled && $('updateFeedback').textContent.includes('限制')", finish))

        def finish():
            checks.append({"check": "启动一次加三次手动请求无额外重复", "passed": get.call_count == 4})
            # 经真实语言线程和桥接产出罗马音，继续验证新显示偏好重载后的行为。
            bridge._work(bridge.language_pool, "annotated", lambda: bridge._enrich([
                {"start": 0, "end": 5000, "text": "明日へ光を追いかけて", "pronunciation": "a su e hi ka ri wo o i ka ke te", "translation": "向着明天追寻光芒", "timing": "line", "words": []},
                {"start": 5000, "end": 10000, "text": "コーヒーを飲んで sing along", "translation": "喝杯咖啡，一起唱", "timing": "line", "words": []},
            ], "roman-demo"))
            QTimer.singleShot(700, romanized)

        def romanized():
            page.runJavaScript("$('toolsDialog').close(); $('romajiToggle').click();")
            QTimer.singleShot(100, lambda: check("真实语言线程的特殊读音转为罗马音", "state.romaji && state.lines[0].tokens[0].reading==='あす' && state.lines[0].tokens[0].romaji==='asu' && lyricRows[0].querySelector('rt').textContent==='asu'", reload_preferences))

        def reload_preferences():
            view.grab().save(str(output / "romaji-display.png"))
            # 同一个离线 profile 重新载入，沿用 initialize 的歌词快照。
            page.loadFinished.disconnect()
            page.loadFinished.connect(lambda ok: QTimer.singleShot(400, after_reload) if ok else app.exit(2))
            view.reload()

        def after_reload():
            check("重载保留罗马音偏好且新歌词仍按偏好显示", "state.romaji && $('romajiToggle').checked && lyricRows[0].querySelector('rt').textContent==='asu'", disable_romaji)

        def disable_romaji():
            page.runJavaScript("$('romajiToggle').click();")
            QTimer.singleShot(100, lambda: check("关闭后真实歌词恢复假名且无额外更新请求", "!state.romaji && lyricRows[0].querySelector('rt').textContent==='あす'", final_report))

        def final_report():
            checks.append({"check": "界面重载不重复自动检查更新", "passed": get.call_count == 4})
            page.runJavaScript("JSON.stringify(window.__errors)", report)

        def report(raw):
            result = {"checks": checks, "errors": json.loads(raw)}
            (output / "updates-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
            app.exit(0 if all(c["passed"] for c in checks) and not result["errors"] else 1)

        def startup():
            check("启动检查完成但等待首次路径引导", "$('clientPathDialog').open && !$('updateDialog').open && pendingUpdate?.version==='0.4.0'", close_setup)

        def close_setup():
            page.runJavaScript("$('cancelClientPath').click();")
            QTimer.singleShot(100, lambda: check("引导结束后自动提示新版本", "$('updateDialog').open && $('updateDescription').textContent.includes('0.3.0')", manual_current))

        page.loadFinished.connect(lambda ok: QTimer.singleShot(700, startup) if ok else app.exit(2))
        view.setUrl(QUrl.fromLocalFile(str(ROOT / "web/index.html")))
        QTimer.singleShot(15000, lambda: app.exit(2))
        result = app.exec()
        bridge.close()
        return result


if __name__ == "__main__":
    raise SystemExit(main())
