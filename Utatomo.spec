# Windows x64 portable distribution. Runtime DLLs remain separate and replaceable.
from pathlib import Path
import PySide6
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH)
datas = [(str(root / name), name) for name in ("web", "samples")]
datas += [(str(root / "assets" / name), "assets") for name in
          ("icon.svg", "icon.ico", "landscape.svg", "reading-corrections.json")]
datas += [(str(root / "utatomo/client_bridge.js"), "utatomo")]
binaries = []
hiddenimports = []
for package in ("unidic_lite", "cmudict", "pykakasi", "fugashi"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
hiddenimports += collect_submodules("winrt")

a = Analysis([str(root / "main.py")], pathex=[str(root)], binaries=binaries,
             datas=datas, hiddenimports=hiddenimports, hookspath=[],
             hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
# WinRT ships an older MSVC runtime. Use the Qt wheel's runtime consistently.
qt_dir = Path(PySide6.__file__).parent
# The host injects native tools into DLL lookup. Qt uses Windows' system ICU,
# not Poppler's incompatible ICU; Python's OpenSSL must come from Python itself.
runtime_dlls = Path(sys.base_prefix) / "DLLs"
filtered = []
for dest, source, kind in a.binaries:
    if "codex-runtimes" in source.lower():
        replacement = runtime_dlls / Path(dest).name
        if replacement.exists():
            source = str(replacement)
        else:
            continue
    filtered.append((dest, source, kind))
a.binaries = filtered
a.binaries = [(dest, str(qt_dir / Path(dest).name.lower())
               if Path(dest).name.lower().startswith(("msvcp140", "vcruntime140"))
               and (qt_dir / Path(dest).name.lower()).exists() else source, kind)
              for dest, source, kind in a.binaries]
for dll in qt_dir.glob("*140*.dll"):
    a.binaries.append((dll.name, str(dll), "BINARY"))
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Utatomo",
          icon=str(root / "assets/icon.ico"),
          debug=False, bootloader_ignore_signals=False, strip=False,
          upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Utatomo")
