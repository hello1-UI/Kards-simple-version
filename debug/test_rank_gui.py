# -*- coding: utf-8 -*-
"""段位 GUI 测试：账号按钮 / 段位窗 / 结算联动

必须用系统 Python（受管 Python 无 tkinter）：
    py debug/test_rank_gui.py
"""
import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
# 测试绝不写玩家的账号/设置文件
os.environ["KARDS_DATA_DIR"] = tempfile.mkdtemp(prefix="kards_rank_gui_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.argv.append("--no-fullscreen")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json                                 # noqa: E402

import tkinter as tk                        # noqa: E402

import kards_engine as K                    # noqa: E402
import kards_i18n as i18n                   # noqa: E402
import kards_rank as rank                   # noqa: E402
import KARDS as gui                         # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name
          + (f"  {extra}" if (extra and not cond) else ""))


def texts(widget):
    """递归收集控件文字（Label/Button 的 text，Entry 的值）"""
    out = []
    try:
        t = widget.cget("text")
        if t:
            out.append(str(t))
    except tk.TclError:
        pass
    try:
        if isinstance(widget, tk.Entry):
            out.append(widget.get())
    except tk.TclError:
        pass
    for ch in widget.winfo_children():
        out.extend(texts(ch))
    return out


def star_pips(widget):
    """收集所有「单颗星」标签的 fg（段位窗逐颗画星，不是一整串）"""
    out = []
    try:
        if str(widget.cget("text")) == "★":
            out.append(str(widget.cget("fg")))
    except tk.TclError:
        pass
    for ch in widget.winfo_children():
        out.extend(star_pips(ch))
    return out


def find_toplevel(app, role):
    for w in app.winfo_children():
        if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == role:
            return w
    return None


def make_app():
    tmp = os.path.join(tempfile.gettempdir(), "kards_rank_gui_settings.json")
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


def main():
    print("1. 星数与按钮文案")
    check("5 星显示", gui.App._stars_text(5) == "★★★★★")
    check("0 星显示", gui.App._stars_text(0) == "☆☆☆☆☆")
    check("3 星显示", gui.App._stars_text(3) == "★★★☆☆")
    check("越界星数被夹住", gui.App._stars_text(9) == "★★★★★")

    app = make_app()
    try:
        app.account = "Tester"
        app.rank_state = {"tier": 12, "stars": 3, "best": 5, "streak": 2,
                          "zero_losses": 1, "season": rank.season_id(),
                          "lb_pts": 0, "lb_win": 0, "lb_lose": 0,
                          "lb_active": False}
        txt = app._account_btn_text()
        check("账号按钮带段位", "12" in txt and "★★★☆☆" in txt, txt)
        check("账号按钮带名字", "Tester" in txt, txt)

        print("2. 段位窗：内容齐全")
        # 段位窗会强制重取（force=True）：把账号层也打桩，否则会读到空账号
        gui.account.get_rank = lambda name=None: dict(app.rank_state)
        rows = [{"name": "元帅甲", "tier": 1, "stars": 2, "pts": 21,
                 "win": 9, "lose": 2, "pos": 1},
                {"name": "Tester", "tier": 12, "stars": 3, "pts": 4,
                 "win": 2, "lose": 1, "pos": 2}]
        gui.account.leaderboard = lambda limit=20: {
            "rows": rows, "total": 2, "me": None, "online": True,
            "season": rank.season_id()}
        app.open_rank_dialog()
        app.update()
        win = find_toplevel(app, "rank")
        check("段位窗已创建", win is not None)
        if win is not None:
            all_txt = " | ".join(texts(win))
            check("显示当前段位数字", "12" in all_txt, all_txt[:200])
            pips = star_pips(win)
            gold = sum(1 for c in pips if c.upper() == gui.GOLD.upper())
            check("5 颗星全画出来", len(pips) == 5, pips)
            check("其中 3 颗是实星（金色）", gold == 3, pips)
            check("显示升段进度", "还差" in all_txt, all_txt[:200])
            check("显示连胜", "连胜" in all_txt, all_txt[:200])
            check("显示保护段位", "保护段位" in all_txt, all_txt[:200])
            check("未上榜有提示", "1 段" in all_txt and "排行榜" in all_txt)
            check("排行榜有第一名", "元帅甲" in all_txt, all_txt[:300])
            check("排行榜有自己", "Tester" in all_txt)
            check("显示积分", "21" in all_txt)
            check("显示规则", "25 段" in all_txt, all_txt[-260:])
            check("窗口只有一个", sum(
                1 for w in app.winfo_children()
                if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == "rank") == 1)
            app.open_rank_dialog()          # 再点一次不应叠窗
            app.update()
            check("重复打开不叠窗", sum(
                1 for w in app.winfo_children()
                if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == "rank") == 1)
            win.destroy()
            app.update()

        print("3. 段位窗：游客态")
        app.account = None
        app.rank_state = None
        app.open_rank_dialog()
        app.update()
        win = find_toplevel(app, "rank")
        check("游客也能开窗", win is not None)
        if win is not None:
            all_txt = " | ".join(texts(win))
            check("游客看到登录引导", "尚未登录" in all_txt, all_txt[:200])
            check("游客看到段位说明", "联机" in all_txt, all_txt[:250])
            win.destroy()
            app.update()

        print("4. 结算联动：联机走排位、人机走 2 胜 1 星")
        calls = {"rank": [], "ai": [], "stats": []}
        gui.account.rank_add = lambda n, r: (
            calls["rank"].append((n, r)) or
            {"rank": {"tier": 11, "stars": 0, "best": 5, "streak": 3,
                      "zero_losses": 0, "season": rank.season_id(),
                      "lb_pts": 0, "lb_win": 0, "lb_lose": 0, "lb_active": False},
             "change": {"result": r, "stars": 2, "from": (12, 3), "to": (11, 0),
                        "promoted": True, "demoted": False, "protected": False,
                        "entered": False, "lb": 0, "season_rolled": False}})
        gui.account.stats_add = lambda n, r: calls["stats"].append((n, r))
        gui.account.rank_add_ai = lambda n, r: (
            calls["ai"].append((n, r)) or
            {"rank": {"tier": 12, "stars": 2, "best": 12, "streak": 0,
                      "zero_losses": 0, "ai_wins": 1,
                      "season": rank.season_id(),
                      "lb_pts": 0, "lb_win": 0, "lb_lose": 0, "lb_active": False},
             "change": {"result": r, "stars": 0, "from": (12, 2), "to": (12, 2),
                        "promoted": False, "demoted": False,
                        "protected": False, "entered": False, "lb": 0,
                        "season_rolled": False, "ai": True, "ai_win": 1,
                        "ai_pending": True}})
        gui.account.currency_reward = lambda r, name=None: {"gold": 1, "diamonds": 0}
        logs = []
        cap = {}
        app.account = "Tester"
        app.add_log = lambda m: logs.append(m)
        app.refresh = lambda: None
        app.show_end_animation = lambda won, on_done=None, nation=None, rank_line="": (
            cap.update(won=won, line=rank_line))
        db = K.card_database()
        p1 = K.Player("我", "德国", [db["近卫步兵"]] * K.DECK_SIZE)
        p2 = K.Player("敌", "苏联", [db["近卫步兵"]] * K.DECK_SIZE)
        g = K.Game(p1, p2, interactive=False)
        app.game = g
        app._game_online = True
        app._finishing = False
        app.finish(winner=p1)
        check("联机胜利 → 记段位", calls["rank"] == [("Tester", "win")],
              calls["rank"])
        check("结算页拿到段位文案", "晋级" in cap.get("line", ""), cap)
        check("日志写了段位", any("段位" in x for x in logs), logs[-3:])
        check("段位缓存已更新", app.rank_state and app.rank_state["tier"] == 11,
              app.rank_state)

        calls["rank"].clear()
        calls["ai"].clear()
        cap.clear()
        app._finishing = False
        app._game_online = False
        app.finish(winner=p1)
        check("人机对局走 rank_add_ai", calls["ai"] == [("Tester", "win")],
              calls["ai"])
        check("人机对局不调联机结算", calls["rank"] == [], calls["rank"])
        check("人机第 1 胜提示再赢 1 场", "再赢" in cap.get("line", ""), cap)
        check("人机结算更新段位缓存",
              app.rank_state and app.rank_state["ai_wins"] == 1, app.rank_state)

        calls["rank"].clear()
        cap.clear()
        gui.account.rank_add = lambda n, r: None
        app._finishing = False
        app._game_online = True
        app.finish(winner=p1)
        check("结算失败不崩且提示", any("未送达" in x for x in logs[-4:]), logs[-4:])
        check("结算失败不显示段位行", cap.get("line") == "", cap)
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
