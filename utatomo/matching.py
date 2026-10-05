"""歌曲和歌词版本排序。纯函数便于验证，不涉及网络或播放器状态。"""

import re
import unicodedata
from difflib import SequenceMatcher

from .lyrics import parse_lyrics

CREDIT = re.compile(r"^\s*(?:作词|作曲|编曲|作詞|作曲|編曲|词|曲|歌|詞|曲|唄)\s*[:：]")


def timing_issues(lines):
    """发现会吞掉整句的异常时间，不用猜测的最小时长改写原时间轴。"""
    issues = []
    for line, following in zip(lines, lines[1:]):
        if line["start"] is None or following["start"] is None or line.get("words"):
            continue
        text = line["text"].strip()
        if not text or CREDIT.match(text):
            continue
        interval = following["start"] - line["start"]
        minimum = 300 if following["text"].strip() else 800
        if len(normalize(text)) >= 4 and interval < minimum:
            issues.append({"start": line["start"], "text": text, "interval": interval})
    return issues


def same_recording(candidate, selected):
    """标题包含完整版本名，歌手相同且时长接近，才考虑替代歌词。"""
    return bool(selected and candidate.get("duration") and selected.get("duration")
                and normalize(candidate.get("title")) == normalize(selected.get("title"))
                and normalize(candidate.get("artist")) == normalize(selected.get("artist"))
                and abs(candidate["duration"] - selected["duration"]) <= 2500)


def lyric_content(text):
    return normalize("".join(line["text"] for line in parse_lyrics(text)
                             if not CREDIT.match(line["text"])))


def sort_versions(versions):
    longest = max((v["characters"] for v in versions), default=0)
    # 完整且无异常的版本优先；同等质量保留原曲来源的顺序。
    versions.sort(key=lambda v: (v["characters"] >= longest * .8,
                                 -len(v.get("timingIssues", [])), v["quality"]), reverse=True)
    return versions


def normalize(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text or "")).casefold()


def rank_songs(songs, title, artist, album="", duration=0):
    """当前队列优先，其次比较标题、歌手、专辑和时长；同分保持来源顺序。

    保留 live、伴奏等标题文字，避免将不同录音版本误当作同一个版本。
    缺失时长不会得到时长奖励，也不会因为未知时长被扣分。
    """
    def score(song):
        name = SequenceMatcher(None, normalize(title), normalize(song["title"])).ratio()
        singer = SequenceMatcher(None, normalize(artist), normalize(song["artist"])).ratio()
        result = name * 60 + singer * 25
        if album and normalize(album) == normalize(song.get("album")):
            result += 10
        if duration and song.get("duration"):
            result += max(-20, 15 - abs(duration - song["duration"]) / 1000)
        if song.get("fromQueue"):
            result += 30
        return result

    unique = {str(song["id"]): song for song in reversed(songs)}
    return sorted(unique.values(), key=score, reverse=True)


def lyric_versions(payload):
    """保留逐字与逐行原文；译文与对应时间轴配对，过滤空白和损坏版本。

    逐字版本需要真正有单词时间且文本覆盖率足够，否则优先使用完整 LRC。
    罗马音不是另一份原文，不将其自动替换为歌唱正文。
    """
    variants = []
    for key, label, translation in (("yrc", "逐字歌词", "ytlrc"), ("lrc", "逐行歌词", "tlyric")):
        text = (payload.get(key) or {}).get("lyric", "")
        lines = parse_lyrics(text)
        meaningful = [line for line in lines if line["text"].strip()]
        if not meaningful:
            continue
        timed = sum(line["start"] is not None for line in meaningful)
        words = sum(bool(line["words"]) for line in meaningful)
        variants.append({"id": key, "label": label, "text": text,
                         "timingIssues": timing_issues(lines),
                         "pronunciation": (payload.get("yromalrc" if key == "yrc" else "romalrc") or {}).get("lyric", ""),
                         "translation": (payload.get(translation) or {}).get("lyric", ""),
                         "characters": sum(len(line["text"]) for line in meaningful),
                         "quality": (2 if words else 1 if timed else 0)})
    return sort_versions(variants)
