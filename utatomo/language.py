"""离线注音：UniDic 词法分析 + 未登录词回退 + CMU 英语发音库。

采用词典读法而非逐字拼接。歌曲里的特殊读法不能总由词法分析推断，
因此允许用户校正；保存的校正会在后续加载同一词时优先使用。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import cmudict
import fugashi
import pykakasi

from .readings import align_reading, phonetic

HAN = re.compile(r"[\u3400-\u9fff々]")
ENGLISH = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*|[^A-Za-z]+")
PHONES = dict(
    zip(
        "AA AE AH AO AW AY B CH D DH EH ER EY F G HH IH IY JH K L M N NG OW OY P R S SH T TH UH UW V W Y Z ZH".split(),
        "ɑ æ ʌ ɔ aʊ aɪ b tʃ d ð ɛ ɝ eɪ f ɡ h ɪ i dʒ k l m n ŋ oʊ ɔɪ p ɹ s ʃ t θ ʊ u v w j z ʒ".split(),
    )
)


def hiragana(value: str) -> str:
    return "".join(
        chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char for char in value
    )


def to_ipa(phones: list[str]) -> str:
    """CMU ARPAbet 转宽式美式 IPA。标注声调重音，保留词典的不确定性。"""
    result = []
    stress_at = {}
    previous_vowel = -1
    # IPA 重音位于音节之前；依据英语允许的音节首辅音组合切分，而非放在元音之前。
    onsets = {
        "PR",
        "PL",
        "BR",
        "BL",
        "TR",
        "DR",
        "KR",
        "KL",
        "GR",
        "GL",
        "FR",
        "FL",
        "THR",
        "SHR",
        "SP",
        "ST",
        "SK",
        "SM",
        "SN",
        "SL",
        "SW",
        "TW",
        "KW",
        "SPR",
        "STR",
        "SKR",
        "SPL",
        "SKW",
    }
    for index, phone in enumerate(phones):
        if phone[-1:] in ("0", "1", "2"):
            if phone.endswith(("1", "2")):
                start = 0 if previous_vowel < 0 else index
                if previous_vowel >= 0 and index > previous_vowel + 1:
                    start = index - 1
                    for candidate in range(previous_vowel + 1, index - 1):
                        if "".join(phones[candidate:index]) in onsets:
                            start = candidate
                            break
                stress_at[start] = "ˈ" if phone.endswith("1") else "ˌ"
            previous_vowel = index
    for index, phone in enumerate(phones):
        base = phone.rstrip("012")
        sound = PHONES.get(base, base.lower())
        if phone == "AH0":
            sound = "ə"
        if phone == "ER0":
            sound = "ɚ"
        stress = stress_at.get(index, "")
        result.append(stress + sound)
    return "".join(result)


class Annotator:
    def __init__(self, data_dir: Path):
        self.tagger = fugashi.Tagger()
        self.kakasi = pykakasi.kakasi()
        self.english = cmudict.dict()
        self.corrections = json.loads((Path(__file__).resolve().parents[1] / "assets/reading-corrections.json").read_text(encoding="utf-8"))
        self.override_path = data_dir / "overrides.json"
        try:
            self.overrides = json.loads(self.override_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.overrides = {}
        self.scoped_path = data_dir / "song-overrides.json"
        try:
            self.scoped = json.loads(self.scoped_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.scoped = {}

    def correct(self, text: str, reading: str, scope="", line_key="", token_start=0) -> None:
        if scope:
            key = json.dumps([scope, line_key, token_start, text], ensure_ascii=False)
            if reading.strip():
                self.scoped[key] = reading.strip()
            else:
                self.scoped.pop(key, None)
            self.scoped_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.scoped_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.scoped, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.scoped_path)
            return
        if reading.strip():
            self.overrides[text] = reading.strip()
        else:
            self.overrides.pop(text, None)
        self.override_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.override_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.overrides, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.override_path)
        self.annotate.cache_clear()

    def english_token(self, surface: str) -> dict:
        normalized = surface.lower().replace("’", "'")
        variants = self.english.get(normalized)
        reading = to_ipa(variants[0]) if variants else ""
        return {
            "text": surface,
            "reading": self.overrides.get(surface, reading),
            "lemma": normalized,
            "language": "en",
            "pos": "英语",
            "source": "用户校正"
            if surface in self.overrides
            else "CMU 美式宽式音标"
            if variants
            else "未收录发音",
        }

    @lru_cache(maxsize=4096)
    def annotate(self, text: str) -> list[dict]:
        tokens = []
        cursor = 0
        for word in self.tagger(text):
            surface = word.surface
            # MeCab 丢弃空格，必须从原文补回，英语不能粘连。
            index = text.find(surface, cursor)
            if index > cursor:
                tokens.append(
                    {
                        "text": text[cursor:index],
                        "reading": "",
                        "lemma": "",
                        "language": "",
                        "pos": "",
                        "source": "",
                    }
                )
            cursor = max(cursor, index) + len(surface)
            if re.fullmatch(r"[A-Za-z]+(?:['’][A-Za-z]+)*", surface):
                tokens.append(self.english_token(surface))
                continue
            feature = word.feature
            reading = getattr(feature, "kana", "") or getattr(feature, "pron", "") or ""
            source = "UniDic 词典"
            if reading in ("", "*") and HAN.search(surface):
                reading = "".join(item["hira"] for item in self.kakasi.convert(surface))
                source = "常用读音回退"
            reading = hiragana(reading)
            if not HAN.search(surface):
                reading = ""
            lemma = getattr(feature, "lemma", "") or surface
            lemma = lemma.split("-")[0] if lemma != "*" else surface
            tokens.append(
                {
                    "text": surface,
                    "reading": self.overrides.get(surface, reading),
                    "lemma": lemma,
                    "language": "ja",
                    "pos": getattr(feature, "pos1", "") or "",
                    "source": "用户校正" if surface in self.overrides else source,
                }
            )
        if cursor < len(text):
            tokens.append(
                {
                    "text": text[cursor:],
                    "reading": "",
                    "lemma": "",
                    "language": "",
                    "pos": "",
                    "source": "",
                }
            )
        # 英文整行直接分词，防止日语分析器将英文缩写或所有格拆碎。
        if not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", text):
            tokens = [
                self.english_token(m[0])
                if m[0][0].isascii() and m[0][0].isalpha()
                else {
                    "text": m[0],
                    "reading": "",
                    "lemma": "",
                    "language": "",
                    "pos": "",
                    "source": "",
                }
                for m in ENGLISH.finditer(text)
            ]
        return tokens

    def enrich(self, lines: list[dict], scope="") -> list[dict]:
        for line in lines:
            # 缓存里的词典结果不能被歌曲注音 / 用户修正改写。
            tokens = [dict(token) for token in self.annotate(line["text"])]
            readings = align_reading(tokens, line.get("pronunciation", ""))
            references = [(align_reading(tokens, item["pronunciation"]), item["source"])
                          for item in line.get("readingReferences", [])]
            cursor = 0
            line_key = json.dumps([line["start"], line["text"]], ensure_ascii=False)
            for index, token in enumerate(tokens):
                token["lineKey"], token["tokenStart"] = line_key, cursor
                token["scope"] = scope
                candidates = []
                if token["reading"]:
                    candidates.append({"reading": token["reading"], "source": token["source"]})
                if readings and HAN.search(token["text"]):
                    token["reading"] = readings[index]
                    token["source"] = "歌曲罗马音 / 假名参考"
                    candidates.append({"reading": readings[index], "source": token["source"]})
                for alternative, origin in references:
                    if alternative and HAN.search(token["text"]):
                        candidates.append({"reading": alternative[index], "source": f"其他歌词来源 {origin}"})
                # 作者明确写在原文里的 ruby 高于机器生成的罗马音。
                inline = self._inline_reading(line, token, cursor)
                if inline:
                    token["reading"], token["source"] = inline, "原文括号注音"
                    candidates.append({"reading": inline, "source": token["source"]})
                for correction in self.corrections:
                    if (scope.removeprefix("netease:") in correction["songIds"]
                            and line["text"].startswith(correction["linePrefix"])
                            and cursor == correction["tokenStart"] and token["text"] == correction["text"]):
                        token["reading"] = correction["reading"]
                        token["source"] = correction["source"]
                        token["readingReference"] = correction["reference"]
                        candidates.append({"reading": token["reading"], "source": "已核对歌曲读音"})
                if token["text"] in self.overrides:
                    token["reading"], token["source"] = self.overrides[token["text"]], "用户校正"
                key = json.dumps([scope, line_key, cursor, token["text"]], ensure_ascii=False)
                if scope and key in self.scoped:
                    token["reading"] = self.scoped[key]
                    token["source"] = "本句用户校正"
                token["readingCandidates"] = candidates
                token["readingConflict"] = (len({phonetic(c["reading"]) for c in candidates}) > 1
                                              and token["source"] == "歌曲罗马音 / 假名参考")
                cursor += len(token["text"])
            line["tokens"] = tokens
            line["readingSource"] = "song" if readings else "dictionary"
        return lines

    @staticmethod
    def _inline_reading(line, token, cursor):
        end, position, result = cursor + len(token["text"]), cursor, ""
        hints = [h for h in line.get("inlineReadings", [])
                 if cursor <= h["start"] and h["start"] + len(h["text"]) <= end]
        if not hints:
            return ""
        for hint in hints:
            plain = line["text"][position:hint["start"]]
            if HAN.search(plain):
                return ""
            result += hiragana(plain) + hiragana(hint["reading"])
            position = hint["start"] + len(hint["text"])
        plain = line["text"][position:end]
        return "" if HAN.search(plain) else result + hiragana(plain)
