# -*- coding: utf-8 -*-
"""德意志步兵（《卡牌效果》文档对齐）专项测试

覆盖：中立衍生牌（生产/爆破/计划）、行动费（operate）、
老兵（vet_when 三种触发）、山地（mtn_grow 双词条语义）、
烟幕（不可被攻击 + 行动后失去）、击杀得 Kredits（kill_kredits，
第158 在**击杀方**场上生效）、回合开始得 Kredits（turn_kredits）、
钳击成长（pincer_grow）、生产入手（production_to_hand）。

运行: python debug/test_german_inf.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kards_engine as core

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f" ({detail})" if detail else ""))


def eq(name, got, want):
    ok = got == want
    check(name, ok, "" if ok else f"{got!r} != {want!r}")


db = core.card_database()
INF_2_2 = core.UnitCard("测试步兵", "德国", 2, 2, 2, [], "步兵", operate=0)


def new_game():
    deck = [INF_2_2] * core.DECK_SIZE
    p1 = core.Player("你", "德国", list(deck))
    p2 = core.Player("AI", "苏联", list(deck))
    return core.Game(p1, p2, interactive=False)


def place(g, card, side, position, slot=1, kredits=10):
    """部署并摆位：card 可传卡名（查池）或模板卡对象"""
    c = card if isinstance(card, core.UnitCard) else db[card]
    u = g.deploy_unit(side, c)
    u.position = position
    u.slot = slot
    u.fresh_deploy = False
    u.can_attack = True
    u.owner.kredits = kredits
    return u


def play_order(g, p, card):
    """把手牌设为指定指令并打出（绕过抽牌流程）"""
    p.hand[:] = [card]
    return g.play_card(p, 0)


# ---- 1. 文档收录与中立过滤 ----
print("== 1. 卡池收录 ==")
norm = lambda s: re.sub(r"\s+", "", s)
DOC = ["第一步兵团", "第102掷弹兵团", "第158补给营", "第18步兵团", "第28猎兵团",
       "第30步兵团", "第4先锋营", "第432步兵团", "第56猎兵团", "第738猎兵团",
       "第95山地工兵营", "卡茨曼团", "山地人营", "第104装甲掷弹兵团",
       "第1097国民掷弹兵团", "第141山地猎兵团", "第15侦察营", "第22步兵团",
       "第27燧发枪兵团", "第3空降猎兵团", "第36摩托化步兵营", "第50步兵团",
       "第59装甲掷弹兵团", "第62步兵团", "第64装甲掷弹兵团", "第74装甲掷弹兵团",
       "第8空降猎兵团", "第87掷弹兵团", "第957国民掷弹兵团", "第96步兵团",
       "库尔马克侦察营", "第101步兵团", "第13山地猎兵团", "第136山地猎兵团",
       "第14装甲掷弹兵团", "第3装甲掷弹兵团", "第304装甲掷弹兵团",
       "第33装甲掷弹兵团", "第342燧发枪兵营", "第361非洲兵团", "第39装甲掷弹兵团",
       "第4空降猎兵团", "第5装甲掷弹兵团", "第980国民掷弹兵团", "第989步兵团",
       "统帅堂装甲掷弹兵师", "蓝色军团", "溃军", "生产", "爆破", "计划"]
names = {norm(c.name) for c in db.values()}
miss = [n for n in DOC if norm(n) not in names]
eq("文档 51 张全部收录", miss, [])
neu = [c for c in db.values() if c.nation == "中立"]
eq("中立衍生牌 4 张", sorted(c.name for c in neu),
   sorted(["溃军", "生产", "爆破", "计划"]))
ok = core.allowed_cards("德国", db)
check("中立牌不进德国卡组", all(c.nation != "中立" for c in ok))

# ---- 2. 中立指令 ----
print("== 2. 中立指令 ==")
g = new_game()
me, foe = g.players
me.kredits = 5
play_order(g, me, db["生产"])
eq("生产: +1 Kredits", me.kredits, 6)

t = place(g, INF_2_2, foe, "前线", slot=1, kredits=5)
t2 = place(g, INF_2_2, foe, "前线", slot=2)
t.defense = 3
t2.defense = 5
play_order(g, me, db["爆破"])
eq("爆破: 打最弱的目标", t.defense, 2)

n0 = len(me.hand)
play_order(g, me, db["计划"])
eq("计划: 抽一张牌", len(me.hand) - n0, 1)

# ---- 3. 行动费 operate ----
print("== 3. 行动费 ==")
g = new_game()
me, foe = g.players
a = place(g, "第102掷弹兵团", me, "后方", kredits=0)   # operate=1
check("行动费不足无法移动", g.move_unit(a, "前线") is False and me.kredits == 0)
me.kredits = 3
check("移动扣行动费", g.move_unit(a, "前线") and me.kredits == 2)

b = place(g, INF_2_2, foe, "前线", slot=1, kredits=5)
me.kredits = 5
b.defense = 1
g.do_attack(a, b)
check("攻击扣行动费", me.kredits == 4, f"kredits={me.kredits}")
check("目标被击杀", b.defense <= 0)

# ---- 4. 老兵 ----
print("== 4. 老兵 ==")
g = new_game()
me, foe = g.players
v = place(g, "第102掷弹兵团", me, "后方", kredits=9)   # vet_when=acted
g.move_unit(v, "前线")
eq("第102: 行动后升老兵(攻)", v.attack, 2)
eq("第102: 行动后升老兵(防)", v.defense, 3)
check("第102: 获得冲击", v.has("冲击"))

w = place(g, "第50步兵团", me, "后方", slot=2)         # vet_when=front_move
g.move_unit(w, "前线")
eq("第50: 上前线升老兵(攻)", w.attack, 4)
eq("第50: 上前线升老兵(防)", w.defense, 3)
check("第50: 获得伏击", w.has("伏击"))

g2 = new_game()
me2, _ = g2.players
q = place(g2, "第64装甲掷弹兵团", me2, "后方", slot=1)  # vet_when=turn_start_front
g2.move_unit(q, "前线")
g2.end_turn(); g2.start_turn()          # 对手的回合开始：不结算我方
g2.end_turn(); g2.start_turn()          # 我方的回合开始：升级
eq("第64: 我方回合开始在前线升老兵(攻)", q.attack, 3)
eq("第64: 我方回合开始在前线升老兵(防)", q.defense, 3)

# ---- 5. 山地 ----
print("== 5. 山地 ==")
g = new_game()
me, foe = g.players
m1 = place(g, "第13山地猎兵团", me, "后方", slot=1)    # mtn_grow（自身成长词条）
m2 = place(g, "第136山地猎兵团", me, "后方", slot=2)   # 普通山地 4/3
eq("第136: 新山地受已有山地加成", (m2.attack, m2.defense), (5, 4))
eq("第13: 友方山地加入时 +1/+1", (m1.attack, m1.defense), (3, 4))

# ---- 6. 烟幕 ----
print("== 6. 烟幕 ==")
g = new_game()
me, foe = g.players
s = place(g, "第28猎兵团", me, "后方", slot=1, kredits=5)   # 1/1 烟幕
foe_atk = place(g, INF_2_2, foe, "前线", slot=1, kredits=5)
pool = g.attack_targets(foe_atk)
check("烟幕: 不可被攻击", all(x is not s for x in pool), str([x.name for x in pool]))
me.kredits = 5
t = place(g, INF_2_2, foe, "前线", slot=2)
g.do_attack(s, t)
check("烟幕: 行动后失去", not s.has("烟幕"))

# ---- 7. 击杀得 Kredits（第158 在击杀方场上） ----
print("== 7. 击杀 Kredits ==")
g = new_game()
me, foe = g.players
place(g, "第158补给营", me, "后方", slot=1)            # kill_kredits，我方场上
killer = place(g, INF_2_2, me, "前线", slot=2, kredits=5)
k = place(g, INF_2_2, foe, "前线", slot=1, kredits=5)
k.defense = 1
me.kredits = 5
g.do_attack(killer, k)
check("击杀敌军: +2 Kredits", me.kredits == 7, f"kredits={me.kredits}")

# ---- 8. 回合开始 Kredits ----
print("== 8. 回合 Kredits ==")
g = new_game()
me, foe = g.players
place(g, "第95山地工兵营", me, "后方", slot=1)         # turn_kredits
g.end_turn(); g.start_turn()            # 对手回合
g.end_turn(); g.start_turn()            # 我方回合开始
base = g.turn_num // 2 + 1              # 正常回合收入
eq("第95: 我方回合开始 +1 Kredits", me.kredits, base + 1)

# ---- 9. 钳击 ----
print("== 9. 钳击 ==")
g = new_game()
me, foe = g.players
pc = place(g, "第101步兵团", me, "后方", kredits=9)    # pincer_grow
pc.attack, pc.defense = 2, 2
t = place(g, INF_2_2, foe, "前线", slot=1)
me.kredits = 9
g.do_attack(pc, t)
eq("第101: 攻击时 +1/+1", (pc.attack, pc.defense), (3, 3))

# ---- 10. 生产入手 ----
print("== 10. 生产入手 ==")
g = new_game()
me, foe = g.players
d = place(g, "第957国民掷弹兵团", me, "后方", slot=1)
g.on_deploy(d)                          # place() 绕过了 play_card，手动补部署效果
check("第957: 部署入手一张生产", any(c.name == "生产" for c in me.hand),
      f"hand={len(me.hand)}")

# ---- 汇总 ----
print("=" * 56)
fails = [r for r in results if not r[1]]
print(f"通过 {len(results) - len(fails)} 项 / 失败 {len(fails)} 项")
for name, _, detail in fails:
    print("FAIL:", name, detail)
print("全部通过 ✓" if not fails else "存在失败 ✗")
sys.exit(1 if fails else 0)
