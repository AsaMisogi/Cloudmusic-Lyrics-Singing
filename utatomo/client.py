"""本机网易云客户端通道：后台线程串行处理 CDP 请求，与声音下载无关。

仅连接固定回环端口和 orpheus 主页面，不访问浏览器或任意远程调试地址。
界面脚本不改写客户端文件、不替换已有事件监听；断开后客户端正常运行。
"""

import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
import websocket

LOG = logging.getLogger(__name__)
PORT = 9222
SCRIPT = Path(__file__).with_name("client_bridge.js").read_text(encoding="utf-8")


class ClientConnection:
    def __init__(self):
        self.ws = None
        self.sequence = 0
        self.retry_after = 0
        self.state = None
        self.http = requests.Session()
        self.http.trust_env = False  # 回环通信不经过系统代理。

    def evaluate(self, expression):
        self.sequence += 1
        self.ws.send(json.dumps({"id": self.sequence, "method": "Runtime.evaluate",
                                 "params": {"expression": expression, "returnByValue": True,
                                            "awaitPromise": True}}))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            message = json.loads(self.ws.recv())
            if message.get("id") != self.sequence:
                continue
            result = message.get("result", {})
            if message.get("error") or result.get("exceptionDetails"):
                raise ValueError("网易云客户端未接受操作，可能已切换歌曲或客户端接口已变化。")
            return result.get("result", {}).get("value")
        raise TimeoutError("网易云客户端响应超时。")

    def connect(self):
        response = self.http.get(f"http://127.0.0.1:{PORT}/json", timeout=.5,
                                 allow_redirects=False)
        response.raise_for_status()
        page = next((p for p in response.json()
                     if p.get("type") == "page" and
                     p.get("url", "").split("#")[0] == "orpheus://orpheus/pub/app.html"), None)
        if not page:
            raise ValueError("本机端口未提供网易云主页面。")
        address = page.get("webSocketDebuggerUrl", "")
        parsed = urlparse(address)
        if parsed.scheme != "ws" or parsed.hostname not in ("localhost", "127.0.0.1") or parsed.port != PORT:
            raise ValueError("拒绝连接非本机网易云通道。")
        self.ws = websocket.create_connection(address, timeout=2, suppress_origin=True,
                                              http_no_proxy=["localhost", "127.0.0.1"])
        self.evaluate(SCRIPT)

    def poll(self):
        if not self.ws and time.monotonic() < self.retry_after:
            return None
        try:
            if not self.ws:
                self.connect()
            state = self.evaluate("window.__utatomoClient ? window.__utatomoClient.snapshot() : null")
            if state is None:
                state = self.evaluate(SCRIPT)  # 页面刷新后重新安装小型适配器。
            if state:
                state["sample"] = time.monotonic()
            self.state = state
            return state
        except Exception as exc:
            if self.ws:
                LOG.info("客户端通道断开：%s", exc)
            self.close()
            self.retry_after = time.monotonic() + 3
            return None

    def command(self, name, value=0, identity=""):
        if not self.ws:
            raise ValueError("客户端连接已断开，请重新连接。")
        args = ",".join(json.dumps(v, ensure_ascii=False) for v in (name, value, identity))
        result = self.evaluate(f"window.__utatomoClient.command({args})")
        if result is not True:
            raise ValueError("网易云没有确认此播放指令。")

    def close(self):
        if self.ws:
            self.ws.close()
        self.ws = None
        self.state = None
