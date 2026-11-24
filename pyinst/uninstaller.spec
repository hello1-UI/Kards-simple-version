# -*- mode: python ; coding: utf-8 -*-
"""卸载器打包 spec：apk/uninstall.py → pyinst/dist_tools/KARDS卸载器.exe（图形界面）

⚠ 卸载器里有 `--gc`（后台清理）与 `--cli`（脚本化）两条控制台路径，
  而且 --gc 需要凭命令行启动自己 —— 必须保留 console=True；
  图形模式启动时 FreeConsole() 自己把黑框藏掉。
"""
import os

# SPECPATH 由 PyInstaller 注入，等于「spec 文件所在目录」（已是绝对路径）。
# 项目根 = 它再往上一层。
ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, 'apk', 'uninstall.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=['winreg', 'setup_ui', 'uninstaller_ui'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['unittest', 'pydoc', 'doctest', 'test'],
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
    console=True,              # --gc / --cli 都要控制台输出，不能改成 windowed
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
