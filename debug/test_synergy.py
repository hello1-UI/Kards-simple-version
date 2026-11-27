# -*- coding: utf-8 -*-
"""[协力] 与 [士气伤害] 规则回归（对齐官方 KARDS「国土阵线」机制）

官方规则（kards.com 国土阵线公告）：
  使用协力卡牌时，除非回合开始时场上有相同国家的友方单位，
  否则总部会受到士气伤害。
  士气伤害（旧称疲劳）：牌库抽空时触发，第1次1点、第2次2点，以此类推；
  与协力惩罚共用同一计数器。

覆盖点：
  1. 回合开始无同国友军 → 打协力卡 → 士气伤害 1
  2. 回合开始有同国友军 → 打协力卡 → 无伤害
  3. 快照语义：回合开始有友军、本回合阵亡 → 仍无伤害
  4. 快照语义：回合开始无友军、本回合新部署同国单位 → 仍有伤害
  5. 快照每回合刷新：上回合受伤、本回合有友军 → 不再受伤
  6. 牌库抽空递增：1 → 2 → 3
  7. 共用计数器：疲劳与协力惩罚累进（疲劳1 → 协力2）
  8. 不同国家的单位不满足协力条件
  9. 协力单位自身不算（打出前不在快照里）

用法: python debug/test_synergy.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
random.seed(20261127)

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


def put_unit(g, p, name="测试兵", attack=1, defense=1, position="支援阵线",
             keywords=None):
    card = K.UnitCard(name, p.nation, 1, attack, defense,
                      list(keywords or []), "步兵")
    u = K.Unit(card, p)
    u.attack, u.defense, u.max_defense = attack, defense, defense
    u.position = position
    u.slot = len(p.board)
    u.fresh_deploy = False
    u.can_attack = True
    p.board.append(u)
    return u


def synergy_card(nation="德国", cost=1):
    return K.UnitCard("协力兵", nation, cost, 2, 2, ["协力"], "步兵")


def play_synergy(g, p, nation="德国"):
    """把一张协力卡放进手牌并打出，返回 play_card 的返回值"""
    card = synergy_card(nation)
    p.hand.append(card)
    p.kredits = max(p.kredits, card.cost)
    return g.play_card(p, len(p.hand) - 1)


def begin_turn(g, p):
    """切到 p 的回合并正常 start_turn（含快照）"""
    if g.current is not p:
        g.current = p
    g.start_turn()


def main():
    print("\n=== 1. 回合开始无同国友军 → 士气伤害 1 ===")
    g, p1, p2 = new_game()
    begin_turn(g, p1)
    hq0 = p1.hq
    ok = play_synergy(g, p1)
    check("打出成功", ok is True)
    check("士气计数 = 1", p1.morale == 1, f"morale={p1.morale}")
    check("总部受到 1 点士气伤害", p1.hq == hq0 - 1, f"hq={p1.hq}")

    print("\n=== 2. 回合开始有同国友军 → 无伤害 ===")
    g, p1, p2 = new_game()
    put_unit(g, p1)                       # 与 p1 同国（德国）
    begin_turn(g, p1)
    hq0 = p1.hq
    play_synergy(g, p1)
    check("同国友军在场，无士气伤害", p1.morale == 0 and p1.hq == hq0,
          f"morale={p1.morale} hq={p1.hq}")

    print("\n=== 3. 快照语义：友军本回合阵亡仍无伤害 ===")
    g, p1, p2 = new_game()
    u = put_unit(g, p1)
    begin_turn(g, p1)                     # 快照：场上有德国单位
    p1.board.remove(u)                    # 本回合阵亡（离场）
    hq0 = p1.hq
    play_synergy(g, p1)
    check("友军回合开始时在场，阵亡后仍不算违约",
          p1.morale == 0 and p1.hq == hq0, f"morale={p1.morale} hq={p1.hq}")

    print("\n=== 4. 快照语义：本回合新部署同国单位不算 ===")
    g, p1, p2 = new_game()
    begin_turn(g, p1)                     # 快照：空场
    put_unit(g, p1)                       # 本回合才部署的同国单位
    hq0 = p1.hq
    play_synergy(g, p1)
    check("回合开始没友军，即使当回合部署了也算违约",
          p1.morale == 1 and p1.hq == hq0 - 1, f"morale={p1.morale} hq={p1.hq}")

    print("\n=== 5. 快照每回合刷新 ===")
    g, p1, p2 = new_game()
    begin_turn(g, p1)                     # 第1回合：空场
    hq0 = p1.hq
    play_synergy(g, p1)                   # 违约 → 1
    check("第1回合违约受 1 点", p1.morale == 1 and p1.hq == hq0 - 1)
    put_unit(g, p1)                       # 部署同国单位（下一回合起满足协力）
    g.end_turn()
    begin_turn(g, p2)
    g.end_turn()
    begin_turn(g, p1)                     # 快照：有德国单位
    hq1 = p1.hq
    play_synergy(g, p1)
    check("第2回合有友军，不再受伤", p1.morale == 1 and p1.hq == hq1,
          f"morale={p1.morale} hq={p1.hq}")

    print("\n=== 6. 牌库抽空：士气伤害 1 → 2 → 3 ===")
    g, p1, p2 = new_game()
    p1.deck.clear()
    hq0 = p1.hq
    g.draw_cards(p1, 1)
    check("第1次抽空受 1 点", p1.morale == 1 and p1.hq == hq0 - 1,
          f"morale={p1.morale} hq={p1.hq}")
    g.draw_cards(p1, 1)
    check("第2次抽空受 2 点", p1.morale == 2 and p1.hq == hq0 - 3,
          f"morale={p1.morale} hq={p1.hq}")
    g.draw_cards(p1, 1)
    check("第3次抽空受 3 点", p1.morale == 3 and p1.hq == hq0 - 6,
          f"morale={p1.morale} hq={p1.hq}")

    print("\n=== 7. 共用计数器：疲劳 1 → 疲劳 2（回合开始抽牌）→ 协力 3 ===")
    g, p1, p2 = new_game()
    p1.deck.clear()
    hq0 = p1.hq
    g.draw_cards(p1, 1)                   # 疲劳：1
    begin_turn(g, p1)                     # 回合开始抽牌 → 疲劳：2（快照空场）
    play_synergy(g, p1)                   # 协力：3（共用计数器）
    check("协力惩罚取计数器当前值 3", p1.morale == 3,
          f"morale={p1.morale}")
    check("总部累计受 1+2+3=6 点", p1.hq == hq0 - 6, f"hq={p1.hq}")

    print("\n=== 8. 不同国家单位不满足协力 ===")
    g, p1, p2 = new_game()
    foreign = put_unit(g, p1, name="异国兵")
    foreign.card = K.UnitCard("异国兵", "苏联", 1, 1, 1, [], "步兵")
    begin_turn(g, p1)
    hq0 = p1.hq
    play_synergy(g, p1, nation="德国")
    check("场上只有苏联单位，德国协力卡违约",
          p1.morale == 1 and p1.hq == hq0 - 1, f"morale={p1.morale}")

    print("\n=== 9. 协力单位自身不算同国友军 ===")
    g, p1, p2 = new_game()
    begin_turn(g, p1)                     # 空场快照
    hq0 = p1.hq
    play_synergy(g, p1)                   # 打出第1张
    play_synergy(g, p1)                   # 场上已有第1张协力单位（同国）
    check("第2张协力卡：单位本身不算友军，继续违约",
          p1.morale == 2 and p1.hq == hq0 - 3, f"morale={p1.morale} hq={p1.hq}")

    print("\n=== 11. AI：有安全牌时不违约，攥住协力卡 ===")
    g, p1, p2 = new_game()
    begin_turn(g, p1)                     # 快照：空场
    cheap = K.UnitCard("便宜兵", "德国", 1, 2, 2, [], "步兵")
    syn = synergy_card("德国", cost=2)
    p1.hand[:] = [cheap, syn]
    p1.kredits = 5
    put_unit(g, p2)                       # 给对面摆个单位，AI 有事可做
    list(g.ai_steps())
    check("便宜兵已打出", cheap not in p1.hand)
    check("协力卡仍攥在手里", syn in p1.hand)
    check("本回合没吃士气伤害", p1.morale == 0, f"morale={p1.morale}")

    print("\n=== 12. AI：只剩协力卡时肯吃一次士气伤害 ===")
    g, p1, p2 = new_game()
    begin_turn(g, p1)
    syn = synergy_card("德国", cost=2)
    p1.hand[:] = [syn]
    p1.kredits = 5
    list(g.ai_steps())
    check("协力卡已打出（不攥死）", syn not in p1.hand)
    check("吃过 1 点士气伤害", p1.morale == 1, f"morale={p1.morale}")

    print("\n=== 10. 文案与导出一致性 ===")
    check("KEYWORD_GUIDE 含协力", any(k == "协力" for k, _, _ in K.KEYWORD_GUIDE))
    check("TERM_GUIDE 含士气伤害", any(k == "士气伤害" for k, _ in K.TERM_GUIDE))
    check("疲劳术语已并入士气伤害",
          not any(k == "疲劳" for k, _ in K.TERM_GUIDE))
    check("KEYWORD_I18N 协力英文名为 Synergy（官方）",
          K.KEYWORD_I18N["协力"]["en"] == "Synergy")

    print(f"\n=== 协力/士气伤害回归: {len(PASS)} 通过 / {len(FAIL)} 失败 ===")
    if FAIL:
        for name in FAIL:
            print("  失败: " + name)
        sys.exit(1)


if __name__ == "__main__":
    main()
