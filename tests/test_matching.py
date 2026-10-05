"""覆盖容易误配的同名歌曲、时长差异和不完整逐字歌词。"""
import unittest

from utatomo.matching import lyric_versions, rank_songs


class MatchingTests(unittest.TestCase):
    def test_album_and_duration_select_recording(self):
        songs = [
            {"id": 1, "title": "Song", "artist": "Singer", "album": "Live", "duration": 240000},
            {"id": 2, "title": "Song", "artist": "Singer", "album": "Studio", "duration": 180000},
            {"id": 3, "title": "Song (Live)", "artist": "Singer", "duration": 180000},
        ]
        self.assertEqual(rank_songs(songs, "Song", "Singer", "Studio", 180000)[0]["id"], 2)

    def test_queue_wins_and_duplicate_retains_origin(self):
        songs = [{"id": 1, "title": "Song", "artist": "Singer", "fromQueue": True},
                 {"id": 1, "title": "Song", "artist": "Singer"},
                 {"id": 2, "title": "Song", "artist": "Singer"}]
        ranked = rank_songs(songs, "Song", "Singer")
        self.assertEqual(len(ranked), 2)
        self.assertTrue(ranked[0]["fromQueue"])

    def test_complete_word_timing_preferred_and_translations_paired(self):
        payload = {"yrc": {"lyric": "[1000,2000](1000,2000,0)Hello world"},
                   "lrc": {"lyric": "[00:01]Hello world"},
                   "ytlrc": {"lyric": "[00:01]你好"}, "tlyric": {"lyric": "[00:01]世界"}}
        versions = lyric_versions(payload)
        self.assertEqual([v["id"] for v in versions], ["yrc", "lrc"])
        self.assertIn("你好", versions[0]["translation"])
        self.assertIn("世界", versions[1]["translation"])

    def test_incomplete_yrc_does_not_replace_full_lrc(self):
        payload = {"yrc": {"lyric": "[1000,100](1000,100,0)H"},
                   "lrc": {"lyric": "[00:01]Hello world\n[00:03]Full song"}}
        self.assertEqual(lyric_versions(payload)[0]["id"], "lrc")

    def test_empty_versions(self):
        self.assertEqual(lyric_versions({"yrc": None, "lrc": {"lyric": "[00:00]"}}), [])

    def test_timed_preferred_to_untimed(self):
        payload = {"yrc": {"lyric": "Hello world"}, "lrc": {"lyric": "[00:01]Hello world"}}
        self.assertEqual(lyric_versions(payload)[0]["id"], "lrc")
