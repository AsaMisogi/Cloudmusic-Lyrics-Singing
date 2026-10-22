"""经授权的真实曲库切歌验收：必须传 --switch-client，结束后恢复原曲与播放状态。

曲库、偏好及歌词使用临时数据；不重启客户端，不修改账号收藏/歌单。
SMTC 不提供时间轴时只能恢复曲目与暂停/播放状态，无法恢复原进度。
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utatomo import app as runtime
from utatomo.library import cloud_track
from utatomo.matching import normalize
from utatomo.client_launcher import play_cloud_song, detect_client
from PySide6.QtCore import QEvent, QTimer, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow


async def system_state(command=""):
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
    manager = await Manager.request_async()
    session = next((s for s in manager.get_sessions() if any(
        word in s.source_app_user_model_id.lower() for word in ("cloudmusic", "netease", "orpheus"))), None)
    if session is None:
        raise ValueError("请先打开网易云并选择一首歌。")
    if command == "pause":
        await session.try_pause_async()
    media = await session.try_get_media_properties_async()
    info = session.get_playback_info()
    timeline = session.get_timeline_properties()
    return {"title": media.title, "artist": media.artist, "playing": int(info.playback_status) == 4,
            "position": round(timeline.position.total_seconds()*1000), "canSeek": info.controls.is_playback_position_enabled}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--switch-client", action="store_true")
    parser.add_argument("--target-id", default="")
    args = parser.parse_args()
    if not args.switch_client:
        parser.error("会切换真实歌曲，请先取得用户授权，再加 --switch-client。")
    initial = asyncio.run(system_state())
    path = Path(os.environ.get("LOCALAPPDATA", "")) / "NetEase/CloudMusic/webdata/file/playingList"
    songs = []
    for entry in json.loads(path.read_text(encoding="utf-8"))["list"]:
        song = entry.get("track", {})
        songs.append({"id": str(song["id"]), "title": song["name"], "artist": " / ".join(a["name"] for a in song.get("artists", [])),
                      "album": song.get("album", {}).get("name", ""), "duration": song.get("duration", 0), "fromQueue": True})
    exact = [s for s in songs if normalize(s["title"]) == normalize(initial["title"]) and normalize(s["artist"]) == normalize(initial["artist"])]
    if len(exact) != 1:
        raise ValueError("无法从本地队列唯一确认原曲 ID，未执行切歌。")
    original = exact[0]
    target = next(s for s in songs if s["id"] != original["id"] and (not args.target_id or s["id"] == args.target_id))
    directory = str(detect_client().parent)
    output = ROOT / "output"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary, patch.object(runtime, "DATA", Path(temporary)):
        app = QApplication([])
        window = QMainWindow()
        window.resize(1080, 760)
        view = QWebEngineView(window)
        window.setCentralWidget(view)
        profile = QWebEngineProfile(view)
        page = runtime.LocalPage(profile, view)
        view.setPage(page)
        bridge = runtime.Bridge(window)
        bridge.update_started = True
        bridge.client_settings.save(directory)
        bridge.services.identify = lambda title, artist: [s for s in songs if normalize(s["title"]) == normalize(title) and normalize(s["artist"]) == normalize(artist)]
        bridge.services.cover = lambda song_id: ""
        bridge.services.lyric_options = lambda *unused: [{"id": "test", "label": "原创验收歌词", "text": "[00:00]Sing along with me.", "translation": "", "source": "原创验收歌词"}]
        bridge.library.add([cloud_track(original), cloud_track(target)])
        channel = QWebChannel(page)
        channel.registerObject("backend", bridge)
        page.setWebChannel(channel)
        window.show()
        result = None

        def start(ok):
            if not ok:
                app.exit(2)
                return
            variables = {"target": "cloud:"+target["id"], "original": "cloud:"+original["id"], "initial": initial}
            script = "window.cloudTest=" + json.dumps(variables) + ";\n" + (ROOT / "scripts/verify_library_cloud.js").read_text(encoding="utf-8")
            QTimer.singleShot(500, lambda: page.runJavaScript(script))

        def poll():
            page.runJavaScript("JSON.stringify(window.__cloudLibraryResult || null)", finish)

        def finish(raw):
            nonlocal result
            if result is not None or not raw or raw == "null":
                return
            result = json.loads(raw)
            timer.stop()
            result["initial"] = initial
            result["targetId"] = target["id"]
            result["positionRestored"] = bool(initial["canSeek"])
            view.grab().save(str(output / "library-cloud-ui.png"))
            app.exit(0 if all(c["passed"] for c in result["checks"]) and not result["errors"] else 1)

        page.loadFinished.connect(start)
        timer = QTimer()
        timer.timeout.connect(poll)
        timer.start(100)
        view.setUrl(QUrl.fromLocalFile(str(ROOT / "web/index.html")))
        QTimer.singleShot(35000, lambda: app.exit(2))
        status = app.exec()
        bridge.close()
        bridge.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        window.close()
        # 失败也必须收尾；不因 UI 断言失败把用户留在测试歌曲。
        current = asyncio.run(system_state())
        if current["title"] != initial["title"]:
            play_cloud_song(directory, original["id"])
            for unused in range(40):
                current = asyncio.run(system_state())
                if current["title"] == initial["title"]:
                    break
                import time
                time.sleep(.25)
        if not initial["playing"]:
            asyncio.run(system_state("pause"))
        result = result or {"checks": [], "errors": ["真实曲库切歌验收超时"]}
        result["restored"] = asyncio.run(system_state())
        result["checks"].append({"check": "验收后恢复原曲及原播放状态", "passed":
            result["restored"]["title"] == initial["title"] and result["restored"]["playing"] == initial["playing"]})
        (output / "library-cloud-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return status if all(c["passed"] for c in result["checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
