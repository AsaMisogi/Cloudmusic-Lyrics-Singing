"""桌面窗口、播放控制和后台任务协调。

GUI 线程只处理窗口和 QMediaPlayer；词法分析在单独线程串行执行，
网络任务使用独立线程池。每次换歌增加 generation，旧请求返回时自动
丢弃，防止快速切歌时将上一首歌词绘制到当前歌曲上。
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import logging.handlers
import os
import re
import sys
import time
from pathlib import Path

# Qt WebEngine 的部分 Windows 版本使用固定 60 Hz begin-frame 限制。
# 在初始化 Chromium 前去除该上限；保留硬件加速与操作系统合成。
# 排障时可设 UTATOMO_SYSTEM_VSYNC=1 恢复引擎默认值。
if os.environ.get("UTATOMO_SYSTEM_VSYNC") != "1":
    chromium_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if "--disable-frame-rate-limit" not in chromium_flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (chromium_flags + " --disable-frame-rate-limit").strip()

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot, QLockFile
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineSettings,
    QWebEngineProfile,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow

from .language import Annotator
from .lyrics import align_translation, align_pronunciation, parse_lyrics, read_text
from .media import CloudMedia
from .services import Services
from .matching import rank_songs, normalize
from . import __version__
from .updates import check_update, REPOSITORY_URL, RELEASES_URL
from .client_launcher import ClientSettings, prepare_client, launch_client

ROOT = Path(__file__).resolve().parent.parent
WRITABLE_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else ROOT
DATA = WRITABLE_ROOT / "data"
LOG = logging.getLogger(__name__)


class LocalPage(QWebEnginePage):
    """桥接只给项目的本地界面使用；外部网页一律交给系统浏览器。"""

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if (
            url.isLocalFile()
            and Path(url.toLocalFile()).resolve() == ROOT / "web" / "index.html"
        ):
            return True
        if (
            url.scheme() == "https"
            and navigation_type
            == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
        ):
            QDesktopServices.openUrl(url)
        return False

    def javaScriptConsoleMessage(self, level, message, line, source):
        LOG.info("界面 %s:%s %s", Path(source).name, line, message)


class Bridge(QObject):
    event = Signal(str, str)
    incoming = Signal(str, object)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.mode = "cloud"
        self.generation = 0
        self.lines = []
        self.metadata = {
            "title": "等待音乐响起",
            "artist": "在网易云播放歌曲，或打开本地音频",
        }
        self.identity = ""
        self.cloud_state = {"connected": False}
        self.ready = False
        self.loop_region = None
        self.last_loop_seek = 0
        self.lyric_offset = 0
        self.audio_path = None
        self.song_id = None
        self.candidates = []
        self.versions = []
        self.selected_version = ""
        self.auto_candidates = []
        self.language_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="reading"
        )
        self.network_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="network"
        )
        self.launch_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="client-launch"
        )
        # 更新属于应用级任务，使用独立队列，不受切歌取消和歌词请求拥塞影响。
        self.update_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="update"
        )
        self.update_started = False
        self.update_busy = False
        self.update_manual = False
        self.update_url = ""
        self.closing = False
        self.annotator = None
        self.pending = []
        self.services = Services(DATA)
        self.client_settings = ClientSettings(DATA)
        self.client_busy = False
        self.client_confirmation = None
        self.client_deadline = 0
        self.client_timer = QTimer(self)
        self.client_timer.setInterval(500)
        self.client_timer.timeout.connect(self._check_client_connection)
        self.incoming.connect(self._receive)
        self.chime_player = None
        self.chime_audio = None
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player.setAudioOutput(self.audio)
        self.player.errorOccurred.connect(
            lambda error, message: self.send(
                "error", {"message": "音频播放失败：" + message}
            )
        )
        self.player.mediaStatusChanged.connect(self._media_status)
        self.cloud = CloudMedia(lambda kind, payload: self.incoming.emit(kind, payload))
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.last_state_time = 0

    def send(self, kind: str, data):
        if self.ready:
            self.event.emit(kind, json.dumps(data, ensure_ascii=False))

    def _work(self, pool, kind, function, generation=None, extra=None):
        """工作线程只产出数据；Qt 信号将处理重新送回主线程。"""
        future = pool.submit(function)
        # 客户端启动不属于歌曲请求；切歌不能取消尚在排队的启动或重启。
        if pool not in (self.launch_pool, self.update_pool):
            self.pending = [item for item in self.pending if not item.done()]
            self.pending.append(future)

        def completed(task):
            try:
                self.incoming.emit(
                    "result",
                    {
                        "kind": kind,
                        "data": task.result(),
                        "generation": generation,
                        "extra": extra,
                    },
                )
            except concurrent.futures.CancelledError:
                pass
            except Exception as exc:
                LOG.exception("%s 任务失败", kind)
                self.incoming.emit(
                    "result",
                    {
                        "kind": "failure",
                        "data": {"message": str(exc), "task": kind},
                        "generation": generation,
                        "extra": extra,
                    },
                )

        future.add_done_callback(completed)

    def _reading_scope(self):
        if self.song_id:
            return "netease:" + str(self.song_id)
        if self.mode == "local":
            return "local:" + str(self.audio_path or "")
        return "cloud:" + self.identity

    def _enrich(self, lines, scope=""):
        if self.annotator is None:
            self.annotator = Annotator(DATA)
        return self.annotator.enrich(lines, scope)

    @Slot()
    def initialize(self):
        self.ready = True
        self.send("mode", {"mode": self.mode})
        self.send("track", self.metadata)
        self.send("cloud", self.cloud_state)
        self._send_client_settings(setup=not self.client_settings.confirmed and "--smoke-test" not in sys.argv)
        self.send("clientStatus", {"busy": self.client_busy})
        self._send_versions()
        if self.lines:
            self.send("lyrics", {"lines": self.lines})
        LOG.info("界面已连接；数据目录：%s", DATA)
        self.send("appVersion", {"version": __version__})
        # WebChannel 已就绪再检查，保证结果可以送达；一个进程只自动检查一次。
        if not self.update_started and "--smoke-test" not in sys.argv:
            self.update_started = True
            self._check_update(manual=False)

    def _check_update(self, manual=True):
        """合并重复点击；手动加入启动检查时，仍显示这次检查的完整结果。"""
        if self.closing:
            return
        self.update_manual = self.update_manual or manual
        if self.update_busy:
            return
        self.update_busy = True
        self.send("updateStatus", {"busy": True})
        self._work(self.update_pool, "update", check_update)

    def _finish_update(self, data):
        if self.closing:
            return
        self.update_busy = False
        manual, self.update_manual = self.update_manual, False
        self.update_url = data.get("url", "") if data["status"] == "available" else ""
        self.send("updateStatus", {"busy": False})
        if data["status"] == "error":
            LOG.warning("检查更新：%s", data["message"])
        # 自动检查只在发现更新时打扰用户；手动检查始终给出成功或失败反馈。
        if manual or data["status"] == "available":
            self.send("updateResult", {**data, "manual": manual})

    @Slot(str, str)
    def action(self, name, raw):
        try:
            value = json.loads(raw or "null")
            self._action(name, value)
        except Exception as exc:
            LOG.exception("操作失败：%s", name)
            self.send("clientPathError" if name == "saveClientPath" else "error", {"message": str(exc)})

    def _action(self, name, value):
        if name == "mode":
            if value not in ("local", "cloud") or value == self.mode:
                return
            if self.mode == "local":
                self.player.pause()
            self.mode = value
            self._clear_track()
            self.identity = ""
            self.metadata = {
                "title": "等待网易云播放" if value == "cloud" else "打开一首喜欢的歌",
                "artist": "支持 MP3 · FLAC · WAV · M4A · OGG"
                if value == "local"
                else "自动识别当前歌曲与歌词",
            }
            self.send("track", self.metadata)
            self.send("mode", {"mode": value})
            if value == "local" and self.audio_path:
                self._open_audio(self.audio_path)
        elif name == "openAudio":
            path, _ = QFileDialog.getOpenFileName(
                self.window,
                "选择本地歌曲",
                str(ROOT),
                "音频 (*.mp3 *.flac *.wav *.m4a *.ogg *.opus *.aac *.wma);;所有文件 (*)",
            )
            if path:
                self._open_audio(Path(path))
        elif name in ("openLyrics", "openTranslation"):
            path, _ = QFileDialog.getOpenFileName(
                self.window,
                "选择中文译文" if name == "openTranslation" else "选择歌词",
                str(self.audio_path.parent if self.audio_path else ROOT),
                "歌词 (*.lrc *.yrc *.txt);;所有文件 (*)",
            )
            if path:
                text = read_text(Path(path))
                if name == "openTranslation":
                    if not self.lines:
                        raise ValueError("请先加载原文歌词。")
                    self.generation += 1
                    align_translation(self.lines, text)
                    for version in self.versions:
                        if version["id"] == self.selected_version:
                            version["translation"] = text
                    self.send(
                        "lyrics", {"lines": self.lines, "source": "导入的中文译文"}
                    )
                else:
                    key = "import:" + str(time.monotonic_ns())
                    self.versions.append({"id": key, "label": Path(path).name,
                                          "text": text, "translation": "", "source": Path(path).name})
                    self._select_version(key)
        elif name == "chime":
            self._play_chime()
        elif name == "toggle":
            if self.mode == "cloud":
                self.cloud.command("toggle")
            elif self.player.source().isEmpty():
                raise ValueError("请先打开本地音频。")
            elif self.player.isPlaying():
                self.player.pause()
            else:
                self.player.play()
        elif name in ("seek", "seekAndPlay"):
            position = max(0, int(value))
            if (
                self.loop_region
                and not self.loop_region[0] <= position < self.loop_region[1]
            ):
                self.loop_region = None
                self.send("loop", {"enabled": False})
            self._seek(position, play=name == "seekAndPlay")
        elif name == "rate":
            rate = float(value)
            if not 0.5 <= rate <= 1.5:
                raise ValueError("播放速度范围为 0.5–1.5 倍。")
            if self.mode == "cloud":
                self.cloud.command("rate", rate)
            else:
                self.player.setPlaybackRate(rate)
        elif name == "volume":
            self.audio.setVolume(max(0, min(1, float(value))))
        elif name == "loop":
            if value is None:
                self.loop_region = None
            else:
                start, end = int(value[0]), int(value[1])
                if start < 0 or end - start < 100:
                    raise ValueError("循环范围至少为 100 毫秒。")
                if self.mode == "cloud" and end - start < 800:
                    raise ValueError("客户端同步循环至少为 0.8 秒；更短循环请用本地音频。")
                if self.mode == "cloud" and not self.cloud_state.get("canSeek"):
                    raise ValueError("网易云没有开放跳转，请使用本地模式进行循环。")
                self.loop_region = (start, end)
                self._seek(start)
            self.send(
                "loop",
                {"enabled": self.loop_region is not None, "region": self.loop_region},
            )
        elif name == "search":
            query = str(value).strip()
            if not query:
                return
            match = re.search(r"(?:[?&]id=|^)(\d{1,20})(?:\D|$)", query)
            if match:
                self._fetch_lyrics(match[1])
            else:
                self.send("busy", {"message": "正在搜索歌曲…"})
                self._work(
                    self.network_pool,
                    "search",
                    lambda: self.services.search(query),
                    self.generation,
                )
        elif name == "selectSong":
            self.auto_candidates = []
            self._fetch_lyrics(str(value["id"]))
        elif name == "selectVersion":
            self._select_version(str(value))
        elif name == "practice":
            # 同步练唱直接使用客户端正在播放的音轨，与歌词候选 ID 无关。
            # 仅当客户端明确给出普通本地文件时，才可转入独立播放器。
            local = self.cloud_state.get("localAudio", "")
            if local and Path(local).is_file() and Path(local).suffix.lower() in (".mp3", ".flac", ".wav", ".m4a", ".ogg", ".aac"):
                lines, metadata = self.lines, dict(self.metadata)
                position = self.cloud_state.get("position", 0)
                self._open_audio(Path(local))
                # _open_audio 可能触发同名歌词注音，作废该任务，保留用户当前版本。
                self.generation += 1
                self.lines, self.metadata = lines, metadata
                self.player.setPosition(int(position))
                self.send("track", metadata)
                self.send("lyrics", {"lines": lines, "source": "客户端本地音频"})
            else:
                self.send("notice", {"message": "当前音频由网易云直接播放，可在下方播放、暂停、跳转和循环。独立变速练唱可打开本地音频。"})
        elif name == "connectCloud":
            self._launch_cloud()
        elif name == "confirmClientRestart":
            # 前端只能确认当前待处理请求，不能构造任意路径的重启操作。
            directory = self.client_confirmation
            if directory is None:
                return
            self.client_confirmation = None
            if value is not True:
                self._finish_client_connection()
                return
            self.send("busy", {"message": "正在关闭并重新启动网易云…"})
            self._work(self.launch_pool, "clientLaunch", lambda: launch_client(directory, restart=True))
        elif name == "saveClientPath":
            if self.client_busy:
                raise ValueError("客户端正在连接，请稍后修改路径。")
            if not isinstance(value, str):
                raise ValueError("请选择有效的网易云安装目录。")
            self.client_settings.save(value)
            self._send_client_settings(saved=True)
            self.send("notice", {"message": "网易云路径已保存，下次连接时使用。"})
        elif name == "chooseClientPath":
            if self.client_busy:
                return
            # 选择目录只修改输入框，点击保存后才更改持久配置。
            directory = QFileDialog.getExistingDirectory(
                self.window, "选择包含 cloudmusic.exe 的网易云音乐文件夹",
                self.client_settings.directory or str(WRITABLE_ROOT),
            )
            if directory:
                self.send("clientPathSelected", {"directory": directory})
        elif name == "dictionary":
            word, language = str(value["lemma"] or value["text"]), value["language"]
            self._work(
                self.network_pool,
                "dictionary",
                lambda: self.services.dictionary(word, language),
                extra=value,
            )
        elif name == "correct":
            scope = self._reading_scope()
            if value.get("scope") != scope or not any(
                t.get("lineKey") == value.get("lineKey") and t.get("tokenStart") == value.get("tokenStart")
                and t["text"] == value["text"] for line in self.lines for t in line.get("tokens", [])
            ):
                raise ValueError("歌词已切换，请重新选择需要修正的词。")
            self.generation += 1
            token, reading = str(value["text"]), str(value["reading"])
            snapshot = json.loads(json.dumps(self.lines))

            def correct():
                if self.annotator is None:
                    self.annotator = Annotator(DATA)
                self.annotator.correct(token, reading, scope, value["lineKey"], value["tokenStart"])
                return self.annotator.enrich(snapshot, scope)

            self._work(self.language_pool, "annotated", correct, self.generation)
        elif name == "translate":
            if not self.lines:
                raise ValueError("请先加载歌词。")
            self.generation += 1
            snapshot = json.loads(json.dumps(self.lines))
            self.send("busy", {"message": "正在补充中文机译；首次请求需要联网…"})

            def translate():
                missing = [
                    line
                    for line in snapshot
                    if line["text"] and not line.get("translation")
                ]
                for start in range(0, len(missing), 12):
                    chunk = missing[start : start + 12]
                    translated = self.services.translate(
                        "\n".join(line["text"] for line in chunk)
                    ).splitlines()
                    if len(translated) != len(chunk):
                        translated = [
                            self.services.translate(line["text"]) for line in chunk
                        ]
                    for line, translation in zip(chunk, translated):
                        line["translation"] = translation
                        line["machineTranslation"] = True
                return snapshot

            self._work(self.network_pool, "translated", translate, self.generation)
        elif name == "offset":
            self.lyric_offset = max(-10000, min(10000, int(value)))
        elif name == "demo":
            self._open_audio(ROOT / "samples" / "practice.wav")
        elif name == "author":
            QDesktopServices.openUrl(QUrl("https://space.bilibili.com/315312"))
        elif name == "github":
            self._open_project_url(REPOSITORY_URL)
        elif name == "checkUpdate":
            self._check_update()
        elif name == "openUpdate":
            # 不接受前端传来的 URL，只打开本次检查得到的项目 Release。
            self._open_project_url(self.update_url or RELEASES_URL)
        elif name == "releases":
            self._open_project_url(RELEASES_URL)
        elif name == "dictionaryWeb":
            from urllib.parse import quote

            QDesktopServices.openUrl(
                QUrl(
                    "https://www.youdao.com/result?word="
                    + quote(str(value))
                    + "&lang=ja"
                )
            )
        elif name == "retry":
            self.identity = ""
        else:
            raise ValueError("未知操作：" + name)

    def _clear_track(self):
        for future in self.pending:
            future.cancel()  # 取消尚未开始的旧歌曲任务；已在途请求由 generation 隔离。
        self.generation += 1
        self.lines = []
        self.loop_region = None
        self.lyric_offset = 0
        self.song_id = None
        self.candidates = []
        self.versions = []
        self.selected_version = ""
        self.auto_candidates = []
        self._send_versions()
        self.send("lyrics", {"lines": []})
        self.send("loop", {"enabled": False})
        self.send("reset", {})

    def _launch_cloud(self):
        """串行处理一次连接请求；运行中的客户端必须等用户确认后再重启。"""
        if self.client_busy:
            return
        if self.cloud_state.get("transport") == "client":
            self.send("notice", {"message": "已连接客户端，可直接使用下方播放控制。"})
            return
        if not self.client_settings.confirmed:
            self._send_client_settings(setup=True)
            return
        self.client_busy = True
        self.send("clientStatus", {"busy": True})
        self.send("busy", {"message": "正在检查网易云客户端…"})
        directory = self.client_settings.directory
        self._work(self.launch_pool, "clientPrepare", lambda: prepare_client(directory))

    def _send_client_settings(self, setup=False, saved=False):
        self.send("clientSettings", {"directory": self.client_settings.directory,
                                     "setup": setup, "saved": saved})

    def _confirm_client_restart(self, directory):
        self.client_confirmation = directory
        self.send("clientRestartRequired", {"directory": directory})

    def _finish_client_connection(self):
        self.client_timer.stop()
        self.client_busy = False
        self.client_confirmation = None
        self.client_deadline = 0
        self.send("clientStatus", {"busy": False})

    def _check_client_connection(self):
        # 接收到真实播放器快照才宣告成功；启动进程成功不等于已经双向同步。
        if self.cloud_state.get("transport") == "client":
            self._finish_client_connection()
            self.send("notice", {"message": "已连接网易云客户端，可以双向同步播放进度。"})
        elif time.monotonic() >= self.client_deadline:
            self._finish_client_connection()
            self.send("error", {"message": "网易云已启动，但尚未收到直连播放信息。请在网易云播放一首歌；若仍无法同步，请检查路径、客户端版本或 9222 端口是否被占用。工具会继续自动尝试连接。"})

    def _open_audio(self, path: Path):
        if not path.is_file():
            raise ValueError("音频文件不存在。")
        if self.mode == "cloud" and self.cloud_state.get("playing"):
            # 避免两个播放器同时发声；只在用户实际打开音频时暂停网易云。
            self.cloud.command("pause")
        self.mode = "local"
        self._clear_track()
        self.audio_path = path
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.setPlaybackRate(1.0)
        self.metadata = {
            "title": "晴れた日のうた · 功能示例"
            if path.name == "practice.wav"
            else path.stem,
            "artist": "原创提示音轨 · 用于体验跳转与循环"
            if path.name == "practice.wav"
            else "本地音频 · " + path.suffix.upper().lstrip("."),
        }
        self.send("mode", {"mode": "local"})
        self.send("track", self.metadata)
        lyric_files = [path.with_suffix(ext) for ext in (".yrc", ".lrc", ".txt")
                       if path.with_suffix(ext).is_file()]
        if lyric_files:
            translation = next(
                (
                    path.with_name(path.stem + ext)
                    for ext in (".zh.lrc", ".trans.lrc")
                    if path.with_name(path.stem + ext).is_file()
                ),
                None,
            )
            translated = read_text(translation) if translation else ""
            self.versions = [{"id": str(lyric), "label": lyric.name,
                              "source": lyric.name, "text": read_text(lyric), "translation": translated}
                             for lyric in lyric_files]
            self._select_version(self.versions[0]["id"])
        LOG.info("加载本地歌曲：%s", path)

    def _load_text(self, text, translated="", source="", pronunciation="", references=None, issues=None):
        lines = parse_lyrics(text)
        if not lines:
            raise ValueError("歌词文件中没有可用文本。")
        if len(lines) > 3000:
            raise ValueError("歌词超过 3000 行，请缩小文件。")
        if translated:
            align_translation(lines, translated)
        if pronunciation:
            align_pronunciation(lines, pronunciation)
        for line in lines:
            line["readingReferences"] = [item for item in (references or [])
                                         if normalize(item["text"]) == normalize(line["text"])]
        scope = self._reading_scope()
        self.send("busy", {"message": "正在生成假名与英语音标…"})
        self._work(
            self.language_pool,
            "annotated",
            lambda: self._enrich(lines, scope),
            self.generation,
            {"source": source, "timingIssues": issues or []},
        )

    def _fetch_lyrics(self, song_id, automatic=False):
        self.generation += 1
        self.song_id = song_id
        self.versions = []
        self.selected_version = ""
        self._send_versions()
        self.send("busy", {"message": "正在读取网易云歌词…"})
        candidates = [dict(song) for song in self.candidates]
        selected = next((song for song in candidates if str(song["id"]) == str(song_id)),
                        dict(self.metadata) if str(self.metadata.get("songId")) == str(song_id) else {})
        self._work(
            self.network_pool,
            "downloaded",
            lambda: self.services.lyric_options(song_id, candidates, selected),
            self.generation,
            {"source": "网易云 · " + song_id, "automatic": automatic},
        )

    def _send_versions(self):
        self.send("versions", {"songs": self.candidates, "songId": self.song_id,
                              "versions": [{"id": v["id"], "label": v["label"] + (" · 时间疑似异常" if v.get("timingIssues") else "")} for v in self.versions],
                              "selected": self.selected_version})

    def _select_version(self, version):
        item = next((v for v in self.versions if v["id"] == version), None)
        if item is None:
            raise ValueError("这份歌词版本已不可用，请重新选择。")
        # 切换原文后旧的翻译、注音、循环范围均不应覆盖新版本。
        self.generation += 1
        self.loop_region = None
        self.send("loop", {"enabled": False})
        self.selected_version = version
        self._send_versions()
        self._load_text(item["text"], item["translation"],
                        item.get("source", f"网易云 · {self.song_id} · {item['label']}"),
                        item.get("pronunciation", ""), item.get("readingReferences"), item.get("timingIssues"))

    @Slot(str, object)
    def _receive(self, kind, payload):
        if kind == "cloud":
            self.cloud_state = payload
            if self.mode == "cloud":
                self.send("cloud", payload)
                if payload.get("connected"):
                    if payload["identity"] != self.identity and payload.get("title"):
                        self.identity = payload["identity"]
                        self._clear_track()
                        self.metadata = {
                            "title": payload["title"],
                            "artist": payload["artist"],
                            "album": payload.get("album", ""),
                            "duration": payload.get("duration", 0),
                            "songId": payload.get("songId"),
                        }
                        self.send("track", self.metadata)
                        if payload.get("songId"):
                            # 封面按真实播放身份隔离，不受歌词版本 generation 变化影响。
                            self._work(self.network_pool, "cover",
                                       lambda song_id=str(payload["songId"]): self.services.cover(song_id),
                                       extra={"identity": self.identity})
                        self._work(
                            self.network_pool,
                            "autoSearch",
                            lambda meta=dict(self.metadata): self._identify(meta),
                            self.generation,
                            dict(self.metadata),
                        )
                    if payload.get("playing"):
                        self._check_loop(payload["position"])
        elif kind == "error":
            self.loop_region = None
            self.send("loop", {"enabled": False})
            self.send(kind, payload)
        elif kind == "result":
            if (
                payload["generation"] is not None
                and payload["generation"] != self.generation
            ):
                return
            task, data, extra = payload["kind"], payload["data"], payload["extra"] or {}
            if task == "update":
                self._finish_update(data)
            elif task == "clientPrepare":
                directory = str(data["exe"].parent)
                if data["running"]:
                    self._confirm_client_restart(directory)
                else:
                    self.send("busy", {"message": "正在启动网易云客户端…"})
                    self._work(self.launch_pool, "clientLaunch", lambda: launch_client(directory))
            elif task == "clientLaunch":
                if data["confirmation"]:
                    self._confirm_client_restart(data["directory"])
                else:
                    self.client_deadline = time.monotonic() + 30
                    self.client_timer.start()
                    self.send("busy", {"message": "网易云已启动，正在等待直连…请在客户端播放一首歌。"})
            elif task == "cover":
                if self.mode == "cloud" and extra.get("identity") == self.identity:
                    self.metadata["cover"] = data
                    self.send("cover", {"cover": data})
            elif task == "failure":
                if data.get("task") == "update":
                    self._finish_update({"status": "error", "message": "检查更新未完成，请稍后重试。"})
                    return
                if data.get("task") in ("clientPrepare", "clientLaunch"):
                    self._finish_client_connection()
                if data.get("task") == "downloaded" and extra.get("automatic") and self.auto_candidates:
                    self._fetch_lyrics(str(self.auto_candidates.pop(0)["id"]), automatic=True)
                    return
                if data.get("task") == "dictionary":
                    self.send(
                        "dictionary",
                        {
                            "token": extra,
                            "definitions": [data["message"]],
                            "source": "查询未完成",
                        },
                    )
                else:
                    self.send("error", data)
            elif task in ("annotated", "translated"):
                self.lines = data
                self.send(
                    "lyrics",
                    {
                        "lines": data,
                        "source": extra.get(
                            "source", "中文机译" if task == "translated" else ""
                        ),
                        "timingIssues": extra.get("timingIssues", []),
                    },
                )
                self.send("notice", {"message": f"已加载 {len(data)} 行歌词"})
            elif task == "downloaded":
                self.versions = data
                if self.versions:
                    self._select_version(self.versions[0]["id"])
                else:
                    self.send("error", {"message": "这份歌词没有可用文本，请切换其他歌曲版本。"})
            elif task == "autoSearch":
                if extra.get("songId"):
                    # 客户端当前 ID 比搜索评分更可靠，歌词切换不能改变真实播放身份。
                    direct = {"id": extra["songId"], "title": extra["title"], "artist": extra["artist"],
                              "album": extra.get("album", ""), "duration": extra.get("duration", 0), "fromQueue": True}
                    data = [direct] + data
                self.candidates = rank_songs(data, extra["title"], extra["artist"],
                                             extra.get("album", ""), extra.get("duration", 0))
                if extra.get("songId"):
                    self.candidates.sort(key=lambda s: str(s["id"]) != str(extra["songId"]))
                self._send_versions()
                if self.candidates:
                    if not extra.get("songId"):
                        # Windows 媒体会话没有 ID 时，采用自动匹配的当前歌曲；手动切歌词不换封面。
                        self._work(self.network_pool, "cover",
                                   lambda song_id=str(self.candidates[0]["id"]): self.services.cover(song_id),
                                   extra={"identity": self.identity})
                    self.auto_candidates = self.candidates[1:3]
                    self._fetch_lyrics(str(self.candidates[0]["id"]), automatic=True)
                else:
                    self.send("notice", {"message": "没有匹配到歌词，可搜索歌曲或导入歌词。"})
            elif task == "search":
                self.candidates = data
                self._send_versions()
                self.send("search", {"songs": data, "automatic": False})
            elif task == "dictionary":
                self.send("dictionary", {**data, "token": extra})

    def _seek(self, position, play=False):
        """歌词点击可请求跳转并播放；微调、循环和进度拖动保持原播放状态。"""
        LOG.info("%s 跳转 %.3f 秒", self.mode, position / 1000)
        if self.mode == "cloud":
            if not self.cloud_state.get("canSeek"):
                raise ValueError("网易云当前未开放进度跳转。可在本地模式使用精细跳转。")
            self.cloud.command(
                "seekAndPlay" if play else "seek", min(position, self.cloud_state.get("duration") or position)
            )
        else:
            if not self.player.isSeekable():
                raise ValueError("音频尚未就绪，或该文件不支持跳转。")
            self.player.setPosition(min(position, self.player.duration()))
            if play:
                self.player.play()

    def _identify(self, metadata):
        try:
            return self.services.identify(metadata["title"], metadata["artist"])
        except Exception:
            # 客户端 ID 已知时无需依赖搜索服务是否在线，仍可读取缓存歌词。
            if metadata.get("songId"):
                return []
            raise

    def _check_loop(self, position):
        cooldown = 0.02 if self.mode == "local" else 0.65
        if (
            self.loop_region
            and position >= self.loop_region[1]
            and time.monotonic() - self.last_loop_seek > cooldown
        ):
            self.last_loop_seek = time.monotonic()
            self._seek(self.loop_region[0])

    def _media_status(self, status):
        if (
            status == QMediaPlayer.MediaStatus.EndOfMedia
            and self.loop_region
            and self.mode == "local"
        ):
            self.player.setPosition(self.loop_region[0])
            self.player.play()

    def _tick(self):
        if self.mode == "local":
            if self.player.isPlaying():
                self._check_loop(self.player.position())
            if time.monotonic() - self.last_state_time > 0.08:
                self.last_state_time = time.monotonic()
                self.send(
                    "playback",
                    {
                        "position": self.player.position(),
                        "duration": self.player.duration(),
                        "playing": self.player.isPlaying(),
                        "rate": self.player.playbackRate(),
                        "canSeek": self.player.isSeekable(),
                        "canRate": True,
                    },
                )

    def _play_chime(self):
        """按需创建独立音效播放器，不接入歌曲进度、模式、循环或播放状态。

        音效使用随包资源路径，源码和 PyInstaller 均无需依赖导出目录。
        每次先停止再播放，从头重播且最多一个实例；退出时显式停止。
        """
        if self.chime_player is None:
            self.chime_audio = QAudioOutput(self)
            self.chime_audio.setVolume(0.8)
            self.chime_player = QMediaPlayer(self)
            self.chime_player.setAudioOutput(self.chime_audio)
            self.chime_player.errorOccurred.connect(
                lambda error, message: self.send("error", {"message": "音效播放失败：" + message})
            )
            self.chime_player.setSource(QUrl.fromLocalFile(str(ROOT / "assets" / "chime.wav")))
        self.chime_player.stop()
        self.chime_player.play()

    def _open_project_url(self, url):
        """系统浏览器启动失败时保留可理解的反馈，不将网页载入歌词窗口。"""
        if not QDesktopServices.openUrl(QUrl(url)):
            self.send("error", {"message": "无法打开系统浏览器，请手动访问：" + url})

    def close(self):
        self.closing = True
        self.timer.stop()
        self.client_timer.stop()
        self.player.stop()
        if self.chime_player is not None:
            self.chime_player.stop()
        self.cloud.close()
        self.language_pool.shutdown(wait=False, cancel_futures=True)
        self.network_pool.shutdown(wait=False, cancel_futures=True)
        self.update_pool.shutdown(wait=False, cancel_futures=True)
        # 已确认重启必须完成「关闭 → 启动」，不能因主程序退出只执行前半步。
        self.launch_pool.shutdown(wait=True, cancel_futures=True)


def main():
    DATA.mkdir(exist_ok=True)
    (DATA / "logs").mkdir(exist_ok=True)
    log_file = logging.handlers.RotatingFileHandler(
        DATA / "logs" / "utatomo.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), log_file],
    )
    LOG.info("咏伴 Utatomo %s · 作者 @朝禊ASOGI", __version__)
    if sys.platform == "win32":
        # 独立的任务栏身份配合窗口图标，源码启动也不会使用 Python 默认图标。
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ASOGI.Utatomo")
    app = QApplication(sys.argv)
    app.setApplicationName("Utatomo")
    app.setOrganizationName("ASOGI")
    app.setWindowIcon(QIcon(str(ROOT / "assets" / "icon.ico")))
    lock = QLockFile(str(DATA / "instance.lock"))
    if not lock.tryLock(100):
        LOG.error("咏伴已经运行，请切换到现有窗口。")
        return 1
    window = QMainWindow()
    window.setWindowTitle("咏伴 · Utatomo — 歌词跟唱助手")
    window.resize(1360, 900)
    window.setMinimumSize(960, 700)
    view = QWebEngineView(window)
    # 验收使用临时 profile，避免示例中的词典开关、字号等覆盖用户偏好。
    if "--smoke-test" in sys.argv:
        profile = QWebEngineProfile(view)
    else:
        profile = QWebEngineProfile("utatomo", view)
        profile.setPersistentStoragePath(str(DATA / "webview"))
        profile.setCachePath(str(WRITABLE_ROOT / ".cache" / "webview"))
    page = LocalPage(profile, view)
    view.setPage(page)
    page.settings().setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
    )
    channel = QWebChannel(page)
    bridge = Bridge(window)
    channel.registerObject("backend", bridge)
    page.setWebChannel(channel)
    window.setCentralWidget(view)
    view.setUrl(QUrl.fromLocalFile(str(ROOT / "web" / "index.html")))
    window.show()
    def report_display():
        screen = window.windowHandle().screen()
        bridge.send("displayInfo", {"refreshRate": round(screen.refreshRate(), 2),
                                    "unlimited": os.environ.get("UTATOMO_SYSTEM_VSYNC") != "1"})
    window.windowHandle().screenChanged.connect(lambda *_: report_display())
    page.loadFinished.connect(lambda *_: QTimer.singleShot(500, report_display))
    app.aboutToQuit.connect(bridge.close)
    # 自动化验证使用真实 Qt 页面与播放器；不更改用户正在播放的网易云歌曲。
    if "--smoke-test" in sys.argv:
        output = WRITABLE_ROOT / "output"
        output.mkdir(exist_ok=True)

        def smoke():
            bridge.cloud_state["playing"] = False
            bridge._open_audio(ROOT / "samples" / "practice.wav")
            QTimer.singleShot(1500, exercise)

        checks = []

        def check(label, passed):
            checks.append({"check": label, "passed": bool(passed)})
            LOG.info("验收 %s：%s", label, "通过" if passed else "失败")

        def exercise():
            check("本地音轨时长 40 秒", bridge.player.duration() == 40000)
            check(
                "双语歌词与离线注音",
                len(bridge.lines) == 8
                and bool(bridge.lines[0].get("translation"))
                and any(token["reading"] for token in bridge.lines[0]["tokens"]),
            )
            page.runJavaScript(
                "document.querySelectorAll('.lyric-line')[1].click(); setDictionary(true);"
            )
            QTimer.singleShot(350, after_click)

        def after_click():
            check("点击歌词跳转到 5 秒并播放", 5000 <= bridge.player.position() <= 5600 and bridge.player.isPlaying())
            bridge.audio.setVolume(0)
            bridge.player.pause()
            bridge._action("rate", 0.75)
            bridge._action("loop", [5000, 5500])
            bridge._action("toggle", None)
            QTimer.singleShot(1800, after_loop)

        def after_loop():
            check("本地播放器真实播放", bridge.player.isPlaying())
            check("0.75 倍速", abs(bridge.player.playbackRate() - 0.75) < 0.001)
            check("循环保持在指定区间", 5000 <= bridge.player.position() < 5650)
            bridge._action("rate", 1.0)
            bridge._action("loop", [5000, 5100])
            QTimer.singleShot(850, after_short_loop)

        def after_short_loop():
            check("100 毫秒短区间循环", 5000 <= bridge.player.position() < 5250)
            bridge._action("loop", None)
            bridge.player.pause()
            bridge._seek(9500)
            page.runJavaScript(
                "document.getElementById('toast').hidden=true; showWord(state.lines[0].tokens.find(t=>t.text==='光'));"
            )
            QTimer.singleShot(1000, exercise_chime)

        def exercise_chime():
            # 经真实桥接触发并解码随包音效，确认不覆盖已暂停的歌曲。
            page.runJavaScript("action('chime');")
            QTimer.singleShot(700, after_chime)

        def after_chime():
            check("独立音效真实解码并播放", bridge.chime_player is not None
                  and bridge.chime_player.duration() > 0 and bridge.chime_player.isPlaying())
            check("音效保持歌曲位置与暂停状态", abs(bridge.player.position() - 9500) <= 30
                  and not bridge.player.isPlaying() and bridge.mode == "local")
            bridge.chime_audio.setVolume(0)
            bridge._action("chime", None)
            check("重复触发音效从头播放", bridge.chime_player.position() <= 30)
            QTimer.singleShot(200, after_chime_repeat)

        def after_chime_repeat():
            check("重复音效继续播放", bridge.chime_player.isPlaying())
            bridge.chime_player.stop()
            capture()

        def capture():
            check("精细跳转 9.500 秒", abs(bridge.player.position() - 9500) <= 30)
            view.grab().save(str(output / "app-screenshot.png"))

            def report(value):
                result = {"checks": checks, "frontend": json.loads(value)}
                (output / "smoke-result.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(
                    "SMOKE_RESULT=" + json.dumps(result, ensure_ascii=False), flush=True
                )
                passed = (
                    all(item["passed"] for item in checks)
                    and not result["frontend"]["errors"]
                    and result["frontend"]["bridge"]
                )
                window.resize(1024, 720)
                bridge._seek(22000)
                page.runJavaScript(
                    "showWord(state.lines[4].tokens.find(t=>t.text==='light'));"
                )

                def compact():
                    view.grab().save(str(output / "app-english-compact.png"))
                    app.exit(0 if passed else 1)

                QTimer.singleShot(1200, compact)

            page.runJavaScript(
                "JSON.stringify({title:document.title,lines:document.querySelectorAll('.lyric-line').length,errors:window.__errors||[],bridge:!!window.backend,dictionary:!document.getElementById('dictionaryPanel').hidden})",
                report,
            )

        QTimer.singleShot(3500, smoke)
        QTimer.singleShot(25000, lambda: app.exit(2))
    result = app.exec()
    lock.unlock()
    logging.shutdown()
    # 已关闭播放器和窗口；终止仍在等待网络响应的只读工作线程，使两个窗口同步退出。
    os._exit(result)
