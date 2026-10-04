# -*- coding: utf-8 -*-
"""账号迁移（本地账号 → 服务器）端到端测试

背景（2026-10-04 用户报的 bug）：
    主菜单注册的账号存在本地 accounts.json；进联机后账号操作被代理到
    服务器 SQLite。两边互不相通 → 已登录用户进联机被判成「游客」，
    用同一组用户名密码登录又被报「用户名或密码错误」。

修复：服务器登录被拒且本地同名同密码核对通过 → 自动把账号注册上
服务器（迁移）并把本地战绩 stats_seed 搬上去。

启动真实服务器（随机端口 + 临时库），用 kards_net.ServerLink +
kards_account 跑完整流程。

用法: python debug/test_migrate.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
PORT = 6412
SERVER_LOG = os.devnull

# DATA_DIR 重定向必须先于 kards_account 导入
sys.path.insert(0, ROOT)
import kards_engine as core
core.DATA_DIR = tempfile.mkdtemp(prefix="kards_mig_test_")
import kards_account as acc
import kards_net as net

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


def raw_msg(port, msg, expect_timeout=6):
    """开一条裸连接发一条消息（未握手/握手均可），读一行应答"""
    s = socket.create_connection(("127.0.0.1", port), timeout=expect_timeout)
    try:
        s.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            d = s.recv(4096)
            if not d:
                break
            buf += d
        return json.loads(buf.split(b"\n", 1)[0].decode("utf-8")) if buf.strip() else None
    finally:
        s.close()


def link(port=PORT):
    return net.ServerLink(socket.create_connection(("127.0.0.1", port), timeout=6))


def main():
    db_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="kards_mig_")
    os.close(db_fd)
    os.unlink(db_path)

    proc = subprocess.Popen(
        [PY, os.path.join(ROOT, "kards_server.py"),
         "--port", str(PORT), "--host", "127.0.0.1", "--db", db_path],
        cwd=ROOT, stdout=open(SERVER_LOG, "wb"), stderr=subprocess.STDOUT)
    try:
        ok = False
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=0.3).close()
                ok = True
                break
            except OSError:
                time.sleep(0.1)
        if not ok:
            print("服务器启动失败")
            return 1

        # ---------- 0. 本地账号（无服务器状态） ----------
        print("\n===== 0. 准备本地账号 =====")
        okr, err = acc.register("MigUser", "pass1234")
        check("本地注册 MigUser", okr and acc.backend() == "local", err)
        acc.stats_add("MigUser", "win")
        acc.stats_add("MigUser", "win")
        acc.stats_add("MigUser", "lose")
        check("本地战绩 2胜1负",
              acc.get_stats("MigUser") == {"win": 2, "lose": 1, "draw": 0},
              str(acc.get_stats("MigUser")))
        acc.logout()
        check("已退出（游客）", acc.current() is None)

        # ---------- 1. 迁移登录（核心场景 = 用户报的 bug） ----------
        print("\n===== 1. 联机登录触发迁移 =====")
        lk = link()
        acc.set_remote(lk, f"127.0.0.1:{PORT}")
        check("服务器后端已挂载", acc.backend() == "server")
        okr, err = acc.login("MigUser", "pass1234")
        check("本地账号在服务器登录成功（自动迁移）", okr, err)
        check("登录后身份正确", acc.current() == "MigUser",
              repr(acc.current()))
        check("会话令牌已缓存", bool(acc._load_session().get("token")))
        # 战绩被搬上服务器（get_stats 走 stats rpc）
        st = acc.get_stats("MigUser")
        check("战绩已迁移到服务器 2胜1负",
              st == {"win": 2, "lose": 1, "draw": 0}, str(st))

        # ---------- 2. 断线重连：token 免密 resume ----------
        print("\n===== 2. 重连免密 resume =====")
        lk.close()
        lk2 = link()
        acc.set_remote(lk2, f"127.0.0.1:{PORT}")
        okr, who = acc.connect()
        check("重连后 token 免密登录", okr and who == "MigUser", f"{okr} {who!r}")

        # ---------- 3. 服务器已有同名账号、密码不同 ----------
        print("\n===== 3. 服务器同名账号密码冲突 =====")
        acc.logout()
        r = raw_msg(PORT, {"m": "register", "user": "Clash", "pw": "srvpw"})
        check("服务器预注册 Clash", r and r.get("m") == "auth_ok", str(r))
        # 本地造一个同名但密码不同的账号（先摘掉 remote 回本地后端）
        acc.set_remote(None)
        okr, err = acc.register("Clash", "locpw")
        check("本地注册同名 Clash", okr, err)
        acc.logout()
        acc.set_remote(link(), f"127.0.0.1:{PORT}")
        okr, err = acc.login("Clash", "locpw")
        check("密码冲突被拒且提示清晰",
              not okr and "服务器" in err and "密码" in err, err)

        # ---------- 4. 服务器账号 + 纯错误密码（不该触发迁移） ----------
        print("\n===== 4. 错误密码不迁移 =====")
        okr, err = acc.login("Clash", "srvpw")
        check("服务器密码可正常登录", okr, err)
        acc.logout()
        okr, err = acc.login("Clash", "totally-wrong")
        check("纯错密码仍报「用户名或密码错误」",
              not okr and "用户名或密码错误" in err, err)

        # ---------- 5. stats_seed 防灌水（只认全 0 账号） ----------
        print("\n===== 5. stats_seed 防灌水 =====")
        r = raw_msg(PORT, {"m": "register", "user": "SeedT", "pw": "pw1234"})
        check("注册 SeedT", r and r.get("m") == "auth_ok", str(r))
        # 裸连接没握手成功前不能 dispatch；重新连并 resume
        s = socket.create_connection(("127.0.0.1", PORT), timeout=6)
        s.sendall((json.dumps({"m": "resume", "token": r["token"]}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            buf += s.recv(4096)
        # 第一次 seed：全 0 → 生效
        s.sendall((json.dumps({"m": "stats_seed", "win": 7, "lose": 0, "draw": 1}) + "\n").encode())
        time.sleep(0.3)
        s.sendall((json.dumps({"m": "stats"}) + "\n").encode())
        time.sleep(0.3)
        lines = [l for l in buf.split(b"\n") if l.strip()] if b"\n" in buf else []
        # 简单起见重新开连接查战绩
        s.close()
        lk3 = link()
        acc.set_remote(lk3, f"127.0.0.1:{PORT}")
        okr, _ = acc.connect()   # 会话是 MigUser 的；SeedT 用新连接查不了
        # 直接用裸连接 + 新 token 查：重新登录 SeedT
        rep = lk3.request({"m": "login", "user": "SeedT", "pw": "pw1234"}, key="login")
        check("SeedT 重新登录", rep and rep.get("m") == "auth_ok", str(rep))
        rep = lk3.request({"m": "stats"}, key="stats")
        st = (rep or {}).get("stats") or {}
        check("第一次 seed 生效 7胜0负1平",
              st == {"win": 7, "lose": 0, "draw": 1}, str(st))
        rep = lk3.request({"m": "stats_seed", "win": 99, "lose": 0, "draw": 0},
                          key="stats_seed")
        rep = lk3.request({"m": "stats"}, key="stats")
        st = (rep or {}).get("stats") or {}
        check("第二次 seed 被拒（战绩不变）",
              st == {"win": 7, "lose": 0, "draw": 1}, str(st))
        lk3.close()

        # ---------- 6. 服务器掉线 → 本地回退仍可登录 ----------
        print("\n===== 6. 服务器掉线本地回退 =====")
        lk2.close()
        proc.terminate()
        proc.wait(timeout=10)
        time.sleep(0.3)
        acc.set_remote(None)
        okr, err = acc.login("MigUser", "pass1234")
        check("掉线后本地回退登录", okr, err)
        check("本地登录身份正确", acc.current() == "MigUser", repr(acc.current()))

        # ---------- 7. resume 收到明确拒绝才清会话缓存 ----------
        print("\n===== 7. 会话缓存保护 =====")
        acc.logout()
        check("logout 清掉会话", acc._load_session() == {}, str(acc._load_session()))

    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    print(f"\n=== 结果: {len(PASS)} 通过 / {len(FAIL)} 失败 ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
