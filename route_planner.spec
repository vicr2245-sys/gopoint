# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Route Planner.

Build with:  pyinstaller route_planner.spec --noconfirm
(or just run build.bat, which does this for you)

Notes for future-you:

- onedir, not onefile: QtWebEngine apps generally work more reliably in
  onedir mode. onefile re-extracts everything to a fresh temp folder on
  every single launch (slower startup) and has a track record of causing
  path-related issues for QtWebEngine's separate helper process in other
  PyQt projects. onedir keeps everything in one folder next to the .exe,
  and tends to draw less Windows Defender/SmartScreen suspicion than a
  self-extracting single file.

- console=True for now: keeps a console window open showing any startup
  errors/tracebacks — valuable while you're still confirming the build
  works cleanly. Once you've verified a normal run end-to-end, flip this
  to False below for a release build with no terminal window.

- collect_all('PyQt5'): QtWebEngine's resource bundling (icudtl.dat,
  qtwebengine_resources.pak, translations, locales, the separate
  QtWebEngineProcess executable) is a common PyInstaller pain point where
  the default automatic hook sometimes misses files, leaving you with a
  blank/broken map view. Collecting everything is the safe, reliable
  choice — it does make the build noticeably larger (expect several
  hundred MB), which is normal for a Chromium-based embedded browser.

- No custom icon yet. Add one later by dropping a .ico file in this
  folder and setting icon='your-icon.ico' in the EXE(...) block below.
"""
from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = [
    ('gopoint_icon.ico', '.'),
    ('gopoint_icon.png', '.'),
]
binaries = []
hiddenimports = [
    'anthropic',
    'PyQt5.QtWebEngineWidgets',
    'PyQt5.QtWebChannel',
    'PyQt5.QtNetwork',
]

for pkg in ('PyQt5',):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GoPoint',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='gopoint_icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='GoPoint',
)
