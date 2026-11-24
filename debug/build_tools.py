# -*- coding: utf-8 -*-
"""一键打包安装器/卸载器 exe + 发布包

用法: python debug/build_tools.py
产出（全部在 pyinst/ 下）:
  pyinst/dist_tools/KARDS安装器.exe
  pyinst/dist_tools/KARDS卸载器.exe
  KARDS_SimpleVersion-Setup.zip

注意：exe 必须用**系统 Python** 打包（受管 Python 缺少部分运行时依赖），
脚本会自动挑选可用的解释器。
"""
import os
import subprocess
import sys

import pyfind

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PYINST = os.path.join(ROOT, "pyinst")

# 打包用的解释器：优先系统 Python（tkinter/winreg 齐全），由 pyfind 现算
CANDIDATES = pyfind.candidates()


def pick_python():
    for p in CANDIDATES:
        if os.path.isfile(p):
            try:
                r = subprocess.run([p, "-c", "import PyInstaller"],
                                   capture_output=True, timeout=60)
                if r.returncode == 0:
                    return p
            except Exception:
                continue
    raise SystemExit("找不到带 PyInstaller 的 Python 解释器")


def build(py, spec_name):
    spec = os.path.join(PYINST, spec_name)
    print(f"\n>>> 打包 {spec_name}")
    r = subprocess.run(
        [py, "-m", "PyInstaller", spec,
         "--distpath", os.path.join(PYINST, "dist_tools"),
         "--workpath", os.path.join(PYINST, "build_tools"),
         "--noconfirm"],
        cwd=ROOT, capture_output=True, text=True, timeout=900)
    tail = (r.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        print("   " + line)
    if r.returncode != 0:
        print(r.stdout or "", r.stderr or "")
        raise SystemExit(f"打包失败: {spec_name}")


def _game_version():
    import re
    with open(os.path.join(ROOT, "KARDS.py"), encoding="utf-8") as f:
        m = re.search(r"^VERSION\s*=\s*\(([^)]+)\)", f.read(), re.M)
    return ".".join(x.strip() for x in m.group(1).split(",") if x.strip()) if m else ""


def check_game_zip():
    """检查 KARDS.zip 是否与当前版本匹配。

    ⚠ 安装器的下载地址按版本 tag 固定，但 Release 资产是**手动**上传的。
    历史上就出过「代码发版了、资产没更新」→ 用户装完还是旧版的事故。
    这里在打包时提前吭声，避免带着旧 zip 去发版。
    """
    import zipfile
    zpath = os.path.join(ROOT, "KARDS.zip")
    want = _game_version()
    if not os.path.isfile(zpath):
        print(f"⚠ 没有 KARDS.zip —— 发版前先跑: python debug/pack_game.py")
        return
    try:
        with zipfile.ZipFile(zpath) as z:
            names = z.namelist()
            ver = (z.read("KARDS/VERSION.txt").decode("utf-8", "replace").strip()
                   if "KARDS/VERSION.txt" in names else None)
            n_models = len([n for n in names
                            if n.startswith("KARDS/_internal/models/")
                            and n.endswith(".json")])
    except Exception as e:                 # noqa: BLE001
        print(f"⚠ KARDS.zip 读取失败: {e}")
        return
    size = os.path.getsize(zpath) / 1048576
    if not ver:
        print("⚠ KARDS.zip 里没有 KARDS/VERSION.txt —— 安装器会把它当旧包拒装；"
              "请用 python debug/pack_game.py 重打")
    elif want and ver != want:
        print(f"⚠ KARDS.zip 是 v{ver}，工程是 v{want} —— 请重跑 debug/pack_game.py")
    else:
        print(f"KARDS.zip 版本 v{ver} ✓  内置模板 {n_models} 套  {size:.1f} MB")


def main():
    py = pick_python()
    print(f"使用解释器: {py}")
    print(f"产物目录:   {PYINST}")
    check_game_zip()

    build(py, "installer.spec")
    build(py, "uninstaller.spec")

    print("\n>>> 生成发布包")
    r = subprocess.run([py, os.path.join(HERE, "pack_installer.py")],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr or "")
        raise SystemExit("发布包生成失败")

    print("\n全部完成。建议接着跑一遍验收：")
    print("  python debug/test_setup_package.py")
    print("  python debug/test_installer_shortcut.py")


if __name__ == "__main__":
    main()
