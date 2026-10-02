# -*- coding: utf-8 -*-
"""GitHub 域名的 DNS 兜底 —— **优先信任系统解析，只在系统解析不可达时才接管**

背景：
  2026-10-01 本机 DNS 对 github.com / raw.githubusercontent.com 返回被污染或
  不可达的 IP，于是在进程内猴子补丁 socket.getaddrinfo 强行映射到实测 IP。

  2026-10-02 投毒解除，系统解析恢复正常（github.com → 20.205.243.166、
  api.github.com → 20.205.243.168、uploads.github.com → 20.205.243.161，
  全部可达）。但**硬编码表还停在旧世界**，于是它把 uploads.github.com 指向
  已失效的 140.82.113.6 → 发布 Release 时资产上传稳定 404。

  ⚠ 教训：硬编码 IP 表会随着网络环境变化悄悄腐烂，而且**失败方式是静默的**
  （请求发到错的主机，拿到 404 而不是连接错误，很难一眼看出是 DNS 的锅）。

现在的策略（自愈）：
  对表里的每个域名，**先按系统解析试连**（TCP 443，短超时，并行探测）；
  系统解析能连上 → 就用系统的（这张表等于不存在，不会拖慢也不会带偏）；
  系统解析全连不上 → 才退回表里的候选 IP。

  结果按 (host, port) 缓存在进程内，所以最多只在首次访问某域名时付一次探测成本。

用法:
    import gh_dns; gh_dns.install()
    # 之后同进程内所有 urllib / requests 访问 GitHub 都会拿到能连上的 IP

自检（会打印每个域名最终选了哪个 IP、来自系统还是兜底）:
    python debug/gh_dns.py --check
"""
import socket
import sys
import threading
import time

# 仅作**兜底**候选：只有在系统解析出的所有 IP 都连不上时才会用到。
# 表里没有的域名一律不干预，直接走系统解析。
FALLBACK_IP = {
    # —— 20.205.243.x：GitHub 亚太边缘节点（2026-10-02 实测全部可达）
    "github.com": "20.205.243.166",
    "www.github.com": "20.205.243.166",
    "gist.github.com": "20.205.243.166",
    "api.github.com": "20.205.243.168",
    "uploads.github.com": "20.205.243.161",
    "codeload.github.com": "20.205.243.165",
    "collector.github.com": "20.205.243.168",
    # —— 140.82.113.x：美国节点，旧表值，实测仍可达，留作第二手
    "alive.github.com": "140.82.113.6",
}

# 这些域名本机 **TCP 443 完全不通**（185.199.x.x 段被阻断），
# 列出来只是为了 --check 能给出明确结论，不作为兜底目标。
KNOWN_BLOCKED = (
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "avatars.githubusercontent.com",
    "camo.githubusercontent.com",
    "user-images.githubusercontent.com",
    "github.githubassets.com",
)

PROBE_TIMEOUT = 1.2          # 单个 IP 的 TCP 探测超时（秒）

_installed = False
_orig_getaddrinfo = None
_cache = {}                  # (host, port) -> ip or None
_cache_lock = threading.Lock()


def _tcp_ok(ip, port, timeout=PROBE_TIMEOUT):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except OSError:
            pass


def _first_reachable(ips, port, timeout=PROBE_TIMEOUT):
    """并行探测，按传入顺序返回第一个能连上的 IP。

    并行很关键：串行探测 4 个不可达 IP 会累加超时（4×1.2s），
    并行则整体只花约一个超时的时间。
    """
    hits = {}
    lock = threading.Lock()

    def probe(ip):
        ok = _tcp_ok(ip, port, timeout)
        with lock:
            hits[ip] = ok

    threads = [threading.Thread(target=probe, args=(ip,), daemon=True) for ip in ips]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout + 0.8)
    for ip in ips:                       # 保持原顺序（解析顺序自带优先级含义）
        if hits.get(ip):
            return ip
    return None


def _system_ips(host, port, *args, **kwargs):
    """系统解析出的 IPv4 列表（有序、去重）。用 _orig_getaddrinfo 避免递归。"""
    try:
        infos = _orig_getaddrinfo(host, port, *args, **kwargs)
    except OSError:
        return []
    out = []
    for info in infos:
        try:
            ip = info[4][0]
        except (IndexError, TypeError):
            continue
        if ":" in ip or ip in out:       # 只要 IPv4，且去重
            continue
        out.append(ip)
    return out


def _pick_ip(host, port, *args, **kwargs):
    """决定这个域名该用哪个 IP。返回 None 表示"交给系统解析"。"""
    if host not in FALLBACK_IP:
        return None

    with _cache_lock:
        if (host, port) in _cache:
            return _cache[(host, port)]

    chosen = None
    # 1) 先信系统：能连上就用系统的
    sys_ips = _system_ips(host, port, *args, **kwargs)
    if sys_ips:
        chosen = _first_reachable(sys_ips, port)
    # 2) 系统解析全军覆没，才用兜底候选
    if chosen is None:
        alt = FALLBACK_IP.get(host)
        if alt and alt not in sys_ips and _tcp_ok(alt, port):
            chosen = alt

    with _cache_lock:
        _cache[(host, port)] = chosen
    return chosen


def install(verbose=False):
    """安装解析补丁（进程级、幂等）。

    注意：这里**不再**无条件重写域名 —— 只有系统解析不可达时才接管，
    所以 DNS 正常的环境下这个补丁等于透明的。
    """
    global _installed, _orig_getaddrinfo
    if _installed:
        return
    _orig_getaddrinfo = socket.getaddrinfo

    def patched(host, port, *args, **kwargs):
        if isinstance(host, str):
            ip = _pick_ip(host, port, *args, **kwargs)
            if ip:
                if verbose:
                    print(f"  [dns] {host} -> {ip}（系统解析不可达，用兜底）")
                return _orig_getaddrinfo(ip, port, *args, **kwargs)
        return _orig_getaddrinfo(host, port, *args, **kwargs)

    socket.getaddrinfo = patched
    _installed = True


def uninstall():
    global _installed
    if _installed and _orig_getaddrinfo is not None:
        socket.getaddrinfo = _orig_getaddrinfo
        _installed = False


def check():
    """自检：报告每个域名的系统解析结果、最终选用、以及是否可达"""
    install()
    import urllib.request

    targets = [
        ("github.com", "https://github.com/hello1-UI/Kards-simple-version"),
        ("api.github.com", "https://api.github.com/repos/hello1-UI/Kards-simple-version"),
        ("uploads.github.com", "https://uploads.github.com/"),
        ("codeload.github.com", "https://codeload.github.com/"),
        ("raw.githubusercontent.com", "https://raw.githubusercontent.com/"),
    ]

    print("[gh_dns] GitHub 连通性自检：")
    print(f"  {'域名':28s} {'系统解析':22s} {'实际使用':16s} 结果")
    ok = 0
    for name, url in targets:
        probe_args = dict(type=socket.SOCK_STREAM)
        sys_ips = _system_ips(name, 443, **probe_args)
        picked = _pick_ip(name, 443, **probe_args)
        src = "兜底IP" if picked else ("系统" if sys_ips else "—")
        shown = picked or (sys_ips[0] if sys_ips else "解析失败")
        sys_shown = ",".join(sys_ips[:2]) if sys_ips else "无"
        if len(sys_ips) > 2:
            sys_shown += f"(+{len(sys_ips)-2})"
        t0 = time.time()
        try:
            r = urllib.request.urlopen(url, timeout=20)
            print(f"  {name:28s} {sys_shown:22s} {shown:16s} OK {r.status} [{src}] "
                  f"{time.time()-t0:.1f}s")
            ok += 1
        except Exception as e:                       # noqa: BLE001
            note = "  ← 已知被阻断段" if name in KNOWN_BLOCKED else ""
            print(f"  {name:28s} {sys_shown:22s} {shown:16s} FAIL "
                  f"{type(e).__name__} [{src}]{note}")

    print(f"\n{ok}/{len(targets)} 可达（不可达域名若在 KNOWN_BLOCKED 中属预期）")
    return ok >= len(targets) - len(KNOWN_BLOCKED)


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
    print(__doc__)
