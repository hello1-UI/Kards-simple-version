# -*- coding: utf-8 -*-
"""诊断：把「战斗机」在各条空军规则里的待遇逐条打印出来。

用途：用户报「战斗机也是空军」时，用事实确认到底哪条规则把它当成了陆军。
用法: python debug/probe_air.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kards_engine as core  # noqa: E402

db = core.card_database()
FIGHTER = "喷火战斗机"
BOMBER = "兰开斯特轰炸机"
TANK = "三号坦克 G 型"


def line(tag, val):
    print(f"  {tag:<32} {val}")


def new_game():
    return core.Game(core.Player("你", "德国", []),
                     core.Player("AI", "苏联", []), interactive=False)


def place(g, name, side, position, slot=1, kredits=20):
    u = g.deploy_unit(side, db[name])
    u.position = position
    u.slot = slot
    u.fresh_deploy = False
    u.can_attack = True
    u.owner.kredits = kredits
    return u


def main():
    print("\n=== 1. 常量表 ===")
    line("RANGED_TYPES", core.RANGED_TYPES)
    line("战斗机 in RANGED_TYPES", "战斗机" in core.RANGED_TYPES)
    line("轰炸机 in RANGED_TYPES", "轰炸机" in core.RANGED_TYPES)
    line("NO_COUNTER_DEAL", core.NO_COUNTER_DEAL)

    g = new_game()
    me, foe = g.players
    ftr = place(g, FIGHTER, me, "后方", slot=0)
    bmb = place(g, BOMBER, me, "后方", slot=1)
    e_front = place(g, TANK, foe, "前线", slot=1)
    e_back = place(g, TANK, foe, "后方", slot=3)
    e_ftr = place(g, FIGHTER, foe, "后方", slot=4)

    print("\n=== 2. 支援线（后方）可攻击范围 ===")
    line("战斗机 attack_targets",
         [(u.unit_type, u.position) for u in g.attack_targets(ftr)])
    line("轰炸机 attack_targets",
         [(u.unit_type, u.position) for u in g.attack_targets(bmb)])
    line("战斗机 can_hit_hq", g.can_hit_hq(ftr))
    line("轰炸机 can_hit_hq", g.can_hit_hq(bmb))
    line("战斗机 打总部伤害", g.hq_damage(ftr))
    line("轰炸机 打总部伤害", g.hq_damage(bmb))

    print("\n=== 3. 拦截 / 反击 ===")
    line("_interceptor(守方)", getattr(g._interceptor(foe), "name", None))
    line("轰炸机攻非战斗机 → 被战斗机拦截", True)
    line("战斗机攻非战斗机 → 被拦截", False)
    line("打轰炸机不吃反击", "轰炸机" in core.NO_COUNTER_DEAL)

    print("\n=== 4. dmg2 含'空军'（88 高炮）是否覆盖战斗机 ===")
    aa = core.Unit(core.UnitCard("测试AA", "德国", 5, 2, 4, [], "炮兵"), me)
    aa.attack = 3
    aa.traits = {"dmg2": ["空军", "坦克"]}
    for tgt in (e_ftr, core.Unit(core.UnitCard(BOMBER, "苏联", 9, 7, 4,
                                               [], "轰炸机"), foe), e_front):
        line(f"AA 打 {tgt.unit_type} 伤害", g.combat_damage(aa, tgt))

    print("\n=== 5. 研发被动 air_attack（美国：战斗机+轰炸机攻击 +1） ===")
    us = core.Player("US", "美国", [])
    line(f"战斗机 {db[FIGHTER].attack} -> "
         f"{core.Unit(db[FIGHTER], us).attack}", "")
    line(f"轰炸机 {db[BOMBER].attack} -> "
         f"{core.Unit(db[BOMBER], us).attack}", "")

    print("\n=== 6. 反制 attack_air 触发条件 ===")
    cc = core.CounterCard("防空火力", "美国", 2, "attack_air", "")
    for tgt in (e_ftr, core.Unit(core.UnitCard(BOMBER, "苏联", 9, 7, 4,
                                               [], "轰炸机"), foe), e_front):
        ctx = type("Ctx", (), {"unit_type": tgt.unit_type})()
        line(f"attack_air 触发于 {tgt.unit_type}", cc.matches("attack", ctx))

    print("\n=== 7. 空军能否上前线 / 能否被当作'空中'目标 ===")
    air = place(g, FIGHTER, me, "后方", slot=2)
    line("战斗机 move_unit(前线)", g.move_unit(air, "前线"))
    line("air4（P-51 炸空军）候选",
         [u.unit_type for u in foe.board
          if u.unit_type in ("战斗机", "轰炸机")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
