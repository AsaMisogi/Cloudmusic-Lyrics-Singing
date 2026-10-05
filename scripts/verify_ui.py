"""在真实 Qt WebEngine 中验收歌词跟随、字号、版本切换、拖动和帧率。

使用临时离线 profile 与假后端，不改用户偏好，不控制网易云播放。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from utatomo.app import LocalPage  # 同正式入口使用相同的 Chromium 刷新设置。
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

app = QApplication([])
view = QWebEngineView()
view.resize(960, 700)
profile = QWebEngineProfile(view)
page = LocalPage(profile, view)
view.setPage(page)
view.show()
output = ROOT / "output"
output.mkdir(exist_ok=True)

def start(ok):
    if not ok:
        app.exit(2)
        return
    page.runJavaScript((ROOT / "scripts/verify_ui.js").read_text(encoding="utf-8"))
    timer.start(100)

def poll():
    page.runJavaScript("JSON.stringify(window.__uiResult || null)", finish)

def finish(raw):
    if not raw or raw == "null":
        return
    timer.stop()
    result = json.loads(raw)
    result["screenHz"] = view.screen().refreshRate()
    (output / "ui-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    view.grab().save(str(output / "ui-compact.png"))
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    app.exit(0 if all(c["passed"] for c in result["checks"]) and not result["errors"] else 1)

timer = QTimer()
timer.timeout.connect(poll)
page.loadFinished.connect(start)
view.setUrl(QUrl.fromLocalFile(str(ROOT / "web/index.html")))
QTimer.singleShot(15000, lambda: app.exit(2))
raise SystemExit(app.exec())
