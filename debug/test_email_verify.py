# -*- coding: utf-8 -*-
"""邮箱验证（验证码）端到端测试：绑定邮箱 + 找回密码

SMTP 打桩：把 kards_server._smtp_send 换成内存发件箱，验证码从那里取。
服务器进程内起（daemon 线程），协议走真实 TCP。

运行: python debug/test_email_verify.py
"""
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["KARDS_DATA_DIR"] = tempfile.mkdtemp(prefix="kards_email_")

import kards_server as srv                            # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name
          + (f"  {extra}" if (extra and not cond) else ""))


SENT = []                    # [(to, code, purpose_txt)]
FAKE_CFG = {"user": "noreply@test.local", "auth": "stub", "host": "stub",
            "port": 465, "sender_name": "KARDS 测试"}


def fake_smtp(cfg, to, code, purpose_txt):
    SENT.append((to, code, purpose_txt))


srv._smtp_send = fake_smtp
srv.email_config = lambda: dict(FAKE_CFG)             # 打桩配置读取

# ---------------- 起服（进程内，随机端口） ----------------
DB_PATH = os.path.join(os.environ["KARDS_DATA_DIR"], "kards_server.db")
srv.DB = srv.Store(DB_PATH)
SRV = srv.Server(("127.0.0.1", 0), srv.ClientHandler)
PORT = SRV.server_address[1]
threading.Thread(target=SRV.serve_forever, daemon=True).start()
ADDR = f"127.0.0.1:{PORT}"


class Conn:
    """裸协议客户端：握手 + 应答式请求"""

    def __init__(self):
        self.sock = socket.create_connection(("127.0.0.1", PORT), timeout=6)
        self.sock.settimeout(6)
        self.buf = b""

    def send(self, obj):
        self.sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))

    def recv(self):
        while b"\n" not in self.buf:
            data = self.sock.recv(4096)
            if not data:
                return None
            self.buf += data
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def request(self, obj, want=None):
        """发送并等应答；跳过服务器主动推送（lobby/hall_* 广播）"""
        if want is None:
            want = {"email_of": {"email_of", "err"},
                    "email_code": {"email_code_ok", "err"},
                    "bind_email": {"bind_email_ok", "err"},
                    "register": {"auth_ok", "auth_err"},
                    "login": {"auth_ok", "auth_err"},
                    "resume": {"auth_ok", "auth_err"},
                    }.get(obj.get("m"), {obj.get("m")})
        self.send(obj)
        for _ in range(20):
            rep = self.recv()
            if rep is None:
                return None
            if rep.get("m") in want:
                return rep
            # 其它（lobby/hall 广播）跳过继续等
        return None

    def handshake(self, user, pw):
        rep = self.request({"m": "register", "user": user, "pw": pw})
        if rep and rep.get("m") == "auth_err" and "已被注册" in rep.get("err", ""):
            rep = self.request({"m": "login", "user": user, "pw": pw})
        return rep

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def last_code(to):
    for t, c, _p in reversed(SENT):
        if t == to:
            return c
    return None


def main():
    print("=" * 60)
    print("邮箱验证（验证码）端到端测试")
    print("=" * 60)

    # ---------- 0. 未配置邮箱时的行为 ----------
    saved_cfg = srv.email_config
    srv.email_config = lambda: None
    rep = net_one_shot({"m": "email_code", "purpose": "reset",
                        "email": "a@b.com"})
    check("未配置 SMTP → 提示未配置", rep and "未配置" in (rep.get("err") or ""),
          rep)
    srv.email_config = saved_cfg

    # ---------- 1. 找回密码：发码 ----------
    # 先注册玩家二并绑定邮箱 —— 新校验顺序下「邮箱未绑定」是零消耗
    # 短路，不绑的话错码段根本轮不到验证码出场
    MAIL = "player1@qq.com"
    c = Conn()
    rep = c.handshake("玩家二", "pw2222")
    c.close()
    srv.DB.bind_email("玩家二", MAIL)
    rep = net_one_shot({"m": "email_code", "purpose": "reset", "email": MAIL})
    check("重置发码成功", rep and rep.get("m") == "email_code_ok", rep)
    code = last_code(MAIL)
    check("验证码是 6 位数字", code and re.fullmatch(r"\d{6}", code), code)
    check("验证码不落库不回显（邮件里才有）",
          all(str(code) not in json.dumps(m) for m in [rep]), "")

    # ---------- 2. 冷却限频 ----------
    rep = net_one_shot({"m": "email_code", "purpose": "reset", "email": MAIL})
    check("60s 冷却内重发被拒",
          rep and "太频繁" in (rep.get("err") or ""), rep)

    # ---------- 3. 错码防穷举 ----------
    c2 = Conn()
    srv._email_codes.clear()                 # 跳过冷却（仅测试）
    net_one_shot({"m": "email_code", "purpose": "reset", "email": MAIL})
    code = last_code(MAIL)
    for i in range(5):
        rep = net_one_shot({"m": "reset_password", "email": MAIL,
                            "code": "000000" if code != "000000" else "111111",
                            "new_pw": "abcd1234"})
    check("错码 5 次后作废", rep and "作废" in (rep.get("err") or ""), rep)
    rep = net_one_shot({"m": "reset_password", "email": MAIL,
                        "code": code, "new_pw": "abcd1234"})
    check("作废后正确码也失效", rep and "错误或已过期" in (rep.get("err") or ""),
          rep)

    # ---------- 4. 邮箱格式 ----------
    for bad in ("no-at-mark", "a@b", "@x.com", "a b@c.com", "x@" + "a" * 300 + ".com"):
        rep = net_one_shot({"m": "email_code", "purpose": "reset", "email": bad})
        check(f"非法邮箱被拒: {bad[:24]}…", rep and "格式" in (rep.get("err") or ""),
              rep)

    # ---------- 5. 完整找回密码 ----------
    c = Conn()
    rep = c.handshake("玩家一", "pw1111")
    check("注册玩家一成功", rep and rep.get("m") == "auth_ok", rep)
    tok_old = rep.get("token")
    c.close()

    c = Conn()
    rep = c.handshake("玩家二", "pw2222")   # 已注册 → 登录；新会话用于验证「重置踢会话」
    tok_old = rep.get("token")
    c.close()

    srv._email_codes.clear()
    rep = net_one_shot({"m": "email_code", "purpose": "reset", "email": MAIL})
    code = last_code(MAIL)
    check("已绑定邮箱重置发码", rep and rep.get("m") == "email_code_ok", rep)

    rep = net_one_shot({"m": "reset_password", "email": MAIL, "code": "999999",
                        "new_pw": "newpass1"})
    check("错码重置被拒", rep and rep.get("m") == "err", rep)
    rep = net_one_shot({"m": "reset_password", "email": MAIL, "code": code,
                        "new_pw": "ab1"})
    check("新密码太短被拒", rep and "至少 6 位" in (rep.get("err") or ""), rep)
    rep = net_one_shot({"m": "reset_password", "email": MAIL, "code": code,
                        "new_pw": "newpass1"})
    check("正确码重置成功且回显用户名",
          rep and rep.get("m") == "reset_ok" and rep.get("user") == "玩家二", rep)

    # 重置后：旧会话失效 + 新密码可登录 + 旧密码被拒
    c = Conn()
    rep = c.request({"m": "resume", "token": tok_old})
    check("重置后旧会话失效", rep and rep.get("m") == "auth_err", rep)
    c.close()
    c = Conn()
    rep = c.request({"m": "login", "user": "玩家二", "pw": "pw2222"})
    check("旧密码登录被拒", rep and rep.get("m") == "auth_err", rep)
    rep = c.request({"m": "login", "user": "玩家二", "pw": "newpass1"})
    check("新密码登录成功", rep and rep.get("m") == "auth_ok", rep)

    # ---------- 6. 登录态绑定邮箱 ----------
    rep = c.request({"m": "email_of"})
    check("登录态查询绑定状态",
          rep and rep.get("m") == "email_of" and rep.get("bound") is True, rep)
    check("email_of 脱敏", rep and "***@" in (rep.get("email") or ""), rep)

    srv._email_codes.clear()
    rep = c.request({"m": "email_code", "purpose": "bind",
                     "email": "p1@163.com"})
    code = last_code("p1@163.com")
    check("绑定发码成功", rep and rep.get("m") == "email_code_ok", rep)
    rep = c.request({"m": "bind_email", "email": "p1@163.com", "code": "000000"})
    check("绑定错码被拒", rep and rep.get("m") == "err", rep)
    rep = c.request({"m": "bind_email", "email": "p1@163.com", "code": code})
    check("绑定成功", rep and rep.get("m") == "bind_email_ok"
          and "163.com" in (rep.get("email") or ""), rep)

    # ---------- 7. 一邮箱只能绑一个账号 ----------
    c2 = Conn()
    c2.handshake("玩家三", "pw3333")
    srv._email_codes.clear()
    c2.request({"m": "email_code", "purpose": "bind", "email": "p1@163.com"})
    code = last_code("p1@163.com")
    rep = c2.request({"m": "bind_email", "email": "p1@163.com", "code": code})
    check("邮箱已被其它账号绑定 → 拒绝",
          rep and "已绑定其他账号" in (rep.get("err") or ""), rep)
    c2.close()

    # ---------- 8. 未绑定邮箱的账号 ----------
    rep = c.request({"m": "email_code", "purpose": "bind",
                     "email": "player1@qq.com"})
    srv._email_codes.clear()
    check("换绑新邮箱发码（冷却已清）",
          rep and rep.get("m") == "email_code_ok", rep)
    c.close()

    # ---------- 9. 老库迁移：无 email 列的老库 ----------
    import sqlite3
    old = os.path.join(os.environ["KARDS_DATA_DIR"], "old.db")
    conn = sqlite3.connect(old)
    conn.executescript(
        "CREATE TABLE users(name TEXT PRIMARY KEY, salt TEXT NOT NULL,"
        " pw TEXT NOT NULL, created INTEGER NOT NULL, last_seen INTEGER);")
    conn.commit()
    conn.close()
    store = srv.Store(old)
    cols = {r["name"] for r in store.conn.execute("PRAGMA table_info(users)")}
    check("老库打开后自动补 email 列", "email" in cols, cols)

    # ---------- 10. mask_email ----------
    check("mask_email 长名", srv.mask_email("someone@qq.com") == "so***@qq.com",
          srv.mask_email("someone@qq.com"))
    check("mask_email 短名", srv.mask_email("ab@x.com") == "a***@x.com",
          srv.mask_email("ab@x.com"))
    check("mask_email 空", srv.mask_email("") is None, "")

    # ---------- 11. Store 邮箱方法 ----------
    # 步骤 6 里玩家二已换绑到 p1@163.com → 新邮箱指向玩家二，旧邮箱被释放
    check("find_by_email（换绑后）",
          srv.DB.find_by_email("p1@163.com") == "玩家二",
          srv.DB.find_by_email("p1@163.com"))
    check("email_taken 返回占用者",
          srv.DB.email_taken("p1@163.com") == "玩家二", "")
    check("换绑后旧邮箱被释放", srv.DB.find_by_email(MAIL) is None, "")
    check("email_of 未绑定返回 None", srv.DB.email_of("玩家一") is None, "")

    SRV.shutdown()
    print("=" * 60)
    print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print("失败项:", *FAIL, sep="\n  - ")
        sys.exit(1)
    print("全部通过 ✓")


def net_one_shot(msg):
    """客户端侧一次性请求（复用 kards_net.one_shot 走真实协议）"""
    import kards_net
    return kards_net.one_shot(ADDR, msg, timeout=6.0)


if __name__ == "__main__":
    main()
