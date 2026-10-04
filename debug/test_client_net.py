# -*- coding: utf-8 -*-
"""客户端网络层集成测试：ServerLink / kards_account 服务器后端

启动一个真实的 kards_server 子进程（临时端口 + 临时 DB），
然后用 ServerLink 走完整流程：
  注册 / 重复注册 / 错误密码 / 令牌 resume / 大厅快照 /
  快速匹配（两个客户端配对）/ 邀请码房间 / 行动中转 / 断线通知

运行: python debug/test_client_net.py
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_net as net                      # noqa: E402
import kards_account as account              # noqa: E402
import kards_engine as core                  # noqa: E402

# ⚠ 服务器 stdout **不要**用 PIPE 而不读：Windows 管道缓冲区只有 4-8KB，
# 服务器 log() 每条连接都会打印，写满后 print 阻塞 → 单线程 accept 循环卡死。
SERVER_LOG = os.devnull

PASS = 0
FAIL = []


def check(label, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  [OK] {label}")
    else:
        FAIL.append(label)
        print(f"  [!!] {label} {extra}")


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
            s = socket.create_connection(("127.0.0.1", port), 0.3)
            s.close()
            return True
        except OSError:
            time.sleep(0.15)
    return False


class Client:
    """一个测试用客户端：先建 socket，握手成功后才套上 ServerLink。

    ⚠ 两条必须遵守的协议事实（踩过坑）：
    1. **握手必须是第一条消息**。服务器的 handshake() 读第一条消息，不是
       login/register/resume 就直接 auth_err（协议级垃圾才断开；
       2026-10-04 起认证失败保留连接允许重试，见 kards_server.handshake）。
       所以不能在连接时就发 lobby —— 必须先认证。
    2. ServerLink.inbox 是单一队列，`request(key=...)` 的应答等待者可能
      截走同类型的推送事件。这里统一改成「应答也只走 inbox + 按类型过滤」，
       测试语义更清晰，也顺便覆盖了 GUI 用的就是这条路。
    """

    def __init__(self, port):
        self.port = port
        self.sock = socket.create_connection(("127.0.0.1", port), 5)
        self.sock.settimeout(None)
        self.link = None
        self.events = []
        self.user = None
        self.token = None

    # ---- 握手 ----

    def auth(self, kind, user=None, pw=None, **kw):
        """认证。成功才把 socket 包成 ServerLink（服务器在此之后才接受业务消息）"""
        obj = {"m": kind}
        if user is not None:
            obj["user"] = user
        if pw is not None:
            obj["pw"] = pw
        obj.update(kw)
        self.sock.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        rep = self._read_until(("auth_ok", "auth_err"), timeout=8)
        if rep and rep.get("m") == "auth_ok":
            self.user = rep.get("user")
            self.token = rep.get("token")
            self.link = net.ServerLink(self.sock, ("127.0.0.1", self.port))
        return rep

    def _read_until(self, types, timeout=6):
        """直接读 socket 直到出现指定类型（握手期还没有 ServerLink）"""
        end = time.time() + timeout
        buf = b""
        self.sock.settimeout(1.0)
        while time.time() < end:
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                return None
            if not data:
                return None
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    m = json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if m.get("m") in types:
                    self.sock.settimeout(None)
                    return m
                self.events.append(m)
        self.sock.settimeout(None)
        return None

    # 命令 → 应答类型。必须与 kards_server.dispatch 逐条对齐：
    # ⚠ 服务器的应答类型**不一定**等于请求类型，等错类型会一直等到超时
    #   （stats_add → stats、deck_save → deck_saved、deck_del → deck_list…）
    _REPLY = {
        "lobby":        ("lobby",),
        "match":        ("matched", "matching", "err"),
        "cancel_match": ("match_cancelled", "err"),
        "create_room":  ("room_created", "err"),
        "join_room":    ("matched", "join_err", "err"),
        "leave_room":   ("err", "peer_left"),
        "stats":        ("stats", "err"),
        "stats_add":    ("stats", "err"),
        "deck_save":    ("deck_saved", "err"),
        "deck_list":    ("deck_list", "err"),
        "deck_get":     ("deck_data", "err"),
        "deck_del":     ("deck_list", "err"),
        "ping":         ("pong",),
    }

    def req(self, m, timeout=5, **kw):
        """发一条请求并等应答。

        ⚠ 等待期间必须**持续把非应答包收进 events**：ServerLink 的收包线程
        不会自己清空 inbox，而同一个连接在等应答时可能同时收到别人的
        `lobby` 广播等事件。wait() 已经做了"边等边收"，这里不额外处理，
        但结论是：**不能用 request(key=...)**，那会把事件包误当应答吃掉。
        """
        self.link.send({"m": m, **kw})
        types = self._REPLY.get(m, (m, "err"))
        return self.wait(*types, timeout=timeout)

    def wait(self, *types, timeout=5, keep=False):
        """等一个指定类型的事件（非该类型的留在 events 缓冲里）"""
        end = time.time() + timeout
        while True:
            for i, e in enumerate(self.events):
                if e.get("m") in types:
                    if not keep:
                        self.events.pop(i)
                    return e
            remain = end - time.time()
            if remain <= 0:
                return None
            try:
                self.events.append(self.link.inbox.get(timeout=min(remain, 0.2)))
            except Exception:
                pass

    def drain(self):
        while True:
            try:
                self.events.append(self.link.inbox.get_nowait())
            except Exception:
                return

    def clear(self):
        """丢弃所有已缓冲事件"""
        self.drain()
        self.events = []

    def send_raw(self, obj):
        return self.link.send(obj)

    def close(self):
        try:
            if self.link is not None:
                self.link.close()
            self.sock.close()
        except Exception:
            pass


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmp = tempfile.mkdtemp(prefix="kards_net_test_")
    db = os.path.join(tmp, "t.db")
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(root, "kards_server.py"),
         "--host", "127.0.0.1", "--port", str(port), "--db", db],
        stdout=open(SERVER_LOG, "wb"), stderr=subprocess.STDOUT,
        cwd=root)
    try:
        if not wait_port(port):
            print("服务器未能启动")
            sys.exit(1)
        run_tests(port)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
        # 测试用的账号目录（DATA_DIR/decks_*）清掉，避免污染真实用户目录
        try:
            import kards_engine
            for n in ("外包注册员", "alice", "bob", "carol"):
                d = account.deck_dir(n)
                if os.path.isdir(d) and os.path.basename(d).startswith("decks_"):
                    shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass

    print()
    if FAIL:
        print(f"FAILED: {len(FAIL)}/{PASS + len(FAIL)}")
        for f in FAIL:
            print("  -", f)
        sys.exit(1)
    print(f"ALL OK ({PASS} checks)")


def run_tests(port):
    a = Client(port)

    print("1. 握手与注册")
    # ⚠ 握手前发业务消息：服务器一定拒绝（不能靠"没应答"来判断，
    # 必须确认收到的是明确错误，否则会把"服务器卡死"误判成"通过"）
    early = c_auth_fail(port, {"m": "lobby"})
    check("握手前发 lobby 被明确拒绝",
          early is not None and early.get("m") == "auth_err", early)
    rep = a.auth("register", user="alice", pw="pw1234")
    check("注册返回 auth_ok", rep and rep.get("m") == "auth_ok", rep)
    check("auth_ok 带 token", bool(rep and rep.get("token")), rep)
    check("auth_ok 回显用户名", (rep or {}).get("user") == "alice", rep)
    token = (rep or {}).get("token")
    a.drain()

    print("2. 密码 / 重名校验")
    # 每次认证都用**独立连接**（历史习惯保留）：现在认证失败后服务器
    # 保留连接允许重试，但独立连接的写法对本测试更干净、互不干扰
    b = Client(port)
    rep = b.auth("register", user="alice", pw="other")
    check("重复注册被拒", rep and rep.get("m") == "auth_err", rep)
    b.close()

    b2 = Client(port)
    rep = b2.auth("login", user="alice", pw="wrongpw")
    check("错误密码被拒", rep and rep.get("m") == "auth_err", rep)
    b2.close()

    b3 = Client(port)
    rep = b3.auth("login", user="alice", pw="pw1234")
    check("正确密码登录成功", rep and rep.get("m") == "auth_ok", rep)
    b3.link.close()

    print("3. 非法用户名 / 密码")
    c = Client(port)
    rep = c.auth("register", user="x", pw="pw1234")
    check("用户名过短被拒", rep and rep.get("m") == "auth_err", rep)
    c.close()

    c2 = Client(port)
    rep = c2.auth("register", user="okname", pw="1")
    check("密码过短被拒", rep and rep.get("m") == "auth_err", rep)
    c2.close()

    print("4. 令牌 resume 免密重连")
    d = Client(port)
    rep = d.auth("resume", token=token)
    check("resume 成功", rep and rep.get("m") == "auth_ok", rep)
    d.drain()
    rep = c_auth_fail(port, {"m": "resume", "token": "bogus-token"})
    check("伪造令牌被拒", rep and rep.get("m") == "auth_err", rep)

    print("5. 大厅快照广播")
    e = Client(port)
    rep = e.auth("login", user="alice", pw="pw1234")
    check("alice 重新登录（挤掉旧连接）", rep and rep.get("m") == "auth_ok", rep)
    e.drain()
    a.drain()
    rep = e.req("lobby")
    check("请求大厅有应答", isinstance(rep, dict) and rep.get("m") == "lobby", rep)
    names = [u.get("name") for u in (rep or {}).get("players", [])]
    check("大厅含自己", "alice" in names, names)
    e.drain()

    print("6. 快速匹配（双人配对）")
    f = Client(port)
    rep = f.auth("register", user="bob", pw="pw1234")
    check("bob 注册成功", rep and rep.get("m") == "auth_ok", rep)
    f.drain()
    e.drain()
    e.send_raw({"m": "match"})
    time.sleep(0.25)
    f.send_raw({"m": "match"})
    me1 = e.wait("matched", timeout=6)
    me2 = f.wait("matched", timeout=6)
    check("先匹配者收到 matched", me1 is not None, me1)
    check("后匹配者收到 matched", me2 is not None, me2)
    check("双方房间号一致", (me1 or {}).get("room") == (me2 or {}).get("room"), (me1, me2))
    check("双方角色互补", {(me1 or {}).get("role"), (me2 or {}).get("role")} == {"host", "guest"},
          (me1, me2))
    check("对局双方对手名正确",
          (me1 or {}).get("opp") == "bob" and (me2 or {}).get("opp") == "alice",
          (me1, me2))
    time.sleep(0.3)
    e.drain()
    f.drain()

    print("7. 行动中转（act / seed / ready / concede / chat）")
    e.send_raw({"m": "seed", "seed": 12345})
    got = f.wait("seed", timeout=4)
    check("seed 被转发", got and got.get("seed") == 12345, got)
    check("seed 带 from_role", got and got.get("from_role") == "host", got)
    e.send_raw({"m": "act", "k": "play", "i": 3})
    got = f.wait("act", timeout=4)
    check("act 被转发", got and got.get("k") == "play" and got.get("i") == 3, got)
    # 关键回归：信封用 "m"，行动里的 "t" 是目标槽位，必须原样保留
    e.send_raw({"m": "act", "k": "attack", "s": 1, "t": 5})
    got = f.wait("act", timeout=4)
    check("act 的 t（目标槽位）未被信封覆盖", got and got.get("t") == 5, got)
    check("act 的 m 仍是 act", got and got.get("m") == "act", got)
    f.send_raw({"m": "chat", "text": "gg"})
    got = e.wait("chat", timeout=4)
    check("chat 双向转发", got and got.get("text") == "gg", got)
    e.send_raw({"m": "ready"})
    got = f.wait("ready", timeout=4)
    check("ready 被转发", got is not None, got)

    print("8. 断线通知")
    f.link.close()
    gone = e.wait("peer_left", timeout=6)
    check("对手断开 → peer_left", gone is not None, gone)

    print("9. 邀请码房间")
    e.drain()
    rep = e.req("create_room")
    check("建房返回 room_created", isinstance(rep, dict) and rep.get("m") == "room_created", rep)
    code = (rep or {}).get("code")
    check("邀请码非空", bool(code), rep)
    g = Client(port)
    rep = g.auth("login", user="bob", pw="pw1234")
    check("bob 登录（旧连接已断）", rep and rep.get("m") == "auth_ok", rep)
    g.drain()
    rep = g.req("join_room", code=code)
    check("凭邀请码入房 → matched", isinstance(rep, dict) and rep.get("m") == "matched", rep)
    check("入房角色为 guest", (rep or {}).get("role") == "guest", rep)
    rep2 = e.wait("peer_joined", "matched", timeout=5)
    check("房主收到有人加入", rep2 is not None, rep2)
    g.drain()
    e.drain()
    g.send_raw({"m": "act", "k": "end"})
    got = e.wait("act", timeout=4)
    check("房内行动转发方向正确（guest→host）",
          got and got.get("k") == "end" and got.get("from_role") == "guest", got)

    print("10. 错误邀请码")
    h = Client(port)
    h.auth("register", user="carol", pw="pw1234")
    h.drain()
    rep = h.req("join_room", code="ZZZZ99")
    check("错误邀请码被拒", isinstance(rep, dict) and rep.get("m") in ("join_err", "err"), rep)

    print("11. 战绩与卡组云同步")
    rep = h.req("stats")
    check("查询战绩有应答", isinstance(rep, dict), rep)
    rep = h.req("stats_add", result="win")
    check("上报战绩有应答", rep is not None, rep)
    rep = h.req("stats")
    st = (rep or {}).get("stats") or {}
    check("战绩已累加", st.get("win") == 1, rep)
    # ⚠ 字段名必须与 kards_server.dispatch 对齐：
    #   deck_save 用 title / content（不是 name / deck）
    #   deck_list / deck_get / deck_del 都按 (nation, title) 定位
    rep = h.req("deck_save", nation="德国", title="测试卡组",
                content="#国家:德国\n3 装甲掷弹兵")
    check("保存卡组有应答", rep is not None, rep)
    rep = h.req("deck_list")
    titles = [d.get("title") for d in (rep or {}).get("decks", [])]
    check("卡组列表含刚保存的", "测试卡组" in titles, rep)
    rep = h.req("deck_get", nation="德国", title="测试卡组")
    check("取回卡组内容一致",
          isinstance(rep, dict) and rep.get("m") == "deck_data"
          and "装甲掷弹兵" in (rep.get("content") or ""), rep)
    rep = h.req("deck_del", nation="德国", title="测试卡组")
    titles = [d.get("title") for d in (rep or {}).get("decks", [])]
    check("删除卡组生效", "测试卡组" not in titles, rep)

    print("12. 客户端账号模块走服务器后端")
    # ⚠ 这里必须用一个**未握手**的裸链接：account 自己会发握手消息，
    # 而 ServerLink 只在握手成功后才可用。
    k = Client(port)
    check("k 尚未握手（link 为 None）", k.link is None)
    account.set_remote(_RawLink(k), f"127.0.0.1:{port}")
    check("backend 切换为 server", account.backend() == "server")
    ok, err = account.register("外包注册员", "pw12345")
    check("account.register 走服务器成功", ok, err)
    # 回归：_rpc 曾经不传 key → ServerLink 用 id 配对 → 服务器不回显 id
    # → 永远超时返回 None → register 看起来成功但 current() 是 None
    check("服务器认这个名字（回归：会话已缓存）",
          account.current() == "外包注册员", account.current())
    check("会话文件已落盘",
          (account._load_session() or {}).get("name") == "外包注册员",
          account._load_session())
    st = account.get_stats("外包注册员")
    check("stats 走服务器可读（回归：_rpc 带 key）",
          isinstance(st, dict) and st.get("win") == 0, st)
    account.stats_add("外包注册员", "win")
    st = account.get_stats("外包注册员")
    check("stats_add 生效到服务器", st.get("win") == 1, st)
    # 回归：解绑不应清掉会话缓存（否则重连要重新输密码）
    account.set_remote(None)
    check("解绑后回落到 local", account.backend() == "local")
    check("解绑不清会话缓存（回归）",
          (account._load_session() or {}).get("name") == "外包注册员",
          account._load_session())
    account._drop_session()
    k.close()

    print("13. 取消匹配")
    h.send_raw({"m": "match"})
    time.sleep(0.2)
    h.send_raw({"m": "cancel_match"})
    got = h.wait("match_cancelled", timeout=5)
    check("取消匹配有应答", got is not None, got)

    for cli in (a, b, d, e, g, h):
        cli.close()


def c_auth_fail(port, msg):
    """开一个临时连接发一条握手消息，返回应答"""
    cli = Client(port)
    m = msg.get("m")
    if m in ("login", "register"):
        rep = cli.auth(m, user=msg.get("user"), pw=msg.get("pw"))
    elif m == "resume":
        rep = cli.auth("resume", token=msg.get("token"))
    else:
        # 非握手消息（协议级垃圾）：服务器回 auth_err 并断开
        cli.sock.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        rep = cli._read_until(("auth_err", "err"), timeout=5)
    cli.close()
    return rep


class _RawLink:
    """给 kards_account 用的适配器：包一层「还没握手」的裸 socket。

    kards_account.set_remote 要求对象提供 alive / send / request，
    而它的 request 会**自己发握手消息**（login/register/resume）。
    所以这里不能在 ServerLink 上做（那就已经握过手了），
    必须在裸 socket 上实现一次最小版的「发一条 + 等一类应答」。
    """

    def __init__(self, cli):
        self.cli = cli
        self.alive = True
        self._buf = b""

    def send(self, obj):
        try:
            self.cli.sock.sendall(
                (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            return True
        except OSError:
            self.alive = False
            return False

    def request(self, obj, timeout=6.0, key=None):
        if not self.send(obj):
            return None
        types = {
            "login": ("auth_ok", "auth_err"),
            "register": ("auth_ok", "auth_err"),
            "resume": ("auth_ok", "auth_err"),
            "stats": ("stats", "err"),
            "stats_add": ("stats", "err"),
        }.get(obj.get("m"), (obj.get("m"), "err"))
        rep = self.cli._read_until(types, timeout=timeout)
        if rep and rep.get("m") == "auth_ok":
            self.cli.user = rep.get("user")
            self.cli.token = rep.get("token")
        return rep

    def close(self):
        self.alive = False


if __name__ == "__main__":
    main()
