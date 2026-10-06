"""Build the portable Windows release with bundled dependency notices."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    # SVG 是图标源文件，每次构建同步生成可执行文件使用的多尺寸 ICO。
    subprocess.run([sys.executable, str(ROOT / "scripts/create_icon.py")], cwd=ROOT, check=True)
    build_env = os.environ.copy()
    # Avoid collecting unrelated DLLs from tools injected into the host PATH.
    windows = Path(os.environ["SystemRoot"])
    build_env["PATH"] = os.pathsep.join(map(str, [Path(sys.executable).parent,
        Path(sys.base_prefix), windows / "System32", windows]))
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "Utatomo.spec"],
                   cwd=ROOT, env=build_env, check=True)
    bundle = ROOT / "dist/Utatomo"
    notices = bundle / "THIRD-PARTY-LICENSES"
    notices.mkdir(exist_ok=True)
    distributions = []
    for dist in importlib.metadata.distributions():
        if dist.metadata["Name"].lower() in {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes"}:
            continue
        name = dist.metadata["Name"]
        distributions.append({"name": name, "version": dist.version,
                              "source": dist.metadata.get_all("Project-URL", [])})
        metadata_dir = notices / name
        metadata_dir.mkdir(exist_ok=True)
        (metadata_dir / "METADATA").write_text(dist.read_text("METADATA") or "", encoding="utf-8")
        for item in dist.files or []:
            if any(part.lower().startswith(("license", "copying", "notice", "copyright"))
                   or part.upper() in {"GPL", "LGPL", "BSD"} for part in item.parts):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    target = notices / name / str(item)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    (notices / "versions.json").write_text(json.dumps(distributions, indent=2), encoding="utf-8")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.exists():
        raise FileNotFoundError(python_license)
    shutil.copy2(python_license, notices / "Python-LICENSE.txt")
    shutil.copy2(ROOT / "docs/third-party.md", bundle / "THIRD-PARTY.md")
    shutil.copytree(ROOT / "docs/licenses", notices / "additional", dirs_exist_ok=True)
    shutil.copy2(ROOT / "README.md", bundle / "README.md")
    if (ROOT / "LICENSE").exists():
        shutil.copy2(ROOT / "LICENSE", bundle / "LICENSE")
    # The README's relative image links also work in the extracted archive.
    shutil.copytree(ROOT / "docs/images", bundle / "docs/images", dirs_exist_ok=True)
    for name in ("architecture.md", "third-party.md", "verification.md"):
        shutil.copy2(ROOT / "docs" / name, bundle / "docs" / name)
    version = __import__("tomllib").loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    archive = ROOT / "dist" / f"Utatomo-{version}-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(bundle.rglob("*")):
            if path.is_file() and path.relative_to(bundle).parts[0] not in {"data", ".cache", "output"}:
                zf.write(path, path.relative_to(bundle.parent))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (ROOT / "dist/SHA256SUMS.txt").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(f"Release: {archive} ({archive.stat().st_size / 1024**2:.1f} MiB)")


if __name__ == "__main__":
    main()
