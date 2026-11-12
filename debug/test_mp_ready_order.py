# -*- coding: utf-8 -*-
"""联机「准备」时序回归：准备顺序颠倒也必须能开局

用户报障原文："两边都准备了，但开不了"；随后补充：
"有一方进，另一方显示对方卡组卡牌数量异常"。

根因（已修）：
    `_start_mp()` 里有一句 `self.mp_opp = None`。对手如果**先**点了准备，
    他的 ready 已经被 _mp_prep_watch / _lobby_drain_events 收进 mp_opp；
    我方随后点准备时把这唯一的对手信息清成 None，而对手不会重发 ready：
      · 主机侧：永远等不到"对手已就绪" → 双方一起卡在「等待对手准备」
      · 客户端侧：收到 seed 后 `opp = {}` → 卡组 0 张 ≠ 30 →
        「对手卡组数量异常，连接中止」（正是用户看到的现象）
    修复：点准备时不再清 mp_opp；种子先到而 ready 未到时先暂存
    `_mp_pending_seed`，等 ready 落地再开局。

不依赖真实服务器，用 FakeLink 精确复刻消息时序。

    py debug/test_mp_ready_order.py
"""
import os
import queue
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.argv.append("--no-fullscreen")
sys.argv.append("--no-update-check")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                              # noqa: E402

import KARDS as gui                               # noqa: E402
import kards_engine as core                        # noqa: E402
import kards_i18n as i18n                          # noqa: E402

PASS, FAIL, POPUPS = [], [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


class FakeLink:
    """最小可用的服务器链路替身：发出的消息记在 sent，收到的靠 inbox。"""

    def __init__(self):
        self.inbox = queue.Queue()
        self.sent = []
        self.alive = True
        self.intentional = False

    def send(self, obj):
        self.sent.append(obj)
        return True

    def close(self):
        self.alive = False


def prepare(app, nation="德国"):
    """把界面推到「组卡界面 + 卡组已填满」（等价于玩家组完卡）。"""
    app.mp_mode = True
    if getattr(app, "start_frame", None) is None or not app.start_frame.winfo_exists():
        app.start_frame = tk.Frame(app, bg=gui.BG)
        app.start_frame.pack()
    app._build_nation_select(mp=True)
    app._build_deck_builder(nation, mp=True)
    deck = core.build_deck(nation, app.db)
    app.deck_counts = {}
    for c in deck:
        app.deck_counts[c.name] = app.deck_counts.get(c.name, 0) + 1


def main():
    gui.account.stats_add = lambda *a, **k: None
    gui.account.currency_reward = lambda *a, **k: {"gold": 0, "diamonds": 0}
    # 无头环境不能真弹窗（会卡死在没人点的对话框上）；记录调用即可
    gui.messagebox.showerror = lambda *a, **k: POPUPS.append(("error", a))
    gui.messagebox.showwarning = lambda *a, **k: POPUPS.append(("warn", a))
    gui.messagebox.showinfo = lambda *a, **k: POPUPS.append(("info", a))

    app = gui.App()
    # _mp_launch() 末尾会进 pygame 主循环打完整局（阻塞几十回合）；测试只关心
    # 「有没有开起来」，把它换成空操作。
    app._run_pyboard = lambda: None
    try:
        app._cancel_timers()
        app.mp_link = FakeLink()
        app.mp_role = "host"
        prepare(app)
        opp_deck = [c.name for c in core.build_deck("苏联", app.db)]
        my_deck = app._counts_to_deck()
        check("测试用卡组是合法 30 张", len(my_deck) == core.DECK_SIZE, str(len(my_deck)))

        print("== A. 对手先准备、我方后准备（用户踩到的时序） ==")
        app.mp_link.inbox.put({"m": "ready", "nation": "苏联", "deck": opp_deck})
        app._lobby_drain_events()
        check("对手先到的 ready 被收下", app.mp_opp is not None, str(app.mp_opp))

        app._start_mp()
        check("点准备后**没有**抹掉对手信息", app.mp_opp is not None,
              "mp_opp 被清空 —— 这就是两边都准备了却开不了的根因")
        check("我方 ready 已发出",
              any(m.get("m") == "ready" for m in app.mp_link.sent),
              str(app.mp_link.sent))

        app._mp_poll_hello()
        seeds = [m for m in app.mp_link.sent if m.get("m") == "seed"]
        check("主机随后发出开局种子", bool(seeds), str(app.mp_link.sent))
        check("主机进入对局", app.game is not None)
        check("没有弹出「卡组数量异常」",
              not any(p[0] == "error" for p in POPUPS), str(POPUPS))

        print("== B. 客户端：种子先到、ready 后到（顺序颠倒） ==")
        app.game = None
        app._mp_pending_seed = None
        app.mp_opp = None
        app.mp_role = "client"
        app.mp_link.sent.clear()
        app.mp_link.inbox.put({"m": "seed", "seed": 12345})
        app._mp_poll_hello()                     # 只收到 seed：应当暂存，不报错
        check("缺对手信息时暂存种子而不是报错",
              app._mp_pending_seed == 12345 and app.game is None,
              "pending=%r game=%r" % (app._mp_pending_seed, app.game))
        check("暂存阶段没有弹「卡组数量异常」",
              not any("卡组数量异常" in str(p[1]) for p in POPUPS), str(POPUPS))
        app.mp_link.inbox.put({"m": "ready", "nation": "德国", "deck": opp_deck})
        app._mp_poll_hello()                     # ready 到了：立即开局
        check("ready 到达后客户端成功开局", app.game is not None)
        check("种子被消费掉（不会重复开局）", app._mp_pending_seed is None)

        print("== C. 我方先准备、对手后准备（原有路径不回归） ==")
        app.game = None
        app._cancel_timers()
        app._mp_pending_seed = None
        app.mp_opp = None
        app.mp_role = "host"
        app._mp_me_ready = False
        app.mp_link = FakeLink()
        prepare(app)
        app._start_mp()
        check("我方先准备时 mp_opp 为空", app.mp_opp is None)
        app.mp_link.inbox.put({"m": "ready", "nation": "苏联", "deck": opp_deck})
        app._mp_poll_hello()
        check("对手后到时主机照常开局", app.game is not None)
        check("全程没有弹窗（错误提示）",
              not [p for p in POPUPS if p[0] == "error"], str(POPUPS))

        print("== D. 准备过程在日志里留下可诊断记录 ==")
        log = " ".join(app.mp_lobby_log)
        check("日志含「已发出准备」", i18n.t("mp_log_ready_sent") in log, log[-160:])
        check("日志含「对手已就绪」", "对手已就绪" in log or "已就绪" in log, log[-160:])
    finally:
        try:
            app._cancel_timers()
            app.destroy()
        except Exception:                          # noqa: BLE001
            pass

    print("\n===== %d PASS / %d FAIL =====" % (len(PASS), len(FAIL)))
    if FAIL:
        for n in FAIL:
            print("  FAILED:", n)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
