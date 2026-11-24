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

# 资源清单：**曲库完全不进发行包**。
# 曲库 4 GB 左右、几百个文件，随包分发会让安装、更新、校验全部不可行
# （也超过 GitHub 单资产 2 GB 限制）。现在音乐是**可选包**：玩家在
# 设置 → 其它 →「可选音乐包」里按需下载，或自己把 music*.zip 放到数据目录，
# 由 kards_musicpack 在启动时解压到音乐目录。
_ASSET_DIR = os.path.join(ROOT, "assets")
_ASSET_ITEMS = []
if os.path.isdir(_ASSET_DIR):
    for _sub in ("cards", "hq", "sfx", "fonts"):
        _p = os.path.join(_ASSET_DIR, _sub)
        if os.path.isdir(_p):
            _ASSET_ITEMS.append((_p, os.path.join("assets", _sub)))
    for _fn in sorted(os.listdir(_ASSET_DIR)):
        # 兜底：极少数自建发行流程会把 zip 放进 assets/，这里照旧带上；
        # 但官方发版（debug/build_tools.py）不会产生这种文件。
        if _fn.lower().startswith("music") and _fn.lower().endswith(".zip"):
            _ASSET_ITEMS.append((os.path.join(_ASSET_DIR, _fn), "assets"))

# 内置 UI 模板（编好的配色，只读）：装到 `_internal/models/*.json`。
# 安装器可以选择把这个目录删掉（apk/install.py --no-models），
# 所以它必须是一个**独立目录**，不能混进 assets/ 里。
_MODEL_DIR = os.path.join(ROOT, "models")
if os.path.isdir(_MODEL_DIR):
    _ASSET_ITEMS.append((_MODEL_DIR, "models"))

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
    ] + _ASSET_ITEMS,
    hiddenimports=[
        # 这几个是同目录的兄弟模块，正常 import 能被分析到；显式列出是为了
        # 防止将来有人把 import 挪进函数体（延迟导入）导致漏打。
        # kards_server 是**故意**列进来的：`KARDS.exe --server` 会
        # import kards_server（见 KARDS.py::run_server_entry），
        # 但那是在一个分支里延迟导入的，分析器可能看不到。
        'kards_engine', 'kards_i18n', 'kards_net', 'kards_account',
        'kards_host', 'kards_update', 'kards_server',
        # 跨局域网联机：kards_upnp 由 kards_host 在**函数内**延迟导入，
        # 显式声明一下更保险（否则离线环境可能漏打，表现为「找不到 UPnP 路由器」）。
        'kards_upnp',
        # 增强对战界面：kards_board 在 _activate_pyboard() 里延迟导入，
        # pygame 又在 kards_board 里导入 —— 全部显式声明，防止漏打。
        # （pygame 的 DLL 由 PyInstaller 自带的 hook-pygame 收集）
        'kards_board', 'pygame',
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
