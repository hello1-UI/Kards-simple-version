# -*- coding: utf-8 -*-
"""安装器「装到自己所在目录」场景的回归测试

背景（用户实际遇到）：
    用户把 Setup 包解压到某目录，在里面直接双击 KARDS安装器.exe，
    然后把安装路径也填成同一个目录。此时：
      1) cleanup_old() 会试图删掉正在运行的 KARDS安装器.exe
      2) 解压 KARDS.zip 时又要写同名文件 → WinError 32

本测试用**真实的独占文件锁**复现，并**按安装器的真实调用顺序**
（cleanup_old → extract）验证不会崩。

运行: python debug/test_installer_selfdir.py
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
sys.path.insert(0, os.path.join(ROOT, "apk"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import install                      # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


def make_zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data if isinstance(data, bytes) else data.encode())


# 子进程：CreateFileW + dwShareMode=0 独占打开 → 真实复现 WinError 32
LOCKER = r'''
import ctypes, sys, time
from ctypes import wintypes
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = wintypes.HANDLE
k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                            wintypes.HANDLE]
h = k32.CreateFileW(sys.argv[1], 0x80000000, 0, None, 3, 0, None)
if h in (-1, 0xFFFFFFFFFFFFFFFF):
    print("LOCKFAIL", k32.GetLastError(), flush=True)
else:
    print("LOCKED", flush=True)
    time.sleep(30)
'''


def main():
    tmp = tempfile.mkdtemp(prefix="kards_selfdir_")
    holder = None
    try:
        # ---- 模拟 Setup 包解压出来的目录 ----
        target = os.path.join(tmp, "Setup")
        os.makedirs(target, exist_ok=True)
        setup_zip = os.path.join(tmp, "KARDS_SimpleVersion-Setup.zip")
        make_zip(setup_zip, {
            "KARDS安装器.exe": "FAKE_INSTALLER_EXE",
            "KARDS卸载器.exe": "FAKE_UNINSTALLER_EXE",
            "说明.txt": "安装说明",
            "KARDS/KARDS.py": "# source",
        })
        with zipfile.ZipFile(setup_zip) as z:
            z.extractall(target)
        installer_exe = os.path.join(target, "KARDS安装器.exe")
        check("Setup 目录已铺好（含安装器 exe）", os.path.isfile(installer_exe))

        # 游戏包：与安装器 exe 同名 → 必然撞车
        game_zip = os.path.join(tmp, "KARDS.zip")
        make_zip(game_zip, {
            "KARDS/KARDS安装器.exe": b"INSTALLER_FROM_GAME_ZIP" * 100,
            "KARDS/KARDS.exe": b"GAME" * 5000,
            "KARDS/_internal/base_library.zip": b"X" * 20000,
        })

        # ---- 锁住安装器 exe（模拟"它正在运行"）----
        script = os.path.join(tmp, "locker.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(LOCKER)
        holder = subprocess.Popen([sys.executable, script, installer_exe],
                                  stdout=subprocess.PIPE, text=True)
        line = holder.stdout.readline().strip()
        check("子进程已独占锁定安装器 exe（真实 WinError 32 场景）",
              line == "LOCKED", line)

        print("1. 先 cleanup_old（安装器的真实第一步）")
        install.cleanup_old(target)
        check("正在运行的安装器 exe 没被删掉", os.path.isfile(installer_exe))
        check("卸载器被保留",
              os.path.isfile(os.path.join(target, "KARDS卸载器.exe")))
        check("Setup 自带的说明.txt 被清掉（不是本次安装内容）",
              not os.path.isfile(os.path.join(target, "说明.txt")))
        check("源码版目录 KARDS/ 被清掉",
              not os.path.isdir(os.path.join(target, "KARDS")))

        print("2. 再 extract（安装器的真实第二步）")
        try:
            install.extract(game_zip, target)
            ok, err = True, ""
        except Exception as e:                     # noqa: BLE001
            ok, err = False, f"{type(e).__name__}: {e}"
        check("解压不崩（被占用文件可容忍）", ok, err)

        print("3. 结果校验")
        check("KARDS.exe 正常解压",
              os.path.getsize(os.path.join(target, "KARDS.exe")) == 20000)
        check("_internal 内文件正常解压",
              os.path.isfile(os.path.join(target, "_internal",
                                          "base_library.zip")))
        check("被占用的安装器 exe 原文件未被破坏",
              os.path.getsize(installer_exe) == len("FAKE_INSTALLER_EXE"),
              os.path.getsize(installer_exe))
        new_path = installer_exe + ".new"
        check("同名被占用文件已另存为 .new",
              os.path.isfile(new_path)
              and os.path.getsize(new_path) == len(b"INSTALLER_FROM_GAME_ZIP" * 100),
              f"exists={os.path.isfile(new_path)}")

        print("4. 释放锁后再装一次：应干净覆盖")
        holder.kill()
        holder.wait()
        holder = None
        time.sleep(0.3)
        try:
            install.extract(game_zip, target)
            ok2 = True
        except Exception as e:                     # noqa: BLE001
            ok2 = False
            print("   ", e)
        check("锁释放后可正常覆盖写入", ok2)
        check("安装器 exe 已被覆盖为新内容",
              os.path.getsize(installer_exe) == len(b"INSTALLER_FROM_GAME_ZIP" * 100),
              os.path.getsize(installer_exe))
        # .new 是「上次被占用时」的产物，installer 不会自动清理（留给用户手动确认），
        # 这里只断言它没被当成正式文件写坏
        check("残留的 .new 内容仍是上次那份（未被覆写）",
              (not os.path.isfile(new_path))
              or os.path.getsize(new_path) == len(b"INSTALLER_FROM_GAME_ZIP" * 100),
              os.path.getsize(new_path) if os.path.isfile(new_path) else "无")

        print("5. cleanup_old 按『全路径』保护正在运行的进程")
        victim_dir = os.path.join(tmp, "victim")
        os.makedirs(victim_dir, exist_ok=True)
        other = os.path.join(victim_dir, "旧文件.txt")
        with open(other, "w", encoding="utf-8") as f:
            f.write("should be removed")
        running = install._running_exes()
        self_key = os.path.normcase(os.path.abspath(sys.executable))
        check("当前解释器在保护集合里", self_key in running, len(running))
        # 把解释器**拷贝**到 victim 目录（路径不同）→ 不在保护集合里；
        # 但真正的保护是「全路径」，此处只验证保护集合的判定逻辑
        fake_self = os.path.join(victim_dir, os.path.basename(sys.executable))
        shutil.copy2(sys.executable, fake_self)
        check("拷贝件（路径不同）不在保护集合里",
              os.path.normcase(os.path.abspath(fake_self)) not in running)
        install.cleanup_old(victim_dir)
        check("victim 里的旧文件被清掉", not os.path.isfile(other))
        check("拷贝件也被清掉（路径不同 → 不享受保护）",
              not os.path.isfile(fake_self))

        print("6. _running_exes 基本性质")
        running = install._running_exes()
        check("含当前解释器",
              os.path.normcase(os.path.abspath(sys.executable)) in running,
              len(running))
        check("都是规范化绝对路径",
              all(os.path.isabs(p) and p == os.path.normcase(p)
                  for p in running))
    finally:
        if holder is not None:
            holder.kill()
            holder.wait()
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(f"FAILED: {len(FAIL)}/{len(PASS) + len(FAIL)}")
        for f in FAIL:
            print("  -", f)
        sys.exit(1)
    print(f"ALL OK ({len(PASS)} checks)")


if __name__ == "__main__":
    main()
