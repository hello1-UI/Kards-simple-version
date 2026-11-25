# -*- coding: utf-8 -*-
"""指挥点 / 指挥点槽规则测试。

规则（用户指定）：
    · 开局指挥点槽 = 0；
    · 我方回合开始 +1 槽，涨到 12 为止；
    · 槽的绝对上限 24；
    · 之后指挥点回满 = 槽数。

跑法：
    python debug/test_cp_slots.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import kards_engine as core                                    # noqa: E402
import kards_i18n as i18n                                      # noqa: E402

PASS, FAIL = [], []


def check(label, cond, extra=""):
    if cond:
        PASS.append(label)
        print("  [OK] %s" % label)
    else:
        FAIL.append(label)
        print("  [FAIL] %s  %s" % (label, extra))


DB = core.card_database()
FILLER = core.UnitCard("测试步兵", "德国", 1, 1, 1, [], "步兵", operate=0)


def new_game():
    p1 = core.Player("你", "德国", [FILLER] * core.DECK_SIZE)
    p2 = core.Player("AI", "苏联", [FILLER] * core.DECK_SIZE)
    g = core.Game(p1, p2, interactive=False)
    return g, p1, p2


def next_turn(g):
    g.end_turn()
    g.start_turn()


def slots_rules():
    print("1. 开局：槽与指挥点都是 0")
    g, p1, p2 = new_game()
    check("开局槽 = 0", p1.cp_slots == 0 and p2.cp_slots == 0,
          (p1.cp_slots, p2.cp_slots))
    check("开局指挥点 = 0", p1.kredits == 0 and p2.kredits == 0,
          (p1.kredits, p2.kredits))

    print("\n2. 回合开始：+1 槽，指挥点回满")
    g.start_turn()                       # 先手第一回合
    check("先手首回合槽 = 1", p1.cp_slots == 1, p1.cp_slots)
    check("先手首回合指挥点 = 槽数", p1.kredits == p1.cp_slots, p1.kredits)
    check("对手槽不动", p2.cp_slots == 0, p2.cp_slots)

    p1.kredits = 0                       # 花光
    next_turn(g)                         # 对手回合
    check("对手首回合槽 = 1（不再白拿 1 点）", p2.cp_slots == 1, p2.cp_slots)
    check("对手首回合指挥点 = 1", p2.kredits == 1, p2.kredits)
    next_turn(g)                         # 我方第二回合
    check("我方第二回合槽 = 2", p1.cp_slots == 2, p1.cp_slots)
    check("指挥点回满（花光也补回）", p1.kredits == 2, p1.kredits)

    print("\n3. 每回合只涨 1 槽，涨到 12 停")
    g, p1, p2 = new_game()
    seq = []
    for _ in range(15):                  # 15 个「我方回合」
        g.start_turn()
        seq.append(p1.cp_slots)
        g.end_turn()
        g.start_turn()                   # 对手回合（我方槽不动）
        g.end_turn()
    check("槽序列为 1..12 后恒为 12",
          seq[:12] == list(range(1, 13)) and all(x == 12 for x in seq[12:]),
          seq)
    check("涨到 12 后指挥点 = 12", p1.kredits == 12, p1.kredits)
    check("成长上限常量是 12", core.CP_SLOT_GROWTH_CAP == 12)
    check("绝对上限常量是 24", core.CP_SLOT_MAX == 24)

    print("\n4. 槽的绝对上限 24（成长本身不越界）")
    g, p1, p2 = new_game()
    p1.cp_slots = 23
    g.start_turn()
    check("23 → 成长不动（已过 12），指挥点 = 23", p1.cp_slots == 23 and p1.kredits == 23,
          (p1.cp_slots, p1.kredits))
    p1.cp_slots = 40                     # 模拟「+槽」卡牌堆过头
    next_turn(g)
    next_turn(g)
    check("超过上限时夹到 24", p1.cp_slots == core.CP_SLOT_MAX, p1.cp_slots)

    print("\n5. 卡牌加的是指挥点，不是槽")
    g, p1, p2 = new_game()
    g.start_turn()
    g.deploy_unit(p1, DB["第95山地工兵营"])
    g.end_turn()
    g.start_turn()                       # 对手
    g.end_turn()
    g.start_turn()                       # 我方：槽 +1，单位再 +1 指挥点
    slots = p1.cp_slots
    check("第95 只加指挥点", p1.kredits == slots + 1, (p1.kredits, slots))
    check("第95 不改槽", p1.cp_slots == slots, p1.cp_slots)

    # 生产（中立衍生指令）：+1 指挥点，不改槽
    before = p1.cp_slots
    p1.hand[:] = [core.NEUTRAL_PRODUCTION]
    g.play_card(p1, 0)
    check("生产 +1 指挥点", p1.kredits == slots + 2, p1.kredits)
    check("生产不改槽", p1.cp_slots == before, p1.cp_slots)

    print("\n6. 双方槽互相独立")
    g, p1, p2 = new_game()
    g.start_turn()
    next_turn(g)
    next_turn(g)
    check("两回合后 我方 2 / 对手 1",
          (p1.cp_slots, p2.cp_slots) == (2, 1), (p1.cp_slots, p2.cp_slots))

    print("\n7. 结束的对局不再涨槽")
    g, p1, p2 = new_game()
    g.start_turn()
    g.over = True
    before = p1.cp_slots
    g.start_turn()
    check("over 后 start_turn 不涨槽", p1.cp_slots == before, p1.cp_slots)


def glossary():
    print("\n8. 关键词说明：指挥点（不再是 Kredits）")
    zh = dict(core.keyword_guide("zh"))["kw_group_term"]
    names = [n for n, _d in zh]
    check("中文术语叫「指挥点」", "指挥点" in names, names)
    check("不再出现 Kredits 词条", "Kredits" not in names, names)
    desc = dict(zh)["指挥点"]
    check("说明里提到槽与 12/24", "槽" in desc and "12" in desc and "24" in desc, desc)
    en = dict(core.keyword_guide("en"))["kw_group_term"]
    check("英文仍叫 Kredits（官方英文名）", "Kredits" in [n for n, _d in en],
          [n for n, _d in en])
    check("中文界面不残留 Kredits 文案",
          "Kredits" not in i18n.t("my_info", name="x", nation="y", hq=1,
                                  kr=1, slots=1, deck=1, perk="", counters=""))


def ui_strings():
    print("\n9. 信息条文案（三语言都带 {slots}）")
    for lang in ("zh", "en", "ja"):
        for key in ("my_info", "foe_info"):
            s = i18n.LANGS[lang][key]
            check("%s/%s 含 {slots}" % (lang, key), "{slots}" in s, s)
    txt = i18n.t("my_info", name="你", nation="德国", hq=20, kr=3, slots=5,
                 deck=30, perk="", counters="")
    check("中文信息条显示「指挥点 3/5」", "指挥点 3/5" in txt, txt)

    print("\n10. 棋盘上的指挥点槽菱形")
    import pygame
    import kards_board as board
    pygame.init()
    surf = pygame.Surface((400, 60))
    surf.fill((0, 0, 0))
    rect = pygame.Rect(0, 0, 400, 56)

    class Me:
        cp_slots = 5
        kredits = 3

    board.PygameBoard._draw_cp_slots(object(), surf, rect, Me())
    gold = board.C(board.GOLD)
    px = []
    for x in range(400):
        for y in range(56):
            if surf.get_at((x, y))[:3] == gold:
                px.append((x, y))
    check("实心菱形画出来了（金像素 > 0）", len(px) > 20, len(px))
    xs = sorted({x for x, _y in px})
    check("菱形靠右排布", bool(xs) and min(xs) > 200, (min(xs) if xs else None))
    # 在菱形中线那一行数「金色连续段」= 实心个数
    row = [1 if surf.get_at((x, 12))[:3] == gold else 0 for x in range(400)]
    runs, prev = 0, 0
    for v in row:
        if v and not prev:
            runs += 1
        prev = v
    check("3 个实心（当前指挥点）", runs == 3, runs)

    surf2 = pygame.Surface((400, 60))
    surf2.fill((0, 0, 0))

    class Zero:
        cp_slots = 0
        kredits = 0

    board.PygameBoard._draw_cp_slots(object(), surf2, rect, Zero())
    check("0 槽不画东西（开局不显示空槽）",
          all(surf2.get_at((x, y))[:3] == (0, 0, 0)
              for x in range(0, 400, 7) for y in range(0, 56, 5)))


def main():
    slots_rules()
    glossary()
    ui_strings()
    print("\n" + "=" * 52)
    print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
