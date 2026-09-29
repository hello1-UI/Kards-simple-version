# -*- coding: utf-8 -*-
"""headless 机制测试：验证对齐原版 KARDS 后的引擎行为。
用法: python debug/test_original.py
"""
import io
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
random.seed(42)

import kards as K

PASS = []
FAIL = []


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
    return next(i for i, c in enumerate(p.hand) if c.name == name)


def main():
    print("== 1. 装甲/装甲2：只减免战斗伤害 ==")
    g, p1, p2 = make_game()
    db = K.card_database()
    tiger = deploy(g, p2, db["虎式坦克"])       # 8/8 装甲2
    g.damage_unit(tiger, 5)                     # 效果伤害
    check("效果伤害不减", tiger.defense == 3, f"defense={tiger.defense}")
    tiger.defense = 8
    g.damage_unit(tiger, 5, combat=True)        # 战斗伤害
    check("战斗伤害减2", tiger.defense == 5, f"defense={tiger.defense}")

    print("== 2. 伏击：防守方先出手 ==")
    g, p1, p2 = make_game()
    db = K.card_database()
    zero = deploy(g, p2, db["零式战斗机"])      # 4/4 伏击
    big = deploy(g, p1, K.UnitCard("重坦", "苏联", 5, 9, 9, ["闪击"], "坦克"))
    big.can_attack = True
    g.do_attack(big, zero)
    check("伏击先手打残攻击者", big.defense == 5, f"atk defense={big.defense}")
    check("零战阵亡", zero not in p2.board)
    zero2 = deploy(g, p2, db["零式战斗机"])
    small = deploy(g, p1, K.UnitCard("步兵", "苏联", 1, 2, 2, ["闪击"], "步兵"))
    small.can_attack = True
    g.do_attack(small, zero2)
    check("伏击击杀攻击者则攻击无效", small not in p1.board and zero2 in p2.board)

    print("== 3. 奋战：每回合攻击两次 ==")
    g, p1, p2 = make_game()
    db = K.card_database()
    fury = deploy(g, p1, db["装甲掷弹兵"])      # 2/2 奋战
    fury.can_attack = True
    t1 = deploy(g, p2, K.UnitCard("靶1", "德国", 1, 0, 3, [], "步兵"))
    t2 = deploy(g, p2, K.UnitCard("靶2", "德国", 1, 0, 3, [], "步兵"))
    check("第一次可攻击", g.unit_ready(fury))
    g.do_attack(fury, t1)
    check("第二次仍可攻击", g.unit_ready(fury))
    g.do_attack(fury, t2)
    check("两次后不可攻击", not g.unit_ready(fury))

    print("== 4. 动员：回合开始+1/+1，受伤移除 ==")
    g, p1, p2 = make_game("苏联", "德国", filler1="殖民步兵")
    db = K.card_database()
    col = deploy(g, p1, db["殖民步兵"])         # 1/1 闪击 动员
    g.current = p1
    g.start_turn()
    check("回合开始+1/+1", col.attack == 2 and col.defense == 2 and col.mob == 1,
          f"{col.attack}/{col.defense} mob={col.mob}")
    g.damage_unit(col, 1)                       # 还原+1点伤害 → 1/0 阵亡
    check("受伤后加成移除并按基础生命承伤", col.mob == 0 and col.attack == 1
          and (col.defense <= 0),
          f"{col.attack}/{col.defense} mob={col.mob}")

    print("== 5. 亡计 + 大和号 ==")
    g, p1, p2 = make_game()
    db = K.card_database()
    hay = deploy(g, p1, db["隼式战斗机"])
    hq0 = p2.hq
    g.destroy_unit(hay)
    check("隼式亡计2伤", p2.hq == hq0 - 2, f"hq={p2.hq}")
    deploy(g, p1, db["步兵联队"])
    deploy(g, p1, db["九七式坦克"])
    db["大和号战列舰"].effect(g, p1)
    check("大和号授予亡计", all(u.dying_hq == 2 for u in p1.board))
    u0 = p1.board[0]
    hq0 = p2.hq
    g.destroy_unit(u0)
    check("任意日军单位亡计生效", p2.hq == hq0 - 2)

    print("== 6. 万岁冲锋：消灭攻≤4陆军 + 强制结束 ==")
    g, p1, p2 = make_game()
    db = K.card_database()
    deploy(g, p1, db["步兵联队"])               # 2攻步兵
    deploy(g, p2, db["三号突击炮"])             # 2攻坦克
    tiger = deploy(g, p2, db["虎式坦克"])       # 8攻坦克 保留
    b17 = deploy(g, p2, K.UnitCard("巨机", "德国", 9, 9, 9, [], "轰炸机"))
    db["万岁冲锋"].effect(g, p1)
    check("低攻陆军被消灭", len(p1.board) == 0 and len(p2.board) == 2)
    check("高攻与空军保留", tiger in p2.board and b17 in p2.board)
    check("force_end 标记", g.force_end)

    print("== 7. 九五式：指令疼痛 ==")
    g, p1, p2 = make_game()
    db = K.card_database()
    deploy(g, p2, db["九五式轻战车"])
    hq0 = p1.hq
    p1.kredits = 10
    g.play_card(p1, hand_idx(p1, "动员兵"))
    check("出指令自身总部-1", p1.hq == hq0 - 1, f"hq={p1.hq}")

    print("== 8. 步兵增援反制：友军阵亡→+2/+3 ==")
    g, p1, p2 = make_game()
    db = K.card_database()
    fr = db["步兵增援"]
    p1.counters.append(fr)
    a = deploy(g, p1, db["步兵联队"])
    b = deploy(g, p1, db["九七式坦克"])
    g.destroy_unit(a)
    check("反制消耗", fr not in p1.counters)
    check("存活单位+2/+3", b.attack == 5 and b.defense == 6, f"{b.attack}/{b.defense}")

    print("== 9. 步兵班：反制触发成长 ==")
    g, p1, p2 = make_game()
    db = K.card_database()
    gren = deploy(g, p2, db["步兵班"])          # 2/2 counter_grow
    p2.counters.append(db["反坦克炮"])
    atk = deploy(g, p1, db["T-34坦克"])
    atk.can_attack = True
    g.do_attack(atk, gren)
    check("反制触发", atk not in p1.board)
    check("步兵班+2/+2", gren.attack == 4 and gren.defense == 4, f"{gren.attack}/{gren.defense}")

    print("== 10. 部署效果 ==")
    db = K.card_database()
    # 谢尔曼抽2
    g, p1, p2 = make_game("美国", "德国", filler1="谢尔曼坦克")
    deploy(g, p1, db["谢尔曼坦克"], pos="前线")
    p1.kredits = 10
    n0 = len(p1.hand)
    g.play_card(p1, hand_idx(p1, "谢尔曼坦克"))
    check("谢尔曼抽2", len(p1.hand) == n0 - 1 + 2, f"hand={len(p1.hand)}")
    # 四号坦克撤退
    g, p1, p2 = make_game("苏联", "德国", filler1="四号坦克")
    foe_u = deploy(g, p2, db["三号突击炮"], pos="前线")
    p1.kredits = 12
    g.play_card(p1, hand_idx(p1, "四号坦克"))
    check("四号坦克迫使撤退", foe_u.position == "后方")
    # 蚊式 nuke3
    g, p1, p2 = make_game("英国", "德国", filler1="德哈维兰蚊式")
    victim = deploy(g, p2, db["步兵班"])
    p1.kredits = 12
    g.play_card(p1, hand_idx(p1, "德哈维兰蚊式"))
    check("蚊式3伤", victim not in p2.board)
    # 丛林渗透队 snipe2
    g, p1, p2 = make_game("日本", "德国", filler1="丛林渗透队")
    low = deploy(g, p2, db["步兵班"])           # 2攻
    tiger = deploy(g, p2, db["虎式坦克"])       # 8攻
    p1.kredits = 12
    g.play_card(p1, hand_idx(p1, "丛林渗透队"))
    check("丛林渗透消灭低攻单位", low not in p2.board and tiger in p2.board)
    # M13/40（盟国卡由主国玩家使用）
    g, p1, p2 = make_game("德国", "德国", filler1="M13/40坦克")
    p1.kredits = 12
    for _ in range(3):
        deploy(g, p1, db["黑衫军"])
    g.play_card(p1, hand_idx(p1, "M13/40坦克"))
    m = p1.board[-1]
    check("M13/40 优势获得闪击奋战", "闪击" in m.keywords and "奋战" in m.keywords)
    # 殖民步兵 foe_hand
    g, p1, p2 = make_game("苏联", "德国", filler1="殖民步兵")
    p2.hand = [db["步兵班"]] * 4
    p1.kredits = 12
    g.play_card(p1, hand_idx(p1, "殖民步兵"))
    col2 = p1.board[-1]
    check("殖民步兵按对手手牌+4/+4", col2.attack == 5 and col2.defense == 5,
          f"{col2.attack}/{col2.defense}")

    print("== 11. M10/远程榴弹炮/斯图卡 ==")
    g, p1, p2 = make_game("美国", "德国")
    db = K.card_database()
    tank = deploy(g, p2, db["四号坦克"])        # 5/5 坦克
    m10 = deploy(g, p1, db["M10狼獾"])          # 3/2
    m10.can_attack = True
    g.do_attack(m10, tank)
    check("M10消灭受其伤害的坦克", tank not in p2.board)
    long_tom = deploy(g, p1, db["远程榴弹炮"])
    long_tom.can_attack = True
    deploy(g, p2, db["步兵班"])
    g.do_attack(long_tom, p2.board[0])
    check("榴弹炮随机分配不崩溃", True)
    stuka = deploy(g, p1, db["斯图卡俯冲轰炸机"])
    stuka.can_attack = True
    n_hand = len(p2.hand)
    p2.board.clear()
    g.do_hq_attack(stuka)
    check("斯图卡弃对手1牌", n_hand == 0 or len(p2.hand) == n_hand - 1)

    print("== 12. 呜啦!/闪电战 临时增益还原 ==")
    g, p1, p2 = make_game()
    db = K.card_database()
    inf = deploy(g, p1, db["近卫步兵"])
    a0 = inf.attack
    db["为了祖国"].effect(g, p1)
    check("呜啦+3攻", inf.attack == a0 + 3)
    g.current = p1
    g.end_turn()
    check("回合结束还原", inf.attack == a0, f"atk={inf.attack}")
    check("overflow_turn 清除", not inf.overflow_turn)

    print("== 13. ATS 本土防卫军 ==")
    g, p1, p2 = make_game("英国", "德国")
    db = K.card_database()
    db["本土防卫军"].effect(g, p1)
    n0 = len(p1.hand)
    g.damage_hq(p2, 3)
    check("3伤触发抽牌", len(p1.hand) == n0 + 1, f"hand={len(p1.hand)}")
    g.current = p1
    g.end_turn()
    check("回合结束标记清除", p2.ats_mark == 0)

    print("== 14. 廓尔喀/横须贺/九七式 ==")
    g, p1, p2 = make_game("日本", "德国", filler1="廓尔喀步枪团")
    db = K.card_database()
    p1.orders_played = 2
    p1.kredits = 12
    g.play_card(p1, hand_idx(p1, "廓尔喀步枪团"))
    gur = p1.board[-1]
    check("廓尔喀+2攻", gur.attack == 1 + 2 + 1, f"atk={gur.attack}")  # 1基+2指令+1日HQ
    g, p1, p2 = make_game("日本", "德国", filler1="海军特别陆战队")
    deploy(g, p1, K.UnitCard("民兵", "中立", 0, 1, 1, [], "步兵"))
    p1.kredits = 12
    g.play_card(p1, hand_idx(p1, "海军特别陆战队"))
    y = p1.board[-1]
    check("横须贺+1/+1", y.attack == 2 + 1 and y.defense == 4, f"{y.attack}/{y.defense}")
    g, p1, p2 = make_game("日本", "德国", filler1="步兵联队")
    chi = deploy(g, p1, db["九七式坦克"])
    p1.kredits = 12
    g.play_card(p1, hand_idx(p1, "步兵联队"))
    inf2 = p1.board[-1]
    check("九七式光环+1攻", inf2.attack == 2 + 1 + 1, f"atk={inf2.attack}")

    print("== 15. 特种空勤团 lock5 / B-17 untargetable ==")
    g, p1, p2 = make_game()
    db = K.card_database()
    deploy(g, p2, db["特种空勤团"])
    big = deploy(g, p1, db["T-34坦克"])         # 5攻
    big.can_attack = True
    check("攻≥5被封锁", not g.unit_ready(big))
    g2, q1, q2 = make_game("德国", "美国", filler1="炮火准备")
    b17 = deploy(g2, q2, db["B-17空中堡垒"])
    q1.kredits = 12
    g2.play_card(q1, hand_idx(q1, "炮火准备"))
    check("指令无法选中B-17", b17 in q2.board and b17.defense == 6)

    print("== 16. 双倍伤害特性 ==")
    g, p1, p2 = make_game()
    db = K.card_database()
    su85 = deploy(g, p1, db["SU-85坦克歼击车"])  # 5/3 对坦双倍
    su85.can_attack = True
    panzer = deploy(g, p2, db["四号坦克"])       # 5/5
    g.do_attack(su85, panzer)
    check("对坦双倍10伤", panzer not in p2.board)
    flak = deploy(g, p2, db["88毫米炮"])         # 3/4 伏击 对空/坦双倍
    fighter = deploy(g, p1, db["拉-7战斗机"])    # 4/4
    fighter.can_attack = True
    g.do_attack(fighter, flak)
    check("88炮伏击对空双倍6伤", fighter.defense == -2 or fighter not in p1.board,
          f"def={fighter.defense}")

    print("== 17. 舰炮支援(轰炸突袭)相邻波及 ==")
    g, p1, p2 = make_game("苏联", "德国", filler1="舰炮支援")
    db = K.card_database()
    deploy(g, p2, db["步兵班"], slot=0)
    deploy(g, p2, db["步兵班"], slot=1)
    deploy(g, p2, db["步兵班"], slot=3)
    p1.kredits = 12
    g.play_card(p1, hand_idx(p1, "舰炮支援"))
    check("相邻波及生效(不崩溃)", True)

    print("== 18. 卡池完整性/稀有度/卡组构建 ==")
    db = K.card_database()
    check("卡池数量212", len(db) == 212, f"n={len(db)}")
    rar = {}
    for c in db.values():
        rar[c.rarity] = rar.get(c.rarity, 0) + 1
    print("   稀有度分布:", rar)
    for n in K.MAIN_NATIONS:
        deck = K.build_deck(n, db)
        ok, msg = K.validate_deck(deck, n, db)
        check(f"{n} 推荐卡组合法", ok, msg)

    print(f"\n=== 结果: {len(PASS)} 通过 / {len(FAIL)} 失败 ===")
    if FAIL:
        print("失败用例:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
