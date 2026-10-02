# -*- mode: python ; coding: utf-8 -*-
"""KARDS 主程序打包 spec：KARDS.py → dist/KARDS/KARDS.exe（无控制台 GUI）

⚠ spec 里的路径必须以 **spec 文件所在目录** 为基准解析（PyInstaller 的约定），
所以这里统一用 SPEC_DIR 算出项目根 ROOT，再拼绝对路径。
这样无论从哪个工作目录执行 pyinstaller，结果都一致。
"""
import os

# SPECPATH 由 PyInstaller 注入，等于「spec 文件所在目录」（已是绝对路径）。
# 项目根 = 它再往上一层。不要再套 abspath，那会多剥一层目录。
ROOT = os.path.dirname(SPECPATH)
DIST = os.path.join(ROOT, "pyinst", "dist")
WORK = os.path.join(ROOT, "pyinst", "build")

a = Analysis(
    [os.path.join(ROOT, 'KARDS.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # ⚠ kards_server.py 是**独立的服务器程序**，由玩家自己启动
        # （python kards_server.py 或打包后的 exe）。它不是被 import 的模块，
        # PyInstaller 的依赖分析看不见它 —— 必须当数据文件带进包，
        # 否则联机模式在大厅里根本起不来服务器。
        (os.path.join(ROOT, 'kards_server.py'), '.'),
    ],
    hiddenimports=[
        # 这几个是同目录的兄弟模块，正常 import 能被分析到；显式列出是为了
        # 防止将来有人把 import 挪进函数体（延迟导入）导致漏打。
        # kards_server 是**故意**列进来的：`KARDS.exe --server` 会
        # import kards_server（见 KARDS.py::run_server_entry），
        # 但那是在一个分支里延迟导入的，分析器可能看不到。
        'kards_engine', 'kards_i18n', 'kards_net', 'kards_account',
        'kards_host', 'kards_update', 'kards_server',
    ],
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
    name='KARDS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,             # GUI 程序：不弹控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='KARDS',
)
