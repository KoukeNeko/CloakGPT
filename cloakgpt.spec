# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all


cloakbrowser_datas, cloakbrowser_binaries, cloakbrowser_hiddenimports = collect_all(
    "cloakbrowser"
)
playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all(
    "playwright"
)

a = Analysis(
    ["cloakgpt.py"],
    pathex=[],
    binaries=cloakbrowser_binaries + playwright_binaries,
    datas=cloakbrowser_datas + playwright_datas,
    hiddenimports=cloakbrowser_hiddenimports + playwright_hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name="cloakgpt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
