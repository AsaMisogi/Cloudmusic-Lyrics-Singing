"""个人曲库与最近播放。只保存引用和元数据，不复制或删除音频。

SQLite 由 Qt 主线程独占；一次操作内的曲目、歌单关系和历史清理共同提交。
播放身份与歌词候选分开：网易云用真实歌曲 ID，本地文件用规范化绝对路径。
搜索使用绑定参数，分页后才检查文件存在性，避免大曲库阻塞每帧绘制。
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
import unicodedata
import uuid
from pathlib import Path

AUDIO_SUFFIXES = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus", ".aac", ".wma"}
PAGE_SIZE = 50
HISTORY_LIMIT = 500  # 两种来源各保留 500 首；收藏和歌单不受历史淘汰影响。


def search_text(value: str) -> str:
    """全半角、大小写归一化；不改变展示和歌曲身份。"""
    return unicodedata.normalize("NFKC", value).casefold()


def local_track(path: Path, title="", artist="", duration=0) -> dict:
    path = path.expanduser().resolve()
    if path.suffix.lower() not in AUDIO_SUFFIXES:
        raise ValueError("请选择支持的普通音频文件（MP3、FLAC、WAV 等）。")
    return {"key": "local:" + os.path.normcase(str(path)), "source": "local",
            "path": str(path), "songId": "", "title": title or path.stem,
            "artist": artist, "album": "", "duration": max(0, int(duration))}


def cloud_track(song: dict) -> dict:
    song_id = str(song.get("songId") or song.get("id") or "")
    if song_id and not re.fullmatch(r"[1-9]\d{0,19}", song_id):
        raise ValueError("网易云歌曲 ID 必须是有效的正整数。")
    title = str(song.get("title") or ("网易云歌曲 " + song_id)).strip()
    artist, album = str(song.get("artist") or ""), str(song.get("album") or "")
    # SMTC 可能没有 ID。仍保留真实播放记录，但不把手选的歌词版本当作播放对象。
    key = "cloud:" + song_id if song_id else "cloud-meta:" + "\x1f".join((title, artist, album))
    return {"key": key, "source": "cloud", "path": "", "songId": song_id,
            "title": title, "artist": artist, "album": album,
            "duration": max(0, int(song.get("duration") or 0))}


class LibraryStore:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(data_dir / "library.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        try:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError("曲库由较新版本创建，请使用新版咏伴打开。")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS tracks (
                    key TEXT PRIMARY KEY, source TEXT NOT NULL, path TEXT NOT NULL,
                    songId TEXT NOT NULL, title TEXT NOT NULL, artist TEXT NOT NULL,
                    album TEXT NOT NULL, duration INTEGER NOT NULL DEFAULT 0,
                    search TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0,
                    added INTEGER NOT NULL, lastPlayed INTEGER
                );
                CREATE TABLE IF NOT EXISTS playlists (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, nameKey TEXT NOT NULL UNIQUE,
                    created INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS playlist_tracks (
                    playlistId TEXT REFERENCES playlists(id) ON DELETE CASCADE,
                    trackKey TEXT REFERENCES tracks(key) ON DELETE CASCADE ON UPDATE CASCADE,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (playlistId, trackKey)
                );
                CREATE INDEX IF NOT EXISTS recent_tracks ON tracks(source, lastPlayed DESC);
            """)
            if version < 2:
                # 旧版把红心兼作曲库成员标记；升级保留全部既有红心和歌单。
                # 新版用独立字段保存曲库归属，取消最爱不再让歌曲消失。
                with self.db:
                    # sqlite3 不会为 DDL 自动 BEGIN；显式开启，确保加列和回填
                    # 一起回滚，写入失败后下次启动仍能从原 schema 重试。
                    self.db.execute("BEGIN")
                    self.db.execute("ALTER TABLE tracks ADD COLUMN inLibrary INTEGER NOT NULL DEFAULT 0")
                    self.db.execute("""UPDATE tracks SET inLibrary=1 WHERE favorite=1
                        OR key IN (SELECT trackKey FROM playlist_tracks)""")
                    self.db.execute("PRAGMA user_version = 2")
        except Exception:
            self.db.close()
            raise

    def _upsert(self, track: dict):
        fields = ("key", "source", "path", "songId", "title", "artist", "album", "duration")
        self.db.execute("""
            INSERT INTO tracks (key, source, path, songId, title, artist, album, duration, search, added)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET title=excluded.title, artist=excluded.artist,
                album=excluded.album, path=excluded.path,
                duration=CASE WHEN excluded.duration>0 THEN excluded.duration ELSE tracks.duration END,
                search=excluded.search
        """, [track[k] for k in fields] + [search_text(" ".join(str(track[k]) for k in
              ("title", "artist", "album", "path", "songId"))), self._now()])
        if track["source"] == "cloud" and track["songId"]:
            unresolved = cloud_track({**track, "songId": "", "id": ""})["key"]
            self._merge_reference(unresolved, track["key"])

    def _merge_reference(self, old_key, new_key):
        """补全真实歌曲 ID 或重新定位时，把旧引用合并到同一曲目。"""
        old = self.db.execute("SELECT favorite, inLibrary, lastPlayed FROM tracks WHERE key=?", (old_key,)).fetchone()
        if old is None:
            return
        self.db.execute("""UPDATE tracks SET favorite=MAX(favorite, ?), inLibrary=MAX(inLibrary, ?),
            lastPlayed=CASE WHEN ? IS NULL THEN lastPlayed
              ELSE MAX(COALESCE(lastPlayed, 0), ?) END WHERE key=?""",
                        (old["favorite"], old["inLibrary"], old["lastPlayed"], old["lastPlayed"], new_key))
        self.db.execute("""INSERT OR IGNORE INTO playlist_tracks
            SELECT playlistId, ?, position FROM playlist_tracks WHERE trackKey=?""", (new_key, old_key))
        self.db.execute("DELETE FROM tracks WHERE key=?", (old_key,))

    @staticmethod
    def _now():
        return time.time_ns() // 1_000_000

    def add(self, tracks: list[dict], playlist_id=""):
        """加入曲库，可同时加入歌单；最爱只由用户显式点击红心设置。"""
        with self.db:
            if playlist_id:
                self._playlist(playlist_id)
            for track in tracks:
                self._upsert(track)
                self.db.execute("UPDATE tracks SET inLibrary=1 WHERE key=?", (track["key"],))
                if playlist_id:
                    self._add_member(playlist_id, track["key"])

    def played(self, track: dict):
        with self.db:
            self._upsert(track)
            # 毫秒内的连续切歌也严格保序，不能因旧曲目 rowid 较小而排到后面。
            latest = self.db.execute("SELECT COALESCE(MAX(lastPlayed), 0) FROM tracks").fetchone()[0]
            self.db.execute("UPDATE tracks SET lastPlayed=? WHERE key=?", (max(self._now(), latest+1), track["key"]))
            self.db.execute("""
                UPDATE tracks SET lastPlayed=NULL WHERE source=? AND lastPlayed IS NOT NULL
                AND key NOT IN (SELECT key FROM tracks WHERE source=? AND lastPlayed IS NOT NULL
                                ORDER BY lastPlayed DESC, rowid DESC LIMIT ?)
            """, (track["source"], track["source"], HISTORY_LIMIT))
            self._prune()

    def _prune(self):
        # 历史清理绝不影响收藏及歌单。仅删除没有任何用途的数据库引用。
        self.db.execute("""DELETE FROM tracks WHERE inLibrary=0 AND favorite=0 AND lastPlayed IS NULL
                           AND key NOT IN (SELECT trackKey FROM playlist_tracks)""")

    def track(self, key: str) -> dict:
        row = self.db.execute("SELECT * FROM tracks WHERE key=?", (key,)).fetchone()
        if row is None:
            raise ValueError("这首歌已从列表移除，请刷新后重试。")
        return dict(row)

    def favorite(self, key: str, enabled: bool):
        with self.db:
            self.track(key)
            self.db.execute("UPDATE tracks SET favorite=? WHERE key=?", (int(enabled), key))
            if enabled:
                self.db.execute("UPDATE tracks SET inLibrary=1 WHERE key=?", (key,))
            self._prune()

    def create_playlist(self, name: str) -> str:
        name, normalized = self._name(name)
        playlist_id = uuid.uuid4().hex
        with self.db:
            if self.db.execute("SELECT 1 FROM playlists WHERE nameKey=?", (normalized,)).fetchone():
                raise ValueError("已有同名歌单，请换个名字。")
            self.db.execute("INSERT INTO playlists VALUES (?, ?, ?, ?)",
                            (playlist_id, name, normalized, self._now()))
        return playlist_id

    @staticmethod
    def _name(name):
        name = str(name).strip()
        if not name or len(name) > 80:
            raise ValueError("歌单名称请填写 1–80 个字符。")
        return name, search_text(name)

    def _playlist(self, playlist_id):
        if not self.db.execute("SELECT 1 FROM playlists WHERE id=?", (playlist_id,)).fetchone():
            raise ValueError("歌单已不存在，请重新选择。")

    def rename_playlist(self, playlist_id: str, name: str):
        name, normalized = self._name(name)
        with self.db:
            self._playlist(playlist_id)
            if self.db.execute("SELECT 1 FROM playlists WHERE nameKey=? AND id<>?", (normalized, playlist_id)).fetchone():
                raise ValueError("已有同名歌单，请换个名字。")
            self.db.execute("UPDATE playlists SET name=?, nameKey=? WHERE id=?", (name, normalized, playlist_id))

    def delete_playlist(self, playlist_id: str):
        with self.db:
            self._playlist(playlist_id)
            self.db.execute("DELETE FROM playlists WHERE id=?", (playlist_id,))
            self._prune()

    def _add_member(self, playlist_id, key):
        self.db.execute("""INSERT OR IGNORE INTO playlist_tracks VALUES (?, ?,
            (SELECT COALESCE(MAX(position), -1)+1 FROM playlist_tracks WHERE playlistId=?))""",
                        (playlist_id, key, playlist_id))

    def membership(self, playlist_id: str, key: str, enabled=True):
        with self.db:
            self._playlist(playlist_id)
            self.track(key)
            if enabled:
                self.db.execute("UPDATE tracks SET inLibrary=1 WHERE key=?", (key,))
                self._add_member(playlist_id, key)
            else:
                self.db.execute("DELETE FROM playlist_tracks WHERE playlistId=? AND trackKey=?", (playlist_id, key))
                self._prune()

    def remove(self, key: str, history_only=False):
        with self.db:
            self.track(key)
            if history_only:
                self.db.execute("UPDATE tracks SET lastPlayed=NULL WHERE key=?", (key,))
                self._prune()
            else:
                # 移出曲库时保留最近播放；所有歌单关系同时移除。
                self.db.execute("UPDATE tracks SET favorite=0, inLibrary=0 WHERE key=?", (key,))
                self.db.execute("DELETE FROM playlist_tracks WHERE trackKey=?", (key,))
                self._prune()

    def clear_history(self, source="all"):
        with self.db:
            if source in ("local", "cloud"):
                self.db.execute("UPDATE tracks SET lastPlayed=NULL WHERE source=?", (source,))
            else:
                self.db.execute("UPDATE tracks SET lastPlayed=NULL")
            self._prune()

    def relink(self, key: str, path: Path) -> str:
        old = self.track(key)
        if old["source"] != "local" or not path.is_file():
            raise ValueError("请选择存在的本地音频文件。")
        replacement = local_track(path, old["title"], old["artist"], old["duration"])
        new_key = replacement["key"]
        with self.db:
            if key == new_key:
                return key
            self._upsert(replacement)
            # 新路径已在曲库时合并收藏、历史与歌单，不产生重复记录或丢失引用。
            self._merge_reference(key, new_key)
        return new_key

    def query(self, options: dict) -> dict:
        source = options.get("source", "all")
        view = options.get("view", "recent")
        playlist_id = str(options.get("playlistId") or "")
        where, values = [], []
        if source in ("local", "cloud"):
            where.append("t.source=?")
            values.append(source)
        if view == "recent":
            where.append("t.lastPlayed IS NOT NULL")
        elif view == "playlist":
            self._playlist(playlist_id)
            where.append("t.key IN (SELECT trackKey FROM playlist_tracks WHERE playlistId=?)")
            values.append(playlist_id)
        elif view == "loved":
            where.append("t.favorite=1")
        else:
            where.append("t.inLibrary=1")
        for word in search_text(str(options.get("query") or "")).split():
            where.append("t.search LIKE ? ESCAPE '\\'")
            values.append("%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        predicate = " AND ".join(where)
        total = self.db.execute("SELECT COUNT(*) FROM tracks t WHERE " + predicate, values).fetchone()[0]
        page = max(0, min(int(options.get("page") or 0), max(0, (total-1)//PAGE_SIZE)))
        order = "t.lastPlayed DESC, t.rowid DESC" if view == "recent" else "t.added DESC, t.title"
        if view == "playlist":
            order = "(SELECT position FROM playlist_tracks WHERE trackKey=t.key AND playlistId=?)"
        rows = self.db.execute("SELECT t.* FROM tracks t WHERE " + predicate + " ORDER BY " + order + " LIMIT ? OFFSET ?",
                               values + ([playlist_id] if view == "playlist" else []) + [PAGE_SIZE, page*PAGE_SIZE])
        tracks = []
        for row in rows:
            track = dict(row)
            track.pop("search")
            track["available"] = Path(track["path"]).is_file() if track["source"] == "local" else bool(track["songId"])
            tracks.append(track)
        playlists = [dict(row) for row in self.db.execute("""SELECT p.id, p.name, COUNT(m.trackKey) count
            FROM playlists p LEFT JOIN playlist_tracks m ON p.id=m.playlistId GROUP BY p.id ORDER BY p.created, p.id""")]
        counts = {row["source"]: row["count"] for row in self.db.execute(
            "SELECT source, COUNT(*) count FROM tracks WHERE lastPlayed IS NOT NULL GROUP BY source")}
        return {"tracks": tracks, "playlists": playlists, "total": total, "page": page,
                "pageSize": PAGE_SIZE, "recentCounts": counts}

    def close(self):
        self.db.close()
