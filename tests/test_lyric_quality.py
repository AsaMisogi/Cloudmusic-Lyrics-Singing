import tempfile
import unittest
from pathlib import Path

from utatomo.lyrics import parse_lyrics, active_line
from utatomo.matching import timing_issues, same_recording
from utatomo.services import Services


class LyricQualityTests(unittest.TestCase):
    broken = "[00:50.121]Beautiful world\n[00:50.172]迷わず君だけを見つめている\n[00:58.126]Beautiful boy"
    better = "[00:49.100]Beautiful world\n[00:52.200]迷(まよ)わず君(きみ)だけを見(み)つめている\n[00:57.460]Beautiful boy"

    def test_detects_the_reported_51ms_line(self):
        issues = timing_issues(parse_lyrics(self.broken))
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["interval"], 51)
        self.assertEqual(timing_issues(parse_lyrics(self.better)), [])

    def test_credits_and_real_word_timing_are_not_short_line_errors(self):
        self.assertEqual(timing_issues(parse_lyrics("[00:00]作曲 : Artist\n[00:00.020]作词 : Artist")), [])
        self.assertEqual(timing_issues(parse_lyrics("[1000,100](1000,100,0)hello\n[1100,1000](1100,1000,0)world")), [])

    def test_full_version_artist_and_duration_must_match(self):
        selected = {"title": "Song (Acoustic Mix)", "artist": "Singer", "duration": 310000}
        self.assertTrue(same_recording({**selected, "duration": 310056}, selected))
        for change in ({"title": "Song"}, {"title": "Song (Live)"}, {"artist": "Cover artist"}, {"duration": 330000}):
            self.assertFalse(same_recording({**selected, **change}, selected))

    def test_alternative_preserves_primary_and_does_not_swallow_chorus(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Services(Path(directory))
            service.lyrics = lambda song: {"lrc": {"lyric": self.broken if song == "1" else self.better}}
            selected = {"id": "1", "title": "Song (Mix)", "artist": "Singer", "duration": 310000}
            versions = service.lyric_options("1", [selected, {**selected, "id": "2"}], selected)
        self.assertEqual([v["id"] for v in versions], ["2:lrc", "lrc"])
        lines = parse_lyrics(versions[0]["text"])
        self.assertEqual(lines[active_line(lines, 51000)]["text"], "Beautiful world")
        self.assertEqual(lines[active_line(lines, 52200)]["text"], "迷わず君だけを見つめている")
        self.assertEqual(lines[1]["inlineReadings"][0]["reading"], "まよ")

    def test_missing_alternative_does_not_erase_original(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Services(Path(directory))
            def lyrics(song):
                if song != "1":
                    raise ValueError("unavailable")
                return {"lrc": {"lyric": self.broken}}
            service.lyrics = lyrics
            selected = {"id": "1", "title": "Song", "artist": "Singer", "duration": 310000}
            versions = service.lyric_options("1", [selected, {**selected, "id": "2"}], selected)
        self.assertEqual(len(versions), 1)
        self.assertTrue(versions[0]["timingIssues"])

    def test_different_lyrics_rejected_despite_matching_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Services(Path(directory))
            service.lyrics = lambda song: {"lrc": {"lyric": self.broken if song == "1" else "[00:01]Entirely different song"}}
            selected = {"id": "1", "title": "Song", "artist": "Singer", "duration": 310000}
            versions = service.lyric_options("1", [selected, {**selected, "id": "2"}], selected)
        self.assertEqual(len(versions), 1)
