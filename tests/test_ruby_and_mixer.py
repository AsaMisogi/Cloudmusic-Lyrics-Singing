"""双端共享的注音边界、手动练唱稿以及音量目标隔离。"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from utatomo.language import ruby_parts
from utatomo.mixer import choose_session, cloud_level
from utatomo.ruby_ink import lyric_cells
from utatomo.karaoke import spaced_phrase


class RubyTests(unittest.TestCase):
    def test_kana_anchors(self):
        for text, sound, parts in [
            ("逃げ出し", "にげだし", ["に", "", "だ", ""]),
            ("取り戻す", "とりもどす", ["と", "", "もど", ""]),
            ("飛び出し", "とびだし", ["と", "", "だ", ""]),
            ("お祝い", "おいわい", ["", "いわ", ""]),
            ("明日", "あした", ["あした"]),
            ("食べる", "たべる", ["た", ""]),
            ("取あ戻", "かあああか", ["かあああか"]),  # 内部锚点有多解，不择一硬拆。
        ]:
            with self.subTest(text=text):
                result = ruby_parts(text, sound)
                self.assertEqual([x["reading"] for x in result], parts)
                self.assertEqual("".join(x["text"] for x in result), text)

    def test_cells_keep_ipa_and_manual_alignment(self):
        line = {
            "text": "青空",
            "tokens": [
                {"text": "青空", "reading": "そら", "romaji": "sora", "language": "ja"}
            ],
        }
        self.assertEqual(lyric_cells(line, True), ([("青空", "sora")], ""))
        self.assertEqual(
            lyric_cells(
                dict(line, breaks=[1], segments={"original": "青/空", "kana": "そ/ら"})
            ),
            ([("青", "そ"), ("/", ""), ("空", "ら")], ""),
        )
        eng = {
            "text": "Sing",
            "tokens": [{"text": "Sing", "reading": "sɪŋ", "language": "en"}],
        }
        self.assertEqual(lyric_cells(eng), ([("Sing", "sɪŋ")], ""))
        zh = {
            "text": "我",
            "cantoneseTokens": [{"text": "我", "reading": "ngo5", "language": "zh"}],
        }
        self.assertEqual(lyric_cells(zh), ([("我", "ngo5")], ""))

    def test_phrase_gaps_are_visual_only(self):
        # 原文自带的斜线不处理，补充平面汉字占两个 Qt 游标；第二个斜线才是练唱断点。
        self.assertEqual(spaced_phrase("𠮷/A/B", {3}), ("𠮷/A\u2002/\u2002B", [0,2,3,4,7,8]))
        cells, _ = lyric_cells({"text":"青空","breaks":[1],"tokens":[
            {"text":"青","reading":"あお"},{"text":"空","reading":"そら"}]})
        self.assertEqual(cells, [("青","あお"),("/",""),("空","そら")])


class MixerTests(unittest.TestCase):
    def test_writes_only_to_selected_session(self):
        def session(name, path, active, key):
            proc = SimpleNamespace(
                name=lambda: name, exe=lambda: str(Path(path) / name)
            )
            return SimpleNamespace(Process=proc, State=active, InstanceIdentifier=key)

        muted = session("cloudmusic.exe", "A", 0, "paused")
        playing = session("cloudmusic.exe", "A", 1, "selected")
        elsewhere = session("cloudmusic.exe", "B", 1, "another installation")
        browser = session("browser.exe", "A", 1, "unrelated")
        sessions = [muted, elsewhere, browser, playing]
        self.assertIs(choose_session(sessions, "A"), playing)
        self.assertIsNone(choose_session(sessions, "A", "unrelated"))
        self.assertIsNone(choose_session(sessions, "A", "expired"))

    def test_session_write_reads_back_and_unmutes_only_the_selected_client(self):
        # 系统 COM 枚举替换为一个离线端点，真实用户客户端保持原音量。经过正式的选会话和写入路径。
        level = Mock()
        level.GetMasterVolume.return_value = 0.34
        level.GetMute.side_effect = [True, False]
        session = SimpleNamespace(
            Process=SimpleNamespace(
                name=lambda: "cloudmusic.exe", exe=lambda: "cloudmusic.exe"
            ),
            State=1,
            InstanceIdentifier="session",
            SimpleAudioVolume=level,
        )
        with (
            patch("pycaw.utils.AudioUtilities.GetDeviceEnumerator") as enum,
            patch("pycaw.utils.AudioSession", return_value=session),
        ):
            devices = enum.return_value.EnumAudioEndpoints.return_value
            devices.GetCount.return_value = 1
            items = devices.Item.return_value.Activate.return_value.QueryInterface.return_value.GetSessionEnumerator.return_value
            items.GetCount.return_value = 1
            self.assertEqual(
                cloud_level("", "session", 34), {"percent": 34, "target": "session"}
            )
            level.SetMasterVolume.assert_called_once_with(0.34, None)
            level.SetMute.assert_called_once_with(False, None)
            self.assertIn("message", cloud_level("", "gone", 95))
            self.assertEqual(level.SetMasterVolume.call_count, 1)
