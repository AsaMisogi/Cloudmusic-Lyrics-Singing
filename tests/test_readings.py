import tempfile
import unittest
from pathlib import Path

from utatomo.language import Annotator
from utatomo.lyrics import align_pronunciation, parse_lyrics
from utatomo.matching import lyric_versions
from utatomo.readings import reading_kana


class ReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.annotator = Annotator(Path(cls.directory.name))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def line(self, text, reading, start=1000):
        return {"start": start, "text": text, "pronunciation": reading}

    def test_syllable_boundaries_gemination_and_macrons(self):
        self.assertEqual(reading_kana("shi n a i n'ya kitto shōnen"), "しんあいんやきっとしょうねん")
        self.assertEqual(reading_kana("ヒカリ"), "ひかり")
        self.assertEqual(reading_kana("love you"), "")

    def test_song_specific_reading_does_not_pollute_dictionary_cache(self):
        baseline = self.annotator.annotate("宇宙を抱いて")
        before = [dict(t) for t in baseline]
        line = self.line("宇宙を抱いて", "so ra wo i da i te")
        self.annotator.enrich([line], "song-a")
        self.assertEqual(line["readingSource"], "song")
        self.assertEqual(line["tokens"][0]["reading"], "そら")
        self.assertEqual(baseline, before)
        other = self.line("宇宙を抱いて", "u chu u wo i da i te")
        self.annotator.enrich([other], "song-b")
        self.assertEqual(other["tokens"][0]["reading"], "うちゅう")

    def test_bad_or_misaligned_readings_fall_back(self):
        for reading in ("", "this is English", "a shi ta wa a me", "�hi ka ri"):
            line = self.line("君の光を追いかけて", reading)
            self.annotator.enrich([line])
            self.assertEqual(line["readingSource"], "dictionary")

    def test_scoped_correction_persistence_and_revert(self):
        first = self.line("明日へ", "a su e")
        second = self.line("明日へ", "a shi ta e", 5000)
        self.annotator.enrich([first, second], "scoped-song")
        token = first["tokens"][0]
        args = ("scoped-song", token["lineKey"], token["tokenStart"])
        self.annotator.correct(token["text"], "みらい", *args)
        self.annotator.enrich([first, second], "scoped-song")
        self.assertEqual(first["tokens"][0]["reading"], "みらい")
        self.assertEqual(second["tokens"][0]["reading"], "あした")
        fresh = Annotator(Path(self.directory.name))
        fresh.enrich([first], "scoped-song")
        self.assertEqual(first["tokens"][0]["reading"], "みらい")
        self.annotator.enrich([first], "different-song")
        self.assertEqual(first["tokens"][0]["reading"], "あす")
        self.annotator.correct(token["text"], "", *args)
        self.annotator.enrich([first], "scoped-song")
        self.assertEqual(first["tokens"][0]["reading"], "あす")

    def test_reading_timestamps_no_shift_and_no_reuse(self):
        lines = parse_lyrics("[00:01]明日\n[00:02]世界\n[00:03]光")
        align_pronunciation(lines, "[00:01]a su\n[00:03]hi ka ri")
        self.assertNotIn("pronunciation", lines[1])
        self.assertEqual(lines[2]["pronunciation"], "hi ka ri")
        near = parse_lyrics("[00:01]明日\n[00:01.100]世界")
        align_pronunciation(near, "[00:01]a su")
        self.assertNotIn("pronunciation", near[1])

    def test_version_readings_stay_with_own_timeline(self):
        versions = lyric_versions({
            "lrc": {"lyric": "[00:01]宇宙"},
            "yrc": {"lyric": "[1000,1000](1000,1000,0)宇宙"},
            "romalrc": {"lyric": "[00:01]so ra"},
            "yromalrc": {"lyric": "[00:01]u chu u"},
        })
        self.assertIn("u chu u", versions[0]["pronunciation"])
        self.assertIn("so ra", versions[1]["pronunciation"])

    def test_verified_song_correction_overrules_two_wrong_sources(self):
        line = self.line("額に感じる澄んだ空気", "ga ku ni ka n ji ru su n da ku u ki")
        self.annotator.enrich([line], "netease:2154799261")
        self.assertEqual(line["tokens"][0]["reading"], "ひたい")
        self.assertIn("勘误", line["tokens"][0]["source"])
        self.assertFalse(line["tokens"][0]["readingConflict"])
        self.annotator.enrich([line], "netease:999")
        self.assertEqual(line["tokens"][0]["reading"], "がく")

    def test_inline_furigana_is_preserved_without_duplicating_plain_text(self):
        line = parse_lyrics("[00:01]逃(に)げ出(だ)したい") [0]
        self.assertEqual(line["text"], "逃げ出したい")
        self.annotator.enrich([line])
        self.assertEqual(line["tokens"][0]["reading"], "にげだし")
        self.assertEqual(line["tokens"][0]["source"], "原文括号注音")
        self.assertEqual(parse_lyrics("[00:01]君と（ずっと）歌う")[0]["text"], "君と（ずっと）歌う")

    def test_conflicting_readings_are_exposed_not_called_confirmed(self):
        line = self.line("宇宙を抱いて", "so ra wo i da i te")
        self.annotator.enrich([line])
        token = line["tokens"][0]
        self.assertTrue(token["readingConflict"])
        self.assertEqual({c["reading"] for c in token["readingCandidates"]}, {"そら", "うちゅう"})

    def test_manual_correction_remains_above_verified_correction(self):
        line = self.line("額に感じる澄んだ空気", "ga ku ni ka n ji ru su n da ku u ki")
        self.annotator.enrich([line], "netease:2154799261")
        token = line["tokens"][0]
        args = (token["scope"], token["lineKey"], token["tokenStart"])
        self.annotator.correct("額", "custom", *args)
        self.annotator.enrich([line], token["scope"])
        self.assertEqual(line["tokens"][0]["reading"], "custom")
        self.annotator.correct("額", "", *args)
        self.annotator.enrich([line], token["scope"])
        self.assertEqual(line["tokens"][0]["reading"], "ひたい")
