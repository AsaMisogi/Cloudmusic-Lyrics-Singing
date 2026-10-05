"""外部服务边界：短超时、结果缓存、明确来源，不读取账户登录信息。

网易云和有道公开接口没有稳定性承诺。网络请求只在后台线程运行；
出错交给界面显示，不覆盖已加载的歌词。机器翻译是用户主动触发的功能。
"""

from __future__ import annotations

import base64
from urllib.parse import urlparse
import hashlib
import html
import json
import logging
import os
import re
import uuid
from pathlib import Path

import requests

from difflib import SequenceMatcher
from .matching import lyric_versions, lyric_content, same_recording, sort_versions
from .lyrics import parse_lyrics, align_pronunciation

LOG = logging.getLogger(__name__)


class Services:
    def __init__(self, data_dir: Path):
        self.cache = data_dir / "cache"
        self.cache.mkdir(parents=True, exist_ok=True)

    def cached_json(self, namespace: str, key: str, fetch):
        name = hashlib.sha256(key.encode()).hexdigest()
        path = self.cache / f"{namespace}-{name}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        result = fetch()
        # 同一个任务的键只由对应工作线程写入；replace 避免退出时留下半份 JSON。
        temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        return result

    @staticmethod
    def request(url: str, params: dict):
        response = requests.get(
            url,
            params=params,
            headers={
                "User-Agent": "Mozilla/5.0 Utatomo/0.1",
                "Referer": "https://music.163.com/",
            },
            timeout=(5, 12),
        )
        response.raise_for_status()
        return response.json()

    def cover(self, song_id: str) -> str:
        """后台读取当前歌曲封面，缓存小尺寸图片；缺图/离线静默回退默认图。

        图片通过 data URL 交给界面，保持 WebEngine 禁止联网的 CSP。
        只接收网易云图片域名与常见位图，限制体积，避免把远程 HTML 当图片。
        """
        if not re.fullmatch(r"\d{1,20}", song_id):
            return ""
        path = self.cache / f"cover-{song_id}.json"
        try:
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
            detail = self.request("https://music.163.com/api/song/detail/",
                                  {"ids": "[" + song_id + "]"})
            song = detail.get("songs", [{}])[0]
            url = song.get("album", song.get("al", {})).get("picUrl", "")
            parsed = urlparse(url)
            if not parsed.hostname or not parsed.hostname.endswith(".music.126.net"):
                return ""
            url = parsed._replace(scheme="https").geturl()
            with requests.get(url, params={"param": "300y300"}, timeout=(5, 10),
                              stream=True, allow_redirects=False) as response:
                response.raise_for_status()
                mime = response.headers.get("Content-Type", "").split(";")[0]
                if mime not in ("image/jpeg", "image/jpg", "image/png", "image/webp", "application/octet-stream"):
                    return ""
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > 2 * 1024 * 1024:
                        return ""
            if not content:
                return ""
            # CDN 实际可能返回 image/jpg 标头但内容为 PNG，按位图签名规范化。
            if content.startswith(b"\x89PNG\r\n\x1a\n"):
                mime = "image/png"
            elif content.startswith(b"\xff\xd8\xff"):
                mime = "image/jpeg"
            elif content[:4] == b"RIFF" and content[8:12] == b"WEBP":
                mime = "image/webp"
            else:
                return ""
            result = f"data:{mime};base64," + base64.b64encode(content).decode("ascii")
            temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
            temporary.write_text(json.dumps(result), encoding="utf-8")
            temporary.replace(path)
            return result
        except (requests.RequestException, OSError, ValueError, IndexError, TypeError):
            LOG.info("当前歌曲封面不可用：%s", song_id)
            return ""

    def search(self, query: str) -> list[dict]:
        data = self.request(
            "https://music.163.com/api/search/get", {"s": query, "type": 1, "limit": 12}
        )
        if data.get("code") != 200:
            raise ValueError("网易云搜索暂不可用，请输入歌曲 ID 或导入歌词。")
        return [
            {
                "id": song["id"],
                "title": song["name"],
                "artist": " / ".join(
                    artist["name"] for artist in song.get("artists", song.get("ar", []))
                ),
                "duration": song.get("duration", song.get("dt", 0)),
                "album": song.get("album", song.get("al", {})).get("name", ""),
            }
            for song in data.get("result", {}).get("songs", [])
        ]

    def identify(self, title: str, artist: str) -> list[dict]:
        """优先只读当前播放队列，取歌曲 ID；不读取账户、Cookie 或播放历史。"""
        normalize = lambda text: re.sub(
            r"[\s\W_]+", "", text, flags=re.UNICODE
        ).casefold()
        path = (
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "NetEase/CloudMusic/webdata/file/playingList"
        )
        matches = []
        try:
            if path.stat().st_size < 24 * 1024 * 1024:
                entries = json.loads(path.read_text(encoding="utf-8"))["list"]
                for entry in entries:
                    song = entry.get("track", {})
                    names = " / ".join(item["name"] for item in song.get("artists", []))
                    if normalize(song.get("name", "")) == normalize(
                        title
                    ) and normalize(names) == normalize(artist):
                        matches.append(
                            {
                                "id": song["id"],
                                "title": song["name"],
                                "artist": names,
                                "duration": song.get("duration", 0),
                                "album": song.get("album", {}).get("name", ""),
                                "fromQueue": True,
                            }
                        )
        except (OSError, ValueError, KeyError, TypeError):
            pass
        try:
            online = self.search(title + " " + artist)
        except (requests.RequestException, ValueError):
            if not matches:
                raise
            online = []
        # 队列项排在前面，去重时保留它的来源标记；网络失败仍可用队列匹配。
        return list({str(song["id"]): song for song in reversed(matches + online)}.values())

    def practice_audio(self, song_id: str) -> str:
        """历史公开音频验收工具使用；桌面同步功能不调用此方法。

        不携带账户凭证，不解密受保护文件；公开地址不可用时明确失败。
        写完后原子替换，避免中断下载留下貌似可播放的文件。
        """
        if not re.fullmatch(r"\d{1,20}", song_id):
            raise ValueError("请先匹配当前歌曲的歌词。")
        destination = self.cache / f"audio-{song_id}.mp3"
        if destination.is_file() and destination.stat().st_size > 1024:
            return str(destination)
        temporary = destination.with_suffix("." + uuid.uuid4().hex + ".part")
        try:
            with requests.get(
                "https://music.163.com/song/media/outer/url",
                params={"id": song_id + ".mp3"},
                stream=True,
                timeout=(5, 15),
            ) as response:
                response.raise_for_status()
                if not any(
                    value in response.headers.get("Content-Type", "")
                    for value in ("audio/", "octet-stream")
                ):
                    raise ValueError(
                        "此歌曲未提供公开音频，请打开已获得的本地音频继续练唱。"
                    )
                size = 0
                with temporary.open("wb") as output:
                    for chunk in response.iter_content(128 * 1024):
                        size += len(chunk)
                        if size > 100 * 1024 * 1024:
                            raise ValueError("音频超过 100 MB，请使用本地模式加载。")
                        output.write(chunk)
                if size < 1024:
                    raise ValueError("未获得有效音频，请使用本地歌曲。")
            temporary.replace(destination)
            return str(destination)
        except requests.RequestException as exc:
            raise ValueError("公开音频暂不可用，请使用本地歌曲。") from exc
        finally:
            temporary.unlink(missing_ok=True)

    def lyrics(self, song_id: str) -> dict:
        if not re.fullmatch(r"\d{1,20}", str(song_id)):
            raise ValueError("歌曲 ID 应为纯数字，也可粘贴网易云歌曲链接。")

        def fetch():
            data = self.request(
                "https://music.163.com/api/song/lyric",
                {"id": song_id, "lv": -1, "tv": -1, "yv": -1, "rv": -1, "kv": -1},
            )
            if data.get("code") != 200:
                raise ValueError("网易云歌词接口暂不可用。")
            if not data.get("lrc", {}).get("lyric") and not data.get("yrc", {}).get(
                "lyric"
            ):
                raise ValueError("此歌曲没有可用歌词（可能是纯音乐），可以手动导入。")
            return data

        return self.cached_json("netease", str(song_id), fetch)

    def lyric_options(self, song_id, candidates, selected):
        """时间轴异常时核对同版本候选，保留原始来源供用户切回。"""
        versions = lyric_versions(self.lyrics(song_id))
        for version in versions:
            version["sourceSongId"] = str(song_id)
            version["source"] = f"网易云 · {song_id} · {version['label']}"
        if not versions or not versions[0]["timingIssues"]:
            return versions
        alternatives = [song for song in candidates if str(song["id"]) != str(song_id)
                        and same_recording(song, selected)]
        baseline = lyric_content(versions[0]["text"])
        for song in alternatives[:2]:
            try:
                for version in lyric_versions(self.lyrics(str(song["id"]))):
                    if SequenceMatcher(None, baseline, lyric_content(version["text"]), autojunk=False).ratio() < .85:
                        continue
                    version["id"] = f"{song['id']}:{version['id']}"
                    version["sourceSongId"] = str(song["id"])
                    version["label"] += f" · 同版本候选 {song['id']}"
                    version["source"] = f"网易云 · {song['id']} · {song.get('album', '')} · 同版本替代歌词"
                    versions.append(version)
            except (requests.RequestException, ValueError, OSError):
                LOG.info("替代歌词不可用：%s，保留当前曲目歌词", song["id"])
        # 不同来源只按相同句子核对读音，不把替代时间戳套在原歌词上。
        reading_lines = []
        for version in versions:
            lines = parse_lyrics(version["text"])
            align_pronunciation(lines, version["pronunciation"])
            reading_lines.extend({"text": line["text"], "pronunciation": line["pronunciation"],
                                  "source": version["sourceSongId"]}
                                 for line in lines if line.get("pronunciation"))
        for version in versions:
            version["readingReferences"] = [line for line in reading_lines if line["source"] != version["sourceSongId"]]
        return sort_versions(versions)

    def translate(self, text: str) -> str:
        def fetch():
            try:
                data = self.request(
                    "https://translate.googleapis.com/translate_a/single",
                    {
                        "client": "gtx",
                        "sl": "auto",
                        "tl": "zh-CN",
                        "dt": "t",
                        "q": text,
                    },
                )
                return "".join(item[0] for item in data[0] if item and item[0])
            except (requests.RequestException, ValueError, KeyError, TypeError):
                LOG.info("Google 翻译暂不可用，尝试 MyMemory 公开翻译 API")
            # MyMemory 单次 q 限制为 500 字节，按歌词原有行分批，并保留行对应关系。
            translated = []
            for line in text.splitlines():
                if not line.strip():
                    translated.append("")
                    continue
                if len(line.encode("utf-8")) > 500:
                    raise ValueError(
                        "这一行歌词过长，备用翻译服务无法处理。可手动导入中文译文。"
                    )
                source = (
                    "ja" if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", line) else "en"
                )
                data = self.request(
                    "https://api.mymemory.translated.net/get",
                    {"q": line, "langpair": source + "|zh-CN"},
                )
                if int(data.get("responseStatus", 0)) != 200:
                    raise ValueError(
                        "翻译服务暂不可用或已达免费限额，请稍后再试，或导入中文译文。"
                    )
                value = data.get("responseData", {}).get("translatedText", "")
                if not value:
                    raise ValueError("翻译服务没有返回译文。")
                translated.append(html.unescape(value))
            return "\n".join(translated)

        return self.cached_json("translation", text, fetch)

    def dictionary(self, word: str, language: str) -> dict:
        def fetch():
            data = self.request(
                "https://dict.youdao.com/jsonapi",
                {"q": word, "le": "jap" if language == "ja" else "eng"},
            )
            definitions: list[str] = []
            # ec 与 newjc 在不同词条上结构不同，只提取定义节点，避免展示广告等内容。
            section = (
                (data.get("jc") or data.get("newjc"))
                if language == "ja"
                else data.get("ec")
            )

            def collect(node):
                if isinstance(node, dict):
                    for key, value in node.items():
                        if key in (
                            "exam",
                            "ja_exam_sents",
                            "phrases",
                            "sentence",
                            "lj",
                            "ljStyle",
                            "ljT",
                            "ljPjm",
                        ):
                            continue
                        if key in (
                            "l",
                            "trans",
                            "translation",
                            "mean",
                            "meaning",
                            "tran",
                            "jmsy",
                        ):
                            strings(value)
                        elif isinstance(value, (dict, list)):
                            collect(value)
                elif isinstance(node, list):
                    for item in node:
                        collect(item)

            def strings(node):
                if isinstance(node, str):
                    clean = re.sub(r"<[^>]+>", "", node).strip()
                    if (
                        re.search(r"[\u3400-\u9fff]", clean)
                        and clean not in definitions
                    ):
                        definitions.append(clean)
                elif isinstance(node, list):
                    for value in node:
                        strings(value)
                elif isinstance(node, dict):
                    for value in node.values():
                        strings(value)

            collect(section or {})
            if not definitions:
                raise ValueError(
                    "词典未返回中文释义，可尝试词的原形或使用下方在线词典链接。"
                )
            return {
                "definitions": definitions[:8],
                "source": "有道词典 · 在线查询 / 本地缓存",
            }

        return self.cached_json("dictionary-v2", f"{language}:{word}", fetch)
