# -*- coding: utf-8 -*-
"""战术规则测试：移动行动费 / 兵种攻击规则 / 战斗机拦截 / 反击规则

运行: python debug/test_tactics.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kards_engine as core

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f" ({detail})" if detail else ""))


db = core.card_database()


def new_game():
    p1 = core.Player("你", "德国", [])
    p2 = core.Player("AI", "苏联", [])
    g = core.Game(p1, p2, interactive=False)
    return g


def place(g, card_name, side, position, slot=1, kredits=10):
    """部署并摆位：绕过部署回合限制便于测试"""
    u = g.deploy_unit(side, db[card_name])
    u.position = position
    u.slot = slot
    u.fresh_deploy = False
    u.can_attack = True
    u.owner.kredits = kredits
    return u


# ---- 1. 无闪击部署当回合不能移动/攻击 ----
g = new_game()
me, foe = g.players
u = g.deploy_unit(me, db["步兵班"])               # 无闪击步兵
check("无闪击: 部署当回合不能移动", g.move_unit(u, "前线") is False)
check("无闪击: 部署当回合不能攻击", g.unit_ready(u) is False)
b = g.deploy_unit(me, db["三号坦克 G 型"])        # [闪击]坦克
check("闪击坦克: 部署当回合可移动", g.move_unit(b, "前线") is True)
check("闪击坦克: 移动后仍可攻击", g.unit_ready(b) is True)
t1 = place(g, "步兵班", foe, "前线", slot=1)
b.attack = 5
before = t1.defense
g.do_attack(b, t1)
check("闪击坦克: 部署回合移动+攻击成功", t1.defense == before - 5,
      f"{before}->{t1.defense}")

# ---- 2. 移动消耗行动费 ----
g = new_game()
me, foe = g.players
a = place(g, "第1战斗群", me, "后方", kredits=2)   # 行动费2
check("移动前行动费=2", me.kredits == 2)
ok = g.move_unit(a, "前线")
check("移动成功且扣行动费", ok and me.kredits == 0, f"kredits={me.kredits}")
check("移动后不能再移动", g.move_unit(a, "后方") is False)
a2 = place(g, "第1战斗群", me, "后方", kredits=1)
check("行动费不足无法移动", g.move_unit(a2, "前线") is False and me.kredits == 1)

# ---- 3. 步兵: 移动/攻击二选一 ----
g = new_game()
me, foe = g.players
inf = place(g, "殖民步兵", me, "后方", kredits=10)
g.move_unit(inf, "前线")
check("步兵移动后不能攻击", g.unit_ready(inf) is False)
inf2 = place(g, "殖民步兵", me, "前线", kredits=10)
t = place(g, "步兵班", foe, "前线", slot=1)
inf2.attack = 3
g.do_attack(inf2, t)
check("步兵攻击后不能移动", g.move_unit(inf2, "后方") is False)
tank = place(g, "二号坦克 C 型", me, "后方", kredits=10)
g.move_unit(tank, "前线")
check("坦克移动后仍可攻击", g.unit_ready(tank) is True)

# ---- 4. 支援线攻击资格 ----
g = new_game()
me, foe = g.players
art = place(g, "Pak36反坦克炮", me, "后方")        # 炮兵
f1 = place(g, "步兵班", foe, "前线", slot=1)
f2 = place(g, "T-70", foe, "前线", slot=2)
rear_foe = place(g, "步兵班", foe, "后方", slot=5)
tg = g.attack_targets(art)
check("炮兵支援线可攻击敌方前线", f1 in tg and f2 in tg)
check("炮兵支援线打不到敌方支援线", rear_foe not in tg)
inf_r = place(g, "殖民步兵", me, "后方")
check("步兵在支援线不能攻击(无目标)", g.attack_targets(inf_r) == [])
check("步兵在支援线不能打总部", g.can_hit_hq(inf_r)[0] is False)
check("炮兵支援线可以打总部", g.can_hit_hq(art)[0] is True)

# ---- 5. 炮兵/轰炸机无视警卫 ----
g = new_game()
me, foe = g.players
guard = place(g, "T-70", foe, "前线", slot=1)
guard.keywords.append("警卫")
normal = place(g, "步兵班", foe, "前线", slot=2)
art = place(g, "Pak36反坦克炮", me, "前线", slot=1)
check("炮兵无视警卫(可打非警卫)", normal in g.attack_targets(art))
inf = place(g, "殖民步兵", me, "前线", slot=1)
check("普通单位受警卫保护限制", normal not in g.attack_targets(inf))
gd0 = place(g, "T-70", foe, "前线", slot=0)
gd0.keywords.append("警卫")
check("#0警卫保护总部(普通单位)", g.can_hit_hq(inf)[0] is False)
check("炮兵无视#0警卫可打总部", g.can_hit_hq(art)[0] is True)
bmb = place(g, "斯图卡 B2", me, "后方")
check("轰炸机无视警卫(可打非警卫)", normal in g.attack_targets(bmb))
check("轰炸机无视#0警卫可打总部", g.can_hit_hq(bmb)[0] is True)

# ---- 6. 轰炸机优先打战斗机 ----
g = new_game()
me, foe = g.players
place(g, "步兵班", foe, "前线", slot=1)
fi = place(g, "雅克-3", foe, "前线", slot=2)       # 战斗机(前线)
bmb = place(g, "斯图卡 B2", me, "后方")
tg = g.attack_targets(bmb)
check("轰炸机必须优先打前线战斗机", tg == [fi], str(tg))

# ---- 7. 战斗机拦截 ----
g = new_game()
me, foe = g.players
victim = place(g, "步兵班", foe, "前线", slot=1)
esc = place(g, "伊-15 海鸥", foe, "后方", slot=5)  # 支援线战斗机(拦截者)
esc.attack = 1
bmb = place(g, "斯图卡 B2", me, "前线", slot=1)
bmb.attack = 1
bmb_def, esc_def = bmb.defense, esc.defense
g.do_attack(bmb, victim)
check("拦截: 攻击转向战斗机", esc.defense == esc_def - 1,
      f"{esc_def}->{esc.defense}")
check("拦截: 轰炸机吃战斗机反击", bmb.defense == bmb_def - esc.attack,
      f"{bmb_def}->{bmb.defense}")
check("拦截: 原目标无伤", victim.defense == victim.max_defense)

# ---- 8. 反击规则 ----
g = new_game()
me, foe = g.players
# 炮兵不吃反击
art = place(g, "Pak36反坦克炮", me, "前线", slot=1)
art.attack = 1
t = place(g, "步兵班", foe, "前线", slot=1)        # 3防, 受1伤不死
g.do_attack(art, t)
check("炮兵攻击不吃反击", art.defense == art.max_defense,
      f"{art.defense}/{art.max_defense}")
# 轰炸机打非战斗机不吃反击
bmb = place(g, "斯图卡 B2", me, "前线", slot=1)
bmb.attack = 1
t2 = place(g, "步兵班", foe, "前线", slot=1)
g.do_attack(bmb, t2)
check("轰炸机攻击不吃反击", bmb.defense == bmb.max_defense,
      f"{bmb.defense}/{bmb.max_defense}")
# 轰炸机打战斗机吃反击
bmb2 = place(g, "斯图卡 B2", me, "前线", slot=1)
bmb2.attack = 1
fi = place(g, "雅克-7", foe, "前线", slot=1)       # 无关键字战斗机
fi.attack = 2
b_def = bmb2.defense
g.do_attack(bmb2, fi)
check("轰炸机打战斗机吃反击", bmb2.defense == b_def - fi.attack,
      f"{b_def}->{bmb2.defense}")
# 打轰炸机不吃反击
inf = place(g, "殖民步兵", me, "前线", slot=1)
inf.attack = 1
bmb3 = place(g, "斯图卡 B2", foe, "前线", slot=1)  # 2防, 受1伤不死
g.do_attack(inf, bmb3)
check("打轰炸机不吃反击", inf.defense == inf.max_defense,
      f"{inf.defense}/{inf.max_defense}")
# 轰炸机打总部会被拦截
g = new_game()
me, foe = g.players
esc = place(g, "伊-15 海鸥", foe, "后方", slot=5)
bmb = place(g, "斯图卡 B2", me, "前线", slot=1)
bmb.attack = 3
hq0 = foe.hq
g.do_hq_attack(bmb)
check("轰炸机空袭总部被战斗机拦截", foe.hq == hq0 and esc.defense < esc.max_defense,
      f"HQ{hq0}->{foe.hq}, 拦截机防{esc.max_defense}->{esc.defense}")
# 无战斗机时轰炸机正常空袭
g = new_game()
me, foe = g.players
bmb = place(g, "斯图卡 B2", me, "后方")
hq0 = foe.hq
g.do_hq_attack(bmb)
check("无拦截时轰炸机正常空袭总部(+2)", foe.hq == hq0 - (bmb.attack + 2),
      f"HQ{hq0}->{foe.hq}")

# ---- 汇总 ----
fails = [r for r in results if not r[1]]
print(f"\n==== 战术规则测试: {len(results) - len(fails)}/{len(results)} 通过 ====")
sys.exit(1 if fails else 0)
