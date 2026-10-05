r"""手动联网验收；不会控制网易云，也不会输出歌词全文。

运行：.venv\Scripts\python.exe scripts\verify_online.py
结果保存到 output/online-result.json。公开接口不可用时保留具体失败项。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from utatomo.lyrics import parse_lyrics, align_translation
from utatomo.services import Services

services = Services(ROOT / "data")
results = {}
song_id = "4884152"
payload = services.lyrics(song_id)
lines = parse_lyrics(payload["lrc"]["lyric"])
align_translation(lines, payload.get("tlyric", {}).get("lyric", ""))
results["originalLines"] = len(lines)
results["translatedLines"] = sum(bool(line["translation"]) for line in lines)
results["japaneseDictionary"] = bool(services.dictionary("光", "ja")["definitions"])
results["englishDictionary"] = bool(services.dictionary("light", "en")["definitions"])
try:
    results["machineTranslation"] = services.translate("Let the morning light come in")
except Exception as exc:
    results["machineTranslationError"] = str(exc)
audio_path = services.practice_audio(song_id)
results["audioBytes"] = Path(audio_path).stat().st_size

app = QCoreApplication(sys.argv)
player = QMediaPlayer()
audio = QAudioOutput()
audio.setVolume(0)
player.setAudioOutput(audio)
player.setSource(QUrl.fromLocalFile(audio_path))


def seek():
    results["durationMs"] = player.duration()
    results["seekable"] = player.isSeekable()
    player.setPosition(12510)
    QTimer.singleShot(400, finish)


def finish():
    results["seekPositionMs"] = player.position()
    results["seekPassed"] = abs(player.position() - 12510) <= 30
    player.stop()
    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output/online-result.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)
    app.quit()


QTimer.singleShot(2000, seek)
QTimer.singleShot(10000, app.quit)
app.exec()
raise SystemExit(
    0
    if results.get("seekPassed")
    and results.get("translatedLines")
    and results.get("machineTranslation")
    else 1
)
