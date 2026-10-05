"""覆盖歌曲文件中常见的时间、编码与双语对齐边界。"""

import tempfile
import unittest
from pathlib import Path
from utatomo.lyrics import active_line, align_translation, parse_lyrics, read_text


class LyricTests(unittest.TestCase):
    def test_fraction_multiple_tags_and_offset(self):
        lines = parse_lyrics("[offset:-50]\n[00:01.2][01:02.034]歌\n[01:03.56]次")
        self.assertEqual([line["start"] for line in lines], [1150, 61984, 63510])
        self.assertEqual(lines[0]["end"], 61984)

    def test_bilingual_and_identical_duplicate(self):
        lines = parse_lyrics("[00:01]君と\n[00:01]与你\n[00:01]君と\n[00:04]歌う")
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["translation"], "与你")

    def test_yrc_and_enhanced_lrc(self):
        yrc = parse_lyrics("[1000,900](1000,300,0)君(1300,600,0)と")
        self.assertEqual(yrc[0]["words"][1]["end"], 1900)
        self.assertEqual(yrc[0]["text"], "君と")
        enhanced = parse_lyrics(
            "[00:01]<00:01.000>Hello <00:01.500>world<00:02.000>\n[00:03]Next"
        )
        self.assertEqual(enhanced[0]["words"][1]["end"], 2000)
        self.assertEqual(enhanced[0]["text"], "Hello world")

    def test_translation_nearest_time_and_missing_line(self):
        lines = parse_lyrics("[00:01]a\n[00:03]b\n[00:05]c")
        align_translation(lines, "[00:01.150]甲\n[00:05.2]丙\n[00:50]不匹配")
        self.assertEqual([line["translation"] for line in lines], ["甲", "", "丙"])

    def test_untimed_never_fabricates_timestamps(self):
        lines = parse_lyrics("Hello\n世界")
        self.assertIsNone(lines[0]["start"])
        self.assertEqual(active_line(lines, 10000), -1)

    def test_exact_boundary_and_instrumental_gap(self):
        lines = parse_lyrics("[00:01]歌\n[00:03]\n[00:05]次")
        self.assertEqual(active_line(lines, 999), -1)
        self.assertEqual(active_line(lines, 1000), 0)
        self.assertEqual(active_line(lines, 3000), 1)
        self.assertEqual(lines[1]["text"], "")

    def test_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "song.lrc"
            for encoding in ("utf-8-sig", "utf-16", "gb18030"):
                file.write_bytes("[00:01]歌词".encode(encoding))
                self.assertEqual(read_text(file), "[00:01]歌词")


if __name__ == "__main__":
    unittest.main()
