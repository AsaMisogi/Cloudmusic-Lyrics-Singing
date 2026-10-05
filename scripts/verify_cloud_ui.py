"""用户授权后的端到端验收：工具滑块 → 网易云、网易云跳转 → 工具。

使用真实 Bridge 和 WebChannel；结束时恢复原曲的播放进度和播放状态。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from utatomo.app import Bridge, LocalPage
from utatomo.client import ClientConnection
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow

app = QApplication([])
window = QMainWindow()
window.resize(1360, 900)
view = QWebEngineView(window)
profile = QWebEngineProfile(view)
page = LocalPage(profile, view)
view.setPage(page)
bridge = Bridge(window)
channel = QWebChannel(page)
channel.registerObject("backend", bridge)
page.setWebChannel(channel)
window.setCentralWidget(view)
c = ClientConnection()
initial = c.poll()
if not initial:
    bridge.close()
    raise SystemExit("客户端未连接")
checks = []
finished = False

def check(name, value):
    checks.append({"check": name, "passed": bool(value)})

def seek_from_tool():
    check("正式后端连接客户端", bridge.cloud_state.get("transport") == "client")
    c.command("pause", identity=initial["songId"])
    page.runJavaScript("$('seek').value=20510; $('seek').dispatchEvent(new Event('input')); $('seek').dispatchEvent(new Event('change'));")
    QTimer.singleShot(900, seek_from_client)

def seek_from_client():
    check("工具拖动驱动网易云实际跳转", abs(c.poll()["position"] - 20510) < 700)
    # 模拟客户端侧的变化：通过它自身动作跳转，不调用工具的 seek。
    c.command("seek", 40510, initial["songId"])
    QTimer.singleShot(900, capture)

def capture():
    check("客户端跳转回传后端", abs(bridge.cloud_state["position"] - 40510) < 700)
    page.runJavaScript("JSON.stringify({position: state.position, canSeek: state.canSeek, errors: window.__errors, songOptions: $('songVersion').options.length})", report)

def report(raw):
    global finished
    frontend = json.loads(raw)
    check("客户端跳转回传界面", abs(frontend["position"] - 40510) < 700 and frontend["canSeek"])
    check("界面无脚本异常", not frontend["errors"])
    result = {"checks": checks, "frontend": frontend, "songId": initial["songId"]}
    (ROOT / "output/cloud-ui-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    view.grab().save(str(ROOT / "output/cloud-ui.png"))
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    finished = True
    app.exit(0 if all(item["passed"] for item in checks) else 1)

view.setUrl(QUrl.fromLocalFile(str(ROOT / "web/index.html")))
window.show()
QTimer.singleShot(4500, seek_from_tool)
QTimer.singleShot(15000, lambda: app.exit(2))
code = app.exec()
bridge.close()
try:
    current = c.poll()
    if current and current["songId"] == initial["songId"]:
        c.command("seek", initial["position"], initial["songId"])
        if current["playing"] != initial["playing"]:
            c.command("toggle", identity=initial["songId"])
finally:
    c.close()
raise SystemExit(code)
