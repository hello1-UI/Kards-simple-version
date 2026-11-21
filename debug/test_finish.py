# -*- coding: utf-8 -*-
"""finish() 结算回归测试（真 bug：result 在 won 赋值前被引用 → UnboundLocalError）

覆盖三条结算路径（对应 error.log 里用户实测的两个崩溃点）：
  1. 敌方总部被打死 → check_over() → finish()          【崩溃点 2】
  2. AI 投降 → finish(winner=...)                        【崩溃点 1】
  3. 双方总部同时陷落 → 平局
并验证货币奖励 result（win/lose/draw）正确传入 currency_reward。

必须用系统 Python（受管 Python 无 tkinter）：
    py debug/test_finish.py
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv.append("--no-fullscreen")            # 测试不进全屏
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                          # noqa: E402

import kards_engine as K                      # noqa: E402
import KARDS as gui                           # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


REC = []                                       # (result, name) 记录


def fake_reward(result, name=None):
    REC.append(result)
    return {"gold": 1, "diamonds": 0}


def make_app():
    app = gui.App()
    # 测试期间不要真写账号战绩/货币文件
    gui.account.stats_add = lambda *a, **k: None
    gui.account.currency_reward = fake_reward
    return app


def setup_game(app, my_hq=20, foe_hq=20):
    db = K.card_database()
    p1 = K.Player("我", "德国", [db["步兵班"]] * K.DECK_SIZE)
    p2 = K.Player("敌", "苏联", [db["动员兵"]] * K.DECK_SIZE)
    g = K.Game(p1, p2, interactive=False)
    g.draw_cards(p1, 8)
    g.draw_cards(p2, 8)
    g.players[0].hq = my_hq
    g.players[1].hq = foe_hq
    app.game = g
    b = app._activate_pyboard()
    assert b is not None, "pygame 棋盘激活失败"
    b.sync()
    return g, p1, p2


def main():
    print("== finish() 结算回归 ==")

    print("-- 1. 敌方总部被打死（check_over 路径，崩溃点 2）--")
    app = make_app()
    g, p1, p2 = setup_game(app, foe_hq=0)
    try:
        app.check_over()
        ok = True
    except Exception as exc:
        ok = False
        print(f"      异常: {exc!r}")
    check("check_over→finish 不抛 UnboundLocalError", ok)
    check("胜方=我 → 奖励按 win 结算", REC and REC[-1] == "win", str(REC))
    app.destroy()

    print("-- 2. AI 投降（finish(winner=...) 直传，崩溃点 1）--")
    app = make_app()
    g, p1, p2 = setup_game(app)
    try:
        app.finish(winner=g.winner_of() or p1)   # 我方获胜（模拟对手认输视角取反前逻辑）
        ok = True
    except Exception as exc:
        ok = False
        print(f"      异常: {exc!r}")
    check("finish(winner=...) 不抛 UnboundLocalError", ok)
    check("直传胜者 → 奖励按 win 结算", REC and REC[-1] == "win", str(REC))
    app.destroy()

    print("-- 3. 我方战败（win/lose 对称性）--")
    app = make_app()
    g, p1, p2 = setup_game(app, my_hq=0)
    try:
        app.check_over()
        ok = True
    except Exception as exc:
        ok = False
        print(f"      异常: {exc!r}")
    check("我方总部被打死不抛异常", ok)
    check("败方 → 奖励按 lose 结算", REC and REC[-1] == "lose", str(REC))
    app.destroy()

    print("-- 4. 平局（双方总部同时陷落）--")
    app = make_app()
    g, p1, p2 = setup_game(app, my_hq=0, foe_hq=0)
    try:
        app.finish()
        ok = True
    except Exception as exc:
        ok = False
        print(f"      异常: {exc!r}")
    check("平局结算不抛异常", ok)
    check("平局 → 奖励按 draw 结算", REC and REC[-1] == "draw", str(REC))
    app.destroy()

    print(f"\n结果: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for f in FAIL:
            print("  !!", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
