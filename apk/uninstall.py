# -*- coding: utf-8 -*-
"""KARDS 简化版 —— 卸载器

由安装器复制到安装目录并注册到系统"应用和功能"。
删除内容:
  - 桌面/开始菜单快捷方式
  - 注册表卸载项 (HKLM 或 HKCU)
  - 程序安装目录（本程序所在目录）
  - 用户数据目录 %USERPROFILE%\\AppData\\Kards-Simple-Version（询问后可选删）

用法:
  KARDS卸载器.exe            # 交互式
  KARDS卸载器.exe --purge    # 跳过询问直接删除用户数据
  python uninstall.py [--purge]

既可作为打包后的 exe 运行，也可作为源码 .py 运行（两种形态都能定位安装目录）。
"""
import ctypes
import os
import shutil
import subprocess
import sys
import time

import winreg


def _force_utf8():
    """打包成 exe 后 Windows 控制台默认 GBK，输出 ✓ 之类的符号会崩。
    这里把 stdout/stderr 切成 UTF-8 并容错，避免因编码中断卸载流程。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


_force_utf8()

APP_ID = "Kards-Simple-Version"
DATA_DIR = os.path.join(os.path.expanduser("~"), "AppData", APP_ID)
UNINSTALL_KEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
                 r"\Kards-Simple-Version")
START_MENU = os.path.join(os.environ.get("APPDATA", ""),
                          "Microsoft", "Windows", "Start Menu", "Programs",
                          "KARDS 简化版.lnk")
LNK_NAME = "KARDS 简化版.lnk"
# 卸载器自身可能叫这些名字（找安装目录时用来判断"这里是不是安装目录"）
SELF_MARKERS = ("KARDS卸载器.exe", "uninstaller.exe", "uninstall.py",
                "KARDS.exe")


def self_dir():
    """本程序所在目录。

    打包成 exe 后 __file__ 不可用，改用 sys.executable；
    源码运行时两者都指向脚本所在目录。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """以管理员身份重启自身（UAC）。成功则退出当前进程。"""
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, " ".join(
            f'"{a}"' for a in sys.argv[1:])
    else:
        exe, params = sys.executable, " ".join(f'"{a}"' for a in sys.argv)
    ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params,
                                              None, 1)
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
    targets = [
        os.path.join(shell_desktop(), LNK_NAME),
        START_MENU,
        # 便携版/绿色版可能放在这些位置
        os.path.join(os.path.expanduser("~"), "Desktop", LNK_NAME),
        os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"),
                     "Desktop", LNK_NAME),
    ]
    for lnk in dict.fromkeys(targets):        # 去重且保序
        try:
            if os.path.isfile(lnk):
                os.remove(lnk)
        except OSError as e:
            print(f"  快捷方式删除失败: {lnk} ({e})")
    print("  快捷方式 ✓")


def remove_registry():
    """尝试删除 HKLM 与 HKCU 两处的注册项。

    注意：不能因为某处"不存在"或"无权限"就提前 return —— 两处都要试，
    否则管理员安装（HKLM）后换普通用户卸载、或反之，都会留下残留。
    """
    found = False
    for hive, name in ((winreg.HKEY_LOCAL_MACHINE, "HKLM"),
                       (winreg.HKEY_CURRENT_USER, "HKCU")):
        try:
            winreg.DeleteKey(hive, UNINSTALL_KEY)
            print(f"  系统注册项（{name}）✓")
            found = True
        except FileNotFoundError:
            continue
        except PermissionError:
            print(f"  注册项需管理员权限（{name}）")
        except OSError as e:
            print(f"  注册项删除失败（{name}）: {e}")
    if not found:
        print("  系统注册项：未找到（跳过）")


def _spawn_detached(cmd, cwd=None):
    """启动一个脱离当前进程的子进程（父进程退出后仍继续运行）。

    Windows 上只用 DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP，
    **不要**混用 CREATE_NO_WINDOW（两者语义冲突会导致进程起不来）。
    """
    flags = 0
    flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    return subprocess.Popen(
        cmd, cwd=cwd, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=flags)


def remove_install_dir(target, is_exe):
    """删除安装目录。

    目录里正运行着本程序（exe 或 py），Windows 不允许删除占用中的文件，
    因此起一个脱离的辅助进程：先等本进程退出，再递归删除目录。

    两条路径都**不依赖 cmd.exe / powershell 之外的额外工具**：
      - exe 模式：用同一份 exe 以 `--gc <target>` 参数自调用（最可靠，
        无需外部解释器），它只做「等待 + 删除」一件事。
      - 源码模式：用当前 Python 解释器跑一小段临时脚本。
    """
    if is_exe:
        exe = os.path.abspath(sys.executable)
        # 把自身工作目录挪出安装目录，否则 Windows 会因 CWD 占用而拒绝删除
        try:
            os.chdir(os.environ.get("SystemRoot", "C:\\"))
        except OSError:
            pass
        try:
            _spawn_detached([exe, "--gc", target, exe],
                            cwd=os.environ.get("SystemRoot", "C:\\"))
            print("  已安排后台清理程序目录")
        except OSError as e:
            print(f"  程序目录删除失败: {e}")
        return

    # 源码模式：写一个临时脚本，等本进程退出后删除
    tmp = os.path.join(os.environ.get("TEMP", target), "kards_uninstall_tmp.py")
    # 用三引号字面量整段写，避免逐行拼接时换行/转义出错
    script = '''import os, shutil, sys, time
target = %r
for _ in range(40):
    try:
        shutil.rmtree(target)
        break
    except OSError:
        time.sleep(0.5)
try:
    os.remove(sys.argv[0])
except OSError:
    pass
''' % target
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(script)
        _spawn_detached([sys.executable, tmp])
        print("  已安排后台清理程序目录")
    except OSError as e:
        print(f"  程序目录删除失败: {e}")


def gc_mode(target, self_path):
    """--gc 后台清理模式：等前一个进程释放文件占用后删除整个目录。

    由 remove_install_dir() 以子进程方式调用，自身不做任何交互。

    正在运行的 exe 无法删除自己，所以生成一个 .bat：
      - bat 由 cmd 执行，不受本进程文件占用影响
      - bat 循环重试 rd，直到目录删干净，最后 del 掉自己
    """
    time.sleep(1.5)

    bat = os.path.join(os.environ.get("TEMP", os.path.dirname(target)),
                       "kards_gc_%d.bat" % os.getpid())
    # 关键点：
    #   1) bat 自己必须待在 target 之外（放 TEMP），否则删不掉所在目录
    #   2) 用 `cd /d "%SystemRoot%"` 把工作目录挪出 target ——
    #      进程 CWD 落在目标目录内时，Windows 不允许删除该目录
    #   3) 循环重试 rd，给文件句柄释放留时间
    body = (
        "@echo off\r\n"
        "cd /d \"%SystemRoot%\"\r\n"
        "set TARGET=" + target + "\r\n"
        "for /L %%i in (1,1,40) do (\r\n"
        "  if not exist \"%TARGET%\" goto done\r\n"
        "  rd /s /q \"%TARGET%\" 2>nul\r\n"
        "  ping 127.0.0.1 -n 2 >nul\r\n"
        ")\r\n"
        ":done\r\n"
        "del /f /q \"%~f0\" 2>nul\r\n"
    )
    try:
        # bat 用系统默认编码写（ANSI），避免 cmd 读 UTF-8 时中文路径出错
        with open(bat, "w", encoding="mbcs", errors="replace") as f:
            f.write(body)
    except (OSError, LookupError):
        try:
            with open(bat, "w", encoding="utf-8", errors="replace") as f:
                f.write(body)
        except OSError as e:
            print(f"  后台清理脚本写入失败: {e}")
            return 1

    try:
        _spawn_detached(["cmd", "/c", bat])
    except OSError as e:
        print(f"  后台清理启动失败: {e}")
        return 1
    return 0


def main():
    # 后台清理模式：由 remove_install_dir() 以子进程调用，静默执行后退出
    if "--gc" in sys.argv:
        i = sys.argv.index("--gc")
        if i + 1 < len(sys.argv):
            self_path = sys.argv[i + 2] if i + 2 < len(sys.argv) else sys.executable
            sys.exit(gc_mode(sys.argv[i + 1], self_path))
        sys.exit(1)

    print("=" * 56)
    print("  KARDS 简化版 卸载器")
    print("=" * 56)

    target = self_dir()
    is_exe = getattr(sys, "frozen", False)
    print(f"  程序目录: {target}")

    # 安全检查：确认这确实是安装目录，别把别的目录删了
    if not any(os.path.exists(os.path.join(target, m)) for m in SELF_MARKERS):
        print("  警告: 该目录下没有找到 KARDS 相关文件，"
              "为避免误删，将不删除程序目录。")
        target = None

    # Program Files 需要管理员权限
    if target and not is_admin() and "program files" in target.lower():
        print("  需要管理员权限，弹出 UAC 授权窗口...")
        relaunch_as_admin()
        # 用户拒绝 UAC 会走不到这里；继续尝试（HKCU 部分仍可清理）

    print("[1/4] 删除快捷方式 ...")
    remove_shortcuts()

    print("[2/4] 清理系统注册项 ...")
    remove_registry()

    print("[3/4] 删除程序目录 ...")
    if target:
        print(f"  {target}")

    print("[4/4] 用户数据 ...")
    purge = "--purge" in sys.argv
    keep = "--keep" in sys.argv
    if not purge and not keep:
        # ⚠ 不要用 sys.stdin.isatty() 预判"有没有控制台"：exe 双击时它返回
        # False，会把用户的 y 输入吞掉。直接问，读不到就默认保留。
        # 从"应用和功能"里点卸载通常是静默的，那种情况 input() 会立刻 EOF。
        try:
            print("  是否同时删除用户数据（设置/日志/自组卡组）？")
            ans = input("  [y/N]: ")
            purge = ans.strip().lower() in ("y", "yes")
        except (EOFError, OSError, ValueError, KeyboardInterrupt):
            purge = False
            print("  （读不到输入，默认保留用户数据）")
    if purge:
        shutil.rmtree(DATA_DIR, ignore_errors=True)
        print(f"  已删除: {DATA_DIR}")
    else:
        print(f"  保留用户数据: {DATA_DIR}")

    if target:
        remove_install_dir(target, is_exe)
    print("卸载完成！")
    # exe 双击运行时留一下窗口，方便看结果
    if is_exe:
        try:
            input("按回车键退出 ...")
        except (EOFError, KeyboardInterrupt):
            pass


if __name__ == "__main__":
    main()
