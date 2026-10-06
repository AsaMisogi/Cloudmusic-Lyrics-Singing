"""手动验收路径引导、取消重启与真实客户端重启连接。

仅在用户已授权控制网易云时运行，并显式传入 --restart-client。
使用临时数据目录和 WebEngine profile，不覆盖用户路径或显示设置。
结束后尽量恢复同一首歌曲的原位置与播放状态，不切换用户选择的曲目。
"""

import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if "--restart-client" not in sys.argv:
    raise SystemExit("此验收会重启网易云；得到用户授权后添加 --restart-client 运行。")

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow

import utatomo.app as desktop
from utatomo.client import ClientConnection
from utatomo.client_launcher import running_clients

client = ClientConnection()
initial = client.poll()
client.close()
original_pids = {p.pid for p in running_clients()}
temporary = tempfile.TemporaryDirectory()
desktop.DATA = Path(temporary.name)
application = QApplication([])
window = QMainWindow()
window.resize(960, 700)
view = QWebEngineView(window)
window.setCentralWidget(view)
profile = QWebEngineProfile(view)
page = desktop.LocalPage(profile, view)
view.setPage(page)
bridge = desktop.Bridge(window)
# 此验收只验证连接，歌词/封面网络请求由其他验收负责。
bridge._identify = lambda _: []
bridge.services.lyric_options = lambda *_: []
bridge.services.cover = lambda *_: ""
channel = QWebChannel(page)
channel.registerObject("backend", bridge)
page.setWebChannel(channel)
output = ROOT / "output"
output.mkdir(exist_ok=True)
checks = []
stage = 0
deadline = time.monotonic() + 75
evaluating = False
restarted = False


def check(name, passed):
    checks.append({"check": name, "passed": bool(passed)})
    if not passed:
        raise AssertionError(name)


def inspect(raw):
    global stage, evaluating, restarted
    evaluating = False
    try:
        state = json.loads(raw or "{}")
        if stage == 0 and bridge.ready and state.get("pathOpen"):
            check("首次启动自动预填有效目录", bool(state["path"]) and not bridge.client_settings.confirmed)
            view.grab().save(str(output / "client-path-setup.png"))
            page.runJavaScript("document.getElementById('saveClientPath').click()")
            stage = 1
        elif stage == 1 and bridge.client_settings.confirmed and not state.get("pathOpen"):
            saved = desktop.ClientSettings(desktop.DATA)
            check("真实桥接保存路径且重读一致", saved.confirmed and saved.directory == bridge.client_settings.directory)
            # 当前电脑已在直连模式；模拟普通启动快照，仅用于覆盖连接入口的重启分支。
            bridge.cloud_state = {"transport": "smtc"}
            page.runJavaScript("document.getElementById('connectCloud').click()")
            stage = 2
        elif stage == 2 and state.get("restartOpen"):
            check("运行中的客户端显示确认且尚未退出", {p.pid for p in running_clients()} == original_pids)
            view.grab().save(str(output / "client-restart-confirmation.png"))
            page.runJavaScript("document.getElementById('cancelClientRestart').click()")
            stage = 3
        elif stage == 3 and not state.get("restartOpen") and not bridge.client_busy:
            check("取消重启保留原网易云进程", {p.pid for p in running_clients()} == original_pids)
            bridge.cloud_state = {"transport": "smtc"}
            page.runJavaScript("document.getElementById('connectCloud').click()")
            stage = 4
        elif stage == 4 and state.get("restartOpen"):
            page.runJavaScript("document.getElementById('confirmClientRestart').click()")
            restarted = True
            stage = 5
        elif stage == 5 and not bridge.client_busy:
            check("确认后客户端进程已经重启", not original_pids.intersection(p.pid for p in running_clients()))
            check("重启后恢复真实客户端双向同步", bridge.cloud_state.get("transport") == "client")
            check("连接完成恢复按钮且无脚本错误", not state["disabled"] and not state["errors"])
            view.grab().save(str(output / "client-reconnected.png"))
            application.exit(0)
    except Exception as exc:
        checks.append({"check": str(exc), "passed": False})
        application.exit(1)


def poll():
    global evaluating
    if time.monotonic() > deadline:
        checks.append({"check": "客户端验收超时", "passed": False})
        application.exit(2)
    elif not evaluating:
        evaluating = True
        page.runJavaScript("JSON.stringify({pathOpen:document.getElementById('clientPathDialog').open,path:document.getElementById('clientPathInput').value,restartOpen:document.getElementById('clientRestartDialog').open,disabled:document.getElementById('connectCloud').disabled,errors:window.__errors||[]})", inspect)


timer = QTimer()
timer.setInterval(150)
timer.timeout.connect(poll)
page.loadFinished.connect(lambda ok: timer.start() if ok else application.exit(2))
view.setUrl(QUrl.fromLocalFile(str(ROOT / "web/index.html")))
window.show()
result = application.exec()
timer.stop()
bridge.close()
if restarted and initial:
    try:
        restored = client.poll()
        if restored and restored["songId"] == initial["songId"]:
            client.command("seek", initial["position"], initial["songId"])
            if restored["playing"] != initial["playing"]:
                client.command("toggle", identity=initial["songId"])
    except Exception as exc:
        print(f"原播放状态恢复未完成：{exc}")
client.close()
report = {"checks": checks, "restartPerformed": restarted, "configuration": "temporary"}
(output / "client-launch-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
temporary.cleanup()
raise SystemExit(result)
