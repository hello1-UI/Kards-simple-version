# -*- mode: python ; coding: utf-8 -*-
"""安装器打包 spec：apk/install.py → pyinst/dist_tools/KARDS安装器.exe（带控制台）

⚠ excludes 里**绝不能包含 email** —— urllib.request 依赖它解析响应头，
排掉后运行安装器会直接 ModuleNotFoundError 崩掉。
"""
import os

# SPECPATH 由 PyInstaller 注入，等于「spec 文件所在目录」（已是绝对路径）。
# 项目根 = 它再往上一层。
ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'apk', 'install.py')],
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
    name='KARDS安装器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,              # 安装器需要控制台显示进度
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
