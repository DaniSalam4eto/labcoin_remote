# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: onedir bundle with game + library data next to the .exe."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

_ROOT = Path(SPECPATH)

datas = [
    (str(_ROOT / "data"), "data"),
    (str(_ROOT / "fonts"), "fonts"),
    (str(_ROOT / "logos"), "logos"),
    (str(_ROOT / "seed_songs.json"), "."),
]

_hidden = collect_submodules("present") + [
    "bundle_paths",
    "app_config",
    "autostart",
    "game_audio",
    "doodle",
    "yt_dlp",
    "flask",
    "jinja2",
    "werkzeug",
    "bleak",
    "PIL",
    "PIL.Image",
    "pygame",
]

seen: set[str] = set()
hiddenimports = []
for name in _hidden:
    if name not in seen:
        seen.add(name)
        hiddenimports.append(name)

a = Analysis(
    ["app.py"],
    pathex=[str(_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LabcoinRemote",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LabcoinRemote",
)
