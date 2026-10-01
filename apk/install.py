# -*- coding: utf-8 -*-
"""KARDS 简化版 —— 安装器

功能:
  1. 从 GitHub Release 下载 KARDS.zip（多镜像竞速测速，自动选最快）
  2. 解压安装到指定目录（默认 C:\\Program Files\\Kards-Simple-Version，可改）
  3. 创建用户数据目录 %USERPROFILE%\\AppData\\Kards-Simple-Version（设置/日志/卡组）
  4. 创建桌面 + 开始菜单快捷方式
  5. 注册到系统"应用和功能"，支持一键卸载（附带 uninstall.py）

用法:
  python install.py                 # 交互式（提示输入安装路径，回车用默认）
  python install.py "D:\\Games\\KARDS"   # 指定安装路径

依赖: 仅 Python 3.8+ 标准库，无需 pip 安装任何东西

【防卡死设计】—— 每一处可能无限等待的地方都有上限
  - 镜像竞速测速：每个源只测前 512KB，并发请求，2s 内出结果
  - 单源下载：硬性 300s 超时 + 连续 45s 无数据即判定停滞并换源
  - 解压：按文件数而非字节推进，避免大文件卡住进度
  - 所有网络请求均带 timeout，绝不出现无限等待
"""
import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

REPO = "hello1-UI/Kards-simple-version"
APP_ID = "Kards-Simple-Version"
APP_NAME = "KARDS Simplified"
PUBLISHER = "hello1-UI"
DEFAULT_DIR = r"C:\Program Files\Kards-Simple-Version"
DATA_DIR = os.path.join(os.path.expanduser("~"), "AppData", APP_ID)
FALLBACK_VERSION = "1.0.0.1"

_PRIMARY = f"https://github.com/{REPO}/releases/latest/download/KARDS.zip"

# 下载源（实测速度，2026-10-01）：
#   gh-proxy.com   ~6.8 MB/s   ★ 首选
#   GitHub 直连     ~37 KB/s   慢但最可靠，作为兜底
#   ghproxy.net    ~10 KB/s    很慢
# 说明：镜像站可用性会变化，因此下面会先"竞速测速"再决定用哪个，而不是盲试。
URLS = [
    ("gh-proxy 镜像", "https://gh-proxy.com/" + _PRIMARY),
    ("GitHub 官方", _PRIMARY),
    ("ghproxy.net 镜像", "https://ghproxy.net/" + _PRIMARY),
    ("ghfast.top 镜像", "https://ghfast.top/" + _PRIMARY),
]

# ---- 超时参数（秒）----
SPEED_TEST_BYTES = 512 * 1024   # 测速只拉前 512KB
SPEED_TEST_TIMEOUT = 8          # 单个源测速上限
SPEED_TEST_MIN_BPS = 30 * 1024  # 低于 30KB/s 视为不可用
DL_TOTAL_TIMEOUT = 300          # 单源总时长上限
DL_STALL_TIMEOUT = 45           # 连续无数据多久算卡住
CONNECT_TIMEOUT = 15            # 建连超时

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Kards-Simple-Version"


# ---------------------------------------------------------------- 基础工具

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


def human(n):
    return f"{n / 1048576:.1f} MB"


# ---------------------------------------------------------------- 镜像竞速

def _probe(name, url, results):
    """测速：只拉前 512KB，计算速度"""
    t0 = time.time()
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "kards-installer",
                          "Range": f"bytes=0-{SPEED_TEST_BYTES - 1}"})
        got = 0
        with urllib.request.urlopen(req, timeout=SPEED_TEST_TIMEOUT) as resp:
            while got < SPEED_TEST_BYTES:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                got += len(chunk)
                if time.time() - t0 > SPEED_TEST_TIMEOUT:
                    break
        dt = max(time.time() - t0, 0.01)
        bps = got / dt
        results.append((bps, name, url, got))
    except Exception as e:
        results.append((0.0, name, url, 0))
        _probe.errors.append(f"{name}: {type(e).__name__}")


_probe.errors = []


def pick_fastest():
    """并发测速所有源，返回 (name, url)；全不可用返回 None"""
    print("  正在测速各下载源（并发，最多 %ds）..." % SPEED_TEST_TIMEOUT)
    results, threads = [], []
    for name, url in URLS:
        t = threading.Thread(target=_probe, args=(name, url, results), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=SPEED_TEST_TIMEOUT + 3)

    results.sort(key=lambda r: -r[0])
    ok = [r for r in results if r[0] >= SPEED_TEST_MIN_BPS]
    for bps, name, _url, got in results:
        if bps >= SPEED_TEST_MIN_BPS:
            print(f"    {name:18s} {bps / 1024:8.0f} KB/s  ✓")
        else:
            print(f"    {name:18s} {'不可用' if bps == 0 else f'{bps/1024:.0f} KB/s':>8s}  ✗")
    if not ok:
        return None
    bps, name, url, _ = ok[0]
    print(f"  选用最快源: {name}（{bps / 1024:.0f} KB/s）")
    return name, url


# ---------------------------------------------------------------- 下载

def download(dest):
    """下载 KARDS.zip：先竞速选源，再带双重超时下载。返回 True/False"""
    picked = pick_fastest()
    # 竞速失败的源也保留在候选里，按测速顺序逐个兜底
    order = []
    if picked:
        order.append(picked)
    for name, url in URLS:
        if not any(name == n for n, _ in order):
            order.append((name, url))

    for name, url in order:
        print(f"  从 [{name}] 下载 ...")
        if _download_one(url, dest, name):
            return True
    return False


def _download_one(url, dest, name):
    """单源下载，带总时长 + 停滞双重超时"""
    last_data = [time.time()]
    stop = threading.Event()
    state = {"reason": "", "aborted": False}

    def watchdog():
        """看门狗：总时长超限或停滞过久则中断连接"""
        t0 = time.time()
        while not stop.wait(1.0):
            now = time.time()
            if now - t0 > DL_TOTAL_TIMEOUT:
                state["reason"] = f"总时长超过 {DL_TOTAL_TIMEOUT}s"
                state["aborted"] = True
                return
            if now - last_data[0] > DL_STALL_TIMEOUT:
                state["reason"] = f"连续 {DL_STALL_TIMEOUT}s 无数据（网络停滞）"
                state["aborted"] = True
                return

    wd = threading.Thread(target=watchdog, daemon=True)
    wd.start()

    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "kards-installer"})
        with urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT) as resp, \
                open(dest, "wb") as f:
            total_hdr = resp.getheader("Content-Length")
            total = int(total_hdr) if total_hdr and total_hdr.isdigit() else None
            done, t0, last_ui = 0, time.time(), 0.0
            while True:
                if state["aborted"]:
                    raise IOError(state["reason"])
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                last_data[0] = time.time()
                now = time.time()
                if now - last_ui >= 0.15:       # 限流刷新，避免刷屏卡 UI
                    last_ui = now
                    el = max(now - t0, 0.01)
                    spd = done / el / 1048576
                    if total:
                        filled = int(28 * done / total)
                        bar = "#" * filled + "-" * (28 - filled)
                        left = (total - done) / max(done / el, 1)
                        print(f"\r    [{bar}] {done * 100 // total:3d}% "
                              f"{human(done)}/{human(total)} "
                              f"{spd:.2f}MB/s 剩余~{left:.0f}s", end="")
                    else:
                        print(f"\r    已下载 {human(done)}  {spd:.2f}MB/s", end="")
            print()
        stop.set()

        if total and done != total:
            print(f"    下载不完整（{human(done)}/{human(total)}）")
            return False
        if done == 0:
            print("    未收到任何数据")
            return False
        print(f"  下载完成（{human(done)}，来源 {name}）")
        return True
    except Exception as e:
        stop.set()
        if state["aborted"]:
            msg = state["reason"]
        elif isinstance(e, IOError) and str(e):
            msg = str(e)
        else:
            msg = f"{type(e).__name__}: {e}"
        print(f"    失败: {msg}")
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except OSError:
            pass
        return False


# ---------------------------------------------------------------- 解压

def extract(zip_path, install_dir):
    """解压到 install_dir（用户指定的目录本身 = 程序目录）。

    zip 内的路径都带 `KARDS/` 顶层前缀，这里**剥掉该前缀**再写入，
    保证 KARDS.exe 直接落在 install_dir 下，而不是多套一层。
    以文件为单位推进进度，避免大文件造成进度长时间不动。
    """
    with zipfile.ZipFile(zip_path) as z:
        members = [(i, i.filename) for i in z.infolist() if not i.is_dir()]
        if not members:
            raise IOError("压缩包内没有文件")
        # 若所有条目共享同一个顶层目录，则剥掉它
        tops = {fn.split("/")[0] for _i, fn in members if "/" in fn}
        strip = f"{tops.pop()}/" if len(tops) == 1 and \
            all(fn.startswith(next(iter(tops)) + "/") for _i, fn in members) else ""

        os.makedirs(install_dir, exist_ok=True)
        total = len(members)
        print(f"    目标目录: {install_dir}")
        print(f"    共 {total} 个文件，"
              f"{human(sum(i.file_size for i, _ in members))}")
        for n, (info, fn) in enumerate(members, 1):
            rel = fn[len(strip):] if strip else fn
            dest = os.path.join(install_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out, 512 * 1024)
            if n % 25 == 0 or n == total:
                filled = 20 * n // total
                print(f"\r    [{'#' * filled}{'-' * (20 - filled)}] "
                      f"{n}/{total} 文件", end="")
        print()
    print("  解压完成")


# ---------------------------------------------------------------- 快捷方式 / 注册

def _ps_quote(s):
    """PowerShell 单引号字面量转义：内部的 ' 需写成 ''"""
    return str(s).replace("'", "''")


def make_shortcut(lnk, target, workdir, desc):
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath='%s';$s.WorkingDirectory='%s';"
        "$s.Description='%s';$s.Save()"
        % (_ps_quote(lnk), _ps_quote(target), _ps_quote(workdir), _ps_quote(desc))
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else f"exit {r.returncode}")


def shell_folder(name):
    ps = f"[Environment]::GetFolderPath('{name}')"
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       check=True, capture_output=True, text=True, timeout=30)
    out = r.stdout.strip()
    return out or os.path.join(os.path.expanduser("~"), name)


def register_uninstall(install_dir, version, hklm):
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


def fetch_latest_version():
    """从 GitHub API 取最新 Release 的 tag（失败用回退值，绝不阻塞）"""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/releases/latest")
        with urllib.request.urlopen(req, timeout=10) as r:
            tag = json.load(r).get("tag_name", "")
        v = tag.lstrip("v").strip()
        return v if v else FALLBACK_VERSION
    except Exception:
        return FALLBACK_VERSION


# ---------------------------------------------------------------- 主流程

def cleanup_old(install_dir):
    """覆盖安装：清掉旧程序文件（保留 uninstall.py）"""
    try:
        for n in os.listdir(install_dir):
            p = os.path.join(install_dir, n)
            if n == "uninstall.py":
                continue
            if n in ("KARDS.exe", "KARDS.zip", "_internal"):
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
    except OSError:
        pass


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

    # 管理权限：目标不可写且当前非管理员 → 请求提权
    if not can_write(install_dir) and not is_admin():
        print("  目标目录需要管理员权限，弹出 UAC 授权窗口...")
        relaunch_as_admin()      # 拒绝则降级继续

    # 提前统一超时，避免任何请求无限等待
    socket.setdefaulttimeout(CONNECT_TIMEOUT)

    # 1. 下载
    print("\n[1/4] 下载 KARDS.zip ...")
    tmp_zip = os.path.join(tempfile.gettempdir(), "KARDS-install.zip")
    for p in (tmp_zip, tmp_zip + ".part"):
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    t_dl = time.time()
    if not download(tmp_zip):
        print("\n错误: 所有下载源均失败。")
        print("可能原因：网络受限 / 代理未开启 / 镜像站临时故障。")
        print("建议：检查网络后重试，或手动下载 KARDS.zip 后放到同一目录再运行安装器。")
        input("\n按回车键退出 ...")
        sys.exit(1)
    print(f"  下载耗时 {time.time() - t_dl:.0f}s")

    # 2. 解压
    print("\n[2/4] 解压安装 ...")
    if os.path.isdir(install_dir):
        cleanup_old(install_dir)
    try:
        extract(tmp_zip, install_dir)
    except Exception as e:
        print(f"  解压失败: {e}")
        input("\n按回车键退出 ...")
        sys.exit(1)
    try:
        os.remove(tmp_zip)
    except OSError:
        pass

    # 3. 用户数据目录 + 卸载器
    print("\n[3/4] 初始化用户数据目录 ...")
    for sub in ("", "logs", "decks"):
        os.makedirs(os.path.join(DATA_DIR, sub), exist_ok=True)
    print(f"  用户数据: {DATA_DIR}（设置/日志/自组卡组）")
    uni_src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "uninstall.py")
    if os.path.isfile(uni_src):
        try:
            shutil.copy2(uni_src, os.path.join(install_dir, "uninstall.py"))
        except OSError as e:
            print(f"  卸载器复制失败（不影响游戏）: {e}")

    # 4. 快捷方式 + 系统注册
    print("\n[4/4] 创建快捷方式并注册到系统 ...")
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
    print("  安装完成！双击桌面快捷方式即可开始游戏")
    print(f"  程序目录: {install_dir}")
    print(f"  用户数据: {DATA_DIR}")
    print("=" * 56)
    if os.path.isfile(exe):
        try:
            os.startfile(DATA_DIR)
        except OSError:
            pass
    input("按回车键退出安装器 ...")


if __name__ == "__main__":
    main()
