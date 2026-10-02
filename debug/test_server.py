# -*- coding: utf-8 -*-
"""kards_server.py 端到端测试

启动临时服务器（随机端口 + 临时数据库），用两个真实 socket 客户端跑完整流程：
  注册/登录 → 账号互斥 → 错误密码 → 匹配 → 中转行动 → 断线通知 → 邀请码房间
  → 战绩 → 卡组云同步 → 快速匹配

用法: python debug/test_server.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
PORT = 6399

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


class Cli:
    """测试客户端：后台线程把收到的每条消息按序压进单一队列，保证不丢包。"""

    def __init__(self, port=PORT):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.s.settimeout(None)
        self.dead = False
        self.q = []                  # 所有到达的消息，按到达顺序
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        buf = b""
        while not self.dead:
            try:
                d = self.s.recv(4096)
            except OSError:
                break
            if not d:
                break
            buf += d
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    m = json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                with self.cv:
                    self.q.append(m)
                    self.cv.notify_all()
        with self.cv:
            self.dead = True
            self.cv.notify_all()

    def send(self, obj):
        if self.dead:
            return False
        try:
            self.s.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            return True
        except OSError:
            self.dead = True
            return False

    def wait(self, t, timeout=5):
        """等指定类型消息；其它消息保留在队列中"""
        end = time.time() + timeout
        with self.cv:
            while True:
                for i, m in enumerate(self.q):
                    if m.get("m") == t:
                        return self.q.pop(i)
                remain = end - time.time()
                if remain <= 0:
                    return None
                self.cv.wait(remain)

    def has(self, t):
        with self.lock:
            return any(m.get("m") == t for m in self.q)

    def drain(self, t):
        """取走队列中指定类型的全部消息"""
        with self.lock:
            self.q = [m for m in self.q if m.get("m") != t]

    def wait_any(self, types, timeout=5):
        """等任意一种类型的消息（用于 auth_ok / auth_err 二选一）"""
        end = time.time() + timeout
        with self.cv:
            while True:
                for i, m in enumerate(self.q):
                    if m.get("m") in types:
                        return self.q.pop(i)
                remain = end - time.time()
                if remain <= 0:
                    return None
                self.cv.wait(remain)

    def login(self, user, pw, kind="login"):
        self.send({"m": kind, "user": user, "pw": pw})
        return self.wait_any(("auth_ok", "auth_err"), 6)

    def dump(self):
        with self.lock:
            return [m.get("m") for m in self.q]

    def close(self):
        self.dead = True
        try:
            self.s.close()
        except OSError:
            pass
        with self.cv:
            self.cv.notify_all()


def main():
    db_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="kards_test_")
    os.close(db_fd)
    os.unlink(db_path)          # 让服务器自己创建，避免残留空库

    proc = subprocess.Popen(
        [PY, os.path.join(ROOT, "kards_server.py"),
         "--port", str(PORT), "--host", "127.0.0.1", "--db", db_path],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        # 等服务器就绪
        ok = False
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=0.3).close()
                ok = True
                break
            except OSError:
                time.sleep(0.1)
        if not ok:
            print("服务器启动失败：")
            proc.terminate()
            print(proc.stdout.read().decode("utf-8", "ignore"))
            return 1

        print("\n=========== 1. 注册 / 登录 ===========")
        a = Cli()
        r = a.login("测试员甲", "pass1234", kind="register")
        check("注册成功", r and r.get("m") == "auth_ok", str(r))
        check("返回 token", bool(r and r.get("token")))
        check("初始战绩 0/0/0",
              r and r.get("stats") == {"win": 0, "lose": 0, "draw": 0},
              str(r and r.get("stats")))
        tok_a = r["token"]

        b = Cli()
        r = b.login("测试员乙", "abcd1234", kind="register")
        check("第二个账号注册成功", r and r.get("m") == "auth_ok")

        c = Cli()
        r = c.login("测试员甲", "pass1234", kind="register")
        check("重名注册被拒", r and r.get("m") == "auth_err",
              str(r and r.get("err")))
        c.close()

        c = Cli()
        r = c.login("测试员甲", "wrongpw")
        check("错误密码被拒", r and r.get("m") == "auth_err",
              str(r and r.get("err")))
        c.close()

        c = Cli()
        r = c.login("a", "pass1234", kind="register")
        check("用户名过短被拒（单字符）", r and r.get("m") == "auth_err", str(r))
        c.close()

        c = Cli()
        r = c.login("x" * 20, "pass1234", kind="register")
        check("用户名过长被拒（20 位）", r and r.get("m") == "auth_err", str(r))
        c.close()

        c = Cli()
        r = c.login("测试员丙", "123", kind="register")
        check("密码过短被拒", r and r.get("m") == "auth_err")
        c.close()

        print("\n=========== 2. 会话续期 / 账号互斥 ===========")
        c = Cli()
        c.send({"m": "resume", "token": tok_a})
        r = c.wait("auth_ok", 5)
        check("resume 续期成功", r and r.get("m") == "auth_ok", str(r))
        check("resume 认出原账号", r and r.get("user") == "测试员甲")
        c.close()

        c = Cli()
        c.send({"m": "resume", "token": "bogus-token"})
        r = c.wait("auth_err", 5)
        check("伪造 token 被拒", r and r.get("m") == "auth_err")
        c.close()

        # 甲重复登录 → 旧连接被踢
        a2 = Cli()
        r = a2.login("测试员甲", "pass1234")
        check("重复登录成功", r and r.get("m") == "auth_ok")
        kicked = a.wait("kick", 5)
        check("旧连接收到踢出通知", kicked is not None, str(kicked))

        print("\n=========== 3. 在线大厅 ===========")
        a2.send({"m": "lobby"})
        r = a2.wait("lobby")
        names = {p["name"] for p in (r or {}).get("players", [])}
        check("大厅含甲和乙", {"测试员甲", "测试员乙"} <= names, str(names))
        check("大厅带战绩字段",
              all("stats" in p and "in_game" in p for p in (r or {}).get("players", [])))

        print("\n=========== 4. 快速匹配 ===========")
        a2.send({"m": "match"})
        r = a2.wait("matching", 3)
        check("先到者进入等待队列", r is not None, str(r))

        b.send({"m": "match"})
        ra = a2.wait("matched", 5)
        rb = b.wait("matched", 5)
        check("房主收到 matched", ra is not None, str(ra))
        check("客人收到 matched", rb is not None, str(rb))
        check("角色互斥 host/guest",
              {ra and ra.get("role"), rb and rb.get("role")} == {"host", "guest"},
              f"{ra and ra.get('role')}/{rb and rb.get('role')}")
        check("房间号一致", ra and rb and ra.get("room") == rb.get("room"))
        check("对手名正确",
              ra and ra.get("opp") == "测试员乙" and rb and rb.get("opp") == "测试员甲",
              f"{ra and ra.get('opp')}/{rb and rb.get('opp')}")

        # 开局后服务器应广播「大厅里这两人已在游戏中」
        # 先清掉开局前的旧快照，再拿最新的一份
        a2.drain("lobby")
        b.drain("lobby")
        a2.send({"m": "lobby"})
        r = a2.wait("lobby", 4)
        snap = {p["name"]: p["in_game"] for p in (r or {}).get("players", [])}
        check("开局后大厅标记双方为对局中",
              snap.get("测试员甲") is True and snap.get("测试员乙") is True, str(snap))

        print("\n=========== 5. 对局中转 ===========")
        a2.drain("lobby")
        b.drain("lobby")
        a2.send({"m": "seed", "seed": 12345})
        m = b.wait("seed", 3)
        check("种子转发到对手", m and m.get("seed") == 12345, str(m))
        check("转发带 from_role", m and m.get("from_role") == "host", str(m))

        b.send({"m": "act", "k": "play", "i": 2})
        m = a2.wait("act", 3)
        check("行动指令转发（出牌）",
              m and m.get("k") == "play" and m.get("i") == 2, str(m))
        check("行动来自 guest", m and m.get("from_role") == "guest")

        a2.send({"m": "act", "k": "attack", "s": 1, "t": 0})
        m = b.wait("act", 3)
        check("行动指令转发（攻击）",
              m and m.get("k") == "attack" and m.get("s") == 1 and m.get("t") == 0,
              f"{m}")
        check("攻击来自 host", m and m.get("from_role") == "host", str(m))
        check("目标槽位 t 未被信封覆盖（协议关键点）",
              m and m.get("m") == "act" and m.get("t") == 0, str(m))

        a2.send({"m": "act", "k": "end"})
        m = b.wait("act", 3)
        check("行动指令转发（结束回合）", m and m.get("k") == "end", str(m))

        print("\n=========== 5b. 对局中大厅状态 ===========")
        b.send({"m": "lobby"})
        r = b.wait("lobby", 3)
        snap = {p["name"]: p["in_game"] for p in (r or {}).get("players", [])}
        check("对局中两人仍显示在线且 in_game=True",
              snap.get("测试员甲") is True and snap.get("测试员乙") is True, str(snap))

        print("\n=========== 6. 战绩 ===========")
        a2.send({"m": "stats_add", "result": "win"})
        r = a2.wait("stats", 3)
        check("胜场 +1", r and r.get("stats", {}).get("win") == 1, str(r and r.get("stats")))
        b.send({"m": "stats_add", "result": "lose"})
        r = b.wait("stats", 3)
        check("负场 +1", r and r.get("stats", {}).get("lose") == 1)
        b.send({"m": "stats_add", "result": "draw"})
        r = b.wait("stats", 3)
        check("平场 +1", r and r.get("stats", {}).get("draw") == 1)

        print("\n=========== 7. 断线通知 ===========")
        b.close()
        m = a2.wait("peer_left", 6)
        check("对手断线通知房主", m is not None, str(m))
        a2.send({"m": "lobby"})
        r = a2.wait("lobby", 3)
        me = next((p for p in (r or {}).get("players", [])
                   if p["name"] == "测试员甲"), None)
        check("断线后房主回到大厅", me is not None and not me["in_game"], str(me))

        print("\n=========== 8. 邀请码房间 ===========")
        d = Cli()
        d.login("测试员乙", "abcd1234")
        e = Cli()
        e.login("测试员丁", "efgh1234", kind="register")

        d.send({"m": "create_room"})
        r = d.wait("room_created", 3)
        code = (r or {}).get("code")
        check("创建房间拿到邀请码", bool(code), str(r))

        e.send({"m": "join_room", "code": code.lower()})   # 小写也应识别
        rd = d.wait("matched", 4)
        re_ = e.wait("matched", 4)
        check("房主收到 matched", rd is not None, str(rd))
        check("挑战者收到 matched", re_ is not None, str(re_))
        check("房间角色正确",
              rd and rd.get("role") == "host" and re_ and re_.get("role") == "guest")
        check("邀请码被消费",
              rd and re_ and rd.get("room") == re_.get("room"))

        f = Cli()
        f.login("测试员戊", "ijkl1234", kind="register")
        f.send({"m": "join_room", "code": code})
        r = f.wait("join_err", 3)
        check("过期邀请码被拒", r is not None, str(r))
        f.close()

        print("\n=========== 9. 卡组云同步 ===========")
        d.send({"m": "deck_save", "nation": "德国", "title": "闪电战",
                "content": "#国家:德国\n3 装甲掷弹兵"})
        r = d.wait("deck_saved", 3)
        check("卡组保存成功", r is not None, str(r))
        d.send({"m": "deck_save", "nation": "德国", "title": "第二套",
                "content": "#国家:德国\n2 虎式坦克"})
        d.wait("deck_saved", 3)
        d.send({"m": "deck_list"})
        r = d.wait("deck_list", 3)
        titles = {x["title"] for x in (r or {}).get("decks", [])}
        check("卡组列表含两套", {"闪电战", "第二套"} <= titles, str(titles))
        check("列表带国家与时间戳",
              all("nation" in x and "updated" in x for x in (r or {}).get("decks", [])))

        d.send({"m": "deck_get", "nation": "德国", "title": "闪电战"})
        r = d.wait("deck_data", 3)
        check("按名读取卡组内容",
              r and "装甲掷弹兵" in (r.get("content") or ""), str(r))

        # 用全新账号验证隔离。注意不能用"测试员丁"——那会顶掉 e 的连接
        # （服务端会踢同名旧连接），后面第 10 节的异常容错就全废了；
        # 也不能用"测试员乙"——d 还在用它，同样会被踢。
        g = Cli()
        g.login("测试员己", "mnop1234", kind="register")
        g.send({"m": "deck_list"})
        r = g.wait("deck_list", 3)
        check("卡组按账号隔离（己看不到乙的）",
              (r or {}).get("decks") == [], str((r or {}).get("decks")))
        g.close()

        d.send({"m": "deck_del", "nation": "德国", "title": "第二套"})
        r = d.wait("deck_list", 3)
        titles = {x["title"] for x in (r or {}).get("decks", [])}
        check("删除卡组生效", "第二套" not in titles and "闪电战" in titles, str(titles))

        print("\n=========== 10. 异常输入容错 ===========")
        # 必须用一个"干净"的连接：丁（e）在第 8 节已经进了房间，
        # 此时发 act 会被正常转发而不是报错，断言就会误判。
        h = Cli()
        h.login("测试员庚", "qrst1234", kind="register")
        h.send({"m": "act", "k": "end"})        # 庚不在对局中
        r = h.wait("err", 3)
        check("非对局状态发行动被拒", r is not None, str(r))
        h.send({"m": "no_such_type"})
        r = h.wait("err", 3)
        check("未知消息类型被拒", r is not None)
        h.send({"m": "ping"})
        r = h.wait("pong", 3)
        check("心跳 ping/pong 正常", r is not None)

        # 未登录直接发业务消息 → 服务器应在握手阶段拒绝
        z = Cli()
        z.send({"m": "match"})
        r = z.wait("auth_err", 4)
        check("未握手直接发业务消息被拒",
              r is None or r.get("m") == "auth_err", str(r))
        z.close()

        # 服务器仍在运行（没有因异常崩溃）
        c = Cli()
        r = c.login("测试员甲", "pass1234")
        check("异常输入后服务器仍可用", r and r.get("m") == "auth_ok", str(r))
        c.close()

        for x in (a2, d, e):
            try:
                x.close()
            except Exception:
                pass

    finally:
        proc.terminate()
        try:
            out = proc.stdout.read().decode("utf-8", "ignore")
        except Exception:
            out = ""
        time.sleep(0.3)
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + suffix)
            except OSError:
                pass

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - " + f)
        if out:
            print("\n--- 服务器输出 ---")
            print(out[-3000:])
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
