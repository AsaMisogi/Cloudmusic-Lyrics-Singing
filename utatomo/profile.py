"""便携资料：在线快照、校验、下次启动恢复。备份内的路径不能指定写入位置。"""

import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

FILES = (
    "settings.json",
    "updates.json",
    "desktop.json",
    "song-overrides.json",
    "overrides.json",
    "practice.json",
)
DB = "library.sqlite3"


def read_map(path):
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 应为 JSON 对象。")
    return value


def write_map(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def export_backup(path, data, db, display):
    # 在线快照包含已提交的数据，不直接复制正在使用的数据库文件。
    with tempfile.TemporaryDirectory(dir=path.parent) as folder:
        root = Path(folder)
        with closing(sqlite3.connect(root / DB)) as target:
            db.backup(target)
        with zipfile.ZipFile(root / "backup.zip", "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(
                "manifest.json", json.dumps({"format": "utatomo/1", "display": display})
            )
            z.write(root / DB, DB)
            for name in FILES:
                if (data / name).exists():
                    z.write(data / name, name)
            for f in [
                *(data / "cache").glob("netease-*.json"),
                *(data / "cache").glob("translation-*.json"),
            ]:
                z.write(f, "cache/" + f.name)
        (root / "backup.zip").replace(path)


def stage_backup(path, data):
    """发布待恢复目录之前验证完整文件；取消、损坏或磁盘写满不会改变当前资料。"""
    with tempfile.TemporaryDirectory(dir=data) as folder:
        root = Path(folder) / "validated"
        root.mkdir()
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if (
                len(names) != len(set(names))
                or sum(i.file_size for i in z.infolist()) > 512 * 1024**2
            ):
                raise ValueError("备份存在重复条目或超过 512 MB。")
            for name in names:
                if name not in (*FILES, DB, "manifest.json") and not re.fullmatch(
                    r"cache/(?:netease|translation)-[\w-]+\.json", name
                ):
                    raise ValueError("备份包含无法识别的文件。")
                dest = root / name
                dest.parent.mkdir(exist_ok=True)
                with z.open(name) as src, dest.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                if name.endswith(".json"):
                    if name.startswith("cache/"):
                        json.loads(dest.read_text(encoding="utf-8"))
                    else:
                        read_map(dest)
        manifest = read_map(root / "manifest.json")
        if (
            manifest.get("format") != "utatomo/1"
            or not isinstance(manifest.get("display"), dict)
            or DB not in names
        ):
            raise ValueError("不是完整的咏伴备份。")
        with closing(sqlite3.connect(root / DB)) as db:
            if (
                db.execute("pragma integrity_check").fetchone()[0] != "ok"
                or db.execute("pragma user_version").fetchone()[0] != 2
            ):
                raise ValueError("曲库损坏或版本不兼容。")
            for table, fields in [
                (
                    "tracks",
                    "key,source,path,songId,title,artist,album,duration,search,favorite,added,lastPlayed,inLibrary",
                ),
                ("playlists", "id,name,nameKey,created"),
                ("playlist_tracks", "playlistId,trackKey,position"),
            ]:
                db.execute(f"SELECT {fields} FROM {table} LIMIT 0")
        root.rename(data / "pending-restore")


def apply_pending(data):
    # 单实例锁内、数据库打开前应用；中途断电时，待恢复源仍在，下次可重复执行。
    root = data / "pending-restore"
    if not root.exists():
        return
    for name in (
        *FILES,
        DB,
        *(p.relative_to(root).as_posix() for p in (root / "cache").glob("*.json")),
    ):
        dest = data / name
        if (root / name).is_file():
            dest.parent.mkdir(exist_ok=True)
            temp = dest.with_suffix(".restore-tmp")
            shutil.copyfile(root / name, temp)
            temp.replace(dest)
        else:
            dest.unlink(missing_ok=True)
    write_map(
        data / "restored-display.json", read_map(root / "manifest.json")["display"]
    )
    shutil.rmtree(root)
