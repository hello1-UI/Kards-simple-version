# -*- coding: utf-8 -*-
"""联机模块压力测试：host/client 两个进程各跑一个真实 GUI，自动对打若干回合，
最后各自打印局面快照，由父进程比对是否完全同步。

用法: python test_mp.py host   /   python test_mp.py client
"""
import sys
import time
import random
import traceback

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROLE = sys.argv[1] if len(sys.argv) > 1 else "host"
sys.argv = ["kards_gui.py"]

import kards_engine as core
import KARDS

# 屏蔽所有弹窗（测试环境无人点击）
kards_gui.messagebox.showinfo = lambda *a, **k: None
kards_gui.messagebox.showwarning = lambda *a, **k: None
kards_gui.messagebox.showerror = lambda *a, **k: print("[MSG-ERROR]", a[0] if a else a)

PORT = 5577
DEADLINE = 40.0


def do_one_action(app, rng):
    """替身玩家：按出牌→机动→攻击→结束回合的顺序做一件合法的事。
    注意：必须用独立 RNG，绝不碰全局 random（游戏效果的随机数需要双方严格同步）。"""
    g = app.game
    me = g.players[0]
    # 1) 出牌（单位优先，其次指令/反制）
    for i, c in enumerate(me.hand):
        if c.kind == "unit" and g.get_cost(c, me) <= me.kredits and g.can_deploy(me):
            if g.play_card(me, i):
                app._mp_send_act({"k": "play", "i": i})
                return
    for i, c in enumerate(me.hand):
        if c.kind in ("order", "counter") and g.get_cost(c, me) <= me.kredits:
            if c.kind == "counter" and len(me.counters) >= core.COUNTER_SLOTS:
                continue
            if g.play_card(me, i):
                app._mp_send_act({"k": "play", "i": i})
                return
    # 2) 机动上前线
    for u in me.board:
        if not u.moved and u.position != "前线" and g.can_take_frontline(me):
            if g.move_unit(u, "前线"):
                app._mp_send_act({"k": "move", "s": u.slot, "p": "前线"})
                return
    # 3) 攻击
    for u in me.board:
        if u.can_attack and u.attacks_made < 1 and u.defense > 0:
            targets = g.attack_targets(u)
            if targets:
                t = rng.choice(targets)
                g.do_attack(u, t)
                app._mp_send_act({"k": "attack", "s": u.slot, "t": t.slot})
                return
            ok, _ = g.can_hit_hq(u)
            if ok:
                g.do_hq_attack(u)
                app._mp_send_act({"k": "hq", "s": u.slot})
                return
    # 4) 结束回合（走生产路径，验证 on_end_turn 的联机分支）
    app.on_end_turn()


def snapshot(app):
    g = app.game
    if g is None or g.over:
        return "GAME-OVER"

    def pl(p):
        return (p.hq, p.kredits, p.fatigue, len(p.deck), len(p.counters),
                len(p.hand), tuple(c.name for c in p.hand),
                tuple(sorted((u.slot, u.name, u.position, u.attack, u.defense)
                             for u in p.board)))
    return repr((g.turn_num, g.over, pl(g.players[0]), pl(g.players[1])))


def main():
    rng = random.Random(987654)
    app = kards_gui.App()
    app.anim_enabled = False
    app.update()

    # 记录胜者在本方视角的阵营（me/opponent）+ 是否真实终局，父进程比对
    winner_side = []
    orig_finish = app.finish

    def finish_recorder(winner=None):
        if app.game is not None:
            real = winner is None
            if winner is None:
                winner = (app.game.players[0] if app.game.players[1].hq <= 0
                          else app.game.players[1])
            winner_side.append(("me" if winner is app.game.players[0] else "opponent", real))
        return orig_finish(winner)
    app.finish = finish_recorder

    app.on_battle()                      # → 联机大厅
    app.update()

    if ROLE == "host":
        app.host_port_var.set(str(PORT))
        app._mp_begin_host()
    else:
        time.sleep(1.5)                  # 等主机先监听
        app.join_ip_var.set("127.0.0.1")
        app.join_port_var.set(str(PORT))
        app._mp_begin_join()

    # 等待连接建立（_lobby_poll 会自动进入选阵营界面）
    t0 = time.time()
    while app.mp_link is None:
        app.update()
        time.sleep(0.02)
        if time.time() - t0 > 15:
            raise RuntimeError("连接超时")
    t0 = time.time()
    while time.time() - t0 < 1.0:        # 等 _build_nation_select 被 after 调度
        app.update()
        time.sleep(0.02)

    nation = "德国"
    app._build_deck_builder(nation, mp=True)
    deck = core.build_deck(nation, app.db)
    app.deck_counts = {}
    for c in deck:
        app.deck_counts[c.name] = app.deck_counts.get(c.name, 0) + 1
    app._start_mp()

    # 等待开局
    t0 = time.time()
    while app.game is None:
        app.update()
        time.sleep(0.02)
        if time.time() - t0 > 15:
            raise RuntimeError("开局超时")
    print(f"[{ROLE}] 开局成功，先手判定完毕")

    # 自动对打
    t0 = time.time()
    next_act = 0.0
    actions = 0
    while time.time() - t0 < DEADLINE:
        app.update()
        time.sleep(0.01)
        if app.game is None:
            break
        g = app.game
        if (g.current is g.players[0] and not app.busy
                and time.time() >= next_act):
            do_one_action(app, rng)
            actions += 1
            next_act = time.time() + 0.08
    # 等最后的状态同步稳定
    t0 = time.time()
    while time.time() - t0 < 1.0 and app.game is not None:
        app.update()
        time.sleep(0.02)
    # 结算动画：等「点击回大厅」提示出现后模拟点击
    t0 = time.time()
    while time.time() - t0 < 10 and not getattr(app, "_end_click_ready", False):
        app.update()
        time.sleep(0.02)
    if getattr(app, "_end_click_ready", False):
        app.event_generate("<Button-1>", when="now")
        t0 = time.time()
        while time.time() - t0 < 3 and app.game is not None:
            app.update()
            time.sleep(0.02)

    print(f"[{ROLE}] 对打结束，共执行 {actions} 个行动")
    for side, real in winner_side:
        print(f"WINNER[{ROLE}]={side} real={real}")
    print(f"SNAPSHOT[{ROLE}]={snapshot(app)}")
    try:
        app.destroy()
    except Exception:
        pass
    print(f"TEST[{ROLE}] OK")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
