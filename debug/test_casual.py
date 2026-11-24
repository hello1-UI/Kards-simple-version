# -*- coding: utf-8 -*-
"""休闲模式测试：与 AI / 与真人都不加星

两部分：
  A. 服务器端到端 —— 排位池与休闲池互不配对；matched 回传 casual；
     邀请码房间沿用房主的模式。
  B. 客户端逻辑 —— 入口字段一路带到对局；结算不调段位接口，但战绩/
     金币/每日任务照记；中途退出判定同样不碰段位。

必须用系统 Python（受管 Python 无 tkinter）：
    py debug/test_casual.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ["KARDS_DATA_DIR"] = tempfile.mkdtemp(prefix="kards_casual_")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
PORT = 6401

sys.path.insert(0, ROOT)
sys.argv.append("--no-fullscreen")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name
          + (f"  {extra}" if (extra and not cond) else ""))


# ---------------------------------------------------------------- A. 服务器
class Cli:
    """极简测试客户端：后台线程收包，按类型取。"""

    def __init__(self, port=PORT):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.s.settimeout(None)
        self.dead = False
        self.q = []
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

    def send(self, obj):
        if self.dead:
            return False
        try:
            self.s.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            return True
        except OSError:
            self.dead = True
            return False

    def wait(self, t, timeout=3):
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

    def login(self, user, pw):
        self.send({"m": "register", "user": user, "pw": pw})
        return self.wait("auth_ok", 6)

    def close(self):
        self.dead = True
        try:
            self.s.close()
        except OSError:
            pass
        with self.cv:
            self.cv.notify_all()


def server_tests():
    db_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="kards_casual_")
    os.close(db_fd)
    os.unlink(db_path)
    proc = subprocess.Popen(
        [PY, os.path.join(ROOT, "kards_server.py"), "--port", str(PORT),
         "--host", "127.0.0.1", "--db", db_path],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    clients = []
    try:
        ok = False
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", PORT), timeout=0.3).close()
                ok = True
                break
            except OSError:
                time.sleep(0.1)
        if not ok:
            check("服务器启动", False)
            return

        print("1. 排位池与休闲池互不配对")
        a = Cli(); clients.append(a)
        check("账号 A 就绪", bool(a.login("休闲甲", "pass1234")))
        b = Cli(); clients.append(b)
        check("账号 B 就绪", bool(b.login("休闲乙", "pass1234")))
        c = Cli(); clients.append(c)
        check("账号 C 就绪", bool(c.login("休闲丙", "pass1234")))

        a.send({"m": "match", "casual": 0})
        check("排位 A 进入队列", a.wait("matching") is not None)
        b.send({"m": "match", "casual": 1})
        m = b.wait("matching")
        check("休闲 B 进入队列（没有配到排位 A）",
              m is not None and m.get("casual") is True, m)
        check("A 没被休闲 B 抢走", not a.has("matched"))

        c.send({"m": "match", "casual": 0})
        ma = a.wait("matched", 4)
        mc = c.wait("matched", 4)
        check("排位 A 配到排位 C", ma is not None and mc is not None,
              (ma, mc))
        check("排位对局 casual=False",
              ma is not None and ma.get("casual") is False, ma)
        check("排位对局双方模式一致",
              mc is not None and mc.get("casual") is False, mc)
        check("排位对局互为对手",
              ma and mc and ma.get("opp") == "休闲丙"
              and mc.get("opp") == "休闲甲", (ma, mc))

        d = Cli(); clients.append(d)
        check("账号 D 就绪", bool(d.login("休闲丁", "pass1234")))
        d.send({"m": "match", "casual": 1})
        mb = b.wait("matched", 4)
        md = d.wait("matched", 4)
        check("休闲 B 配到休闲 D", mb is not None and md is not None, (mb, md))
        check("休闲对局 casual=True",
              mb is not None and mb.get("casual") is True, mb)
        check("休闲对局双方模式一致",
              md is not None and md.get("casual") is True, md)

        print("2. 邀请码房间沿用房主模式")
        e = Cli(); clients.append(e)
        check("账号 E 就绪", bool(e.login("休闲戊", "pass1234")))
        f = Cli(); clients.append(f)
        check("账号 F 就绪", bool(f.login("休闲己", "pass1234")))
        e.send({"m": "create_room", "casual": 1})
        rc = e.wait("room_created", 4)
        check("建房成功", rc is not None and bool(rc.get("code")), rc)
        check("房间回传 casual=True", rc is not None and rc.get("casual") is True, rc)
        f.send({"m": "join_room", "code": rc["code"] if rc else "XXXX"})
        me = e.wait("matched", 4)
        mf = f.wait("matched", 4)
        check("房主与加入者都进入对局", me is not None and mf is not None)
        check("房主侧 casual=True", me is not None and me.get("casual") is True, me)
        check("加入者侧 casual=True", mf is not None and mf.get("casual") is True, mf)

        # 排位房再验一遍 False，防「房间永远休闲」
        e.send({"m": "leave_room"})
        time.sleep(0.4)
        f.send({"m": "leave_room"})
        time.sleep(0.4)
        e.send({"m": "create_room", "casual": 0})
        rc2 = e.wait("room_created", 4)
        f.send({"m": "join_room", "code": rc2["code"] if rc2 else "XXXX"})
        me2 = e.wait("matched", 4)
        mf2 = f.wait("matched", 4)
        check("排位房 casual=False",
              me2 is not None and me2.get("casual") is False, me2)
        check("排位房加入者 casual=False",
              mf2 is not None and mf2.get("casual") is False, mf2)

        print("3. 取消匹配不会连累别人排队")
        # 该用例锁的是 do_match 的「不能 pop 掉不匹配候选」修复
        g = Cli(); clients.append(g)
        g.login("休闲庚", "pass1234")
        h = Cli(); clients.append(h)
        h.login("休闲辛", "pass1234")
        g.send({"m": "match", "casual": 0})
        g.wait("matching", 4)
        h.send({"m": "match", "casual": 1})       # 遍历到排位 G，不应把他弹掉
        h.wait("matching", 4)
        time.sleep(0.3)
        i = Cli(); clients.append(i)
        i.login("休闲壬", "pass1234")
        i.send({"m": "match", "casual": 0})
        mg = g.wait("matched", 4)
        check("排位 G 仍在队列并配到新排位 I", mg is not None, mg)
        h.send({"m": "cancel_match"})
        check("休闲 H 可正常取消", h.wait("match_cancelled", 4) is not None)
    finally:
        for cli in clients:
            cli.close()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        for p in (db_path, db_path + "-wal", db_path + "-shm"):
            try:
                os.unlink(p)
            except OSError:
                pass


# ---------------------------------------------------------------- B. 客户端
def client_tests():
    import tkinter as tk
    import kards_engine as K
    import kards_i18n as i18n
    import KARDS as gui

    def _exists_text(root, needle):
        """在控件树里找含 needle 的 Label/Button 文本"""
        found = []

        def _walk(w):
            try:
                t = str(w.cget("text"))
                if needle in t:
                    found.append(t)
            except (tk.TclError, AttributeError):
                pass
            for ch in w.winfo_children():
                _walk(ch)

        _walk(root)
        return bool(found)

    tmp = os.path.join(tempfile.gettempdir(), "kards_casual_settings.json")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"language": "zh"}, fh)
    i18n._SETTINGS_PATH = tmp
    i18n.set_lang("zh")
    gui.App._account_dialog = lambda self, for_server=False: None
    gui.App.open_update_dialog = lambda self, auto=False: None

    app = gui.App()
    app.geometry("1200x800+10+10")
    try:
        app.attributes("-fullscreen", False)
    except tk.TclError:
        pass
    app.update()

    rec = {"stats": [], "rank": [], "ai": [], "money": [], "quest": [],
           "end": [], "logs": []}
    gui.account.stats_add = lambda n, r: rec["stats"].append((n, r))
    gui.account.currency_reward = lambda r, name=None: (
        rec["money"].append((name, r)) or {"gold": 10, "diamonds": 0})
    gui.quests.record_game = lambda r, **kw: rec["quest"].append((r, kw.get("online")))
    app._rank_settle = lambda r: (rec["rank"].append(r) or "")
    app._rank_settle_ai = lambda r: (rec["ai"].append(r) or "")
    app.show_end_animation = lambda won, on_done=None, nation=None, rank_line="": (
        rec["end"].append((won, rank_line)))
    app.refresh = lambda: None
    app._music_play = lambda *a, **k: None
    app.add_log = lambda m: rec["logs"].append(m)
    app._refresh_account_btn = lambda: None
    app._refresh_quest_btn = lambda: None
    app.account = "休闲测试员"
    app._pyboard = None

    def clear():
        for v in rec.values():
            v.clear()

    def new_game():
        db = K.card_database()
        p1 = K.Player("我", "德国", [db["近卫步兵"]] * K.DECK_SIZE)
        p2 = K.Player("敌", "苏联", [db["近卫步兵"]] * K.DECK_SIZE)
        return K.Game(p1, p2, interactive=False)

    print("4. 主菜单有休闲入口")
    texts = []
    def walk(w):
        try:
            t = w.cget("text")
            if t:
                texts.append(str(t))
        except (tk.TclError, AttributeError):
            pass
        for ch in w.winfo_children():
            walk(ch)
    walk(app.start_frame)
    check("入口卡标题含「休闲」", any("休闲" in t for t in texts),
          [t for t in texts if "休闲" in t])
    check("入口卡提示写明不加星",
          any("不加星" in t for t in texts), [t for t in texts if "不加星" in t])

    # 布局断言：三张入口卡必须完整落在窗口内、互不重叠。
    # （屏幕锁着时截图全黑，人眼验收抓不到 —— 用几何断言兜底，实测踩过。）
    cards = []
    def find_cards(w):
        try:
            # CardWidget：固定宽 200 的 Frame（pack 时 ipady 会把高度撑到 250），
            # 标题是它第一个子 Label
            if (w.winfo_width() == 200 and type(w).__name__ == "CardWidget"
                    and w.winfo_children()):
                first = w.winfo_children()[0]
                title = str(first.cget("text"))
                if title in ("⚔ 战斗", "🎯 练习", "♣ 休闲"):
                    cards.append((title,
                                  w.winfo_rootx(), w.winfo_rooty(),
                                  w.winfo_width(), w.winfo_height()))
        except (tk.TclError, AttributeError):
            pass
        for ch in w.winfo_children():
            find_cards(ch)
    app.update()
    find_cards(app.start_frame)
    check("找到三张入口卡", len(cards) == 3, cards)
    if len(cards) == 3:
        vx, vy = app.winfo_rootx(), app.winfo_rooty()
        vw, vh = app.winfo_width(), app.winfo_height()
        inside = all(x >= vx and y >= vy and x + w <= vx + vw and y + h <= vy + vh
                     for _, x, y, w, h in cards)
        check("入口卡完整落在窗口内", inside, (vx, vy, vw, vh, cards))
        ordered = sorted(cards, key=lambda c: c[1])
        no_overlap = all(ordered[i][1] + ordered[i][3] <= ordered[i + 1][1]
                         for i in range(2))
        check("入口卡横向不重叠", no_overlap, ordered)

    print("5. 休闲选择界面：AI / 真人两条路")
    app._build_casual_select()
    app.update()
    texts.clear(); walk(app.start_frame)
    check("有「对战 AI」", any("对战 AI" in t for t in texts), texts)
    check("有「对战真人」", any("对战真人" in t for t in texts), texts)
    check("说明含不加星", any("不加星" in t or "不掉星" in t for t in texts), texts)

    print("5b. 返回主菜单：旧界面必须销毁（叠加 bug 回归）")
    app._casual_back()
    app.update()
    check("休闲选择页已销毁（标题不在控件树里）",
          not _exists_text(app, "休闲模式"), None)
    check("主菜单已重建（三入口卡可见）",
          _exists_text(app, "♣ 休闲") and _exists_text(app, "⚔ 战斗"), None)
    # root 直属 Frame 只应有一个 start_frame
    tops = [w for w in app.winfo_children() if isinstance(w, tk.Frame)]
    check("主窗口下只挂一个界面 Frame", len(tops) == 1,
          [(type(w).__name__, str(getattr(w, "winfo_width", lambda: 0)())) for w in tops])
    texts.clear(); walk(app.start_frame)
    check("返回后休闲子页文案消失",
          not any("对战真人" in t for t in texts), texts)

    print("5c. 再进休闲选择再返回（往返一次仍正常）")
    app._build_casual_select()
    app.update()
    app._casual_back()
    app.update()
    check("第二次返回后界面唯一",
          len([w for w in app.winfo_children() if isinstance(w, tk.Frame)]) == 1)

    print("6. 休闲入口把标志一路带进对局")
    app._build_nation_select(casual=True)
    app.update()
    check("国家选择记住 casual", app.casual is True)
    app._build_deck_builder("德国", mp=False, casual=True)
    app.update()
    check("组卡界面记住 casual", app.casual is True)
    app.deck_counts = {}
    deck = K.build_deck("德国", app.db)
    for c in deck:
        app.deck_counts[c.name] = app.deck_counts.get(c.name, 0) + 1
    captured = {}

    def fake_new_game(nation, deck=None, casual=False):
        captured.update(nation=nation, casual=casual)

    app.new_game = fake_new_game
    app._start_custom()
    check("开局沿用休闲标志", captured.get("casual") is True, captured)
    check("开局主国正确", captured.get("nation") == "德国", captured)

    print("7. 休闲人机胜局：不加星，但战绩/金币/任务照记")
    clear()
    app.game = new_game()
    app._game_online = False
    app.casual = True
    app._finishing = False
    app._mp_game_over = False
    app.finish(winner=app.game.players[0])
    check("没调排位结算", rec["rank"] == [], rec["rank"])
    check("没调人机折算", rec["ai"] == [], rec["ai"])
    check("战绩记了一胜", rec["stats"] == [("休闲测试员", "win")], rec["stats"])
    check("金币照发", rec["money"] == [("休闲测试员", "win")], rec["money"])
    check("任务照记", rec["quest"] == [("win", False)], rec["quest"])
    check("结算页文案写明段位不变",
          rec["end"] and rec["end"][-1][1] == i18n.t("casual_no_rank"),
          rec["end"])

    print("8. 休闲联机胜局：同样不加星")
    clear()
    app.game = new_game()
    app._game_online = True
    app.casual = True
    app._finishing = False
    app._mp_game_over = False
    app.finish(winner=app.game.players[0])
    check("联机休闲也没调排位结算", rec["rank"] == [], rec["rank"])
    check("联机休闲没调人机折算", rec["ai"] == [], rec["ai"])
    check("战绩照记", rec["stats"] == [("休闲测试员", "win")], rec["stats"])
    check("任务记为联机场次", rec["quest"] == [("win", True)], rec["quest"])
    check("结算页文案写明段位不变",
          rec["end"] and rec["end"][-1][1] == i18n.t("casual_no_rank"),
          rec["end"])

    print("9. 休闲对局中途退出：判负但不扣星")
    clear()
    app.game = new_game()
    app._game_online = False
    app.casual = True
    app._mp_game_over = False
    app.mp_link = None
    ok = app._forfeit_if_playing()
    check("判负生效", ok is True)
    check("战绩记负", rec["stats"] == [("休闲测试员", "lose")], rec["stats"])
    check("人机段位没被调用", rec["ai"] == [], rec["ai"])
    check("排位段位没被调用", rec["rank"] == [], rec["rank"])
    check("输了也有金币", rec["money"] == [("休闲测试员", "lose")], rec["money"])

    print("10. 非休闲回归：练习仍然每 2 胜折算 1 星")
    clear()
    app.game = new_game()
    app._game_online = False
    app.casual = False
    app._finishing = False
    app._mp_game_over = False
    app.finish(winner=app.game.players[0])
    check("练习走了人机结算", rec["ai"] == ["win"], rec["ai"])
    check("练习没走排位结算", rec["rank"] == [], rec["rank"])

    print("11. 排位大厅 / 休闲大厅文案分开")
    app._lobby_connect = lambda: None
    app._schedule = lambda *a, **k: None
    app._lobby_active = False
    app._build_lobby(casual=True)
    app.update()
    texts.clear(); walk(app.start_frame)
    check("休闲大厅标题", any("休闲大厅" in t for t in texts), texts)
    check("匹配按钮写「休闲匹配」",
          any("休闲匹配" in t for t in texts), texts)
    check("大厅标志 casual=True", app.casual is True)
    app._build_lobby()
    app.update()
    texts.clear(); walk(app.start_frame)
    check("排位大厅标题", any(t.strip() == "联机对战" for t in texts), texts)
    check("匹配按钮写「快速匹配」",
          any("快速匹配" in t for t in texts), texts)
    check("大厅标志复位 casual=False", app.casual is False)

    try:
        app.destroy()
    except Exception:                            # noqa: BLE001
        pass


def main():
    server_tests()
    client_tests()
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
