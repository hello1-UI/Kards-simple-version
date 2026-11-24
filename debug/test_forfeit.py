# -*- coding: utf-8 -*-
"""中途退出判负测试：返回大厅 / 退出程序 / 关窗都按负结算

必须用系统 Python（受管 Python 无 tkinter）：
    py debug/test_forfeit.py
"""
import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ["KARDS_DATA_DIR"] = tempfile.mkdtemp(prefix="kards_forfeit_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.argv.append("--no-fullscreen")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json                                 # noqa: E402

import tkinter as tk                        # noqa: E402

import kards_engine as K                    # noqa: E402
import kards_i18n as i18n                   # noqa: E402
import KARDS as gui                         # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name
          + (f"  {extra}" if (extra and not cond) else ""))


def make_app():
    tmp = os.path.join(tempfile.gettempdir(), "kards_forfeit_settings.json")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"language": "zh"}, fh)
    i18n._SETTINGS_PATH = tmp
    gui.App._account_dialog = lambda self, for_server=False: None
    gui.App.open_update_dialog = lambda self, auto=False: None
    app = gui.App()
    app.geometry("1100x760+20+20")
    try:
        app.attributes("-fullscreen", False)
    except tk.TclError:
        pass
    app.update()
    return app


class Recorder:
    """把结算相关的副作用都记下来，便于断言「记了几次」。"""

    def __init__(self):
        self.stats = []
        self.rank = []
        self.ai = []
        self.money = []
        self.quest = []
        self.logs = []
        self.sent = []

    def install(self, app):
        gui.account.stats_add = lambda n, r: self.stats.append((n, r))
        gui.account.rank_add = lambda n, r: (
            self.rank.append((n, r)) or {"rank": {}, "change": {}})
        gui.account.rank_add_ai = lambda n, r: (
            self.ai.append((n, r)) or {"rank": {}, "change": {}})
        gui.account.currency_reward = lambda r, name=None: (
            self.money.append((name, r)) or {"gold": 0, "diamonds": 0})
        gui.quests.record_game = lambda result, **kw: self.quest.append(
            (result, kw.get("online")))
        app.add_log = lambda m: self.logs.append(m)
        app._refresh_account_btn = lambda: None
        app._refresh_quest_btn = lambda: None
        app._rank_settle = lambda r: (self.rank.append((app.account, r)) or "")
        app._rank_settle_ai = lambda r: (self.ai.append((app.account, r)) or "")

    def clear(self):
        for k in ("stats", "rank", "ai", "money", "quest", "logs", "sent"):
            getattr(self, k).clear()


def new_game():
    db = K.card_database()
    p1 = K.Player("我", "德国", [db["近卫步兵"]] * K.DECK_SIZE)
    p2 = K.Player("敌", "苏联", [db["近卫步兵"]] * K.DECK_SIZE)
    return K.Game(p1, p2, interactive=False)


def main():
    app = make_app()
    rec = Recorder()
    try:
        app.account = "Tester"
        rec.install(app)

        print("1. 对局中退出 = 判负")
        g = new_game()
        app.game = g
        app._game_online = False
        app._mp_game_over = False
        app.mp_link = None
        ok = app._forfeit_if_playing()
        check("返回 True（确实结算了）", ok is True, ok)
        check("引擎记了投降方", g.conceded is g.players[0], g.conceded)
        check("战绩记负", rec.stats == [("Tester", "lose")], rec.stats)
        check("人机走 AI 段位结算", rec.ai == [("Tester", "lose")], rec.ai)
        check("联机段位没被调用", rec.rank == [], rec.rank)
        check("输了也有金币结算", rec.money == [("Tester", "lose")], rec.money)
        check("每日任务记了一局（人机）", rec.quest == [("lose", False)], rec.quest)
        check("日志写了判负", any("判负" in x or "放弃" in x for x in rec.logs),
              rec.logs[-2:])
        check("结算后置位防重复", app._mp_game_over is True)

        print("2. 不会重复结算")
        rec.clear()
        check("再调一次返回 False", app._forfeit_if_playing() is False)
        check("战绩没被记第二遍", rec.stats == [], rec.stats)
        check("任务没被记第二遍", rec.quest == [], rec.quest)

        print("3. 已经结束的对局不算判负")
        rec.clear()
        g2 = new_game()
        g2.over = True
        app.game = g2
        app._mp_game_over = False
        check("over 的对局跳过", app._forfeit_if_playing() is False)
        check("over 的对局不记战绩", rec.stats == [], rec.stats)

        rec.clear()
        g3 = new_game()
        g3.conceded = g3.players[0]
        app.game = g3
        app._mp_game_over = False
        check("已投降的对局跳过", app._forfeit_if_playing() is False)
        check("已投降的对局不补记", rec.stats == [], rec.stats)

        rec.clear()
        app.game = None
        check("没有对局时无副作用", app._forfeit_if_playing() is False)

        print("4. 联机：通知对手 + 走排位结算")
        rec.clear()
        g4 = new_game()
        app.game = g4
        app._game_online = True
        app._mp_game_over = False

        class FakeLink:
            def __init__(self):
                self.msgs = []

            def send(self, m):
                self.msgs.append(m)

        link = FakeLink()
        app.mp_link = link
        ok = app._forfeit_if_playing()
        check("联机退出也判负", ok is True)
        check("向对手发了投降", {"m": "concede"} in link.msgs, link.msgs)
        check("联机走排位结算", rec.rank == [("Tester", "lose")], rec.rank)
        check("联机不走人机结算", rec.ai == [], rec.ai)
        check("每日任务记为联机场次", rec.quest == [("lose", True)], rec.quest)

        print("5. 返回大厅会触发判负")
        rec.clear()
        g5 = new_game()
        app.game = g5
        app._game_online = False
        app._mp_game_over = False
        app.mp_link = None
        app._pyboard = None
        app.back_to_menu()
        app.update()
        check("返回大厅时结算了负场", rec.stats == [("Tester", "lose")], rec.stats)
        check("返回大厅后清空对局", app.game is None, app.game)
        check("主菜单已重建", getattr(app, "start_frame", None) is not None)
        rec.clear()
        app.back_to_menu()
        app.update()
        check("结算页再返回不补记负场", rec.stats == [], rec.stats)

        print("6. 所有退出入口都挂了判负")
        import inspect
        src = inspect.getsource(gui.App.destroy)
        check("destroy 里调判负", "_forfeit_if_playing" in src)
        src2 = inspect.getsource(gui.App.back_to_menu)
        check("back_to_menu 里调判负", "_forfeit_if_playing" in src2)

        print("7. 退出程序时结算（最后一次，会真 destroy）")
        rec.clear()
        g6 = new_game()
        app.game = g6
        app._game_online = False
        app._mp_game_over = False
        app.mp_link = None
        app.destroy()
        check("关窗退出也记负场", rec.stats == [("Tester", "lose")], rec.stats)
        check("关窗退出记了任务", rec.quest == [("lose", False)], rec.quest)
    finally:
        try:
            app.destroy()
        except Exception:                       # noqa: BLE001
            pass

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
