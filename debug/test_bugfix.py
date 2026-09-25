# -*- coding: utf-8 -*-
"""bugfix 回归：动员+装甲 / 大和号持续生效 / 双倍力量复制 / log 安全"""
import io
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
random.seed(7)

import kards as K

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def make_game(n1="苏联", n2="德国", filler1="动员兵", filler2="步兵班"):
    db = K.card_database()
    p1 = K.Player("你", n1, [db[filler1]] * K.DECK_SIZE)
    p2 = K.Player("敌", n2, [db[filler2]] * K.DECK_SIZE)
    g = K.Game(p1, p2, interactive=False)
    g.draw_cards(p1, 8)
    g.draw_cards(p2, 8)
    return g, p1, p2


def deploy(g, p, card, pos="后方", slot=None):
    u = g.deploy_unit(p, card)
    u.position = pos
    if slot is not None:
        u.slot = slot
    return u


def hand_idx(p, name):
    return next((i for i, c in enumerate(p.hand) if c.name == name), None)


def main():
    db = K.card_database()
    print("== 1. 动员+装甲：伤害被装甲完全抵消时加成保留 ==")
    g, p1, p2 = make_game()
    mob = deploy(g, p1, db["殖民步兵"])   # 1/1 闪击 动员（在 p1 场上，回合开始吃动员）
    mob.keywords.append("装甲")
    g.start_turn()
    check("动员+1/+1", mob.mob == 1 and mob.attack == 2 and mob.defense == 2,
          f"a={mob.attack} d={mob.defense} mob={mob.mob}")
    g.damage_unit(mob, 1, combat=True)
    check("装甲抵消1伤 动员保留", mob.mob == 1 and mob.defense == 2 and mob in p1.board,
          f"d={mob.defense} mob={mob.mob}")
    # 垫高防御避免死亡，再吃 2 点战斗伤害（实伤 1）
    mob.defense = 10
    mob.max_defense = 10
    g.damage_unit(mob, 2, combat=True)
    check("实伤1 动员移除", mob.mob == 0 and mob.attack == 1 and mob.defense == 8 and mob in p1.board,
          f"a={mob.attack} d={mob.defense} mob={mob.mob}")

    print("== 1b. 装甲3：战斗伤害减 3，效果伤害不减 ==")
    g1b, u1, v1 = make_game()
    heavy = deploy(g1b, v1, db["虎式坦克"])
    heavy.keywords = ["装甲3"]
    g1b.damage_unit(heavy, 5, combat=True)      # 5-3=2 实伤
    check("装甲3战斗伤害-3", heavy.defense == 6 and heavy in v1.board,
          f"d={heavy.defense}")
    g1b.damage_unit(heavy, 3)                   # 效果伤害 3 全额
    check("装甲3不减效果伤害", heavy.defense == 3, f"d={heavy.defense}")

    print("== 2. 大和号：之后部署的日军单位也获得亡计 ==")
    g2, q1, q2 = make_game("日本", "美国", filler2="步兵班")
    old = deploy(g2, q1, db["零式战斗机"])
    q1.kredits = 12
    yamato = db["大和号战列舰"]
    assert yamato.kind == "order"
    q1.hand.append(yamato)
    g2.play_card(q1, len(q1.hand) - 1)
    check("场上日军获得亡计", old.dying_hq == 2, f"dying_hq={old.dying_hq}")
    new = deploy(g2, q1, db["零式战斗机"])
    check("之后部署的日军不获得亡计", new.dying_hq == 0, f"dying_hq={new.dying_hq}")
    hq0 = q2.hq
    g2.destroy_unit(old)
    check("场上单位亡计结算 2 伤", q2.hq == hq0 - 2, f"{hq0}->{q2.hq}")

    print("== 3. 双倍力量：复制为独立对象 ==")
    g3, r1, r2 = make_game("英国", "苏联", filler1="步兵班", filler2="动员兵")
    ds = db["总动员"]
    other = db["皇家海军炮击"]
    r1.kredits = 12
    r1.hand.append(other)      # 手中需有另一张指令可供复制
    r1.hand.append(ds)
    g3.play_card(r1, len(r1.hand) - 1)
    deck_orders = [c for c in r1.deck if c.kind == "order"]
    check("复制洗入卡组", len(deck_orders) == 1, f"n={len(deck_orders)}")
    check("复制是独立对象", bool(deck_orders)
          and deck_orders[0] is not ds and deck_orders[0] is not other)

    print("== 4. log 安全：stdout 失效不崩溃 ==")
    g4, s1, s2 = make_game()
    real_stdout = sys.stdout
    ok = True
    detail = ""
    try:
        sys.stdout = None
        g4.log("  测试消息")
    except Exception as e:
        ok = False
        detail = repr(e)
    finally:
        sys.stdout = real_stdout
    check("stdout=None 时 log 不崩溃", ok, detail)

    print(f"\n== 结果: {len(PASS)} 通过 / {len(FAIL)} 失败 ==")
    if FAIL:
        print("失败项:", "; ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
