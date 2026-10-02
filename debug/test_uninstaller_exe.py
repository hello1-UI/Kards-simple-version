# -*- coding: utf-8 -*-
"""检验 KARDS卸载器.exe 能否真正删除程序目录（含中文路径 / 空格路径）

不碰真实用户数据目录，只在临时目录里模拟一个"安装目录"。
用法: python debug/test_uninstaller_exe.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "pyinst", "dist_tools", "KARDS卸载器.exe")

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


def make_fake_install(path):
    """搭一个假的安装目录：KARDS.exe + _internal/ + 卸载器本体"""
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "_internal", "pyimod03"), exist_ok=True)
    for rel in ("KARDS.exe", "base_library.zip",
                "_internal/python313.dll", "_internal/pyimod03/mod.pyc"):
        p = os.path.join(path, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"x" * 2048)
    shutil.copy2(EXE, os.path.join(path, "KARDS卸载器.exe"))


def run_case(title, dirname):
    print(f"\n=== {title} ===")
    base = tempfile.mkdtemp(prefix="kards_uni_")
    target = os.path.join(base, dirname)
    make_fake_install(target)
    before = sorted(os.listdir(target))
    print(f"  模拟安装目录: {target}")
    print(f"  删除前: {before}")

    # 直接用 exe 运行，喂一个回车（不删用户数据）
    try:
        r = subprocess.run([os.path.join(target, "KARDS卸载器.exe")],
                           input="\n", capture_output=True, text=True,
                           timeout=60, cwd=target)
        out = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        check(f"{title}: 运行未超时", False, "超时")
        return
    print("  --- 输出 ---")
    for line in out.strip().splitlines():
        print("   | " + line)

    check(f"{title}: 未出现 Traceback", "Traceback" not in out,
          out[-200:] if "Traceback" in out else "")
    check(f"{title}: 走完 4 个步骤", "[4/4]" in out)
    check(f"{title}: 提示保留用户数据", "保留用户数据" in out)

    # 等待脱离进程完成删除
    gone = False
    for _ in range(24):
        if not os.path.isdir(target):
            gone = True
            break
        time.sleep(0.5)
    check(f"{title}: 程序目录已被删除", gone,
          f"残留={sorted(os.listdir(target)) if os.path.isdir(target) else ''}")

    # 清理
    shutil.rmtree(base, ignore_errors=True)


def main():
    if not os.path.isfile(EXE):
        print(f"找不到 {EXE}，请先打包卸载器。")
        return 1
    print(f"测试目标: {EXE}")

    run_case("普通英文路径", "Kards-Simple-Version")
    run_case("中文 + 空格路径", "我的 游戏 KARDS")

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
