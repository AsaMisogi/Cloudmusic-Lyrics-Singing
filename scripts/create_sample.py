"""生成可自由分发的原创提示音轨，只用于验证播放器，不冒充歌曲录音。"""

import math
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "samples"
DEST.mkdir(exist_ok=True)
rate = 22050
notes = [261.63, 329.63, 392, 523.25, 440, 392, 329.63, 293.66]
with wave.open(str(DEST / "practice.wav"), "wb") as audio:
    audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
    frames = bytearray()
    for index in range(rate * 40):
        seconds = index / rate
        beat = seconds % 0.5
        frequency = notes[int(seconds * 2) % len(notes)]
        envelope = min(1, beat / 0.012) * math.exp(-beat * 10)
        value = int(
            4200
            * envelope
            * (
                math.sin(2 * math.pi * frequency * seconds)
                + 0.2 * math.sin(4 * math.pi * frequency * seconds)
            )
        )
        frames.extend(struct.pack("<h", value))
    audio.writeframes(frames)
original = [
    "朝の光を追いかけて",
    "新しい道を歩こう",
    "君と歌うこの歌を",
    "明日へそっと届けよう",
    "Let the morning light come in",
    "Every little step begins",
    "Keep the music in your heart",
    "Sing again, a brand new start",
]
translated = [
    "追逐清晨的阳光",
    "走上崭新的道路吧",
    "与你一起唱响的这首歌",
    "把它轻轻传递到明天",
    "让晨光照进来",
    "每一小步都是开始",
    "把音乐留在心里",
    "再次歌唱，迎接新的开始",
]
for suffix, rows in [(".lrc", original), (".zh.lrc", translated)]:
    (DEST / ("practice" + suffix)).write_text(
        "\n".join(f"[00:{i * 5:02d}.000]{row}" for i, row in enumerate(rows)),
        encoding="utf-8",
    )
