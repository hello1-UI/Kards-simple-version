# -*- coding: utf-8 -*-
"""KARDS 简化版 · 在本机一键开服（大厅里点「建立服务器」）

为什么需要这一层
    联机是**服务器中转**模式，客户端要连的是 `kards_server.py`。
    但普通玩家手上只有一个 exe，没有 Python、也不会开命令行 ——
    让他们自己去 `python kards_server.py` 是不现实的。
    所以主程序要能**用自己把服务器拉起来**：

        KARDS.exe --server             ← 同一个 exe，换个入口跑服务器

    这条入口在 KARDS.py 的 main() 里处理（必须先于 tkinter 启动），
    所以本模块只负责「怎么把子进程拉起来 / 怎么停掉 / 有没有在跑」。

打包形态（onedir）下的目录结构：
    KARDS/            ← restart_dir()
      KARDS.exe
      _internal/      ← 程序目录（数据文件在这里，含 kards_server.py）
    服务器需要 import kards_server（同目录），所以启动时把
    `_internal`（也就是 sys._MEIPASS）放进 PYTHONPATH 并作为 cwd。

⚠ 只监听本机可见的网卡；防火墙没放行时其他机器连不上 —— 这个提示
   交给 GUI（i18n 文案里说明），本模块不弹窗。
"""
import os
import socket
import subprocess
import sys

DEFAULT_PORT = 6000

# 子进程句柄（模块级单例：一个游戏进程只开一个服务器）
_PROC = None
_PORT = DEFAULT_PORT


def resource_dir():
    """能 import 到 kards_server 的目录。

    · onedir 打包 → `_internal/`（sys._MEIPASS）
    · 源码运行   → 本文件所在目录
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


def server_script():
    """kards_server.py 的绝对路径；找不到返回 None（打包漏打时会走到这）。"""
    path = os.path.join(resource_dir(), "kards_server.py")
    return path if os.path.isfile(path) else None


def can_host():
    """本机是否具备开服条件（有脚本 + 有解释器）。"""
    if server_script() is None:
        return False
    return getattr(sys, "frozen", False) or _python_exe() is not None


def _python_exe():
    """源码运行时的解释器（打包后不需要）。"""
    exe = sys.executable
    return exe if exe else None


def port_in_use(host="127.0.0.1", port=DEFAULT_PORT, timeout=0.35):
    """端口是否已被占用（说明可能已经有一个服务器在跑）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        try:
            s.close()
        except OSError:
            pass


def running():
    """我们拉起的那个服务器子进程还在不在。"""
    global _PROC
    if _PROC is None:
        return False
    return _PROC.poll() is None


def start(port=DEFAULT_PORT, extra_args=None):
    """拉起服务器子进程。

    返回 (ok, 说明)：
        (True, "")                      已启动（或本来就在跑）
        (False, "原因")                 起不来
    ⚠ 子进程的 stdout/stderr **必须**指到 devnull：管道没人读会写满缓冲区
      然后子进程卡死（Windows 上尤其明显，见项目历史记录）。
    """
    global _PROC, _PORT
    if running():
        return True, ""
    script = server_script()
    if script is None:
        return False, "缺少 kards_server.py（安装包不完整）"

    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--server", "--port", str(port)]
        cwd = os.path.dirname(os.path.abspath(sys.executable))
    else:
        py = _python_exe()
        if not py:
            return False, "找不到 Python 解释器"
        cmd = [py, script, "--port", str(port)]
        cwd = os.path.dirname(script)

    env = dict(os.environ)
    # 让子进程能找到同目录的 kards_server / kards_engine
    res = resource_dir()
    old = env.get("PYTHONPATH") or ""
    env["PYTHONPATH"] = res + (os.pathsep + old if old else "")

    try:
        devnull = open(os.devnull, "wb")
    except OSError:
        devnull = subprocess.DEVNULL

    kwargs = {}
    if os.name == "nt":
        # 独立进程组：游戏退出时不连带把服务器带走（玩家可能还在用）
        kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
    try:
        _PROC = subprocess.Popen(cmd, cwd=cwd, env=env,
                                 stdin=subprocess.DEVNULL,
                                 stdout=devnull, stderr=devnull, **kwargs)
    except OSError as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            if devnull not in (subprocess.DEVNULL, None):
                devnull.close()
        except OSError:
            pass
    _PORT = port
    return True, ""


def stop():
    """停掉我们拉起的服务器（游戏退出时调用；不是我们拉的不动）。"""
    global _PROC
    if _PROC is None:
        return
    try:
        if _PROC.poll() is None:
            _PROC.terminate()
    except OSError:
        pass
    _PROC = None


def local_addr(port=None):
    """本机在局域网里的地址（填进大厅输入框用）。"""
    port = port or _PORT
    import kards_net
    ips = kards_net.get_local_ips()
    host = ips[0] if ips else "127.0.0.1"
    return f"{host}:{port}"
