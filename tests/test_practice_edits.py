"""校验时间轴投影、练唱稿恢复与客户端采样。无需打开真实播放器。"""

import unittest

from utatomo.karaoke import DesktopClock, sung_ranges
from utatomo.line_edits import apply_text


class PracticeTests(unittest.TestCase):
    def setUp(self):
        self.line = {
            "text": "青空",
            "start": 0,
            "end": 3000,
            "timing": "word",
            "tokens": [{"text": "青空", "reading": "そら"}],
            "words": [
                {"text": "青", "start": 200, "end": 800},
                {"text": "空", "start": 2000, "end": 2800},
            ],
        }

    def test_breath_keeps_original_inter_word_gap(self):
        result = apply_text(self.line, {"original": "青/空"})
        self.assertEqual(result["breaks"], [1])
        self.assertEqual(result["tokens"], self.line["tokens"])
        self.assertEqual(sung_ranges(result, 1500, 3000), [(0, 1), (1, 1)])
        self.assertEqual(sung_ranges(result, 2400, 3000), [(0, 1), (1, 1.5)])

    def test_rewrite_then_restore_word_timing(self):
        rewritten = apply_text(self.line, {"original": "晴れ/た"})
        self.assertEqual((rewritten["text"], rewritten["timing"]), ("晴れた", "line"))
        self.assertNotIn("tokens", rewritten)
        restored = apply_text(rewritten, {})
        self.assertEqual(restored["words"], self.line["words"])
        self.assertEqual(restored["tokens"][0]["reading"], "そら")

    def test_clock_does_not_rewind_on_identical_client_sample(self):
        clock = DesktopClock()
        sample = dict(
            position=1000, connected=True, playing=True, identity="A", duration=8000
        )
        clock.update(sample, 0)
        clock.update(sample, 450)
        self.assertEqual(clock.read(500), 1500)
        clock.update(dict(sample, playing=False, position=1500), 500)
        self.assertEqual(clock.read(1300), 1500)
        clock.update(dict(sample, position=6000), 1350)
        self.assertEqual(clock.read(1350), 6000)

    def test_free_text_has_no_invented_sung_range(self):
        self.assertEqual(
            sung_ranges({"start": None, "text": "自由阅读"}, 1500, 5000), []
        )
