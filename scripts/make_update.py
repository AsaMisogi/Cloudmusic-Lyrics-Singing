"""从两份正式便携包制作增量，覆盖新增、修改和删除；不使用源码 diff 推测发行内容。"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP = {"Utatomo.exe", "README.md", "LICENSE", "THIRD-PARTY.md", "_internal", "docs", "THIRD-PARTY-LICENSES"}


def inspect(path, archive):
    match = re.fullmatch(r"Utatomo-(\d+\.\d+\.\d+)-windows-x64\.zip", path.name)
    if not match:
        raise ValueError("请使用带正式版本号的原始便携包")
    files = {}
    for item in archive.infolist():
        if item.is_dir():
            continue
        prefix, name = item.filename.split("/", 1)
        if prefix != "Utatomo" or name.split("/")[0] not in TOP or name in files:
            raise ValueError(f"发行目录出现意外条目：{item.filename}")
        with archive.open(item) as stream:
            files[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return match[1], files


def sign(payload):
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    encoded = base64.b64encode(data)
    # 私钥留在 Windows 当前用户证书库。找不到对应证书就中止，不自动换密钥。
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
                            str(ROOT / "scripts/Sign-Update.ps1"), str(ROOT / "assets/update-signer.cer")],
                            input=encoded + b"\n", stdout=subprocess.PIPE, check=True)
    return json.dumps({"payload": encoded.decode(), "signature": result.stdout.decode().strip()}).encode()


def asset(path):
    with path.open("rb") as stream:
        return {"name": path.name, "size": path.stat().st_size, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def make(previous, current):
    with zipfile.ZipFile(previous) as old, zipfile.ZipFile(current) as new:
        base, before = inspect(previous, old)
        version, after = inspect(current, new)
        if tuple(map(int, base.split("."))) >= tuple(map(int, version.split("."))):
            raise ValueError("基线必须早于目标版本")
        target = dict(product="utatomo/windows-x64/1", version=version, baseVersion=base,
                      baseExe=before["Utatomo.exe"], files=after)
        patch = current.with_name(f"Utatomo-{base}-to-{version}-patch.zip")
        with zipfile.ZipFile(patch, "w", zipfile.ZIP_DEFLATED) as out:
            # 顶层入口仅供没有内置更新器的旧版使用。软件内安装始终执行本机受信任的助手。
            out.writestr("Utatomo-Update.exe", new.read("Utatomo/_internal/update/Utatomo-Update.exe"))
            out.writestr("target.json", sign(target))
            for name, digest in after.items():
                if digest != before.get(name):
                    file = "Utatomo/" + name
                    out.writestr(file, new.read(file))
    feed = current.with_name("update.json")
    feed.write_bytes(sign(dict(target, patch=asset(patch), full=asset(current))))
    print(f"{base} → {version}：补丁 {patch.stat().st_size / 1048576:.1f} MiB，完整包 {current.stat().st_size / 1048576:.1f} MiB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("previous", type=Path)
    parser.add_argument("current", type=Path)
    args = parser.parse_args()
    make(args.previous, args.current)
