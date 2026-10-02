# -*- coding: utf-8 -*-
"""AI 自动投降测试

验证：
  1. 濒死（血低 + 对方场攻足以斩杀）→ AI 投降
  2. 全面劣势（强度差距大 + 无可用手牌 + 牌库见底）→ AI 投降
  3. 势均力敌 / 有机会翻盘 → 不投降（不能投降太早，否则游戏变得莫名其妙）
  4. ai_steps() 会 yield concede 事件，并置 g.over
  5. 关闭开关后一律不投降

用法: python debug/test_concede.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import kards_engine as core  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


def make_game(db=None):
    """造一局空的双方对局（不抽牌，便于精确摆场面）"""
    db = db if db is not None else core.card_database()
    n1, n2 = core.MAIN_NATIONS[0], core.MAIN_NATIONS[1]
    p1 = core.Player("AI-红军", n1, core.build_deck(n1, db))
    p2 = core.Player("AI-蓝军", n2, core.build_deck(n2, db))
    return core.Game(p1, p2, interactive=False), p1, p2


def put_unit(g, p, name=None, attack=3, defense=3, position="前线",
             unit_type="步兵"):
    """往场上塞一个指定数值的单位（不走部署流程，直接构造）"""
    db = core.card_database()
    card = None
    if name:
        card = next((c for c in db.values() if c.name == name), None)
    if card is None:
        card = core.UnitCard(name or "测试兵", p.nation, 1, attack, defense,
                             [], unit_type=unit_type)
    u = core.Unit(card, p)
    u.attack, u.defense, u.max_defense = attack, defense, defense
    u.position = position
    u.slot = len(p.board)
    u.fresh_deploy = False
    u.can_attack = True
    p.board.append(u)
    return u


def main():
    print("\n=== 1. 濒死 → 投降 ===")
    # 濒死投降的前提是"这回合就要被打死"：血少 + 对方场攻够 + 手里没救命的牌
    g, p1, p2 = make_game()
    g.current = p2                       # 轮到"蓝军"（AI）
    p2.hq = 3                            # 蓝军残血
    p1.hq = 20
    for i in range(3):                   # 红军三个 5 攻前线单位
        put_unit(g, p1, attack=5, defense=4, position="前线")
    p2.hand, p2.deck = [], []            # 弹尽粮绝
    check("濒死（无牌可出）判定为应投降", g.ai_should_concede(p2) is True,
          f"incoming={g.incoming_damage(p1):.1f} hq={p2.hq}")

    # 反例：同样濒死，但手里有能打出的牌 → 再撑一回合（补刀也可能翻盘）
    g, p1, p2 = make_game()
    g.current = p2
    p2.hq, p1.hq = 3, 20
    for i in range(3):
        put_unit(g, p1, attack=5, defense=4, position="前线")
    p2.hand = [c for c in core.card_database().values()][:5]
    p2.kredits = 12
    check("濒死但手里有可打出的牌 → 不投降（先搏一次）",
          g.ai_should_concede(p2) is False,
          f"incoming={g.incoming_damage(p1):.0f} hq={p2.hq} "
          f"可用手牌={len(g.playable_cards(p2))}")

    # 濒死 + 无牌 + 必被斩杀 → 投
    g, p1, p2 = make_game()
    g.current = p2
    p2.hq, p1.hq = 3, 20
    for i in range(3):
        put_unit(g, p1, attack=5, defense=4, position="前线")
    p2.hand, p2.deck = [], []
    check("濒死且必被斩杀 + 无牌可出 → 投降",
          g.ai_should_concede(p2) is True,
          f"incoming={g.incoming_damage(p1):.0f} hq={p2.hq}")

    # 反例：残血但对方场攻打不死，手里还有牌 → 必须继续打
    g, p1, p2 = make_game()
    g.current = p2
    p2.hq, p1.hq = 4, 20
    put_unit(g, p1, attack=2, defense=4, position="前线")
    p2.hand = [c for c in core.card_database().values()][:5]
    p2.kredits = 12
    check("残血但打不死 + 有牌可出 → 不投降",
          g.ai_should_concede(p2) is False,
          f"incoming={g.incoming_damage(p1):.0f} hq={p2.hq} "
          f"可用手牌={len(g.playable_cards(p2))}")

    print("\n=== 2. 全面劣势 → 投降 ===")
    g, p1, p2 = make_game()
    g.current = p2
    p2.hq, p1.hq = 8, 20                 # 血线已低（<= AI_CONCEDE_HP2）
    for i in range(5):                   # 红军 5 个强力单位，蓝军空场
        put_unit(g, p1, attack=6, defense=6, position="前线")
    p2.hand, p2.deck = [], []            # 无手牌、牌库见底
    my, his = g.ai_power(p2), g.ai_power(p1)
    check("强度差距确实很大", his >= my * core.AI_CONCEDE_RATIO,
          f"{my:.1f} vs {his:.1f}")
    check("全面劣势判定为应投降", g.ai_should_concede(p2) is True)

    print("\n=== 3. 势均力敌 / 还有机会 → 不投降（关键：不能投降太早）===")
    g, p1, p2 = make_game()
    g.current = p2
    p2.hq = p1.hq = 20
    for i in range(3):
        put_unit(g, p1, attack=3, defense=3, position="前线")
        put_unit(g, p2, attack=3, defense=3, position="前线")
    check("势均力敌不投降", g.ai_should_concede(p2) is False,
          f"{g.ai_power(p2):.1f} vs {g.ai_power(p1):.1f}")

    g, p1, p2 = make_game()
    g.current = p2
    p2.hq, p1.hq = 20, 20                # 血量还很健康，只是场面吃亏
    for i in range(5):
        put_unit(g, p1, attack=6, defense=6, position="前线")
    p2.deck = list(range(30))
    p2.hand = [c for c in core.card_database().values()][:5]
    p2.kredits = 12
    check("劣势但有可打出的牌 → 不投降",
          g.ai_should_concede(p2) is False,
          f"可用手牌={len(g.playable_cards(p2))} "
          f"power {g.ai_power(p2):.0f} vs {g.ai_power(p1):.0f}")

    g, p1, p2 = make_game()
    g.current = p2
    p2.hq, p1.hq = 5, 20                 # 5 血，对方只有 1 个 3 攻单位 → 打不死
    put_unit(g, p1, attack=3, defense=3, position="前线")
    check("残血但对方场攻打不死 → 不投降", g.ai_should_concede(p2) is False,
          f"incoming={g.incoming_damage(p1):.1f}")

    # 关键：手里攒着一次攻击机会时不许投降（否则看起来像 AI 摆烂）
    g, p1, p2 = make_game()
    g.current = p2
    p2.hq, p1.hq = 6, 20
    u = put_unit(g, p2, attack=4, defense=4, position="前线")
    u.fresh_deploy = False
    u.can_attack = True
    for i in range(5):
        put_unit(g, p1, attack=6, defense=6, position="前线")
    p2.hand, p2.deck = [], []
    check("本回合还有单位能出手 → 先打完再谈投降",
          g.ai_should_concede(p2) is False,
          f"ready 单位可攻击={bool(g.attack_targets(u))}")

    print("\n=== 4. ai_steps 会 yield concede 并置 over ===")
    g, p1, p2 = make_game()
    g.current = p2
    p2.hq = 2
    p1.hq = 20
    for i in range(3):
        put_unit(g, p1, attack=5, defense=5, position="前线")
    p2.hand, p2.deck = [], []            # 无资源，符合濒死投降条件
    steps = list(g.ai_steps())
    types = [s.get("type") for s in steps]
    check("产出 concede 事件", "concede" in types, str(types))
    check("concede 是唯一的动作", types == ["concede"], str(types))
    check("对局被标记结束", g.over is True)
    ev = steps[0]
    check("事件带投降方", ev.get("player") is p2)
    check("事件带理由文本", bool(ev.get("reason")), str(ev.get("reason")))

    print("\n=== 5. 开关可关闭 ===")
    old = core.AI_AUTO_CONCEDE
    try:
        core.AI_AUTO_CONCEDE = False
        g, p1, p2 = make_game()
        g.current = p2
        p2.hq = 1
        for i in range(4):
            put_unit(g, p1, attack=9, defense=9, position="前线")
        check("关掉开关后不投降（绝对劣势也不投）",
              g.ai_should_concede(p2) is False)
    finally:
        core.AI_AUTO_CONCEDE = old
    check("开关已还原", core.AI_AUTO_CONCEDE is old)

    print("\n=== 6. 判定与身份无关（GUI 只对 AI 调用，玩家不自动投降）===")
    g, p1, p2 = make_game()
    g.current = p1
    p1.hq = 1
    for i in range(4):
        put_unit(g, p2, attack=9, defense=9, position="前线")
    p1.hand, p1.deck = [], []
    check("劣势方（无论谁是玩家）判定为 True",
          g.ai_should_concede(p1) is True,
          "（GUI 仅在 AI 回合调用该函数，玩家永远需手动投降）")
    check("优势方判定为 False", g.ai_should_concede(p2) is False)

    print("\n=== 7. 各国总部血量统一为 20 ===")
    hps = {n: c.hp for n, c in core.HQ_CARDS.items()}
    check("所有国家总部血量相同", len(set(hps.values())) == 1, str(hps))
    check("总部血量等于 HQ_HP (=20)", set(hps.values()) == {core.HQ_HP},
          f"HQ_HP={core.HQ_HP} 实配={sorted(set(hps.values()))}")
    check("每国都是 20", all(v == 20 for v in hps.values()), str(hps))
    # 各国仍有各自的研发被动，靠被动区分特色而不是血量
    perks = {n: c.perk for n, c in core.HQ_CARDS.items()}
    check("各国研发被动不重复", len(set(perks.values())) == len(perks),
          str(perks))
    # 建局后总部血应为 20（而不是通过 HQ_CARDS 以外的路径赋值）
    g, p1, p2 = make_game()
    check("建局后双方总部血量都是 20", p1.hq == 20 and p2.hq == 20,
          f"{p1.hq}/{p2.hq}")

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
