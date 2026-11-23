# -*- coding: utf-8 -*-
"""段位系统端到端测试：服务器协议 + 客户端 API + 本地回退

覆盖：
  · 本地后端（离线）段位读写与落盘
  · 服务器 rank / rank_add / rank_seed / rank_board 协议
  · 赛季懒结算（客户端带旧赛季 seed 上云时按服务端时间扣星）
  · 排行榜只收 1 段玩家、按分数排序
  · kards_account.get_rank / rank_add / leaderboard 走真实连接

用法: python debug/test_rank_net.py
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
PORT = 6411

# ⚠ 必须在 import kards_engine/account 之前设好，DATA_DIR 是导入期读取的
_DATA = tempfile.mkdtemp(prefix="kards_rank_test_")
os.environ["KARDS_DATA_DIR"] = _DATA

sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_account as account      # noqa: E402
import kards_net as net              # noqa: E402
import kards_rank as rank            # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


class Cli:
    """测试客户端（与 test_server.py 同款：后台线程 + 条件变量收包）"""

    def __init__(self, port=PORT):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.s.settimeout(None)
        self.dead = False
        self.q = []
        self.lock = __import__("threading").RLock()
        self.cv = __import__("threading").Condition(self.lock)
        __import__("threading").Thread(target=self._reader, daemon=True).start()

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
        return self.wait_any(("auth_ok", "auth_err"))

    def close(self):
        self.dead = True
        try:
            self.s.close()
        except OSError:
            pass


def prev_month():
    y, m = (int(x) for x in rank.season_id().split("-"))
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def wait_connect(addr, timeout=6):
    box = {}
    net.connect_server_async(addr, box, timeout=timeout)
    end = time.time() + timeout + 2
    while time.time() < end and "result" not in box:
        time.sleep(0.05)
    return box.get("result")


def main():
    print("=========== 1. 本地后端（离线）===========")
    ok, err = account.register("LocalR", "pass1234")
    check("本地注册", ok, err)
    st = account.get_rank("LocalR")
    check("初始 25 段 0 星", st and st["tier"] == 25 and st["stars"] == 0, st)
    r1 = account.rank_add("LocalR", "win")
    check("离线也能记段位", r1 and r1["rank"]["stars"] == 1, r1)
    account.rank_add("LocalR", "win")
    r3 = account.rank_add("LocalR", "win")
    check("三连胜第 3 场 +2", r3["change"]["stars"] == 2, r3["change"])
    check("离线状态落盘", account.get_rank("LocalR")["stars"] == 4,
          account.get_rank("LocalR")["stars"])
    board = account.leaderboard()
    check("离线榜单不炸", isinstance(board, dict) and board["online"] is False, board)
    check("未到 1 段不上榜", board["rows"] == [], board["rows"])

    db_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="kards_rank_")
    os.close(db_fd)
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
            print("服务器启动失败")
            return 1

        print("\n=========== 2. 服务器：注册即带段位 ===========")
        a = Cli()
        r = a.auth("甲甲", "pass1234")
        check("注册成功", r and r["m"] == "auth_ok", r)
        check("auth_ok 带段位", isinstance((r or {}).get("rank"), dict), r)
        check("初始 25 段", (r or {}).get("rank", {}).get("tier") == 25)
        a.send({"m": "rank"})
        q = a.wait("rank")
        check("rank 查询", q and q["rank"]["tier"] == 25, q)

        print("\n=========== 3. 连胜与升降 ===========")
        for i in range(3):
            a.send({"m": "rank_add", "result": "win"})
            q = a.wait("rank")
        check("三连胜后 4 星", q and q["rank"]["stars"] == 4, q and q["rank"])
        check("第 3 场 +2 星", q and q["change"]["stars"] == 2, q and q["change"])
        check("连胜 = 3", q and q["rank"]["streak"] == 3)
        # 25 段属于 21~25：负场不扣星。先赢到 24 段，再验扣星。
        a.send({"m": "rank_add", "result": "win"})
        q = a.wait("rank")
        check("满 5 星升到 24 段", q and q["rank"]["tier"] == 24
              and q["rank"]["stars"] == 1, q and q["rank"])
        # ⚠ 24 段仍属 21~25 新手保护：负场不扣星。扣星要 20 段以下，
        # 这里用 seed 造一个 20 段的账号单独验。
        a.send({"m": "rank_add", "result": "lose"})
        q = a.wait("rank")
        check("24 段负场不扣星（新手保护）", q and q["change"]["stars"] == 0,
              q and q["change"])
        check("负场断连胜", q and q["rank"]["streak"] == 0)
        a.send({"m": "rank_add", "result": "draw"})
        q = a.wait("rank")
        check("平局不改段位", q and q["change"]["stars"] == 0, q and q["change"])

        print("\n=========== 4. seed（账号迁移）与反灌水 ===========")
        e = Cli()
        e.auth("戊戊", "pass1234")
        e.send({"m": "rank_seed", "rank": {"tier": 20, "stars": 2, "best": 20,
                                          "season": rank.season_id()}})
        e.wait("rank")
        e.send({"m": "rank_add", "result": "lose"})
        q = e.wait("rank")
        check("20 段负场 -1 星", q and q["change"]["stars"] == -1
              and q["rank"]["stars"] == 1, q and q["change"])
        e.send({"m": "rank_add", "result": "lose"})
        q = e.wait("rank")
        check("1 星再负 → 0 星", q and q["rank"]["stars"] == 0, q and q["rank"])
        b = Cli()
        b.auth("乙乙", "pass1234")
        b.send({"m": "rank_seed", "rank": {
            "tier": 2, "stars": 4, "best": 2, "streak": 5, "season": rank.season_id(),
            "lb_pts": 0, "lb_win": 0, "lb_lose": 0, "lb_active": False}})
        q = b.wait("rank")
        check("seed 本机段位", q and q["rank"]["tier"] == 2 and q["rank"]["stars"] == 4,
              q and q["rank"])
        b.send({"m": "rank_add", "result": "win"})
        q = b.wait("rank")
        check("升上 1 段", q and q["rank"]["tier"] == 1, q and q["rank"])
        check("升段那场不入榜计分", q and q["change"]["entered"]
              and q["rank"]["lb_pts"] == 0, q and q["change"])
        b.send({"m": "rank_add", "result": "win"})
        q = b.wait("rank")
        check("上榜后胜 +3", q and q["rank"]["lb_pts"] == 3, q and q["rank"])
        b.send({"m": "rank_add", "result": "lose"})
        q = b.wait("rank")
        check("上榜后负 -2", q and q["rank"]["lb_pts"] == 1, q and q["rank"])
        b.send({"m": "rank_seed", "rank": {"tier": 1, "stars": 5, "season": rank.season_id(),
                                          "lb_pts": 999}})
        q = b.wait("rank")
        check("已有段位时 seed 被忽略", q and q["rank"]["lb_pts"] == 1,
              q and q["rank"])

        print("\n=========== 5. 排行榜 ===========")
        b.send({"m": "rank_board", "limit": 10})
        q = b.wait("rank_board")
        check("榜单可查", q and isinstance(q.get("rows"), list), q)
        check("乙在榜首", q and q["rows"] and q["rows"][0]["name"] == "乙乙",
              q and q["rows"])
        check("乙的分数正确", q and q["rows"][0]["pts"] == 1)
        check("me 字段是自己", q and q.get("me", {}).get("name") == "乙乙")
        check("未上榜的甲不在榜上",
              q and all(r["name"] != "甲甲" for r in q["rows"]))
        check("总数 = 1", q and q["total"] == 1, q and q.get("total"))

        print("\n=========== 6. 赛季懒结算 ===========")
        c = Cli()
        c.auth("丙丙", "pass1234")
        c.send({"m": "rank_seed", "rank": {
            "tier": 1, "stars": 0, "best": 1, "season": prev_month(),
            "lb_pts": 40, "lb_win": 10, "lb_lose": 5, "lb_active": True}})
        q = c.wait("rank")
        # 1 段 0 星 = 120 总星，扣 25 = 95 → 6 段 0 星
        check("上月赛季 seed 在服务端结算", q and q["rank"]["tier"] == 6,
              q and q["rank"])
        check("结算后排行榜积分清零", q and q["rank"]["lb_pts"] == 0)
        check("结算后赛季号更新", q and q["rank"]["season"] == rank.season_id(),
              q and q["rank"])
        c.send({"m": "rank_board"})
        q = c.wait("rank_board")
        check("结算后 6 段不上榜",
              q and all(r["name"] != "丙丙" for r in q["rows"]), q and q["rows"])

        print("\n=========== 7. 持久化（重连后仍在）===========")
        a.close()
        a2 = Cli()
        r = a2.auth("甲甲", "pass1234", kind="login")
        check("重新登录成功", r and r["m"] == "auth_ok", r)
        check("段位持久化", bool(r) and (r.get("rank") or {}).get("tier") == 24
              and (r.get("rank") or {}).get("stars") == 1, r and r.get("rank"))
        a2.send({"m": "rank"})
        q = a2.wait("rank")
        check("再次查询一致", q and q["rank"]["tier"] == 24
              and q["rank"]["stars"] == 1, q and q["rank"])

        print("\n=========== 8. 客户端 API（真实连接）===========")
        res = wait_connect(f"127.0.0.1:{PORT}")
        check("客户端连上服务器", bool(res and res[0]), res)
        link = res[0] if res else None
        if link is not None:
            account.set_remote(link, f"127.0.0.1:{PORT}")
            ok, err = account.login("甲甲", "pass1234")
            check("客户端登录", ok, err)
            st = account.get_rank()
            check("get_rank 走服务器", st and st["tier"] == 24 and st["stars"] == 1, st)
            got = account.rank_add(account.current(), "win")
            check("rank_add 走服务器", got and got["change"]["stars"] == 1, got)
            bd = account.leaderboard(10)
            check("leaderboard 标记在线", bd["online"] is True, bd.get("online"))
            check("leaderboard 有数据", bd["rows"] and bd["rows"][0]["name"] == "乙乙",
                  bd["rows"])
            check("me 为 None（甲未上榜）", bd["me"] is None, bd["me"])
            account.logout()
            account.set_remote(None)
            link.close()

        print("\n=========== 9. 坏输入不炸 ===========")
        d = Cli()
        d.auth("丁丁", "pass1234")
        d.send({"m": "rank_add", "result": "nonsense"})
        q = d.wait("rank")
        check("未知结果不动段位", q and q["rank"]["tier"] == 25, q and q["rank"])
        d.send({"m": "rank_seed", "rank": None})
        q = d.wait("rank")
        check("seed 空值不炸", q and q["rank"]["tier"] == 25, q and q["rank"])
        d.send({"m": "rank_board", "limit": "x"})
        q = d.wait("rank_board")
        check("limit 坏值不炸", q and isinstance(q.get("rows"), list), q)
        d.close()
    finally:
        for name in ("a", "a2", "b", "c", "d", "e"):
            obj = locals().get(name)
            if obj is not None:
                try:
                    obj.close()
                except Exception:            # noqa: BLE001
                    pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:                    # noqa: BLE001
            proc.kill()

    print()
    print("=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  -", f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
