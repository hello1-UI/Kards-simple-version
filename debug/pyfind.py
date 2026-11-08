# -*- coding: utf-8 -*-
"""pyfind —— 找一个「装了需要的模块」的 Python 解释器

为什么需要这一层
    KARDS.py 顶部就 `import tkinter`，而某些受管的 Python（工具自带、
    Store 版精简包）没有 tkinter。测试脚本如果直接拿 sys.executable 去
    spawn 主程序，会得到 ModuleNotFoundError —— 看起来像"游戏坏了"，
    其实只是解释器选错了。

    以前每个脚本各写一份候选列表，里面还写死了作者本机的绝对路径
    （形如 `%LOCALAPPDATA%\\Programs\\Python\\Python313\\python.exe` 展开后的结果）。
    换台机器那条就废了，而且把用户名带进了公开仓库。

    现在候选是**算出来的**：sys.executable → PATH 上的 python → 常见安装目录，
    再逐个 try `import`，第一个能导入的就用。
"""
import glob
import os
import shutil
import subprocess
import sys

# 常见安装位置（按"越新越可能带 tkinter"的顺序，倒序排）
_INSTALL_GLOBS = (
    r"%LOCALAPPDATA%\Programs\Python\Python3*\python.exe",
    r"%ProgramFiles%\Python3*\python.exe",
    r"%ProgramFiles(x86)%\Python3*\python.exe",
    r"C:\Python3*\python.exe",
)


def candidates():
    """按优先级列出可能可用的解释器（已去重、已过滤不存在的）"""
    out = [sys.executable]
    for name in ("python", "python3", "py"):
        p = shutil.which(name)
        if p:
            out.append(p)
    for pat in _INSTALL_GLOBS:
        expanded = os.path.expandvars(pat)
        if "%" in expanded:              # 环境变量不存在（如非 Windows）就跳过
            continue
        out.extend(sorted(glob.glob(expanded), reverse=True))

    seen, uniq = set(), []
    for p in out:
        try:
            key = os.path.normcase(os.path.abspath(p))
        except (OSError, ValueError):
            continue
        if key in seen or not os.path.isfile(p):
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def find_python(*modules, timeout=25):
    """返回第一个能 `import <modules…>` 的解释器；都失败则回退 sys.executable

    modules 为空时等价于"随便找一个能跑的"。
    """
    probe = "import " + ", ".join(modules) if modules else "pass"
    for p in candidates():
        try:
            r = subprocess.run([p, "-c", probe], capture_output=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0:
            return p
    return sys.executable


if __name__ == "__main__":
    print("\n".join(candidates()))
    print("=" * 40)
    print("带 tkinter:", find_python("tkinter"))
