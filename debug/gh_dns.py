# -*- coding: utf-8 -*-
"""GitHub 域名 DNS 绕过 —— 本机 DNS 对 github.com 返回被污染的不可达 IP

背景（2026-10-01 实测）：
  - github.com          DNS 解析到 20.205.243.166 → TCP 443 完全不通（投毒）
  - api.github.com      解析正常，可达
  - raw.githubusercontent.com 等解析到内网地址 192.168.31.1 → 不可达
  - 而真实边缘节点 140.82.113.4 / 185.199.108.133 直连正常

方案：在进程内猴子补丁 socket.getaddrinfo，把已知域名映射到实测可达 IP。
优点：不需要管理员权限、不改系统 hosts、只影响本进程，退出即恢复。

用法:
    import gh_dns; gh_dns.install()
    # 之后同进程内所有 urllib / requests 访问 GitHub 都会走正确 IP

或命令行自检:
    python debug/gh_dns.py --check
"""
import socket
import sys
import time

# 实测可达的 GitHub 边缘节点（2026-10-01 验证）
# 若某天失效，用 curl --resolve 逐个试新 IP 后更新此表
IP_MAP = {
    "github.com": "140.82.113.4",
    "www.github.com": "140.82.113.4",
    "gist.github.com": "140.82.113.4",
    "api.github.com": "140.82.113.6",
    "uploads.github.com": "140.82.113.6",
    "codeload.github.com": "140.82.113.10",
    "raw.githubusercontent.com": "185.199.108.133",
    "objects.githubusercontent.com": "185.199.108.133",
    "avatars.githubusercontent.com": "185.199.108.133",
    "camo.githubusercontent.com": "185.199.108.133",
    "user-images.githubusercontent.com": "185.199.108.133",
    "github.githubassets.com": "185.199.108.154",
    "collector.github.com": "140.82.113.6",
    "alive.github.com": "140.82.113.6",
}

_installed = False
_orig_getaddrinfo = None


def install(verbose=False):
    """把 GitHub 域名解析重定向到实测可达 IP（进程级，幂等）"""
    global _installed, _orig_getaddrinfo
    if _installed:
        return
    _orig_getaddrinfo = socket.getaddrinfo

    def patched(host, *args, **kwargs):
        ip = IP_MAP.get(host) if isinstance(host, str) else None
        if ip:
            if verbose:
                print(f"  [dns] {host} -> {ip}")
            host = ip
        return _orig_getaddrinfo(host, *args, **kwargs)

    socket.getaddrinfo = patched
    _installed = True


def uninstall():
    global _installed
    if _installed and _orig_getaddrinfo is not None:
        socket.getaddrinfo = _orig_getaddrinfo
        _installed = False


def check():
    """自检：逐域名访问并报告状态"""
    install()
    import urllib.request
    targets = [
        ("github.com", "https://github.com/hello1-UI/Kards-simple-version"),
        ("api.github.com", "https://api.github.com/repos/hello1-UI/Kards-simple-version"),
        ("raw.githubusercontent.com", "https://raw.githubusercontent.com/"),
        ("codeload.github.com", "https://codeload.github.com/"),
    ]
    ok = 0
    for name, url in targets:
        t0 = time.time()
        try:
            r = urllib.request.urlopen(url, timeout=15)
            print(f"  OK   {name:28s} HTTP {r.status}  ({time.time()-t0:.1f}s)")
            ok += 1
        except Exception as e:
            print(f"  FAIL {name:28s} {type(e).__name__}: {e}")
    print(f"\n{ok}/{len(targets)} 可达")
    return ok == len(targets)


if __name__ == "__main__":
    if "--check" in sys.argv:
        print("[gh_dns] GitHub 连通性自检：")
        sys.exit(0 if check() else 1)
    print(__doc__)
