"""真实 WebEngine 键盘事件回归，使用假后端，不控制网易云或改用户设置。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utatomo.app import LocalPage
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

app = QApplication([])
view = QWebEngineView()
profile = QWebEngineProfile(view)
page = LocalPage(profile, view)
view.setPage(page)
view.resize(960, 700)
view.show()
checks = []
jobs = []
# 按真实按下/松开顺序验收 Chromium 默认控件行为，不能只用合成 DOM 事件。
for name, element in [("词典开关", "dictionaryToggle"), ("跟随下拉框", "followMode"),
                      ("播放按钮", "play"), ("字号滑块", "quickFontSize")]:
    jobs.append((name + "焦点下空格仅切换播放", f"$('" + element + "').focus(); window.oldControl = JSON.stringify([document.activeElement.value, document.activeElement.checked]);",
                 Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier,
                 "actions.length === 1 && actions[0][0] === 'toggle' && oldControl === JSON.stringify([document.activeElement.value, document.activeElement.checked])"))
jobs += [
    ("Enter 仍可操作播放按钮", "$('play').focus();", Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier,
     "actions.length === 1 && actions[0][0] === 'toggle'"),
    ("Tab 仍可移动焦点", "$('followMode').focus();", Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier,
     "actions.length === 0 && document.activeElement !== $('followMode')"),
    ("下拉框方向键固定微调且不换选项", "$('followMode').focus(); window.oldValue = $('followMode').value;", Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier,
     "actions.length === 1 && actions[0][0] === 'seek' && $('followMode').value === oldValue"),
    ("下拉框字母键固定单句循环", "$('followMode').focus();", Qt.Key.Key_L, Qt.KeyboardModifier.NoModifier,
     "actions.length === 1 && actions[0][0] === 'loop'"),
    ("弹窗空格保留开关行为", "$('toolsDialog').showModal(); $('playOnLyricSeek').focus(); window.oldChecked = $('playOnLyricSeek').checked;", Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier,
     "actions.length === 0 && $('playOnLyricSeek').checked !== oldChecked"),
    ("输入框正常输入空格", "$('toolsDialog').close(); $('searchDialog').showModal(); $('searchInput').value = ''; $('searchInput').focus();", Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier,
     "actions.length === 0 && $('searchInput').value === ' '"),
    ("修饰键不误触播放", "$('searchDialog').close(); $('followMode').focus();", Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier,
     "actions.length === 0"),
    ("组合键可重复请求音效", "$('followMode').focus();", Qt.Key.Key_M, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
     "actions.length === 1 && actions[0][0] === 'chime'"),
    ("再次组合键仍请求音效", "$('followMode').focus();", Qt.Key.Key_M, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
     "actions.length === 1 && actions[0][0] === 'chime'"),
]


def step():
    if not jobs:
        page.runJavaScript("JSON.stringify(window.__errors)", finish)
        return
    name, setup, key, modifiers, assertion = jobs.pop(0)

    def press(_):
        QTest.keyClick(view.focusProxy(), key, modifiers)
        # 松开事件可能异步派发点击，等待一轮事件循环后核对所有副作用。
        QTimer.singleShot(100, lambda: page.runJavaScript(assertion, checked))

    def checked(passed):
        checks.append({"check": name, "passed": bool(passed)})
        step()

    page.runJavaScript("actions.length = 0; " + setup, press)


def finish(raw):
    result = {"checks": checks, "errors": json.loads(raw)}
    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output/shortcuts-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    app.exit(0 if all(c["passed"] for c in checks) and not result["errors"] else 1)


def loaded(ok):
    if not ok:
        app.exit(2)
        return
    page.runJavaScript("""
      window.actions = [];
      window.backend = {action: (name, raw) => actions.push([name, JSON.parse(raw)])};
      onEvent('mode', {mode:'local'});
      onEvent('lyrics', {lines:[{start:0,end:5000,text:'Sing along',words:[],timing:'line'}]});
      updatePlayback({position:1000,duration:5000,playing:false,canSeek:true});
    """, lambda _: step())


page.loadFinished.connect(loaded)
view.setUrl(QUrl.fromLocalFile(str(ROOT / "web/index.html")))
QTimer.singleShot(15000, lambda: app.exit(2))
raise SystemExit(app.exec())

