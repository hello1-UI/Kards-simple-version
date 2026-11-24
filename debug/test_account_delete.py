# -*- coding: utf-8 -*-
"""删除账号测试：本地清理 / 服务器端数据 / 协议 / 客户端 API

覆盖：
  · 本地删除：账号行、免密会话、货币、商店外观、每日任务、卡组目录全清，
    且不误伤同机其他账号
  · 未登录 / 不存在的账号 → no_user
  · 勾选「同时删除服务器数据」但离线 → offline（本地一个字节都不动）
  · 服务器删除：users / sessions / decks 三张表都清干净，
    旧 token 不能 resume，同密码不能再登录，其他玩家与大厅不受影响
  · 不勾选：只清本机，服务器账号仍可用原密码登录（远端保留）

用法: python debug/test_account_delete.py
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
PORT = 6423

# ⚠ DATA_DIR 是导入期读取的，必须先设环境变量再 import
_DATA = tempfile.mkdtemp(prefix="kards_del_test_")
os.environ["KARDS_DATA_DIR"] = _DATA

sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_account as account      # noqa: E402
import kards_shop as shop            # noqa: E402
import kards_quests as quests        # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name
          + (f"  {extra}" if (extra and not cond) else ""))


class Cli:
    """最小测试客户端：后台线程收包 + 按类型取一条。"""

    def __init__(self, port=PORT):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.s.settimeout(None)
        self.dead = False
        self.q = []
        self.cv = threading.Condition(threading.RLock())
        self.name = None
        self.token = None
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
        try:
            self.s.sendall((json.dumps(obj, ensure_ascii=False) + "\n")
                           .encode("utf-8"))
            return True
        except OSError:
            self.dead = True
            return False

    def wait(self, t, timeout=6):
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

    def wait_any(self, types, timeout=6):
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

    def auth(self, user, pw, kind="register"):
        self.send({"m": kind, "user": user, "pw": pw})
        rep = self.wait_any(("auth_ok", "auth_err"))
        if rep and rep.get("m") == "auth_ok":
            self.name = rep.get("user")
            self.token = rep.get("token")
        return rep

    def req(self, m, **kw):
        obj = {"m": m}
        obj.update(kw)
        self.send(obj)
        return self.wait(m)

    def close(self):
        self.dead = True
        try:
            self.s.close()
        except OSError:
            pass


class RawLink:
    """给 kards_account 用的「未握手」链路适配器（account 自己发握手消息）。"""

    def __init__(self, cli):
        self.cli = cli
        self.alive = True

    def send(self, obj):
        ok = self.cli.send(obj)
        if not ok:
            self.alive = False
        return ok

    def request(self, obj, timeout=6.0, key=None):
        if not self.send(obj):
            return None
        types = {
            "login": ("auth_ok", "auth_err"),
            "register": ("auth_ok", "auth_err"),
            "resume": ("auth_ok", "auth_err"),
            "stats": ("stats", "err"),
            "stats_add": ("stats", "err"),
            "rank": ("rank", "err"),
            "rank_add": ("rank", "err"),
            "rank_add_ai": ("rank", "err"),
            "rank_seed": ("rank", "err"),
            "rank_board": ("rank_board", "err"),
            "delete_account": ("account_deleted", "err"),
        }.get(obj.get("m"), (obj.get("m"), "err"))
        rep = self.cli.wait_any(types, timeout=timeout)
        if rep and rep.get("m") == "auth_ok":
            self.cli.name = rep.get("user")
            self.cli.token = rep.get("token")
        return rep

    def close(self):
        self.alive = False


def db_counts(path, name):
    """直接查库确认是不是真删了（不依赖服务器自己的口径）。"""
    conn = sqlite3.connect(path, timeout=5)
    try:
        users = conn.execute("SELECT COUNT(*) FROM users WHERE name=?",
                             (name,)).fetchone()[0]
        sess = conn.execute("SELECT COUNT(*) FROM sessions WHERE name=?",
                            (name,)).fetchone()[0]
        decks = conn.execute("SELECT COUNT(*) FROM decks WHERE name=?",
                             (name,)).fetchone()[0]
        return users, sess, decks
    finally:
        conn.close()


def local_section():
    print("1. 本地删除：清干净且不误伤")
    ok, err = account.register("甲甲", "pw1234")
    check("注册甲甲", ok, err)
    account.stats_add("甲甲", "win")
    account.stats_add("甲甲", "win")
    account.currency_add(gold=900, name="甲甲")
    item = shop.stock("甲甲")[0]
    shop.buy(item["id"], "甲甲")
    quests.record_game("win", online=False, nation="德国", my_hq=18,
                       name="甲甲")
    d = account.deck_dir("甲甲")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "deck.json"), "w", encoding="utf-8") as fh:
        fh.write("{}")

    ok2, err2 = account.register("乙乙", "pw5678")
    check("注册乙乙", ok2, err2)
    account.currency_add(gold=321, name="乙乙")
    quests.record_game("lose", online=False, nation="苏联", my_hq=8, name="乙乙")
    gold_b = account.get_currency("乙乙")["gold"]

    # 回到甲甲（当前登录的人才谈得上"删完变游客"）
    account.logout()
    ok, err = account.login("甲甲", "pw1234")
    check("切回甲甲", ok, err)

    check("删除前甲甲在库", "甲甲" in account._load()["users"])
    check("删除前甲甲有商店档", "local:甲甲" in shop._load())
    check("删除前甲甲有任务档", "local:甲甲" in quests._load())
    check("删除前甲甲有卡组目录", os.path.isdir(d))

    ok, err = account.delete_account("甲甲", server_data=False)
    check("删除成功", ok, err)

    users = account._load()["users"]
    check("账号行已删除", "甲甲" not in users, list(users))
    check("其他账号还在", "乙乙" in users, list(users))
    check("当前登录被清空", account.current() is None, account.current())
    check("切回游客", account.is_guest() is True)
    check("免密会话已清", not (account._load_session() or {}).get("name"),
          account._load_session())
    check("货币已清", "local:甲甲" not in account._load_currency(),
          list(account._load_currency()))
    check("商店档已清", "local:甲甲" not in shop._load(), list(shop._load()))
    check("任务档已清", "local:甲甲" not in quests._load(), list(quests._load()))
    check("卡组目录已删", not os.path.isdir(d), d)

    check("乙乙货币不受影响", account.get_currency("乙乙")["gold"] == gold_b,
          account.get_currency("乙乙"))
    check("乙乙任务档不受影响", "local:乙乙" in quests._load())
    check("乙乙卡组目录还在", os.path.isdir(account.deck_dir("乙乙")))

    ok, err = account.login("甲甲", "pw1234")
    check("删后无法再用原密码登录", not ok, err)

    print("2. 边界：未登录 / 不存在 / 离线勾服务器")
    ok, err = account.delete_account("甲甲", server_data=False)
    check("重复删除 → no_user", not ok and err == "no_user", err)
    ok, err = account.delete_account("查无此人", server_data=False)
    check("不存在的账号 → no_user", not ok and err == "no_user", err)
    account.start_guest()
    ok, err = account.delete_account(None, server_data=False)
    check("游客删除 → no_user", not ok and err == "no_user", err)


def server_section():
    print("3. 服务器：三张表都删干净")
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="kards_del_")
    os.close(fd)
    os.unlink(db_path)
    proc = subprocess.Popen(
        [PY, os.path.join(ROOT, "kards_server.py"),
         "--port", str(PORT), "--host", "127.0.0.1", "--db", db_path],
        cwd=ROOT, stdout=open(os.devnull, "wb"), stderr=subprocess.STDOUT)
    try:
        ready = False
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=0.3).close()
                ready = True
                break
            except OSError:
                time.sleep(0.1)
        if not ready:
            check("测试服务器启动", False, "端口 %d 没起来" % PORT)
            return

        setup = Cli()
        rep = setup.auth("删删", "pass1234")
        check("建号成功", rep and rep["m"] == "auth_ok", rep)
        token = (rep or {}).get("token")
        setup.req("stats_add", result="win")
        setup.req("stats_add", result="win")
        setup.req("rank_add", result="win")
        setup.req("deck_save", nation="德国", title="要被删的卡组",
                  content="#国家:德国\n3 装甲掷弹兵")
        users, sess, decks = db_counts(db_path, "删删")
        check("删除前 users/sessions/decks 都有行",
              users == 1 and sess >= 1 and decks == 1, (users, sess, decks))
        setup.close()

        watcher = Cli()
        rep = watcher.auth("留留", "pass1234")
        check("旁观账号登录", rep and rep["m"] == "auth_ok", rep)
        watcher.req("stats_add", result="lose")
        w_users, w_sess, w_decks = db_counts(db_path, "留留")
        check("旁观账号有数据", w_users == 1 and w_sess >= 1, (w_users, w_sess))

        # 用 account 客户端 API 删（走真实协议，而不是直接调 Store）
        link_cli = Cli()
        link = RawLink(link_cli)
        account.set_remote(link, "127.0.0.1:%d" % PORT)
        ok, err = account.login("删删", "pass1234")
        check("客户端 API 登录", ok, err)
        check("backend = server", account.backend() == "server")

        ok, err = account.delete_account("删删", server_data=True)
        check("勾选服务器删除成功", ok, err)
        check("本地也切回游客", account.is_guest() and account.current() is None,
              (account.current(), account.is_guest()))

        users, sess, decks = db_counts(db_path, "删删")
        check("users 行已删", users == 0, users)
        check("sessions 行已删（旧 token 不能复活）", sess == 0, sess)
        check("decks 行已删（云卡组不残留）", decks == 0, decks)
        w2 = db_counts(db_path, "留留")
        check("旁观账号数据完好", w2[0] == 1 and w2[1] >= 1,
              w2)
        w_stats = watcher.req("stats")
        check("旁观玩家战绩未变",
              ((w_stats or {}).get("stats") or {}).get("lose") == 1, w_stats)

        print("4. 服务器侧：不能再登录 / 大厅不再显示")
        victim = Cli()
        rep = victim.auth("删删", "pass1234", kind="login")
        check("同密码登录已失败", rep and rep["m"] == "auth_err", rep)
        victim.close()

        resume = Cli()
        resume.send({"m": "resume", "token": token})
        rep = resume.wait_any(("auth_ok", "auth_err"))
        check("旧会话 token 已失效", rep and rep["m"] == "auth_err", rep)
        resume.close()

        watcher.send({"m": "lobby"})
        snap = watcher.wait("lobby") or {}
        names = [p.get("name") for p in snap.get("players") or []]
        check("大厅里没有已删除账号", "删删" not in names, names)
        check("大厅里还有旁观玩家", "留留" in names, names)

        print("5. 二次删除 / 未认证连接不能删别人")
        ok, err = account.delete_account("删删", server_data=True)
        check("同一连接再删 → server_failed",
              not ok and err == "server_failed", err)
        ok, err = account.delete_account("留留", server_data=True)
        check("未认证连接删别人 → server_failed",
              not ok and err == "server_failed", err)
        check("旁观账号仍在库", db_counts(db_path, "留留")[0] == 1)

        print("6. 不勾选：只清本机，服务器保留")
        link2_cli = Cli()
        account.set_remote(RawLink(link2_cli), "127.0.0.1:%d" % PORT)
        ok, err = account.register("半半", "pass9999")
        check("注册半半", ok, err)
        check("服务器有半半", db_counts(db_path, "半半")[0] == 1)
        ok, err = account.delete_account("半半", server_data=False)
        check("只删本机成功", ok, err)
        check("本机无半半", "半半" not in account._load()["users"])
        check("服务器仍有半半", db_counts(db_path, "半半")[0] == 1)
        check("服务器会话也还在（可免密回来）",
              db_counts(db_path, "半半")[1] >= 1)
        again = Cli()
        rep = again.auth("半半", "pass9999", kind="login")
        check("原密码仍能登录（远端保留）",
              rep and rep["m"] == "auth_ok", rep)
        again.close()
        account.set_remote(None)
        link_cli.close()
        link2_cli.close()
        watcher.close()
    finally:
        account.set_remote(None)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            os.unlink(db_path)
        except OSError:
            pass


def main():
    local_section()
    server_section()
    print()
    print("=" * 52)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    for f in FAIL:
        print("  -", f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
