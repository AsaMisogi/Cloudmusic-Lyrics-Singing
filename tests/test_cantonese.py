"""离线粤拼、混合文字、修正隔离及持久化失败行为。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utatomo.language import Annotator


class CantoneseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.annotator = Annotator(Path(self.directory.name))

    def tearDown(self):
        self.directory.cleanup()

    def annotate(self, text, scope="test"):
        line = {"start": 1000, "text": text}
        self.annotator.enrich([line], scope)
        return line

    def test_simplified_traditional_and_tones(self):
        for text in ("廣東我", "广东我"):
            tokens = self.annotate(text)["cantoneseTokens"]
            self.assertEqual([t["reading"] for t in tokens], ["gwong2", "dung1", "ngo5"])

    def test_phrase_context_is_used_for_polyphonic_characters(self):
        tokens = self.annotate("開會我會唱歌")["cantoneseTokens"]
        self.assertEqual(tokens[1]["reading"], "wui2")
        self.assertEqual(tokens[3]["reading"], "wui5")

    def test_original_english_ipa_punctuation_and_unknown_preserved(self):
        text = "我 sing Hello，𠮷！"
        tokens = self.annotate(text)["cantoneseTokens"]
        self.assertEqual("".join(t["text"] for t in tokens), text)
        english = next(t for t in tokens if t["text"] == "sing")
        self.assertEqual(english["reading"], self.annotator.english_token("sing")["reading"])
        self.assertEqual(next(t for t in tokens if t["text"] == "𠮷")["reading"], "")

    def test_japanese_document_kanji_only_line_keeps_original_annotations(self):
        lines = [{"start": 0, "text": "君の光"}, {"start": 5000, "text": "世界"}]
        self.annotator.enrich(lines, "ja")
        self.assertTrue(all("cantoneseTokens" not in line for line in lines))
        self.assertEqual(lines[1]["tokens"][0]["reading"], "せかい")

    def test_translation_is_never_converted(self):
        line = {"start": 0, "text": "Sing with me", "translation": "我和你唱歌"}
        self.annotator.enrich([line])
        self.assertNotIn("cantoneseTokens", line)
        self.assertEqual(line["translation"], "我和你唱歌")

    def test_mostly_chinese_song_can_include_a_japanese_line(self):
        lines = [{"start": index*5000, "text": text} for index, text in enumerate(("我會唱歌", "我愛音樂", "君の光"))]
        self.annotator.enrich(lines)
        self.assertTrue(all("cantoneseTokens" in line for line in lines[:2]))
        self.assertNotIn("cantoneseTokens", lines[2])

    def test_correction_persists_isolated_from_japanese_and_other_scopes(self):
        line = self.annotate("我會唱歌")
        token = line["cantoneseTokens"][0]
        args = ("test", token["lineKey"], token["tokenStart"])
        self.annotator.correct("我", "ngo4", *args, reading_system="jyutping")
        self.annotator.enrich([line], "test")
        self.assertEqual(line["cantoneseTokens"][0]["reading"], "ngo4")
        self.assertNotEqual(line["tokens"][0]["reading"], "ngo4")
        fresh = Annotator(Path(self.directory.name))
        fresh.enrich([line], "test")
        self.assertEqual(line["cantoneseTokens"][0]["reading"], "ngo4")
        self.assertEqual(self.annotate("我會唱歌", "other")["cantoneseTokens"][0]["reading"], "ngo5")
        self.annotator.correct("我", "", *args, reading_system="jyutping")
        self.assertEqual(self.annotate("我會唱歌")["cantoneseTokens"][0]["reading"], "ngo5")

    def test_invalid_jyutping_does_not_save(self):
        with self.assertRaises(ValueError):
            self.annotator.correct("我", "ngoh", "test", "line", 0, "jyutping")
        self.assertFalse(self.annotator.scoped)

    def test_failed_correction_write_preserves_memory_and_disk(self):
        self.annotator.correct("我", "ngo4", "test", "line", 0, "jyutping")
        before = dict(self.annotator.scoped)
        content = self.annotator.scoped_path.read_text(encoding="utf-8")
        with patch.object(Path, "replace", side_effect=PermissionError("只读目录")):
            with self.assertRaises(PermissionError):
                self.annotator.correct("我", "ngo5", "test", "line", 0, "jyutping")
        self.assertEqual(before, self.annotator.scoped)
        self.assertEqual(content, self.annotator.scoped_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
