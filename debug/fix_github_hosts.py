# -*- coding: utf-8 -*-
"""写入 GitHub hosts 加速解析（需管理员权限）

背景：本机 DNS 对 github.com 返回被污染的 20.205.243.166（不可达），
而 api.github.com / raw.githubusercontent.com 等域名解析正常。
本脚本把已知可达的 GitHub 边缘节点写入 hosts，绕过 DNS 投毒。

用法（自动提权）:
    python debug/fix_github_hosts.py
"""
import ctypes
import datetime
import os
import shutil
import sys

HOSTS = r"C:\Windows\System32\drivers\etc\hosts"
MARK_S = "# ===== GitHub 加速（WorkBuddy 添加）====="
MARK_E = "# ===== GitHub 加速结束 ====="
BLOCK = [
    MARK_S,
    "# 背景：本机 DNS 对 github.com 返回被污染的 IP（不可达）",
    "# 以下 IP 为实测可用的 GitHub 边缘节点；若失效需更新本文件后重跑脚本",
    "140.82.113.4      github.com",
    "140.82.113.4      www.github.com",
    "140.82.113.4      gist.github.com",
    "140.82.113.6      api.github.com",
    "140.82.113.10     codeload.github.com",
    "185.199.108.133   raw.githubusercontent.com",
    "185.199.108.133   objects.githubusercontent.com",
    "185.199.108.133   avatars.githubusercontent.com",
    "185.199.108.133   camo.githubusercontent.com",
    "185.199.108.133   user-images.githubusercontent.com",
    "185.199.108.154   github.githubassets.com",
    MARK_E,
]


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def elevate():
    """以管理员身份重新启动本脚本"""
    params = " ".join(f'"{a}"' for a in sys.argv)
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1)
    return ret > 32


def apply_block():
    os.makedirs(r"C:\Users\freet\.workbuddy", exist_ok=True)
    bak = os.path.join(
        r"C:\Users\freet\.workbuddy",
        f"hosts.backup-{datetime.datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(HOSTS, bak)
    print(f"[备份] {bak}")

    with open(HOSTS, "r", encoding="utf-8", errors="ignore") as f:
        cur = f.read()

    # 幂等：移除旧块再追加
    if MARK_S in cur:
        keep, out = True, []
        for ln in cur.splitlines():
            if ln.strip() == MARK_S:
                keep = False
            if keep:
                out.append(ln)
            if ln.strip() == MARK_E:
                keep = True
        cur = "\n".join(out)
        print("[清理] 已移除旧的 GitHub 加速块")

    new = cur.rstrip("\n") + "\n\n" + "\n".join(BLOCK) + "\n"
    with open(HOSTS, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(new)
    print(f"[写入] 成功，hosts 大小 {os.path.getsize(HOSTS)} 字节")


def verify():
    import socket
    print("\n[验证] 解析结果：")
    for d in ("github.com", "api.github.com", "raw.githubusercontent.com",
              "codeload.github.com"):
        try:
            print(f"  {d:34s} -> {socket.gethostbyname(d)}")
        except Exception as e:
            print(f"  {d:34s} -> 失败 {e}")


def main():
    if not is_admin():
        print("[提权] 需要管理员权限，正在请求 UAC …")
        if not elevate():
            print("[失败] 提权被拒绝。请右键以管理员身份运行终端后重试。")
            input("按回车退出…")
            return 1
        return 0
    try:
        apply_block()
        verify()
    except Exception as e:
        print(f"[错误] {e}")
        input("按回车退出…")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
