# -*- coding: utf-8 -*-
"""联机「准备→开局」回归测试（真 bug：准备阶段 ready/seed 被兜底消费吞掉）

历史现象：双方都点了准备，却永远卡在「等待对手准备」。
根因：`_lobby_drain_events()` 把 inbox 全喂给 `_lobby_handle_event()`
→ `_mp_route_in_game()`，后者只看 `self.game is not None`，
准备阶段（还没开局）的 ready/seed 被静默丢弃 → 主机学不到对手已准备，
自然永远不发 seed。

覆盖：
  1. 准备阶段收到 ready → mp_opp 落地（不再被吞）
  2. 主机收到对手 ready → 发 seed + 立即开局
  3. 客户端收到 seed → 按同一种子开局
  4. 准备阶段对手离开 → 提示并回菜单（不再无限等待）

必须用系统 Python（受管 Python 无 tkinter）：
    py debug/test_mp_ready.py
"""
import os
import queue
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv.append("--no-fullscreen")
sys.argv.append("--no-update-check")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import KARDS as gui                           # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


class FakeLink:
    """够用的假链路：inbox 队列 + send 记录"""

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


def make_app():
    app = gui.App()
    app.mp_link = FakeLink()
    app.mp_role = "host"
    app.mp_opp = None
    app.mp_opp_name = None
    launched = []
    app._mp_launch = lambda seed: launched.append(seed)   # 不真开棋盘
    return app, app.mp_link, launched


def main():
    print("== 联机准备阶段路由回归 ==")

    print("-- 1. 准备阶段收到 ready 不再被吞 --")
    app, link, launched = make_app()
    link.inbox.put({"m": "ready", "nation": "苏联", "deck": ["步兵班"] * 39})
    app._lobby_drain_events()
    check("drain 后 mp_opp 已落地", app.mp_opp is not None, str(app.mp_opp))
    check("drain 不会误开局", not launched, str(launched))
    app.destroy()

    print("-- 2. 主机收到对手 ready → 发 seed 并开局 --")
    app, link, launched = make_app()
    link.inbox.put({"m": "ready", "nation": "苏联", "deck": ["步兵班"] * 39})
    app._mp_poll_hello()
    seeds = [m["seed"] for m in link.sent if m.get("m") == "seed"]
    check("主机发出了 seed", len(seeds) == 1, str(link.sent))
    check("开局用的就是发出的 seed", launched and launched[0] == seeds[0],
          f"{launched} vs {seeds}")
    app.destroy()

    print("-- 3. 客户端收到 seed → 同种子开局 --")
    app, link, launched = make_app()
    app.mp_role = "client"
    link.inbox.put({"m": "seed", "seed": 20261110})
    app._lobby_drain_events()
    check("客户端按收到的 seed 开局", launched == [20261110], str(launched))
    app.destroy()

    print("-- 4. 准备阶段对手离开 → 提示并回菜单 --")
    app, link, launched = make_app()
    back = []
    app._mp_cleanup_to_menu = lambda: back.append(1)
    orig_error = gui.messagebox.showerror
    gui.messagebox.showerror = lambda *a, **k: None      # 不要弹窗阻塞
    try:
        link.inbox.put({"m": "peer_left"})
        app._lobby_drain_events()
    finally:
        gui.messagebox.showerror = orig_error
    check("对手离开后回菜单", back == [1], str(back))
    check("对手离开不会开局", not launched, str(launched))
    app.destroy()

    print(f"\n结果: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        for f in FAIL:
            print("  !!", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
