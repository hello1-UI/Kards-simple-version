"""复现 bug 2：联机组完卡组 → 开始战斗 → 卡出页面。

真实端到端：kards_server（随机端口）+ 两个 KARDS 实例（窗口 withdraw，
pygame 走 SDL dummy 无头）走 完整的 连服→登录→快速匹配→组卡→_start_mp
链路（与玩家操作一一对应，复用 --debug-auto）。

判定：
  · 两个窗口都打「就绪！联机对局已开始」→ 开局链路完好；
  · 出现异常栈 / ⚠ 疑似卡出页面 → 复现。
"""
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable if getattr(sys, "frozen", False) else \
    r"C:\Users\freet\AppData\Local\Programs\Python\Python313\python.exe"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_port(port, timeout=10):
    dl = time.time() + timeout
    while time.time() < dl:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return True
        except OSError:
            time.sleep(0.1)
    return False


def main():
    port = free_port()
    tmp = tempfile.mkdtemp(prefix="kards_e2e_")
    env = dict(os.environ)
    env["KARDS_DATA_DIR"] = tmp
    env["SDL_VIDEODRIVER"] = "dummy"

    srv = subprocess.Popen([PY, "kards_server.py", "--port", str(port)],
                           cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert wait_port(port), "服务器没起来"

    base = os.path.join(tmp, "clients")
    procs, outs = [], []
    for tag in ("A", "B"):
        e = dict(env)
        e["KARDS_DATA_DIR"] = os.path.join(base, tag)
        e["KARDS_DEBUG_WITHDRAW"] = "1"
        os.makedirs(e["KARDS_DATA_DIR"], exist_ok=True)
        p = subprocess.Popen(
            [PY, "KARDS.py", "--debug-auto", f"127.0.0.1:{port}", tag],
            cwd=ROOT, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace")
        procs.append(p)

    import threading
    lines = []
    lock = threading.RLock()          # RLock：flush 在持锁状态下也会被调


    def reader(p, idx):
        for line in p.stdout:
            with lock:
                lines.append((idx, line.rstrip()))


    def flush(idx, note):
        with lock:
            for i, ln in lines:
                if i == idx:
                    print(f"  [{idx}] {ln}", flush=True)
            lines[:] = [x for x in lines if x[0] != idx]


    threads = [threading.Thread(target=reader, args=(p, i), daemon=True)
               for i, p in enumerate(procs)]
    for t in threads:
        t.start()

    print(f"服务器 {port}，两个客户端已启动，等待开局…")
    dl = time.time() + 60
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
                    if ("异常" in ln and "Traceback" not in ln) or "卡出页面" in ln:
                        failed = True
                flush(0, "")
                flush(1, "")
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
        srv.terminate()
        time.sleep(1)
        # 再收割一次残余输出
        for i, ln in list(lines):
            print(f"  [{i}] {ln}")

    print()
    print("=== 结果 ===")
    print("A 就绪:", ready[0], " B 就绪:", ready[1], " 失败:", failed)
    ok = ready[0] and ready[1] and not failed
    print("E2E PASS" if ok else "E2E FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
