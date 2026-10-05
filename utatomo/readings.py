"""歌曲罗马音转假名及保守的词边界对齐，不将词典推测当作真实唱法。"""

import re
import unicodedata
from functools import lru_cache

HAN = re.compile(r"[\u3400-\u9fff々]")
KANA = re.compile(r"[ぁ-ゖー]")
ROMAJI = {}
for syllables, kana in (
    ("a i u e o", "あいうえお"), ("ka ki ku ke ko", "かきくけこ"),
    ("sa shi su se so", "さしすせそ"), ("ta chi tsu te to", "たちつてと"),
    ("na ni nu ne no", "なにぬねの"), ("ha hi fu he ho", "はひふへほ"),
    ("ma mi mu me mo", "まみむめも"), ("ya yu yo", "やゆよ"),
    ("ra ri ru re ro", "らりるれろ"), ("wa wi we wo", "わゐゑを"),
    ("ga gi gu ge go", "がぎぐげご"), ("za ji zu ze zo", "ざじずぜぞ"),
    ("da di du de do", "だぢづでど"), ("ba bi bu be bo", "ばびぶべぼ"),
    ("pa pi pu pe po", "ぱぴぷぺぽ"), ("va vi vu ve vo", "ゔぁ ゔぃ ゔ ゔぇ ゔぉ".split()),
):
    ROMAJI.update(zip(syllables.split(), kana))
for stem, base in (("ky", "き"), ("gy", "ぎ"), ("sh", "し"), ("sy", "し"),
                   ("ch", "ち"), ("ty", "ち"), ("j", "じ"), ("jy", "じ"),
                   ("zy", "じ"), ("ny", "に"), ("hy", "ひ"), ("by", "び"),
                   ("py", "ぴ"), ("my", "み"), ("ry", "り")):
    ROMAJI.update({stem + vowel: base + small for vowel, small in zip("auo", "ゃゅょ")})
ROMAJI.update({"si": "し", "ti": "ち", "tu": "つ", "hu": "ふ", "zi": "じ",
               "she": "しぇ", "che": "ちぇ", "je": "じぇ", "fa": "ふぁ",
               "fi": "ふぃ", "fe": "ふぇ", "fo": "ふぉ", "tsa": "つぁ",
               "tsi": "つぃ", "tse": "つぇ", "tso": "つぉ"})


def hira(text):
    return "".join(chr(ord(c) - 96) if "ァ" <= c <= "ヶ" else c
                   for c in unicodedata.normalize("NFKC", text))


def reading_kana(text):
    """保留空格的 n 边界（n a → んあ）；不识别的英文整行拒绝使用。"""
    text = hira(text).lower().replace("’", "'")
    for vowel, replacement in zip("āīūēōâîûêô", ("aa", "ii", "uu", "ee", "ou") * 2):
        text = text.replace(vowel, replacement)
    result = []
    for chunk in re.findall(r"[a-z']+|[ぁ-ゖー]+|[^a-zぁ-ゖー']+", text):
        if re.fullmatch(r"[ぁ-ゖー]+", chunk):
            result.append(chunk)
            continue
        if not re.search(r"[a-z]", chunk):
            if any(c.isalnum() or c == "�" for c in chunk):
                return ""
            continue
        while chunk:
            if chunk.startswith("n'"):
                result.append("ん")
                chunk = chunk[2:]
            elif chunk[0] == "n" and (len(chunk) == 1 or chunk[1] not in "aiueoyn"):
                result.append("ん")
                chunk = chunk[1:]
            elif len(chunk) > 1 and chunk[0] == chunk[1] and chunk[0] not in "aeioun":
                result.append("っ")
                chunk = chunk[1:]
            elif chunk.startswith("nn"):
                result.append("ん")
                chunk = chunk[2:] if len(chunk) == 2 else chunk[1:]
            else:
                key = next((chunk[:n] for n in (3, 2, 1) if chunk[:n] in ROMAJI), None)
                if key is None:
                    return ""
                result.append(ROMAJI[key])
                chunk = chunk[len(key):]
    return "".join(result)


def phonetic(text):
    """长音记法统一用于比较，输出仍保留来源假名。"""
    vowels = {kana[-1]: vowel for roma, kana in ROMAJI.items()
              if (vowel := {"a": "あ", "i": "い", "u": "う", "e": "え", "o": "お"}.get(roma[-1]))}
    result = ""
    for c in hira(text):
        if c == "ー" and result:
            c = vowels.get(result[-1], c)
        result += c
    return result.replace("ぢ", "じ").replace("づ", "ず")


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        following = [i]
        for j, y in enumerate(b, 1):
            following.append(min(following[-1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = following
    return row[-1]


def align_reading(tokens, supplied):
    """固定原文假名作锚点，汉字词允许变读；边界歧义或差异过大时回退。"""
    actual = reading_kana(supplied)
    if not actual or len(actual) > 300 or len(tokens) > 100:
        return None
    target = phonetic(actual)
    expected = []
    for token in tokens:
        if token.get("language") == "en":
            return None  # 英日混行不能把英语当作日语罗马音。
        surface = hira(token["text"])
        value = token.get("reading") if HAN.search(surface) else surface
        expected.append("".join(KANA.findall(hira(value or ""))))

    @lru_cache(maxsize=None)
    def solve(index, start):
        if index == len(tokens):
            return [(0, ())] if start == len(target) else []
        token, guess = tokens[index], phonetic(expected[index])
        candidates = []
        if HAN.search(token["text"]):
            # 送り仮名も固定する。漢字以外の部分を読みに吸収しない。
            pattern = "".join("[ぁ-ゖー]{1,24}" if HAN.search(part) else re.escape(phonetic(part))
                              for part in re.findall(r"[\u3400-\u9fff々]+|[^\u3400-\u9fff々]+", hira(token["text"])))
            for end in range(start + 1, min(len(target), start + max(12, len(guess) + 6)) + 1):
                value = target[start:end]
                if re.fullmatch(pattern, value):
                    cost = distance(guess, value) + (0.2 if value != guess else 0)
                    candidates.append((end, cost))
        else:
            options = {guess}
            if token.get("pos") == "助詞":
                options.add({"は": "わ", "へ": "え", "を": "お"}.get(guess, guess))
            candidates = [(start + len(value), 0) for value in options if target.startswith(value, start)]
        paths = []
        for end, cost in candidates:
            for remaining, path in solve(index + 1, end):
                paths.append((cost + remaining, (actual[start:end],) + path))
        paths.sort(key=lambda p: p[0])
        return paths[:2]

    paths = solve(0, 0)
    if not paths or paths[0][0] > max(6, sum(map(len, expected)) * .35):
        return None
    if len(paths) > 1 and paths[1][0] - paths[0][0] < .5:
        return None
    return paths[0][1]
