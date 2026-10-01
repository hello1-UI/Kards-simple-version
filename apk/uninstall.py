# -*- coding: utf-8 -*-
"""KARDS 简化版 —— 卸载器

由安装器复制到安装目录并注册到系统"应用和功能"。
删除内容:
  - 桌面/开始菜单快捷方式
  - 注册表卸载项 (HKLM 或 HKCU)
  - 程序安装目录（本脚本所在目录）
  - 用户数据目录 %USERPROFILE%\\AppData\\Kards-Simple-Version（默认保留，询问后可选删）

用法: python uninstall.py [--purge]   # --purge 跳过询问直接删除用户数据
"""
import ctypes
import os
import shutil
import subprocess
import sys

import winreg

APP_ID = "Kards-Simple-Version"
DATA_DIR = os.path.join(os.path.expanduser("~"), "AppData", APP_ID)
UNINSTALL_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
                 r"\Kards-Simple-Version")
START_MENU = os.path.join(os.environ.get("APPDATA", ""),
                          "Microsoft", "Windows", "Start Menu", "Programs",
                          "KARDS 简化版.lnk")
SELF_DIR = os.path.dirname(os.path.abspath(__file__))


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    params = " ".join(f'"{a}"' for a in sys.argv)
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1)
    if ret > 32:
        sys.exit(0)


def shell_desktop():
    ps = "[Environment]::GetFolderPath('Desktop')"
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except Exception:
        return os.path.join(os.path.expanduser("~"), "Desktop")


def remove_shortcuts():
    for lnk in (os.path.join(shell_desktop(), "KARDS 简化版.lnk"), START_MENU):
        try:
            if os.path.isfile(lnk):
                os.remove(lnk)
        except OSError as e:
            print(f"  快捷方式删除失败: {lnk} ({e})")
    print("  快捷方式 ✓")


def remove_registry():
    """尝试删除 HKLM 与 HKCU 两处的注册项。
    注意：不能因为某处"不存在"或"无权限"就提前 return —— 两处都要试，
    否则管理员安装（HKLM）后换普通用户卸载、或反之，都会留下残留。"""
    found = False
    for hive, name in ((winreg.HKEY_LOCAL_MACHINE, "HKLM"),
                       (winreg.HKEY_CURRENT_USER, "HKCU")):
        try:
            winreg.DeleteKey(hive, UNINSTALL_KEY)
            print(f"  系统注册项（{name}）✓")
            found = True
        except FileNotFoundError:
            continue
        except OSError as e:
            print(f"  注册项删除失败（{name}）: {e}")
    if not found:
        print("  系统注册项：未找到（跳过）")


def remove_install_dir():
    """删除安装目录。先复制自身到临时文件执行删除（目录含自身时先退避）"""
    marker = os.path.join(SELF_DIR, "uninstall.py")
    if not os.path.isfile(marker):
        print(f"  未找到安装目录标记，跳过删除: {SELF_DIR}")
        return
    tmp = os.path.join(os.environ.get("TEMP", os.path.dirname(SELF_DIR)),
                       "kards_uninstall_tmp.py")
    try:
        # 延迟删除：先把删除任务交给临时脚本，退出自身后再删目录
        # 目标路径用 repr 生成，避免路径含反斜杠/引号时的转义问题
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(
                "import os, shutil, sys, time\n"
                f"target = {SELF_DIR!r}\n"
                "for _ in range(20):\n"
                "    try:\n"
                "        shutil.rmtree(target)\n"
                "        break\n"
                "    except OSError:\n"
                "        time.sleep(0.5)\n"
                "try:\n"
                "    os.remove(sys.argv[0])\n"
                "except OSError:\n"
                "    pass\n"
            )
        subprocess.Popen([sys.executable, tmp],
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    except OSError as e:
        print(f"  安装目录删除失败: {e}")


def main():
    print("=" * 56)
    print("  KARDS 简化版 卸载器")
    print("=" * 56)

    # Program Files 需要管理员权限
    if not is_admin() and "program files" in SELF_DIR.lower():
        print("  需要管理员权限，弹出 UAC 授权窗口...")
        relaunch_as_admin()
        # 用户拒绝 UAC 会走不到这里；继续尝试（HKCU 部分仍可清理）

    print("[1/4] 删除快捷方式 ...")
    remove_shortcuts()

    print("[2/4] 清理系统注册项 ...")
    remove_registry()

    print("[3/4] 删除程序目录 ...")
    print(f"  {SELF_DIR}")

    print("[4/4] 用户数据 ...")
    purge = "--purge" in sys.argv
    if not purge:
        try:
            ans = input("  同时删除用户数据（设置/日志/自组卡组）? [y/N]: ")
            purge = ans.strip().lower() in ("y", "yes")
        except EOFError:
            purge = False
    if purge:
        shutil.rmtree(DATA_DIR, ignore_errors=True)
        print(f"  已删除: {DATA_DIR}")
    else:
        print(f"  保留用户数据: {DATA_DIR}")

    # 目录删除放最后：先启动延迟删除进程，再退出
    remove_install_dir()
    print("卸载完成！")


if __name__ == "__main__":
    main()
