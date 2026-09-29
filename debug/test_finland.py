# -*- coding: utf-8 -*-
"""芬兰卡 + 行动费机制测试

运行: python debug/test_finland.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kards as core

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail else ""))


db = core.card_database()
check("卡池含4张芬兰卡",
      sum(1 for c in db.values() if c.nation == "芬兰") == 4,
      str([c.name for c in db.values() if c.nation == "芬兰"]))


def new_game():
    """构造固定牌局：我方德国 vs 敌方苏联，空牌库避免随机性"""
    p1 = core.Player("你", "德国", [])
    p2 = core.Player("AI", "苏联", [])
    g = core.Game(p1, p2, interactive=False)
    g.players[0].kredits = 0
    return g


# ---- 行动费: unit_ready 与支付 ----
g = new_game()
me = g.players[0]
me.kredits = 2
card = db["第1战斗群"]          # 2费 行动费2
check("第1战斗群 行动费=2", card.operate == 2)
u = core.Unit(card, me)
u.can_attack = True
me.board.append(u)
check("Kredits 2 < 行动费 2? 相等可攻击", g.unit_ready(u))
me.kredits = 1
check("Kredits 1 不足行动费 2 → 不可攻击", not g.unit_ready(u))

me.kredits = 10
foe = g.players[1]
t = core.Unit(db["步兵班"], foe)
t.can_attack = False
foe.board.append(t)
g.do_attack(u, t)
check("攻击后扣除行动费(10-2=8)", me.kredits == 8, f"kr={me.kredits}")

# ---- 第13步兵团: 部署时每有1个敌方单位 +1/+1 ----
g = new_game()
me, foe = g.players[0], g.players[1]
for i in range(3):
    e = core.Unit(db["步兵班"], foe)
    foe.board.append(e)
c13 = db["第13步兵团"]
check("第13步兵团 行动费=1", c13.operate == 1)
u13 = core.Unit(c13, me)
me.board.append(u13)
g.on_deploy(u13)
check("3个敌方单位 → 2+3/4+3 = 5/7",
      u13.attack == 5 and u13.defense == 7,
      f"{u13.attack}/{u13.defense}")

# ---- 洛塔组织: 全体 +1 防御 ----
g = new_game()
me = g.players[0]
a = core.Unit(db["步兵班"], me)
b = core.Unit(db["步兵班"], me)
me.board += [a, b]
d0 = a.defense
db["洛塔组织"].effect(g, me)
check("洛塔组织: 两个单位各 +1 防御",
      a.defense == d0 + 1 and b.defense == d0 + 1,
      f"{a.defense},{b.defense}")

# ---- 西苏精神: 总部受伤转嫁 ----
g = new_game()
me, foe = g.players[0], g.players[1]
me.hq = 25
foe.hq = 27
sisu = db["西苏精神"]
me.counters.append(sisu)
g.damage_hq(me, 5)
check("西苏精神触发: 我方总部不掉血", me.hq == 25, f"hq={me.hq}")
check("敌方总部承受 27-5=22", foe.hq == 22, f"hq={foe.hq}")
check("反制消耗后不再转嫁", len(me.counters) == 0)
g.damage_hq(me, 3)
check("消耗后我方总部正常掉血 25-3=22", me.hq == 22, f"hq={me.hq}")

# ---- 第1战斗群 anti_strong: 对攻击力更高单位 +2 ----
g = new_game()
me, foe = g.players[0], g.players[1]
s = core.Unit(db["第1战斗群"], me)
big = core.Unit(db["虎式坦克"], foe)   # 8攻 > 1攻
me.board.append(s)
foe.board.append(big)
dmg = g.combat_damage(s, big)
check("对更强敌人伤害 1+2=3", dmg == 3, f"dmg={dmg}")
dmg2 = g.combat_damage(big, s)
check("虎式(更强方)不触发", dmg2 == 8, f"dmg={dmg2}")

fails = [r for r in results if not r[1]]
print(f"\n=== 结果: {len(results) - len(fails)} 通过 / {len(fails)} 失败 ===")
sys.exit(1 if fails else 0)
