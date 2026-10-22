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

    def correct(self, text: str, reading: str, scope="", line_key="", token_start=0,
                reading_system="default") -> None:
        # 粤拼与旧假名/IPA 使用不同键，开关粤拼不会改写旧版修正的含义。
        if reading_system == "jyutping":
            reading = " ".join(reading.lower().split())
            if reading and not re.fullmatch(r"[a-z]+[1-6](?: [a-z]+[1-6])*", reading):
                raise ValueError("粤拼请使用字母和 1–6 声调数字，例如 ngo5；留空恢复自动读音。")
        if scope:
            parts = [scope, line_key, token_start, text]
            if reading_system == "jyutping":
                parts.append("jyutping")
            key = json.dumps(parts, ensure_ascii=False)
            scoped = dict(self.scoped)
            if reading.strip():
                scoped[key] = reading.strip()
            else:
                scoped.pop(key, None)
            self.scoped_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.scoped_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(scoped, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.scoped_path)
            self.scoped = scoped
            return
        overrides = dict(self.overrides)
        if reading.strip():
            overrides[text] = reading.strip()
        else:
            overrides.pop(text, None)
        self.override_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.override_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.override_path)
        self.overrides = overrides
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
                    # 助词的写法和发音不同（は→わ、へ→え、を→お）。
                    # 保留 UniDic 上下文判定的发音，仅供纯假名词的罗马音显示。
                    "kanaPronunciation": hiragana(getattr(feature, "pron", "") or "")
                    if getattr(feature, "pos1", "") == "助詞" else "",
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

    @lru_cache(maxsize=4096)
    def romanize(self, reading: str) -> str:
        """沿用离线 pykakasi 的 Hepburn 转写；缓存按最终读音而非原文索引。

        先应用歌曲注音与用户修正再转写，避免把特殊唱法重新按汉字猜读。
        长音保留库输出的元音拼写（如 gakkou / koohii），不额外猜测唱法。
        """
        return "".join(item["hepburn"] for item in self.kakasi.convert(reading))

    def enrich(self, lines: list[dict], scope="") -> list[dict]:
        # 同一份日语歌词里的纯汉字短句仍按日语处理；中文歌词不再显示日语猜读。
        # 显式 language=zh 可覆盖此文档级线索；译文不是原文，不参与判定或粤拼转换。
        japanese_lines = sum(bool(re.search(r"[ぁ-ゖァ-ヶ]", line["text"])) for line in lines)
        chinese_lines = sum(bool(HAN.search(line["text"])) and not re.search(r"[ぁ-ゖァ-ヶ]", line["text"]) for line in lines)
        japanese_document = japanese_lines > 0 and japanese_lines >= chinese_lines
        for line in lines:
            line.pop("cantoneseTokens", None)
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
                # 罗马音是额外的显示字段，原始假名及修正依据保持完整。
                # 纯假名词原本无需 ruby；罗马音模式为这类词也提供拉丁字母注音。
                kana_text = ""
                if not HAN.search(token["text"]) and re.search(r"[ぁ-ゖァ-ヶ]", token["text"]):
                    kana_text = token.get("kanaPronunciation") or token["text"]
                roman_reading = token["reading"] or kana_text
                token["romaji"] = (
                    self.romanize(roman_reading)
                    if token["language"] == "ja" and roman_reading else ""
                )
                cursor += len(token["text"])
            line["tokens"] = tokens
            line["readingSource"] = "song" if readings else "dictionary"
            chinese = (HAN.search(line["text"]) and not re.search(r"[ぁ-ゖァ-ヶ]", line["text"])
                       and (not japanese_document or line.get("language") == "zh"))
            if chinese:
                line["cantoneseTokens"] = self._cantonese_tokens(line, scope, line_key)
        return lines

    @staticmethod
    @lru_cache(maxsize=4096)
    def _cantonese_candidates(text: str) -> tuple:
        """整句转换后逐字取读音，保留词组上下文，不逐字重新猜多音字。

        延迟导入的离线词典随便携包分发；不向任何在线服务发送歌词。
        缓存只含不可变元组，用户修正不会污染其他歌曲的结果。
        """
        import ToJyutping
        return tuple((text, tuple(readings)) for text, readings in ToJyutping.get_jyutping_candidates(text))

    def _cantonese_tokens(self, line, scope, line_key):
        tokens, cursor = [], 0
        pairs, latin = [], ""
        for text, readings in self._cantonese_candidates(line["text"]):
            # ToJyutping 按字返回；先把连续英语重组，避免 CMU 查询变成逐字母注音。
            if re.fullmatch(r"[A-Za-z'’]+", text):
                latin += text
                continue
            if latin:
                pairs.append((latin, ()))
                latin = ""
            pairs.append((text, readings))
        if latin:
            pairs.append((latin, ()))
        for text, readings in pairs:
            # 库保留标点、空格和未收录汉字；英语连续串另交给原有 CMU 处理。
            if re.fullmatch(r"[A-Za-z]+(?:['’][A-Za-z]+)*", text):
                token = self.english_token(text)
            else:
                token = {"text": text, "reading": readings[0] if readings else "",
                         "language": "zh" if HAN.search(text) else "", "lemma": text,
                         "pos": "粤语读音", "source": "ToJyutping 离线粤拼" if readings else "未收录读音"}
            token.update(scope=scope, lineKey=line_key, tokenStart=cursor,
                         readingSystem="jyutping" if token["language"] == "zh" else "default",
                         readingCandidates=[{"reading": reading, "source": "粤拼候选"} for reading in readings])
            key = json.dumps([scope, line_key, cursor, text, "jyutping"], ensure_ascii=False)
            if scope and key in self.scoped:
                token["reading"], token["source"] = self.scoped[key], "本句用户校正"
            tokens.append(token)
            cursor += len(text)
        return tokens

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
