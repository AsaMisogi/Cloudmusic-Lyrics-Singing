"""用发行 ZIP 验收真实 WebChannel → 下载 → 助手切换 → 新版界面。只操作新建的隔离安装。"""
import ctypes
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utatomo.portable_updates import PortableUpdates, PROXY, FEED, verify_feed


def exercise(base, candidate, qa):
    from PySide6.QtCore import QUrl
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QMainWindow
    from utatomo import app as runtime
    root = qa / "Utatomo"
    runtime.DATA = root / "data"
    runtime.DATA.mkdir()
    (runtime.DATA / "desktop.json").write_text('{"tray":false}', encoding="utf8")
    (runtime.DATA / "overrides.json").write_text('{"qa":"保留注音"}', encoding="utf8")
    # 0.8.3 尚无助手，用候选的助手启动首次迁移；以后用已发行的旧版助手验收兼容性。
    helper = root / "_internal/update/Utatomo-Update.exe"
    if not helper.exists():
        helper = candidate / "Utatomo/_internal/update/Utatomo-Update.exe"
    raw = (candidate / "update.json").read_bytes()
    m = verify_feed(raw, helper)
    assert base.name == f"Utatomo-{m['baseVersion']}-windows-x64.zip"
    wrapper = json.loads(raw)
    import base64
    wrapper["payload"] = base64.b64encode(base64.b64decode(wrapper["payload"]) + b" ").decode()
    try:
        verify_feed(json.dumps(wrapper).encode(), helper)
    except ValueError:
        pass
    else:
        raise AssertionError("验签未拒绝被改动的清单")

    class Attachment(io.BufferedReader):
        def geturl(self):
            return self.url
    requested = []
    def open_asset(req, timeout):
        # 不给生产代码加可改写的下载地址。只在测试进程替换 HTTP 读取，抓取实际选中的 URL。
        url = req.full_url
        allowed = {PROXY + FEED: "update.json",
                   f"{PROXY}{runtime.REPOSITORY_URL}/releases/download/v{m['version']}/{m['patch']['name']}": m["patch"]["name"]}
        requested.append(url)
        f = Attachment(io.FileIO(candidate / allowed[url], "r"))
        f.url = url
        return f

    app = QApplication([])
    window = QMainWindow()
    view = QWebEngineView(window)
    profile = QWebEngineProfile(view)
    view.setPage(runtime.LocalPage(profile, view))
    window.setCentralWidget(view)
    with patch.object(runtime, "CloudMedia"), patch("utatomo.portable_updates.urlopen", side_effect=open_asset), \
            patch.object(runtime.QDesktopServices, "openUrl", return_value=True) as browser:
        bridge = runtime.Bridge(window)
        bridge.portable = updater = PortableUpdates(bridge, root, runtime.DATA, m["baseVersion"])
        updater.helper = helper
        bridge.client_settings.confirmed = bridge.update_started = True
        channel = QWebChannel(view.page())
        channel.registerObject("backend", bridge)
        view.page().setWebChannel(channel)
        window.resize(960, 700)
        view.setUrl(QUrl.fromLocalFile(str(ROOT / "web/index.html")))
        window.show()

        def wait(pred, limit=90):
            deadline = time.monotonic() + limit
            while time.monotonic() < deadline:
                app.processEvents()
                if pred():
                    return
                time.sleep(.01)
            raise AssertionError(f"等待超时：{updater.phase} / {updater.message}")
        def js(code):
            values = []
            view.page().runJavaScript(code, 0, values.append)
            wait(lambda: values, 5)
            return values[0]
        def capture(name):
            # WebEngine 合成帧晚于 DOM 回调。只抓本窗口，不抓取用户桌面。
            from PySide6.QtTest import QTest
            QTest.qWait(200)
            view.grab().save(str(qa / (name + ".png")))

        try:
            wait(lambda: bridge.ready)
            js("""$('moreButton').click();document.querySelector('[data-pref="client"]').click()""")
            assert js("$('updateSource').value==='auto' && !$('updateSourceRow').hidden")
            for source in ("github", "mirror", "auto"):
                js(f"$('updateSource').value='{source}';$('updateSource').dispatchEvent(new Event('change'))")
                wait(lambda: updater.source == source)
            assert json.loads(updater.pref.read_text())["source"] == "auto"
            js("$('releasePage').click();document.querySelector('#toolsDialog [data-update-baidu]').click()")
            wait(lambda: browser.call_count == 2)
            capture("settings")
            js("$('checkUpdate').click()")
            wait(lambda: updater.phase in ("available","error"))
            assert updater.phase == "available", updater.message
            wait(lambda: js("$('updateDialog').open"))
            assert js("$('downloadUpdate').textContent==='下载增量补丁'")
            js("$('updateRelease').click();document.querySelector('#updateDialog [data-update-baidu]').click()")
            wait(lambda: browser.call_count == 4)
            assert [call.args[0].toString() for call in browser.call_args_list] == [
                runtime.RELEASES_URL, "https://pan.baidu.com/s/1ZKFEDhp-ZP8Tc7GGMzRvMg?pwd=kzx8",
                runtime.REPOSITORY_URL + "/releases/tag/v" + m["version"], "https://pan.baidu.com/s/1ZKFEDhp-ZP8Tc7GGMzRvMg?pwd=kzx8"]
            capture("offer")
            js("$('downloadUpdate').click()")
            wait(lambda: updater.phase in ("ready","error","available"))
            assert updater.phase == "ready", updater.message
            wait(lambda: js("$('downloadUpdate').textContent==='重启并更新'"))
            capture("ready")
            assert len(requested) == 2 and requested[-1].endswith(m["patch"]["name"])
            js("$('downloadUpdate').click()")
            wait(lambda: updater.phase == "restarting")
        finally:
            bridge.close()
            window.close()


def run(base, candidate):
    qa = Path(tempfile.mkdtemp(prefix="update-qa-", dir=ROOT / "build"))
    print(f"QA: {qa}", flush=True)
    with zipfile.ZipFile(base) as z:
        z.extractall(qa)
    subprocess.run([sys.executable, __file__, str(base), str(candidate), str(qa)], check=True, timeout=150)
    root = qa / "Utatomo"
    job, = root.glob(".utatomo-update-*")
    deadline = time.monotonic() + 100
    while not (job / "started").exists():
        if (job / "update-error.txt").exists():
            raise AssertionError((job / "update-error.txt").read_text(encoding="utf-8-sig"))
        if time.monotonic() >= deadline:
            raise AssertionError("新版没有完成 WebChannel 握手")
        time.sleep(.25)
    assert (job / "started").read_text() == (job / "version").read_text()
    assert json.loads((root / "data/overrides.json").read_text(encoding="utf8")) == {"qa":"保留注音"}
    # 只关闭来自隔离路径的咏伴窗口；正常退出可验证单实例锁与资料的释放。
    import psutil
    processes = [p for p in psutil.process_iter(["exe"]) if p.info["exe"] and Path(p.info["exe"]) == root/"Utatomo.exe"]
    assert len(processes) == 1
    p = processes[0]
    from ctypes import wintypes
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def close(hwnd, _):
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == p.pid and ctypes.windll.user32.IsWindowVisible(hwnd):
            ctypes.windll.user32.PostMessageW(hwnd, 0x10, 0, 0)
        return True
    ctypes.windll.user32.EnumWindows(close, 0)
    assert p.wait(timeout=35) == 0
    print(f"已验证：增量下载、独立助手切换、新版 { (job/'started').read_text() } 界面启动、注音资料与正常退出。")


if __name__ == "__main__":
    args = [Path(a).resolve() for a in sys.argv[1:]]
    (exercise if len(args) == 3 else run)(*args)
