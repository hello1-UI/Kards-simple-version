# -*- coding: utf-8 -*-
"""KARDS 简化版 —— 安装器

功能:
  1. 从 GitHub Release 下载 KARDS.zip（多镜像自动回退）
  2. 解压安装到指定目录（默认 C:\\Program Files\\Kards-Simple-Version，可改）
  3. 创建用户数据目录 %USERPROFILE%\\AppData\\Kards-Simple-Version（设置/日志/卡组）
  4. 创建桌面 + 开始菜单快捷方式
  5. 注册到系统"应用和功能"，支持一键卸载（附带 uninstall.py）

用法:
  python install.py                 # 交互式（提示输入安装路径，回车用默认）
  python install.py "D:\\Games\\KARDS"   # 指定安装路径

依赖: 仅 Python 3.8+ 标准库，无需 pip 安装任何东西
"""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

REPO = "hello1-UI/Kards-simple-version"
APP_ID = "Kards-Simple-Version"
APP_NAME = "KARDS Simplified"
PUBLISHER = "hello1-UI"
DEFAULT_DIR = r"C:\Program Files\Kards-Simple-Version"
DATA_DIR = os.path.join(os.path.expanduser("~"), "AppData", APP_ID)
FALLBACK_VERSION = "1.0.0.1"

# 下载源：官方 + 国内加速镜像（依次尝试）
_PRIMARY = f"https://github.com/{REPO}/releases/latest/download/KARDS.zip"
URLS = [
    _PRIMARY,
    "https://gh-proxy.com/" + _PRIMARY,
    "https://ghproxy.net/" + _PRIMARY,
    "https://mirror.ghproxy.com/" + _PRIMARY,
]

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Kards-Simple-Version"


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """以管理员身份重启自身（UAC 弹窗），成功则不返回"""
    params = " ".join(f'"{a}"' for a in sys.argv)
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1)
    if ret > 32:
        sys.exit(0)
    print("  未获得管理员权限。改用当前用户权限继续（装到 Program Files 可能失败）。")


def can_write(d):
    probe = os.path.join(d, ".probe")
    try:
        os.makedirs(d, exist_ok=True)
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def fetch_latest_version():
    """从 GitHub API 取最新 Release 的 tag 作为版本号（失败用回退值）"""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/releases/latest")
        with urllib.request.urlopen(req, timeout=15) as r:
            tag = json.load(r).get("tag_name", "")
        v = tag.lstrip("v").strip()
        return v if v else FALLBACK_VERSION
    except Exception:
        return FALLBACK_VERSION


def download(dest):
    for i, url in enumerate(URLS, 1):
        src = "GitHub官方" if i == 1 else f"镜像{i - 1}"
        print(f"  尝试下载源 {i}/{len(URLS)}（{src}）...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kards-installer"})
            with urllib.request.urlopen(req, timeout=30) as resp, \
                    open(dest, "wb") as f:
                total = resp.getheader("Content-Length")
                total = int(total) if total else None
                done = 0
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        filled = int(28 * done / total)
                        bar = "#" * filled + "-" * (28 - filled)
                        print(f"\r    [{bar}] {done * 100 // total:3d}% "
                              f"{done / 1048576:.1f}/{total / 1048576:.1f} MB", end="")
                    else:
                        print(f"\r    已下载 {done / 1048576:.1f} MB", end="")
                print()
            if total and done != total:
                raise IOError("下载不完整")
            print(f"  下载完成（来源: {src}）")
            return True
        except Exception as e:
            print(f"    失败: {e}")
    return False


def extract(zip_path, install_dir):
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        # zip 内含顶层 KARDS/ 文件夹时解压到上级，让文件直接落在安装目录
        top = {n.split("/")[0] for n in names if n.strip("/")}
        target = os.path.dirname(install_dir) if top == {"KARDS"} else install_dir
        os.makedirs(install_dir, exist_ok=True)
        for i, n in enumerate(names, 1):
            z.extract(n, target)
            if i % 40 == 0 or i == len(names):
                filled = 20 * i // len(names)
                print(f"\r    解压进度 [{'#' * filled}{'-' * (20 - filled)}] "
                      f"{i}/{len(names)}", end="")
        print()
    print(f"  解压完成 -> {install_dir}")


def make_shortcut(lnk, target, workdir, desc):
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath='%s';$s.WorkingDirectory='%s';"
        "$s.Description='%s';$s.Save()" % (lnk, target, workdir, desc)
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   check=True, capture_output=True)


def shell_folder(name):
    ps = f"[Environment]::GetFolderPath('{name}')"
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       check=True, capture_output=True, text=True)
    return r.stdout.strip()


def register_uninstall(install_dir, version, hklm):
    root = ctypes.windll.advapi32  # noqa: 仅确认 win32 环境
    import winreg
    hive = winreg.HKEY_LOCAL_MACHINE if hklm else winreg.HKEY_CURRENT_USER
    exe = os.path.join(install_dir, "KARDS.exe")
    uni = os.path.join(install_dir, "uninstall.py")
    py = sys.executable
    with winreg.CreateKeyEx(hive, UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, version)
        winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
        winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, install_dir)
        winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, exe)
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ,
                          f'"{py}" "{uni}"')
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
    where = "HKLM" if hklm else "HKCU"
    print(f"  已注册到系统应用列表（{where}），可在 设置->应用 中卸载")


def main():
    print("=" * 56)
    print("  KARDS 简化版 安装器")
    print("=" * 56)

    # 安装路径：命令行参数 > 交互输入 > 默认
    if len(sys.argv) > 1:
        install_dir = os.path.abspath(sys.argv[1])
    else:
        raw = input(f"安装路径 [{DEFAULT_DIR}]: ").strip().strip('"')
        install_dir = os.path.abspath(raw) if raw else DEFAULT_DIR
    print(f"  安装到: {install_dir}")

    # 需要 admin 的情形：目标不可写（典型即 Program Files）
    if not can_write(install_dir) and not is_admin():
        print("  目标目录需要管理员权限，弹出 UAC 授权窗口...")
        relaunch_as_admin()  # 拒绝授权则继续降级尝试

    # 1. 下载
    tmp_zip = os.path.join(tempfile.gettempdir(), "KARDS-install.zip")
    print("[1/4] 下载 KARDS.zip ...")
    if os.path.exists(tmp_zip):
        os.remove(tmp_zip)
    if not download(tmp_zip):
        sys.exit("错误: 所有下载源均失败，请检查网络后重试")

    # 2. 解压
    print("[2/4] 解压安装 ...")
    if os.path.isdir(install_dir):
        # 覆盖安装：保留目录，清掉旧程序文件（不动 uninstall.py 之外的用户文件）
        for n in os.listdir(install_dir):
            p = os.path.join(install_dir, n)
            if n in ("KARDS.exe", "KARDS.zip", "_internal"):
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) \
                    else os.path.remove(p)
    extract(tmp_zip, install_dir)
    os.remove(tmp_zip)

    # 3. 用户数据目录 + 卸载器
    print("[3/4] 初始化用户数据目录 ...")
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "decks"), exist_ok=True)
    print(f"  用户数据: {DATA_DIR}（设置/日志/自组卡组）")
    uni_src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "uninstall.py")
    if os.path.isfile(uni_src):
        shutil.copy2(uni_src, os.path.join(install_dir, "uninstall.py"))

    # 4. 快捷方式 + 系统注册
    print("[4/4] 创建快捷方式并注册到系统 ...")
    exe = os.path.join(install_dir, "KARDS.exe")
    try:
        desktop = shell_folder("Desktop")
        make_shortcut(os.path.join(desktop, "KARDS 简化版.lnk"),
                      exe, DATA_DIR, "KARDS Simplified - WWII Card Game")
        sm = os.path.join(os.environ.get("APPDATA", ""),
                          "Microsoft", "Windows", "Start Menu", "Programs")
        os.makedirs(sm, exist_ok=True)
        make_shortcut(os.path.join(sm, "KARDS 简化版.lnk"),
                      exe, DATA_DIR, "KARDS Simplified - WWII Card Game")
        print("  快捷方式: 桌面 + 开始菜单 ✓")
    except Exception as e:
        print(f"  快捷方式创建失败（不影响游戏本体）: {e}")
    try:
        register_uninstall(install_dir, fetch_latest_version(),
                           hklm=is_admin())
    except Exception as e:
        print(f"  应用注册失败（不影响游戏本体）: {e}")

    print()
    print("=" * 56)
    print(f"  安装完成！双击桌面快捷方式即可开始游戏")
    print(f"  程序目录: {install_dir}")
    print(f"  用户数据: {DATA_DIR}")
    print("=" * 56)
    if os.path.isfile(exe):
        os.startfile(DATA_DIR)  # 打开用户数据目录让用户确认
    input("按回车键退出安装器 ...")


if __name__ == "__main__":
    main()
