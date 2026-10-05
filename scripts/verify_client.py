"""真实客户端验收：短暂播放并跳转，最后恢复原来的位置及播放状态。

仅在用户同意控制网易云后手动运行；测试曲目由用户在客户端选择。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utatomo.client import ClientConnection

c = ClientConnection()
initial = c.poll()
if not initial:
    raise SystemExit("请先启动本机连接模式的网易云并选择歌曲。")
checks = []
try:
    c.command("pause", identity=initial["songId"])
    time.sleep(.3)
    target = min(12510, initial["duration"] / 2)
    c.command("seek", target, initial["songId"])
    time.sleep(.6)
    seek = c.poll()
    checks.append({"check": "客户端实际进度跟随跳转", "passed": abs(seek["position"] - target) < 700, "position": seek["position"]})
    c.command("seekAndPlay", target, initial["songId"])
    time.sleep(1)
    playing = c.poll()
    checks.append({"check": "暂停时跳转后实际播放且进度前进", "passed": playing["playing"] and playing["position"] > seek["position"]})
    c.command("pause", identity=initial["songId"])
    time.sleep(.4)
    checks.append({"check": "客户端暂停", "passed": not c.poll()["playing"]})
finally:
    current = c.poll()
    if current and current["songId"] == initial["songId"]:
        c.command("seek", initial["position"], initial["songId"])
        if current["playing"] != initial["playing"]:
            c.command("toggle", identity=initial["songId"])
    c.close()
result = {"songId": initial["songId"], "title": initial["title"], "checks": checks}
Path("output/client-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if all(c["passed"] for c in checks) else 1)
