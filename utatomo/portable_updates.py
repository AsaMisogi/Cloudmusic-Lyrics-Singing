"""Windows 便携版更新。网络与文件工作在后台，只有用户点「重启并更新」才退出播放器。"""
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from http.client import HTTPException
from pathlib import Path
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, Signal, QCoreApplication

from .profile import read_map, write_map
from .updates import REPOSITORY_URL, RELEASES_URL, version_tuple

PROXY = "https://gh-proxy.org/"
SOURCES = {"auto": (PROXY, ""), "mirror": (PROXY,), "github": ("",)}
FEED = RELEASES_URL + "/download/update.json"
PRODUCT = "utatomo/windows-x64/1"
CHUNK = 1024 * 1024


def fetch(url, source, receive, progress):
    """每条线路从头下载并独立校验。固定源不换线；只构造公开附件网址，无需令牌。"""
    for prefix in SOURCES[source]:
        label = "国内加速" if prefix else "GitHub"
        progress(f"正在连接{label}…")
        try:
            with urlopen(Request(prefix + url, headers={"User-Agent": "Utatomo-Updater/1",
                         "Cache-Control": "no-cache"}), timeout=15) as response:
                if not response.geturl().startswith("https://"):
                    raise ValueError("下载地址不是 HTTPS")
                return receive(response, label)
        except InterruptedError:
            raise
        except (HTTPException, OSError, ValueError, KeyError, TypeError) as exc:
            logging.info("更新线路 %s 未完成：%s", label, type(exc).__name__)
            last = exc
    raise ValueError(f"{label}连接或校验失败，请重试或更换下载源。") from last


def helper_call(helper, args, blob=None):
    return subprocess.run([str(helper), *map(str, args)], input=blob, capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW)


def verify_feed(raw, helper):
    """用当前安装自带的公钥验签。版本与附件名称必须属于本产品，不执行远端提供的 URL。"""
    if len(raw) > 4 * CHUNK:
        raise ValueError("清单过大")
    result = helper_call(helper, ["verify"], raw)
    if result.returncode:
        raise ValueError("发行签名不正确")
    m = json.loads(result.stdout)
    version_tuple(m["version"])
    version_tuple(m["baseVersion"])
    if m["product"] != PRODUCT:
        raise ValueError("不是咏伴的更新")
    for key, name in (("full", f"Utatomo-{m['version']}-windows-x64.zip"),
                      ("patch", f"Utatomo-{m['baseVersion']}-to-{m['version']}-patch.zip")):
        a = m[key]
        if a["name"] != name or not re.fullmatch("[0-9a-f]{64}", a["sha256"]) or not (type(a["size"]) is int and a["size"] > 0):
            raise ValueError("附件清单不完整")
    return m


def receive_asset(response, out, asset, label, progress, cancelled):
    """边收边校验，重试重新截断文件。磁盘错误留给调用方，不伪装成网络故障。"""
    h, done, percent = hashlib.sha256(), 0, -1
    try:
        stream = out.open("wb")
    except OSError as exc:
        raise RuntimeError("无法写入下载目录，请检查目录权限和可用空间。") from exc
    with stream:
        while block := response.read(CHUNK):
            if cancelled.is_set():
                raise InterruptedError()
            done += len(block)
            if done > asset["size"]:
                raise ValueError("附件大小异常")
            try:
                stream.write(block)
            except OSError as exc:
                raise RuntimeError("无法写入补丁，请检查磁盘可用空间。") from exc
            h.update(block)
            value = done * 100 // asset["size"]
            if value != percent:
                percent = value
                progress(f"{label} · 已下载 {value}%", value)
    if done != asset["size"] or h.hexdigest() != asset["sha256"]:
        raise ValueError("附件校验失败")


class PortableUpdates(QObject):
    # worker 只产出消息；界面状态与用户确认始终在 Qt 主线程串行处理。
    received = Signal(str, object)

    def __init__(self, bridge, root, data, version):
        super().__init__(bridge)
        self.bridge, self.root, self.version = bridge, root, version
        self.helper = root / "_internal/update/Utatomo-Update.exe"
        self.pref = data / "updates.json"
        try:
            self.source = read_map(self.pref).get("source", "auto")
        except (OSError, ValueError):
            # 下载偏好损坏不能阻止打开歌词和曲库；下次选源时重新保存。
            logging.warning("无法读取更新偏好，使用国内优先。")
            self.source = "auto"
        if not isinstance(self.source, str) or self.source not in SOURCES:
            self.source = "auto"
        self.phase, self.message, self.percent = "idle", "每次启动自动检查正式版本。", None
        self.raw = self.manifest = self.job = self.future = None
        self.kind = "patch"
        self.manual = False
        self.cancel = threading.Event()
        self.received.connect(self.receive)

    def report(self, prompt=False):
        m = self.manifest or {}
        self.bridge.send("portableUpdate", dict(phase=self.phase, source=self.source, message=self.message,
                         current=self.version, version=m.get("version"), kind=self.kind, percent=self.percent,
                         size=m[self.kind]["size"] if m else None, prompt=prompt, manual=self.manual))

    def set_source(self, source):
        if source not in SOURCES or self.phase in ("checking", "downloading", "ready", "restarting"):
            self.report()
            return
        write_map(self.pref, {"source": source})
        self.source, self.phase, self.message = source, "idle", "下载源已保存。"
        self.raw = self.manifest = None
        self.report()

    def run(self, fn):
        def work():
            try:
                key, value = fn()
            except Exception as exc:
                logging.info("便携更新未完成：%s", type(exc).__name__)
                key, value = "error", str(exc) or "更新未完成，请重试。"
            if not self.cancel.is_set():
                self.received.emit(key, value)
        self.future = self.bridge.update_pool.submit(work)

    def progress(self, message, percent=None):
        if not self.cancel.is_set():
            self.received.emit("progress", (message, percent))

    def check(self, manual=True):
        self.manual |= manual
        if self.phase in ("checking", "downloading", "ready", "restarting"):
            self.report(prompt=manual and self.phase == "ready")
            return
        self.phase, self.message, self.percent = "checking", "正在检查正式版本…", None
        self.report()
        def check():
            def read(response, label):
                raw = response.read(4 * CHUNK + 1)
                return raw, verify_feed(raw, self.helper), label
            return "manifest", fetch(FEED, self.source, read, self.progress)
        self.run(check)

    def receive(self, key, value):
        if self.cancel.is_set():
            return
        if key == "progress":
            self.message, self.percent = value
        elif key == "manifest":
            self.raw, self.manifest, label = value
            m = self.manifest
            self.bridge.update_url = REPOSITORY_URL + "/releases/tag/v" + m["version"]
            if version_tuple(m["version"]) > version_tuple(self.version):
                self.kind = "patch" if self.version == m["baseVersion"] else "full"
                self.phase = "available"
                self.message = "只下载有变化的文件。" if self.kind == "patch" else "没有适用于当前版本的增量补丁，可在软件内下载完整包。"
                self.report(prompt=True)
                self.manual = False
                return
            self.phase, self.message = "current", f"{label}未发现比 {self.version} 更新的正式版。"
        elif key == "ready":
            self.phase, self.message, self.percent = "ready", "新版已校验。重启会中断当前练唱。", None
        elif key == "base":
            self.kind, self.phase, self.percent = "full", "available", None
            self.message = "本机文件与补丁基线不匹配。可改用完整包，曲库和设置保留。"
        elif key == "error":
            self.phase, self.message, self.percent = "error", value, None
        self.report()
        if key != "progress":
            self.manual = False

    def download(self):
        if self.phase != "available":
            return
        self.phase, self.message = "downloading", "正在准备下载…"
        self.report()
        def prepare():
            job = Path(tempfile.mkdtemp(prefix=".utatomo-update-", dir=self.root))
            complete = False
            try:
                m, asset = self.manifest, self.manifest[self.kind]
                url = f"{REPOSITORY_URL}/releases/download/v{m['version']}/{asset['name']}"
                archive = job / "package.zip"
                fetch(url, self.source, lambda r, s: receive_asset(r, archive, asset, s, self.progress, self.cancel), self.progress)
                self.progress("正在校验并准备新版…")
                (job / "update.json").write_bytes(self.raw)
                result = helper_call(self.helper, ["prepare", job, self.kind])
                if result.returncode == 3:
                    return "base", None
                if result.returncode:
                    raise ValueError(result.stderr.decode("utf8", "replace") or "未能准备新版，请检查磁盘空间。")
                archive.unlink()
                shutil.copyfile(self.helper, job / "apply.exe")
                self.job = job
                complete = True
                return "ready", None
            finally:
                if not complete:
                    shutil.rmtree(job, ignore_errors=True)
        self.run(prepare)

    def restart(self):
        if self.phase != "ready" or self.job is None:
            return
        subprocess.Popen([str(self.job / "apply.exe"), "apply", str(os.getpid())], cwd=self.job,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        self.job, self.phase = None, "restarting"
        QCoreApplication.quit()

    def close(self):
        self.cancel.set()
        def cleanup(_=None):
            if self.job is not None:
                shutil.rmtree(self.job, ignore_errors=True)
        # 未交接的下载由工作线程结束后释放；不在 Qt 退出时等待网络或删除仍在写的文件。
        if self.future:
            self.future.add_done_callback(cleanup)
        else:
            cleanup()
