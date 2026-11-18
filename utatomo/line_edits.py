"""把练唱稿投影到歌词行；歌曲原文、用户分段和音轨时间是三个不同的数据。"""

from copy import deepcopy


def apply_text(line, fields):
    """只插斜线时保留词典、逐字时间及原文注音；换字才重算读音，退到行级时间。

    源行保留到恢复操作。存盘的只有按原文定位的差异，不复制整份带词典的歌词。
    """
    base = deepcopy(line.get("editSource", line))
    edit = fields.get("original", "")
    if not edit:
        base["segments"] = fields
        return base
    plain = edit.replace("/", "")
    cuts, n = [], 0
    for char in edit:
        if char == "/":
            cuts.append(n)
        else:
            n += 1
    result = dict(base, editSource=base, breaks=cuts, segments=fields)
    if plain != base["text"]:
        for key in (
            "tokens",
            "cantoneseTokens",
            "inlineReadings",
            "pronunciation",
            "readingReferences",
        ):
            result.pop(key, None)
        result.update(
            text=plain, words=[], timing="none" if base["start"] is None else "line"
        )
    return result
