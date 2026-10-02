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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PYINST = os.path.join(ROOT, "pyinst")

# 打包用的解释器：优先系统 Python（tkinter/winreg 齐全）
CANDIDATES = [
    r"C:\Users\freet\AppData\Local\Programs\Python\Python313\python.exe",
    sys.executable,
]


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


def main():
    py = pick_python()
    print(f"使用解释器: {py}")
    print(f"产物目录:   {PYINST}")

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
