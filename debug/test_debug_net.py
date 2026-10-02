# -*- coding: utf-8 -*-
"""--debug-on-net 自战模式冒烟测试：确认双窗口自动连服 → 匹配 → 开局对打。

⚠ 必须自己起服务器。改造为**服务器模式**之后，`--debug-on-net` 不再自己
监听端口，而是要求先有 `kards_server.py` 在跑（否则只会打一行
「连不上服务器」就退出，测试会白等到超时 —— 这正是本文件早先 FAIL 的原因）。

同时要隔离两个窗口的会话文件：`kards_account` 是模块级单例，两个窗口共用
一份 session.json 时，后连的那个窗口会用前一个的令牌 resume，服务器判
「同账号异地登录」把先连的踢掉（curl 探针已实证）。
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

PY = r"C:/Users/freet/AppData/Local/Programs/Python/Python313/python.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_LOG = os.devnull          # ⚠ 不能是 PIPE：没人读会写满管道把服务器卡死


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_port(port, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), 0.3).close()
            return True
        except OSError:
            time.sleep(0.15)
    return False


def main():
    tmp = tempfile.mkdtemp(prefix="kards_dbgnet_")
    port = free_port()
    srv = subprocess.Popen(
        [PY, os.path.join(ROOT, "kards_server.py"),
         "--host", "127.0.0.1", "--port", str(port),
         "--db", os.path.join(tmp, "db.sqlite")],
        stdout=open(SERVER_LOG, "wb"), stderr=subprocess.STDOUT, cwd=ROOT)
    proc = None
    try:
        if not wait_port(port):
            print("服务器未能启动")
            return 1
        # 让被测进程把账号/会话写到临时目录，别污染真实用户数据
        env = dict(os.environ)
        env["KARDS_DATA_DIR"] = tmp
        proc = subprocess.Popen(
            [PY, "-u", os.path.join(ROOT, "KARDS.py"),
             "--debug-on-net", f"127.0.0.1:{port}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            cwd=ROOT, env=env)
        ready = False
        out = []
        t0 = time.time()
        # 双窗口自动匹配 + 组卡 + 开局，给足时间（实测 ~25s）
        while time.time() - t0 < 90:
            line = proc.stdout.readline()
            if not line:
                break
            out.append(line.rstrip())
            if "就绪" in line:
                ready = True
                break
            if "Traceback" in line or "MSG-ERROR" in line:
                for _ in range(12):
                    extra = proc.stdout.readline()
                    if not extra:
                        break
                    out.append(extra.rstrip())
                break
        print("\n".join(out))
        print("RESULT:", "PASS" if ready else "FAIL")
        if not ready:
            # 把「为什么没就绪」讲清楚，方便定位
            joined = "\n".join(out)
            if "连不上服务器" in joined:
                print("  原因：自战模式没连上服务器（检查地址参数是否被识别）")
            elif not out:
                print("  原因：子进程没有任何输出（可能启动即崩）")
        return 0 if ready else 1
    finally:
        for p in (proc, srv):
            if p is None:
                continue
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
