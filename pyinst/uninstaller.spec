# -*- mode: python ; coding: utf-8 -*-
"""卸载器打包 spec：apk/uninstall.py → pyinst/dist_tools/KARDS卸载器.exe（带控制台）"""
import os

# SPECPATH 由 PyInstaller 注入，等于「spec 文件所在目录」（已是绝对路径）。
# 项目根 = 它再往上一层。
ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'apk', 'uninstall.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=['winreg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pydoc', 'doctest', 'test'],
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
    name='KARDS卸载器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,              # 卸载器需要控制台做交互询问
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
