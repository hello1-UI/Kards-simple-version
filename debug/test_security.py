# -*- coding: utf-8 -*-
"""防盗号加固回归。

覆盖（对应 2026-11-28 安全加固）：
  1. 密码策略：新密码最少 6 位、不得与用户名相同（存量登录不受影响）；
  2. 登录防爆破：连错 5 次锁定 10 分钟，锁定期内密码正确也拒；
  3. 迁移账号哈希升级：sha256 免密建号首次明文登录后自动升级 PBKDF2；
  4. change_pw：验旧密码、错 5 次也触发锁定、成功后作废其它会话；
  5. 本地凭据 DPAPI 加密落盘 + 旧明文兼容；
  6. 桥接层按真实 IP 限流：/c 频率与并发、/s 消息频率。

真实服务器 / 真实 HTTP 桥接（进程内），协议原样走 socket / urllib。
"""
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("KARDS_DATA_DIR", os.path.join(ROOT, ".tmp_sec_test"))
os.makedirs(os.environ["KARDS_DATA_DIR"], exist_ok=True)

import kards_server as srv
import kards_net as net

passed = failed = 0


def check(ok, label, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [!!] {label}  {detail}")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


DB_PATH = os.path.join(tempfile.mkdtemp(prefix="kards_sec_db_"), "db.sqlite")
srv.DB = srv.Store(DB_PATH)
PORT = free_port()
SRV = srv.Server(("127.0.0.1", PORT), srv.ClientHandler)
threading.Thread(target=SRV.serve_forever, daemon=True).start()
print(f"1. 测试服务器就绪（TCP :{PORT}）")


class Conn:
    """裸协议客户端：注册/登录握手 + 任意后续消息。"""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.settimeout(6)
        self.sock.connect(("127.0.0.1", PORT))
        self.sock.settimeout(None)     # ⚠ 长期复用，不能留超时
        self.link = net.ServerLink(self.sock, ("127.0.0.1", PORT))
        self.token = None

    def auth(self, msg):
        """发握手消息，等 auth_ok / auth_err。"""
        self.link.send(msg)
        dl = time.time() + 8
        while time.time() < dl:
            try:
                m = self.link.inbox.get(timeout=0.3)
            except Exception:
                continue
            if isinstance(m, dict) and m.get("m") in ("auth_ok", "auth_err"):
                if m["m"] == "auth_ok":
                    self.token = m.get("token")
                return m
        raise RuntimeError("握手超时")

    def request(self, obj):
        r = self.link.request(obj, key=None if obj.get("m") != "change_pw"
                              else "change_pw", timeout=8)
        return r

    def close(self):
        try:
            self.link.close()
        except Exception:                  # noqa: BLE001
            pass


def wait_inbox(conn, mtype, timeout=8):
    dl = time.time() + timeout
    while time.time() < dl:
        try:
            m = conn.link.inbox.get(timeout=0.3)
        except Exception:
            continue
        if isinstance(m, dict) and m.get("m") == mtype:
            return m
    return None


# ================================================================ 2. 密码策略
print("2. 密码策略（只约束新设密码）")
c = Conn()
r = c.auth({"m": "register", "user": "安全测试甲", "pw": "abc1"})
check(r.get("m") == "auth_err" and "6" in (r.get("err") or ""),
      "4 位密码注册被拒", r)
r = c.auth({"m": "register", "user": "安全测试甲", "pw": "安全测试甲"})
check(r.get("m") == "auth_err", "密码=用户名被拒", r)
r = c.auth({"m": "register", "user": "安全测试甲", "pw": "pw123456"})
check(r.get("m") == "auth_ok", "6 位合规密码注册成功", r)
tok_a = c.token

# 存量 4 位密码账号仍可登录（策略不回溯）
with srv.DB_LOCK:
    salt = srv.secrets.token_hex(16)
    srv.DB.x("INSERT INTO users(name,salt,pw,created,last_seen) VALUES(?,?,?,?,?)",
             ("旧密码老张", salt, srv.DB.hash_pw(salt, "ab12"), 1, 1))
c2 = Conn()
r = c2.auth({"m": "login", "user": "旧密码老张", "pw": "ab12"})
check(r.get("m") == "auth_ok", "存量短密码账号登录不受影响", r)
c2.close()
c.close()

# ================================================================ 3. 登录锁定
print("3. 登录防爆破")
srv.AUTH_LOCK_S = 1          # 测试里把锁缩短到 1s，验证过期后能恢复
srv.AUTH_FAIL_WINDOW = 900
c = Conn()
for i in range(4):
    r = c.auth({"m": "login", "user": "安全测试甲", "pw": "wrongpw"})
check(r.get("m") == "auth_err", "连错 4 次仍未锁定（正常报密码错）", r)
r = c.auth({"m": "login", "user": "安全测试甲", "pw": "wrongpw"})
check(r.get("m") == "auth_err" and "锁定" in (r.get("err") or ""),
      "第 5 次失败触发锁定", r)
r = c.auth({"m": "login", "user": "安全测试甲", "pw": "pw123456"})
check(r.get("m") == "auth_err" and "锁定" in (r.get("err") or ""),
      "锁定期内密码正确也被拒", r)
time.sleep(1.3)
r = c.auth({"m": "login", "user": "安全测试甲", "pw": "pw123456"})
check(r.get("m") == "auth_ok", "锁过期后正确密码恢复登录", r)
c.close()

# ================================================================ 4. 哈希升级
print("4. 迁移账号 sha256 → PBKDF2 自动升级")
import hashlib
lc_salt = "deadbeef"
lc_hash = hashlib.sha256((lc_salt + "oldpw123").encode()).hexdigest()
c = Conn()
r = c.auth({"m": "adopt", "user": "升级测试乙", "salt": lc_salt, "pw": lc_hash})
check(r.get("m") == "auth_ok", "本机免密建号（sha256 哈希）成功", r)
rows = srv.DB.q("SELECT pw FROM users WHERE name='升级测试乙'")
check(rows and rows[0]["pw"].startswith("sha256:"),
      "建号时确实存的弱哈希（复现前提）")
c.close()
c = Conn()
r = c.auth({"m": "login", "user": "升级测试乙", "pw": "oldpw123"})
check(r.get("m") == "auth_ok", "明文登录成功", r)
rows = srv.DB.q("SELECT pw FROM users WHERE name='升级测试乙'")
check(rows and not rows[0]["pw"].startswith("sha256:") and ":" not in rows[0]["pw"],
      "登录后哈希已升级为 PBKDF2")
c2 = Conn()
r = c2.auth({"m": "login", "user": "升级测试乙", "pw": "oldpw123"})
check(r.get("m") == "auth_ok", "升级后原密码仍可登录（登录踢线属正常）", r)
c2.close()
c.close()

# ================================================================ 5. change_pw
print("5. 修改密码（change_pw）")
c = Conn()
c.auth({"m": "register", "user": "改密测试丙", "pw": "pw111111"})
tok_a = c.token             # 发起方会话（改密后应保留）
c2 = Conn()
r = c2.auth({"m": "login", "user": "改密测试丙", "pw": "pw111111"})
check(r.get("m") == "auth_ok", "第二设备登录拿到会话", r)
tok_b = c2.token            # 第二设备的会话（改密后应被作废）
c2.close()                  # ⚠ 同账号重复登录会踢掉旧连接 —— c 已被踢死，
                            # 用 resume 恢复自己的会话再继续操作
c.close()
c = Conn()
r = c.auth({"m": "resume", "token": tok_a})
check(r.get("m") == "auth_ok", "发起方 resume 恢复会话", r)

r = c.request({"m": "change_pw", "old": "wrongold", "new": "pw222222"})
check(r and r.get("m") == "err" and "旧密码" in (r.get("err") or ""),
      "旧密码错误被拒", r)
r = c.request({"m": "change_pw", "old": "pw111111", "new": "ab1"})
check(r and r.get("m") == "err" and "6" in (r.get("err") or ""),
      "新密码太短被拒（不消耗锁定）", r)
r = c.request({"m": "change_pw", "old": "pw111111", "new": "改密测试丙"})
check(r and r.get("m") == "err", "新密码=用户名被拒", r)
r = c.request({"m": "change_pw", "old": "pw111111", "new": "pw222222"})
check(r and r.get("m") == "change_ok", "正确旧密码修改成功", r)

# 旧 token 失效（第二设备的会话被作废）
c3 = Conn()
r = c3.auth({"m": "resume", "token": tok_b})
check(r.get("m") == "auth_err", "其它设备的旧 token 已作废", r)
c3.close()
# 当前会话 token 仍在
c3 = Conn()
r = c3.auth({"m": "resume", "token": tok_a})
check(r.get("m") == "auth_ok", "发起方自己的会话保留", r)
c3.close()
# 新密码登录 / 旧密码登录
c2 = Conn()
r = c2.auth({"m": "login", "user": "改密测试丙", "pw": "pw222222"})
check(r.get("m") == "auth_ok", "新密码可登录", r)
c2.close()
c2 = Conn()
r = c2.auth({"m": "login", "user": "改密测试丙", "pw": "pw111111"})
check(r.get("m") == "auth_err", "旧密码已失效", r)
c2.close()

# 错 5 次旧密码也触发锁定
# （上面的新/旧密码登录测试把 c 踢掉了 —— 同账号一线，先 resume 回来）
c.close()
c = Conn()
r = c.auth({"m": "resume", "token": tok_a})
check(r.get("m") == "auth_ok", "再次 resume 恢复会话", r)
for i in range(5):
    r = c.request({"m": "change_pw", "old": "wrongwrong", "new": "pw333333"})
r_last = c.request({"m": "change_pw", "old": "pw222222", "new": "pw333333"})
check(r_last and r_last.get("m") == "err" and "锁定" in (r_last.get("err") or ""),
      "change_pw 连错 5 次触发锁定", r_last)
time.sleep(1.3)
r = c.request({"m": "change_pw", "old": "pw222222", "new": "pw333333"})
check(r and r.get("m") == "change_ok", "锁过期后改密恢复", r)
c.close()

# ================================================================ 6. DPAPI
print("6. 本地凭据 DPAPI 加密（Windows）")
import kards_account as acct
if sys.platform == "win32":
    tmp = os.path.join(tempfile.mkdtemp(prefix="kards_dpapi_"), "cred.json")
    payload = {"current": "测试者", "users": {"测试者": {"salt": "aa", "pw": "bb"}}}
    acct._write_creds(tmp, payload)
    raw = open(tmp, "rb").read()
    check(raw.startswith(acct._DPAPI_MAGIC), "落盘文件已加密（DPAPI 头）")
    check("测试者".encode("utf-8") not in raw, "明文不出现在文件里")
    check(acct._read_creds(tmp) == payload, "加密往返读取一致")
    with open(tmp, "wb") as f:            # 旧明文兼容
        f.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    check(acct._read_creds(tmp) == payload, "旧明文文件仍可读（自动兼容）")
else:
    print("  [跳过] 非 Windows 平台")

# ================================================================ 7. 桥接限流
print("7. 桥接层按真实 IP 限流（进程内 HTTP）")
import urllib.request
import urllib.error
TMP2 = tempfile.mkdtemp(prefix="kards_sec_relay_")
os.environ["KARDS_DATA_DIR"] = TMP2
_spec = importlib.util.spec_from_file_location(
    "kards_sec_relay_app",
    os.path.join(ROOT, "cloud", "kards_relay", "app.py"))
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)
httpd = app.start_http(0)
BPORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{BPORT}"


def post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


# 正常流程不受影响（这个会话也算进每分钟配额）
sids = []
st, r = post("/c", {})
check(st == 200 and r.get("sid"), "正常建会话不受影响", r)
sid0 = r["sid"]
sids.append(sid0)
st, r = post(f"/s?sid={sid0}", {"sid": sid0,
                                "d": json.dumps({"m": "ping"}, ensure_ascii=False)})
check(st == 200 and r.get("ok"), "正常上行不受影响", r)

# /s 频率闸门（60 条/10s）
flood_ok = 0
got_429 = False
for i in range(80):
    st, r = post(f"/s?sid={sid0}", {"sid": sid0, "d": "{}"})
    if st == 200 and r.get("ok"):
        flood_ok += 1
    if st == 429:
        got_429 = True
        break
check(got_429 and flood_ok >= app.MSG_PER_10S - 1,   # 闸门含前面 ping 占的 1 条
      f"/s 超 {app.MSG_PER_10S} 条/10s 被限流（放行 {flood_ok} 条）")

# /c 频率闸门（6 次/分钟；上面已用 1 次，再建 5 次后第 7 次应 429）
for i in range(5):
    st, r = post("/c", {})
    if st == 200 and r.get("sid"):
        sids.append(r["sid"])
st, r = post("/c", {})
check(st == 429, "单 IP 每分钟建会话超限被 429", (st, r))
st, r = post("/c", {})
check(st == 429, "继续 /c 仍被限", st)

# 释放全部会话后再 /s：并发配额归还后不再 429（时间桶仍在，等窗口滑走）
for s in sids:
    post(f"/x?sid={s}", {"sid": s})
st, r = post(f"/s?sid={sids[0]}", {"sid": sids[0], "d": "{}"})
check(st == 429, "已释放会话的 /s 不再可用（gone/限流）", st)

print()
total = passed + failed
print(f"通过 {passed} 项 / 失败 {failed} 项 / 共 {total} 项")
sys.exit(1 if failed else 0)
