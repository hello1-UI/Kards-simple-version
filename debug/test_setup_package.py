# -*- coding: utf-8 -*-
"""安装器发布包端到端验收：模拟真实用户「解压 → 安装 → 跑游戏 → 卸载」

用法: python debug/test_setup_package.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ZIP = os.path.join(ROOT, "KARDS_SimpleVersion-Setup.zip")

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


def wait_gone(path, tries=40):
    for _ in range(tries):
        if not os.path.isdir(path):
            return True
        time.sleep(0.5)
    return False


def main():
    print("=" * 60)
    print("安装器发布包验收测试")
    print("=" * 60)

    if not os.path.isfile(ZIP):
        print(f"缺少 {ZIP}")
        return 1

    work = tempfile.mkdtemp(prefix="kards_setup_")
    unpack = os.path.join(work, "解压出来的安装包")
    target = os.path.join(work, "安装 到 这里 KARDS")
    os.makedirs(unpack, exist_ok=True)

    try:
        # ---- 1. 模拟用户解压 ----
        print("\n--- 1. 解压发布包 ---")
        with zipfile.ZipFile(ZIP) as z:
            z.extractall(unpack)
        got = sorted(os.listdir(unpack))
        print(f"  解压内容: {got}")
        check("含 KARDS安装器.exe", "KARDS安装器.exe" in got)
        check("含 KARDS卸载器.exe", "KARDS卸载器.exe" in got)
        check("含 安装说明.txt", "安装说明.txt" in got)

        # ---- 2. 运行安装器 ----
        print("\n--- 2. 运行安装器 ---")
        t0 = time.time()
        try:
            r = subprocess.run(
                [os.path.join(unpack, "KARDS安装器.exe"), target],
                input="\n", capture_output=True, text=True, timeout=420,
                cwd=unpack)
            out = (r.stdout or "") + (r.stderr or "")
        except subprocess.TimeoutExpired:
            check("安装器未超时", False, "超过 420s")
            return 1
        dt = time.time() - t0
        for line in out.strip().splitlines()[-22:]:
            print("   | " + line)

        check("安装器无报错", "Traceback" not in out,
              out[-300:] if "Traceback" in out else "")
        check("下载成功", "下载完成" in out)
        check("解压成功", "解压完成" in out)
        check("识别到卸载器", "KARDS卸载器.exe ✓" in out)
        check("安装完成", "安装完成" in out)
        print(f"  安装耗时 {dt:.0f}s")

        # ---- 3. 检查安装结果 ----
        print("\n--- 3. 检查安装结果 ---")
        exe = os.path.join(target, "KARDS.exe")
        uni = os.path.join(target, "KARDS卸载器.exe")
        check("KARDS.exe 就位", os.path.isfile(exe))
        check("卸载器已随装", os.path.isfile(uni))
        check("无多余 KARDS/ 嵌套", not os.path.isdir(os.path.join(target, "KARDS")))
        n = sum(len(f) for _r, _d, f in os.walk(target))
        print(f"  共 {n} 个文件")
        check("文件数量正常(>500)", n > 500, str(n))

        # ---- 4. 跑游戏自检 ----
        print("\n--- 4. 运行游戏自检 ---")
        try:
            g = subprocess.run([exe, "--smoke"], capture_output=True, text=True,
                               timeout=180, cwd=target)
            gout = (g.stdout or "") + (g.stderr or "")
            check("游戏可运行（SMOKE OK）", "SMOKE OK" in gout,
                  gout.strip()[-150:])
            print(f"  {gout.strip().splitlines()[-1] if gout.strip() else '(无输出)'}")
        except subprocess.TimeoutExpired:
            check("游戏可运行（SMOKE OK）", False, "超时")

        # ---- 5. 运行卸载器 ----
        print("\n--- 5. 运行卸载器 ---")
        try:
            u = subprocess.run([uni], input="\n", capture_output=True, text=True,
                               timeout=120, cwd=os.path.dirname(target))
            uout = (u.stdout or "") + (u.stderr or "")
        except subprocess.TimeoutExpired:
            check("卸载器未超时", False, "超时")
            return 1
        for line in uout.strip().splitlines():
            print("   | " + line)
        check("卸载器无报错", "Traceback" not in uout)
        check("走完 4 步", "[4/4]" in uout)
        check("提示保留用户数据", "保留用户数据" in uout)

        # ---- 6. 确认目录已删 ----
        print("\n--- 6. 等待后台清理 ---")
        gone = wait_gone(target)
        check("安装目录被完全删除", gone,
              f"残留={sorted(os.listdir(target))[:8] if os.path.isdir(target) else ''}")

    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
