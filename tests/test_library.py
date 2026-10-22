"""曲库事务、播放身份与文件引用回归；不运行真实播放器或访问外网。"""
import tempfile
import sqlite3
from contextlib import closing
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from utatomo.app import Bridge
from utatomo.client_launcher import play_cloud_song
from utatomo.library import LibraryStore, cloud_track, local_track


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = LibraryStore(self.root)
        self.audio = self.root / "晨光 Hello.wav"
        self.audio.write_bytes(b"fixture")
        self.local = local_track(self.audio, "晨光 Hello", "本地歌手", 40000)
        self.cloud = cloud_track({"songId": "123", "title": "海闊天空", "artist": "歌手", "album": "练唱", "duration": 80000})

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def rows(self, **options):
        return self.store.query(options)["tracks"]

    def test_played_order_deduplicates_and_survives_restart(self):
        with patch.object(self.store, "_now", return_value=1000):
            self.store.played(self.local)
            self.store.played(self.cloud)
            self.store.played(self.local)
        self.assertEqual(self.rows(view="recent")[0]["key"], self.local["key"])
        self.assertEqual({row["key"] for row in self.rows(view="recent")}, {self.local["key"], self.cloud["key"]})
        self.store.close()
        self.store = LibraryStore(self.root)
        self.assertEqual(len(self.rows(view="recent")), 2)
        self.assertEqual(self.rows(view="favorites"), [])

    def test_import_is_deduplicated_and_not_history(self):
        self.store.add([self.local, self.cloud, self.local])
        self.assertEqual(len(self.rows(view="favorites")), 2)
        self.assertEqual(self.rows(view="recent"), [])
        self.assertEqual(len(self.rows(view="favorites", source="cloud")), 1)

    def test_normalized_local_identity_and_source_isolation(self):
        other = local_track(self.audio.parent / "." / self.audio.name)
        self.assertEqual(self.local["key"], other["key"])
        self.assertNotEqual(cloud_track({"songId": "123"})["key"], self.local["key"])
        with self.assertRaises(ValueError):
            cloud_track({"songId": "123&action=delete"})

    def test_search_unicode_multiword_and_literal_wildcards(self):
        self.store.add([self.local, self.cloud])
        self.assertEqual(len(self.rows(view="favorites", query="ＨＥＬＬＯ 晨光")), 1)
        self.assertEqual(len(self.rows(view="favorites", query="练唱 歌手")), 1)
        self.assertEqual(self.rows(view="favorites", query="%"), [])
        self.assertEqual(self.rows(view="favorites", query="_' OR 1=1--"), [])

    def test_mixed_playlist_rename_and_duplicate_membership(self):
        playlist = self.store.create_playlist(" 通勤练唱 ")
        self.store.add([self.local, self.cloud], playlist)
        self.store.membership(playlist, self.local["key"])
        self.assertEqual([row["key"] for row in self.rows(view="playlist", playlistId=playlist)], [self.local["key"], self.cloud["key"]])
        self.store.rename_playlist(playlist, "每天一首")
        self.assertEqual(self.store.query({})["playlists"][0]["name"], "每天一首")
        with self.assertRaises(ValueError):
            self.store.create_playlist("每天一首")
        with self.assertRaises(ValueError):
            self.store.rename_playlist(playlist, " ")

    def test_clear_history_does_not_delete_favorites_playlists_or_file(self):
        playlist = self.store.create_playlist("练唱")
        self.store.add([self.local], playlist)
        self.store.played(self.local)
        self.store.played(self.cloud)
        self.store.clear_history("local")
        self.assertEqual(len(self.rows(view="recent")), 1)
        self.assertEqual(len(self.rows(view="playlist", playlistId=playlist)), 1)
        self.store.clear_history()
        self.assertEqual(self.rows(view="recent"), [])
        self.assertTrue(self.audio.is_file())
        self.assertEqual(len(self.rows(view="favorites")), 1)

    def test_removal_contracts_keep_other_references(self):
        playlist = self.store.create_playlist("练唱")
        self.store.add([self.local], playlist)
        self.store.played(self.local)
        self.store.favorite(self.local["key"], False)
        self.assertEqual(len(self.rows(view="playlist", playlistId=playlist)), 1)
        self.store.membership(playlist, self.local["key"], False)
        self.assertEqual(len(self.rows(view="recent")), 1)
        self.store.remove(self.local["key"], history_only=True)
        self.assertEqual(self.rows(view="recent"), [])
        self.assertTrue(self.audio.is_file())

    def test_delete_playlist_preserves_favorites_and_audio(self):
        playlist = self.store.create_playlist("练唱")
        self.store.add([self.local], playlist)
        self.store.delete_playlist(playlist)
        self.assertEqual(len(self.rows(view="favorites")), 1)
        self.assertTrue(self.audio.is_file())

    def test_invalid_playlist_rolls_back_whole_import(self):
        with self.assertRaises(ValueError):
            self.store.add([self.cloud], "missing")
        self.assertEqual(self.rows(view="favorites"), [])

    def test_history_limit_does_not_prune_collection(self):
        playlist = self.store.create_playlist("永久保留")
        self.store.add([self.cloud], playlist)
        with patch("utatomo.library.HISTORY_LIMIT", 2):
            for song_id in ("123", "456", "789"):
                self.store.played(cloud_track({"songId": song_id}))
        self.assertEqual(len(self.rows(view="recent", source="cloud")), 2)
        self.assertEqual(len(self.rows(view="playlist", playlistId=playlist)), 1)

    def test_missing_file_and_relink_merge_references(self):
        playlist = self.store.create_playlist("练唱")
        self.store.add([self.local], playlist)
        self.store.played(self.local)
        self.audio.unlink()
        self.assertFalse(self.rows(view="recent")[0]["available"])
        replacement = self.root / "新的位置.wav"
        replacement.write_bytes(b"fixture")
        self.store.add([local_track(replacement)])
        key = self.store.relink(self.local["key"], replacement)
        self.assertEqual(len(self.rows(view="favorites")), 1)
        self.assertEqual(self.rows(view="playlist", playlistId=playlist)[0]["key"], key)
        self.assertEqual(self.rows(view="recent")[0]["key"], key)
        self.assertTrue(self.rows(view="recent")[0]["available"])

    def test_pagination_and_out_of_range_clamp(self):
        self.store.add([cloud_track({"songId": str(i), "title": f"歌{i}"}) for i in range(1, 66)])
        first = self.store.query({"view": "favorites"})
        second = self.store.query({"view": "favorites", "page": 99})
        self.assertEqual(first["total"], 65)
        self.assertEqual(len(first["tracks"]), 50)
        self.assertEqual(second["page"], 1)
        self.assertEqual(len(second["tracks"]), 15)

    def test_unresolved_media_identity_is_not_a_lyric_candidate(self):
        media = cloud_track({"title": "当前音频", "artist": "歌手"})
        self.store.played(media)
        self.assertEqual(media["songId"], "")
        self.assertFalse(self.rows(view="recent")[0]["available"])
        bridge = SimpleNamespace(mode="cloud", identity="playing", song_id="wrong-lyric-id", metadata={"title": "当前音频", "songId": "123"})
        self.assertEqual(Bridge._current_library_track(bridge)["songId"], "123")

    def test_confirmed_cloud_id_merges_unresolved_history_and_playlist(self):
        unresolved = cloud_track({"title": "海闊天空", "artist": "歌手", "album": "练唱"})
        playlist = self.store.create_playlist("最近练过")
        self.store.add([unresolved], playlist)
        self.store.favorite(unresolved["key"], True)
        self.store.played(unresolved)
        self.store.played(self.cloud)
        self.assertEqual(len(self.rows(view="recent")), 1)
        self.assertTrue(self.rows(view="recent")[0]["available"])
        self.assertEqual(self.rows(view="playlist", playlistId=playlist)[0]["key"], "cloud:123")
        self.assertTrue(self.store.track("cloud:123")["favorite"])

    def test_backend_records_only_once_per_track_not_per_poll(self):
        bridge = SimpleNamespace(library=self.store, last_history_key="", _send_library=Mock(), _current_library_track=Mock(return_value=self.local), send=Mock())
        Bridge._record_played(bridge)
        Bridge._record_played(bridge)
        self.assertEqual(len(self.rows(view="recent")), 1)
        bridge._send_library.assert_called_once()

    def test_stale_cloud_launch_failure_does_not_cancel_newer_switch(self):
        bridge = SimpleNamespace(generation=0, cloud_play_request={"songId": "456"}, send=Mock())
        Bridge._receive(bridge, "result", {"kind": "failure", "generation": None,
            "data": {"task": "libraryPlay", "message": "旧请求失败"}, "extra": {"songId": "123"}})
        self.assertEqual(bridge.cloud_play_request["songId"], "456")
        bridge.send.assert_not_called()

    def test_background_play_never_starts_or_activates_client(self):
        fake_exe = self.root / "cloudmusic.exe"
        fake_exe.write_bytes(b"fixture")
        with patch("utatomo.client.ClientConnection") as connection, patch("utatomo.client_launcher.subprocess.Popen") as popen:
            play_cloud_song(str(self.root), "123")
            connection.return_value.connect.assert_called_once()
            connection.return_value.command.assert_called_once_with("playSong", "123")
            connection.return_value.close.assert_called_once()
            with self.assertRaises(ValueError):
                play_cloud_song(str(self.root), "123 & arbitrary")
            popen.assert_not_called()

    def test_background_failure_has_no_foreground_fallback(self):
        (self.root / "cloudmusic.exe").touch()
        with patch("utatomo.client.ClientConnection") as connection, patch("utatomo.client_launcher.subprocess.Popen") as popen:
            connection.return_value.connect.side_effect = ConnectionError("offline")
            with self.assertRaisesRegex(ValueError, "连接客户端"):
                play_cloud_song(str(self.root), "123")
            connection.return_value.close.assert_called_once()
            connection.return_value.command.assert_not_called()
            popen.assert_not_called()

    def test_loved_is_independent_of_library_and_playlists(self):
        playlist = self.store.create_playlist("测试")
        self.store.add([self.local, self.cloud], playlist)
        self.assertEqual(self.rows(view="loved"), [])
        self.store.favorite(self.local["key"], True)
        self.assertEqual(self.rows(view="loved")[0]["key"], self.local["key"])
        self.store.favorite(self.local["key"], False)
        self.assertEqual(self.rows(view="loved"), [])
        self.assertEqual(len(self.rows(view="favorites")), 2)
        self.assertEqual(len(self.rows(view="playlist", playlistId=playlist)), 2)
        self.store.remove(self.local["key"])
        self.assertEqual(len(self.rows(view="favorites")), 1)
        self.assertEqual(len(self.rows(view="playlist", playlistId=playlist)), 1)

    def test_schema_one_migration_preserves_existing_hearts_and_members(self):
        playlist = self.store.create_playlist("旧歌单")
        self.store.add([self.local, self.cloud], playlist)
        self.store.favorite(self.cloud["key"], True)
        # 还原上一版真实表形状，再走正式启动迁移；不靠手填新字段冒充兼容。
        self.store.db.execute("ALTER TABLE tracks DROP COLUMN inLibrary")
        self.store.db.execute("PRAGMA user_version=1")
        self.store.db.commit()
        self.store.close()
        self.store = LibraryStore(self.root)
        self.assertEqual(self.store.db.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(len(self.rows(view="favorites")), 2)
        self.assertEqual([t["key"] for t in self.rows(view="loved")], [self.cloud["key"]])
        self.assertEqual(len(self.rows(view="playlist", playlistId=playlist)), 2)

    def test_current_unrecorded_track_can_enter_playlist_without_heart(self):
        playlist = self.store.create_playlist("当前歌曲")
        bridge = SimpleNamespace(library=self.store, library_query={}, _send_library=Mock(), send=Mock(),
                                 _current_library_track=Mock(return_value=self.local))
        Bridge._library_action(bridge, "libraryMembership", {"key": self.local["key"], "current": True, "playlistId": playlist, "enabled": True})
        self.assertEqual(len(self.rows(view="playlist", playlistId=playlist)), 1)
        self.assertEqual(self.rows(view="loved"), [])
        self.assertEqual(self.rows(view="recent"), [])
        with self.assertRaisesRegex(ValueError, "已改变"):
            Bridge._library_action(bridge, "libraryMembership", {"key": "old", "current": True, "playlistId": playlist})

    def test_failed_migration_rolls_back_column_and_retries_on_next_start(self):
        self.store.add([self.cloud])
        self.store.favorite(self.cloud["key"], True)
        self.store.db.execute("ALTER TABLE tracks DROP COLUMN inLibrary")
        self.store.db.execute("PRAGMA user_version=1")
        self.store.db.commit()
        self.store.close()
        class FailBackfill(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql.startswith("UPDATE tracks SET inLibrary=1"):
                    raise sqlite3.OperationalError("模拟回填写入失败")
                return super().execute(sql, *args)
        connect = sqlite3.connect
        with patch("utatomo.library.sqlite3.connect", side_effect=lambda path: connect(path, factory=FailBackfill)):
            with self.assertRaisesRegex(sqlite3.OperationalError, "模拟回填"):
                LibraryStore(self.root)
        with closing(connect(self.root / "library.sqlite3")) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertNotIn("inLibrary", [r[1] for r in db.execute("PRAGMA table_info(tracks)")])
        self.store = LibraryStore(self.root)
        self.assertEqual(self.rows(view="loved")[0]["key"], self.cloud["key"])


if __name__ == "__main__":
    unittest.main()
