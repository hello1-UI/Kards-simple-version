# -*- mode: python ; coding: utf-8 -*-
"""安装器打包 spec：apk/install.py → pyinst/dist_tools/KARDS安装器.exe（图形界面）

⚠ 图形界面是 tkinter 写的 —— excludes 里绝不能有 tkinter；
  也绝不能包含 email（urllib.request 依赖它解析响应头，排掉后运行会崩）。
"""
import os

# SPECPATH 由 PyInstaller 注入，等于「spec 文件所在目录」（已是绝对路径）。
# 项目根 = 它再往上一层。
ROOT = os.path.dirname(SPECPATH)

# 内置 UI 模板塞进安装器 exe（几十 KB）：界面上能显示「N 套配色」，
# 也为将来「离线安装」留路。运行时落在 sys._MEIPASS/models。
MODELS = os.path.join(ROOT, 'models')

a = Analysis(
    [os.path.join(ROOT, 'apk', 'install.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[(MODELS, 'models')],
    hiddenimports=['winreg', 'setup_ui', 'installer_ui'],
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
    name='KARDS安装器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,              # 保留控制台：--cli 模式（脚本化/验收测试）需要输出；
                               # 图形模式启动时 FreeConsole() 自己把黑框藏掉
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
