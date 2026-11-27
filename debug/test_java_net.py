# -*- coding: utf-8 -*-
"""Android/Java 联机客户端 ↔ Python kards_server 端到端互通测试

流程：起一台真实 kards_server（临时库）→ 跑 Java 探针 NetProbe
（同一 JVM 两个会话：注册 → 建房/加入 → 双方 ready → 种子 → act 中转
→ 投降）→ 校验探针退出码与输出。

用法: python debug/test_java_net.py
"""
import os
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
PORT = 6199
LOG = os.path.join(tempfile.gettempdir(), "kards_java_net_probe.log")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name
          + (f"  {detail}" if detail else ""))


def main():
    print("\n=== 1. 编译 Java（engine + net + app + CLI）===")
    srcs = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                       encoding="utf-8")
    srcs.close()
    found = []
    for base in ("android/app/src/main/java/com/kards",
                 "debug/java_cli/android_stub", "debug/java_cli"):
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, base)):
            for f in files:
                if f.endswith(".java"):
                    found.append(os.path.join(dirpath, f))
    with open(srcs.name, "w", encoding="utf-8") as fh:
        fh.write("\n".join(found))
    cls = os.path.join(tempfile.gettempdir(), "kards_net_test_cls")
    r = subprocess.run(["javac", "-d", cls, "@" + srcs.name],
                       cwd=ROOT, capture_output=True)
    err = (r.stderr or b"").decode("gbk", "replace")
    check("javac 编译零错误", r.returncode == 0, err[-500:])
    if r.returncode != 0:
        return 1

    print("\n=== 2. 启动 kards_server（临时库）===")
    db_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="kards_net_")
    os.close(db_fd)
    os.unlink(db_path)
    proc = subprocess.Popen(
        [PY, os.path.join(ROOT, "kards_server.py"),
         "--port", str(PORT), "--host", "127.0.0.1", "--db", db_path],
        cwd=ROOT, stdout=open(LOG, "wb"), stderr=subprocess.STDOUT)
    try:
        ok = False
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=0.3).close()
                ok = True
                break
            except OSError:
                time.sleep(0.1)
        check("服务器就绪 127.0.0.1:%d" % PORT, ok)
        if not ok:
            return 1

        print("\n=== 3. Java 探针全流程对拍 ===")
        try:
            r = subprocess.run(
                ["java", "-cp", cls, "KardsCli", "--netprobe", str(PORT)],
                cwd=ROOT, capture_output=True, timeout=90)
        except subprocess.TimeoutExpired as e:
            check("探针 90s 内完成", False, str(e)[:200])
            return 1
        out = ((r.stdout or b"").decode("gbk", "replace")
               + (r.stderr or b"").decode("gbk", "replace"))
        for line in out.splitlines():
            print("  | " + line)
        check("探针退出码 0（全流程通过）", r.returncode == 0,
              "exit=%d" % r.returncode)
        check("探针自报全部通过", "0 失败" in out or "0 FAIL" in out)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("\n=== 4. Android 禁止开服自查 ===")
    # 全项目 Java 源码不得出现任何服务端监听/服务器入口
    # （只查真实服务端代码特征；注释里提到 kards_server 不算）
    bad = []
    for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "android")):
        for f in files:
            if not f.endswith(".java"):
                continue
            p = os.path.join(dirpath, f)
            with open(p, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for token in ("ServerSocket", "run_server_entry",
                          "bind(", "listen("):
                if token in text:
                    bad.append(f"{os.path.relpath(p, ROOT)}:{token}")
    check("Android 源码无任何开服代码（无服务端监听）", not bad, bad)
    manifest = os.path.join(ROOT, "android", "app", "src", "main",
                            "AndroidManifest.xml")
    with open(manifest, encoding="utf-8") as fh:
        man = fh.read()
    check("Manifest 声明 INTERNET 权限（仅客户端联网）",
          "android.permission.INTERNET" in man)

    print(f"\n=== Java 联机互通回归: {len(PASS)} 通过 / {len(FAIL)} 失败 ===")
    if FAIL:
        for name in FAIL:
            print("  失败: " + name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
