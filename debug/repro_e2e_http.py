"""复现 bug 2（云端 HTTP 桥路径）：本地桥接 + 两个客户端走 HttpServerLink。

完整链路：连服(HttpServerLink)→登录→快速匹配→组卡→_start_mp→开局。
"""
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = r"C:\Users\freet\AppData\Local\Programs\Python\Python313\python.exe"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_http(port, timeout=15):
    import urllib.request
    dl = time.time() + timeout
    while time.time() < dl:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/healthz", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:                              # noqa: BLE001
            time.sleep(0.2)
    return False


def main():
    port = free_port()
    tmp = tempfile.mkdtemp(prefix="kards_e2e_http_")
    env = dict(os.environ)
    env["KARDS_DATA_DIR"] = tmp
    env["PORT"] = str(port)

    relay = subprocess.Popen([PY, "cloud/kards_relay/app.py"], cwd=ROOT, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert wait_http(port), "桥接没起来"

    procs, lines, lock = [], [], threading.RLock()

    for tag in ("A", "B"):
        e = dict(env)
        e["KARDS_DATA_DIR"] = os.path.join(tmp, tag)
        os.makedirs(e["KARDS_DATA_DIR"], exist_ok=True)
        p = subprocess.Popen(
            [PY, "-u", "debug/repro_e2e_http_client.py", str(port), tag],
            cwd=ROOT, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
        procs.append(p)


    def reader(p, idx):
        for line in p.stdout:
            with lock:
                lines.append((idx, line.rstrip()))


    def flush(idx):
        with lock:
            for i, ln in lines:
                if i == idx:
                    print(f"  [{idx}] {ln}", flush=True)
            lines[:] = [x for x in lines if x[0] != idx]


    for i, p in enumerate(procs):
        threading.Thread(target=reader, args=(p, i), daemon=True).start()

    print(f"桥接 {port}，两个 HTTP 客户端已启动…")
    dl = time.time() + 75
    ready = {0: False, 1: False}
    failed = False
    observe_until = None
    try:
        while time.time() < dl:
            time.sleep(0.5)
            with lock:
                for i, ln in list(lines):
                    if "就绪！联机对局已开始" in ln:
                        ready[i] = True
                    if "异常" in ln or "卡出页面" in ln:
                        failed = True
                flush(0)
                flush(1)
            if not (ready[0] and ready[1]):
                continue
            if observe_until is None:
                observe_until = time.time() + 45   # 双方就绪后再看 45s 真实对局
                dl = max(dl, observe_until + 5)
                print("双方就绪，观察 45s 的真实出牌对局…", flush=True)
            if time.time() >= observe_until:
                break
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        relay.terminate()
        time.sleep(1)
        with lock:
            for i, ln in list(lines):
                print(f"  [{i}] {ln}")

    print()
    print("=== 结果 ===")
    print("A 就绪:", ready[0], " B 就绪:", ready[1], " 失败:", failed)
    ok = ready[0] and ready[1] and not failed
    print("HTTP E2E PASS" if ok else "HTTP E2E FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
