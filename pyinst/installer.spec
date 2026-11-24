# -*- mode: python ; coding: utf-8 -*-
"""安装器打包 spec：apk/install.py → pyinst/dist_tools/KARDS安装器.exe（图形界面）

⚠ 图形界面是 tkinter 写的 —— excludes 里绝不能有 tkinter；
  也绝不能包含 email（urllib.request 依赖它解析响应头，排掉后运行会崩）。
"""
import os
import re
import tempfile

# SPECPATH 由 PyInstaller 注入，等于「spec 文件所在目录」（已是绝对路径）。
# 项目根 = 它再往上一层。
ROOT = os.path.dirname(SPECPATH)

# 内置 UI 模板塞进安装器 exe（几十 KB）：界面上能显示「N 套配色」，
# 也为将来「离线安装」留路。运行时落在 sys._MEIPASS/models。
MODELS = os.path.join(ROOT, 'models')


def _game_version():
    """从 KARDS.py 抠 VERSION 元组 → "1.6.3.1"

    ⚠ 安装器必须知道自己对应哪个版本：下载地址按 `releases/download/v{VER}/`
    固定，否则 `latest` 资产一旦没更新，装完还是几个月前的旧版本。
    """
    try:
        with open(os.path.join(ROOT, 'KARDS.py'), encoding='utf-8') as f:
            m = re.search(r"^VERSION\s*=\s*\(([^)]+)\)", f.read(), re.M)
        if m:
            return ".".join(x.strip() for x in m.group(1).split(",") if x.strip())
    except Exception:
        pass
    return ""


_VER = _game_version()
_VER_FILE = ""
if _VER:
    _VER_FILE = os.path.join(tempfile.mkdtemp(prefix="kards_ver_"), "VERSION.txt")
    with open(_VER_FILE, "w", encoding="utf-8") as f:
        f.write(_VER)

a = Analysis(
    [os.path.join(ROOT, 'apk', 'install.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[(MODELS, 'models')] + ([(_VER_FILE, '.')] if _VER_FILE else []),
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
