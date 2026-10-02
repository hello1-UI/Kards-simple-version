# -*- coding: utf-8 -*-
"""自查修复回归：对局结束状态机 / 负血 / 索引边界 / 收缴阵营 / 斩杀估算

覆盖 2026-10-02 自查发现并修复的问题：
  1. damage_hq 在总部已死时不再扣血（血量下限 0）
  2. 血 <= 0 立即置 over（含"对手已死但还没轮到我结算"）
  3. end_turn 检查双方，临时增益无条件还原（不再随早退泄漏）
  4. start_turn / ai_steps 在 over 后不再推进
  5. play_card 拒绝越界与负数索引
  6. winner_of 区分 平局 / 投降 / 被打死
  7. [收缴] 不会缴获自己人
  8. incoming_damage 不把打不到总部的单位算成斩杀伤害

用法: python debug/test_bugfix2.py
"""
import io
import contextlib
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
random.seed(20261002)

import kards_engine as K  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name
          + (f"  {detail}" if detail else ""))


def new_game(n1="德国", n2="苏联"):
    db = K.card_database()
    p1 = K.Player("甲", n1, K.build_deck(n1, db))
    p2 = K.Player("乙", n2, K.build_deck(n2, db))
    return K.Game(p1, p2, interactive=False), p1, p2


def put_unit(g, p, attack=3, defense=3, position="前线", unit_type="步兵",
             keywords=None):
    card = K.UnitCard("测试兵", p.nation, 1, attack, defense,
                      list(keywords or []), unit_type=unit_type)
    u = K.Unit(card, p)
    u.attack, u.defense, u.max_defense = attack, defense, defense
    u.position = position
    u.slot = len(p.board)
    u.fresh_deploy = False
    u.can_attack = True
    p.board.append(u)
    return u


def main():
    print("\n=== 1. 总部血量下限 0 / 死后不再扣血 ===")
    g, p1, p2 = new_game()
    p1.hq = 3
    g.damage_hq(p1, 5)
    check("过量伤害后血量归 0（不为负）", p1.hq == 0, f"hq={p1.hq}")
    g.damage_hq(p1, 3)
    check("继续打已倒下的总部仍是 0", p1.hq == 0, f"hq={p1.hq}")
    check("血 <= 0 立即置 over", g.over is True)

    print("\n=== 2. end_turn 检查双方 + 临时增益不泄漏 ===")
    g, p1, p2 = new_game()
    g.current = p1
    p1.hq, p2.hq = 20, 0
    g.end_turn()
    check("对手已死时 end_turn 置 over", g.over is True)

    g, p1, p2 = new_game()
    u = put_unit(g, p1, attack=3, defense=3)
    g.current = p1
    u.attack += 3
    p1.temp_buffs.append((u, 3))     # 模拟「闪电战」
    # ats_mark 语义：标在"被监视的一方"身上（caster 的对手）。
    # end_turn 里清的是 opponent_of(current)，测试要按同一语义摆。
    p2.ats_mark = 2
    p1.hq = 20
    p2.hq = 0                        # 对手已死 → 走早退分支
    g.end_turn()
    check("早退时也还原临时攻击增益", u.attack == 3, f"attack={u.attack}")
    check("早退时也清空 temp_buffs", p1.temp_buffs == [])
    check("早退时也清 ats_mark", p2.ats_mark == 0, f"ats_mark={p2.ats_mark}")

    print("\n=== 3. over 后不再推进回合 ===")
    g, p1, p2 = new_game()
    t0 = g.turn_num
    g.over = True
    g.start_turn()
    check("over 后 start_turn 不涨回合数", g.turn_num == t0, f"{t0}->{g.turn_num}")
    check("over 后 ai_steps 不产出动作", list(g.ai_steps()) == [])

    print("\n=== 4. play_card 索引边界 ===")
    g, p1, p2 = new_game()
    while len(p1.hand) < 3:
        g.draw_cards(p1, 1)
    n0 = len(p1.hand)
    check("负索引被拒绝", g.play_card(p1, -1) is False)
    check("负索引后手牌数不变", len(p1.hand) == n0, f"{n0}->{len(p1.hand)}")
    check("越界索引被拒绝", g.play_card(p1, 9999) is False)
    check("越界后手牌数不变", len(p1.hand) == n0)
    check("非整数索引被拒绝", g.play_card(p1, "0") is False)

    print("\n=== 5. winner_of 三种结束方式 ===")
    g, p1, p2 = new_game()
    p1.hq, p2.hq = 0, 0
    check("双死 = 平局", g.winner_of() is None)

    g, p1, p2 = new_game()
    p1.hq, p2.hq = 20, 0
    check("对手死 = 我赢", g.winner_of() is p1)

    g, p1, p2 = new_game()
    p1.hq, p2.hq = 0, 20
    check("我死 = 对手赢", g.winner_of() is p2)

    g, p1, p2 = new_game()
    p1.hq, p2.hq = 8, 20
    g.conceded = p1                  # 甲投降
    check("投降 = 对手赢", g.winner_of() is p2)

    print("\n=== 6. [收缴] 不缴获自己人 ===")
    g, p1, p2 = new_game()
    killer = put_unit(g, p1, attack=5, defense=5, keywords=["收缴"])
    friend = put_unit(g, p1, attack=1, defense=1)
    h0 = len(p1.hand)
    g.damage_unit(friend, 99, source=killer)
    check("打死自己人不触发收缴", len(p1.hand) == h0, f"{h0}->{len(p1.hand)}")

    enemy = put_unit(g, p2, attack=1, defense=1)
    h1 = len(p1.hand)
    g.damage_unit(enemy, 99, source=killer)
    check("打死敌人才触发收缴", len(p1.hand) == h1 + 1,
          f"{h1}->{len(p1.hand)}")

    print("\n=== 7. incoming_damage 不虚报斩杀伤害 ===")
    g, p1, p2 = new_game()
    # 后方步兵打不到总部，不应计入斩杀伤害
    put_unit(g, p2, attack=9, defense=9, position="后方", unit_type="步兵")
    inc = g.incoming_damage(p2)
    check("打不到总部的单位不计入斩杀", inc == 0, f"incoming={inc}")

    # 前线单位能打总部 → 计入
    g, p1, p2 = new_game()
    front = put_unit(g, p2, attack=6, defense=6, position="前线", unit_type="步兵")
    inc = g.incoming_damage(p2)
    check("能打总部的单位正常计入", inc >= 6, f"incoming={inc}")

    print("\n=== 8. 批量对局：无负血 / 无状态不一致 ===")
    db = K.card_database()
    neg, mismatch = 0, 0
    for _ in range(60):
        n1, n2 = random.sample(K.MAIN_NATIONS, 2)
        a = K.Player("A", n1, K.build_deck(n1, db))
        b = K.Player("B", n2, K.build_deck(n2, db))
        gg = K.Game(a, b, interactive=False)
        for p in gg.players:
            gg.draw_cards(p, K.START_HP)
        gg.draw_cards(gg.players[1], 1)
        with contextlib.redirect_stdout(io.StringIO()):
            gg.run()
        if any(p.hq < 0 for p in gg.players):
            neg += 1
        if any(p.hq <= 0 for p in gg.players) != bool(gg.over):
            # 投降时可能双方都还活着，属正常
            if gg.conceded is None:
                mismatch += 1
    check("60 局无负血", neg == 0, f"负血局数={neg}")
    check("60 局无 over 状态不一致", mismatch == 0, f"不一致局数={mismatch}")

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
