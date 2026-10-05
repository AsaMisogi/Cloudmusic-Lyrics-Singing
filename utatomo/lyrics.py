"""歌词解析与时间对齐。内部统一使用整数毫秒，避免浮点累积误差。

支持普通 LRC、同一时间的双语 LRC、增强 LRC、网易云 YRC 与纯文本。
普通 LRC 只有逐行时间，界面的逐词渐亮只是插值；不能当作原始逐字时间。
"""

from __future__ import annotations

import bisect
import re
from pathlib import Path

STAMP = re.compile(r"\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]")
WORD_STAMP = re.compile(r"<(\d+):(\d{1,2})(?:\.(\d{1,3}))?>")
INLINE_READING = re.compile(r"([\u3400-\u9fff々]+)[(（]([ぁ-ゖァ-ヶー]+)[)）]")


def extract_inline_readings(line):
    """保留歌词作者写明的注音，正文只保留汉字；不剥掉普通括号正文。"""
    if line.get("words"):
        return
    hints, result, cursor = [], "", 0
    for match in INLINE_READING.finditer(line["text"]):
        result += line["text"][cursor:match.start()]
        hints.append({"start": len(result), "text": match[1], "reading": match[2]})
        result += match[1]
        cursor = match.end()
    if hints:
        line["text"] = result + line["text"][cursor:]
        line["inlineReadings"] = hints


def milliseconds(minutes: str, seconds: str, fraction: str | None) -> int:
    return (
        int(minutes) * 60000
        + int(seconds) * 1000
        + int((fraction or "0").ljust(3, "0"))
    )


def read_text(path: Path) -> str:
    """优先 Unicode，兼容常见中文 Windows 导出的 GB18030 歌词。"""
    raw = path.read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("歌词文件超过 4 MB，请选择歌词文本文件。")
    encodings = ["utf-8-sig", "gb18030"]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.insert(0, "utf-16")
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别歌词编码，请另存为 UTF-8。")


def parse_lyrics(text: str) -> list[dict]:
    """把各种格式转换为按时间排列的行，保留来源提供的逐字时间。"""
    lines: list[dict] = []
    offset_match = re.search(r"\[offset:\s*(-?\d+)\]", text, re.I)
    offset = int(offset_match[1]) if offset_match else 0
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        yrc = re.match(r"^\[(\d+),(\d+)\](.*)$", raw)
        if yrc:
            words = []
            for word in re.finditer(r"\((\d+),(\d+),\d+\)([^()]*)", yrc[3]):
                words.append(
                    {
                        "start": int(word[1]) + offset,
                        "end": int(word[1]) + int(word[2]) + offset,
                        "text": word[3],
                    }
                )
            body = "".join(w["text"] for w in words) or yrc[3]
            lines.append(
                {
                    "start": max(0, int(yrc[1]) + offset),
                    "end": int(yrc[1]) + int(yrc[2]) + offset,
                    "text": body,
                    "words": words,
                    "timing": "word" if words else "line",
                }
            )
            continue
        stamps = list(STAMP.finditer(raw))
        if stamps:
            body = STAMP.sub("", raw).strip()
            markers = list(WORD_STAMP.finditer(body))
            words = []
            for index, marker in enumerate(markers):
                following = markers[index + 1] if index + 1 < len(markers) else None
                fragment = body[
                    marker.end() : following.start() if following else len(body)
                ]
                if fragment:
                    words.append(
                        {
                            "start": milliseconds(*marker.groups()) + offset,
                            "end": milliseconds(*following.groups()) + offset
                            if following
                            else None,
                            "text": fragment,
                        }
                    )
            body = WORD_STAMP.sub("", body)
            # 空白时间标签也保留：它通常代表一段间奏的开始。
            for stamp in stamps:
                lines.append(
                    {
                        "start": max(0, milliseconds(*stamp.groups()) + offset),
                        "end": None,
                        "text": body,
                        "words": [dict(w) for w in words],
                        "timing": "word" if words else "line",
                    }
                )
    if not lines:
        # 无时间文本只展示，不捏造歌曲时间，也不允许点击跳转。
        return [
            {
                "start": None,
                "end": None,
                "text": row.strip(),
                "words": [],
                "timing": "none",
                "translation": "",
            }
            for row in text.splitlines()
            if row.strip() and not re.match(r"^\[\w+:", row)
        ]
    lines.sort(key=lambda line: line["start"])
    merged: list[dict] = []
    for line in lines:
        line["translation"] = ""
        if merged and merged[-1]["start"] == line["start"]:
            previous = merged[-1]
            if line["text"] != previous["text"]:
                previous["translation"] = " / ".join(
                    filter(None, [previous["translation"], line["text"]])
                )
            continue
        merged.append(line)
    for index, line in enumerate(merged):
        extract_inline_readings(line)
        following = merged[index + 1]["start"] if index + 1 < len(merged) else None
        if line["end"] is None:
            line["end"] = following
        for word in line["words"]:
            if word["end"] is None:
                word["end"] = line["end"]
    return merged


def align_translation(lines: list[dict], translated: str, tolerance: int = 700) -> None:
    """译文按最近时间对齐，避免少一行译文导致整首歌串行。"""
    translations = parse_lyrics(translated)
    timed = [line for line in lines if line["start"] is not None]
    starts = [line["start"] for line in timed]
    if not timed:
        for line, translation in zip(lines, translations):
            line["translation"] = translation["text"]
        return
    for translation in translations:
        if translation["start"] is None:
            continue
        index = bisect.bisect_left(starts, translation["start"])
        candidates = [i for i in (index - 1, index) if 0 <= i < len(timed)]
        if candidates:
            nearest = min(
                candidates, key=lambda i: abs(starts[i] - translation["start"])
            )
            if abs(starts[nearest] - translation["start"]) <= tolerance:
                timed[nearest]["translation"] = translation["text"]


def active_line(lines: list[dict], position: int) -> int:
    if not lines or lines[0]["start"] is None:
        return -1
    return bisect.bisect_right([line["start"] for line in lines], position) - 1


def align_pronunciation(lines: list[dict], text: str, tolerance: int = 350) -> None:
    """读音只与同时间轴一对一配对；不按行号补齐缺失行。"""
    readings = [line for line in parse_lyrics(text)
                if line["start"] is not None and line["text"].strip()]
    used = set()
    for line in lines:
        if line["start"] is None or not line["text"].strip():
            continue
        candidates = sorted((abs(item["start"] - line["start"]), i)
                            for i, item in enumerate(readings) if i not in used)
        if not candidates or candidates[0][0] > tolerance:
            continue
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            continue
        index = candidates[0][1]
        used.add(index)
        line["pronunciation"] = readings[index]["text"]
