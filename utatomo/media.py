"""Windows GSMTC 适配器。所有 WinRT 操作都在一个 asyncio 线程中执行。

只连接网易云会话，避免误控制其他播放器。实际播放进度依靠播放器提供
的时间戳外推，暂停时停止外推；不把显示精度当作远端跳转精度承诺。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import logging
import threading
import time

from .client import ClientConnection

LOG = logging.getLogger(__name__)


class CloudMedia:
    def __init__(self, emit):
        self.emit = emit
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run, name="netease-media", daemon=True
        )
        self.session = None
        self.stopping = False
        self.last_identity = ""
        self.last_error = ""
        self.command_lock = None
        self.client = ClientConnection()
        # WebSocket 的发送 / 接收必须在同一工作线程串行执行，避免响应串线。
        self.client_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="cloud-client")
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.command_lock = asyncio.Lock()
        self.loop.run_until_complete(self._watch())
        self.loop.close()

    async def _watch(self):
        manager = None
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager,
            )

            manager = await Manager.request_async()
        except Exception as exc:
            self.emit(
                "cloud",
                {"connected": False, "message": f"Windows 媒体会话不可用：{exc}"},
            )
        while not self.stopping:
            try:
                direct = await self.loop.run_in_executor(self.client_pool, self.client.poll)
                if direct:
                    self.emit("cloud", direct)
                    await asyncio.sleep(.1)
                    continue
                sessions = list(manager.get_sessions()) if manager else []
                session = next(
                    (
                        s
                        for s in sessions
                        if any(
                            name in s.source_app_user_model_id.lower()
                            for name in ("cloudmusic", "netease", "orpheus")
                        )
                    ),
                    None,
                )
                self.session = session
                if session is None:
                    self.last_identity = ""
                    self.emit(
                        "cloud",
                        {
                            "connected": False,
                            "message": "未发现网易云媒体会话。请在网易云播放歌曲，并开启系统媒体控制（SMTC）。",
                        },
                    )
                else:
                    media = await session.try_get_media_properties_async()
                    timeline = session.get_timeline_properties()
                    info = session.get_playback_info()
                    playing = int(info.playback_status) == 4
                    position = timeline.position.total_seconds() * 1000
                    duration = timeline.end_time.total_seconds() * 1000
                    rate = info.playback_rate or 1.0
                    has_timeline = (
                        duration > 0 and timeline.last_updated_time.year > 2000
                    )
                    if playing and has_timeline:
                        elapsed = (
                            dt.datetime.now(dt.timezone.utc)
                            - timeline.last_updated_time
                        ).total_seconds()
                        if elapsed >= 0:
                            position += elapsed * 1000 * rate
                    position = (
                        max(0, min(position, duration))
                        if duration > 0
                        else max(0, position)
                    )
                    identity = f"{media.title}|{media.artist}|{media.album_title}"
                    if identity != self.last_identity:
                        LOG.info("网易云当前歌曲：%s — %s", media.title, media.artist)
                        self.last_identity = identity
                    controls = info.controls
                    self.emit(
                        "cloud",
                        {
                            "connected": True,
                            "title": media.title,
                            "artist": media.artist,
                            "album": media.album_title,
                            "identity": identity,
                            "position": round(position),
                            "duration": round(duration),
                            "playing": playing,
                            "canSeek": controls.is_playback_position_enabled,
                            "canPlay": controls.is_play_pause_toggle_enabled,
                            "canRate": controls.is_playback_rate_enabled,
                            "hasTimeline": has_timeline,
                            "rate": rate,
                            "sample": time.monotonic(),
                            "transport": "smtc",
                        },
                    )
                self.last_error = ""
            except Exception as exc:
                if str(exc) != self.last_error:
                    LOG.warning("网易云媒体会话：%s", exc)
                    self.last_error = str(exc)
                self.emit(
                    "cloud",
                    {
                        "connected": False,
                        "message": "网易云媒体会话暂时不可用，正在重新连接。",
                    },
                )
            await asyncio.sleep(0.25)

    def command(self, command: str, value: float = 0):
        if not self.loop.is_running():
            self.emit("error", {"message": "网易云媒体会话尚未连接。"})
            return
        future = asyncio.run_coroutine_threadsafe(
            self._command(command, value, (self.client.state or {}).get("songId", "")), self.loop
        )

        def finished(result):
            try:
                result.result()
            except (Exception, concurrent.futures.CancelledError) as exc:
                self.emit("error", {"message": f"网易云控制失败：{exc}"})

        future.add_done_callback(finished)

    async def _command(self, command: str, value: float, expected_id=""):
        async with self.command_lock:
            if self.client.state:
                await self.loop.run_in_executor(self.client_pool, self.client.command, command, value, expected_id)
                return
            if self.session is None:
                raise ValueError("请先在网易云播放歌曲。")
            if command == "toggle":
                success = await self.session.try_toggle_play_pause_async()
            elif command == "pause":
                success = await self.session.try_pause_async()
            elif command in ("seek", "seekAndPlay"):
                success = await self.session.try_change_playback_position_async(
                    int(value * 10000)
                )
                # 定位失败时不播放；同一锁内保持两个操作有序。
                if success and command == "seekAndPlay":
                    success = await self.session.try_play_async()
            elif command == "rate":
                success = await self.session.try_change_playback_rate_async(value)
            else:
                raise ValueError("未知播放指令")
            if not success:
                raise ValueError(
                    "当前网易云版本未接受该控制，请使用本地模式进行精细练唱。"
                )

    def close(self):
        self.stopping = True
        self.thread.join(timeout=3)
        self.client_pool.submit(self.client.close)
        self.client_pool.shutdown(wait=False, cancel_futures=False)
