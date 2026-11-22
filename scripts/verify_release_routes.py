"""发布后分别使用固定线路验签 latest，下载两种附件；不会安装或改动运行中的软件。"""
from tempfile import TemporaryDirectory
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from utatomo.portable_updates import CHUNK, FEED, REPOSITORY_URL, fetch, receive_asset, verify_feed


def verify(version, directory):
    errors = []
    for source in ("mirror", "github"):
        try:
            m = fetch(FEED, source, lambda r, _: verify_feed(r.read(4 * CHUNK + 1),
                      directory / "Utatomo/_internal/update/Utatomo-Update.exe"), lambda *_: None)
            if m["version"] != version:
                raise ValueError(f"latest 仍为 {m['version']}")
            for asset in (m["patch"], m["full"]):
                url = f"{REPOSITORY_URL}/releases/download/v{version}/{asset['name']}"
                with TemporaryDirectory() as tmp:
                    fetch(url, source, lambda r, label: receive_asset(r, Path(tmp) / "download",
                          asset, label, lambda *_: None, threading.Event()), lambda *_: None)
                print(f"{source} OK: {asset['name']} ({asset['size']} bytes)", flush=True)
        except Exception as exc:
            errors.append(f"{source}: {exc}")
    if errors:
        raise SystemExit("\n".join(errors))


if __name__ == "__main__":
    verify(sys.argv[1], Path(sys.argv[2]).resolve())
