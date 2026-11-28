# -*- coding: utf-8 -*-
"""召集 / 进军 词条测试：词条移动不耗行动费、不占本回合移动；
占线规则仍然生效；部署与指令卡正确落空/生效。

运行: python debug/test_keywords_move.py
"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kards_engine as core

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f"  [{detail}]" if detail and not cond else ""))


def make_game(n1="德国", n2="苏联"):
    db = core.card_database()
    p1 = core.Player("甲", n1, [db["第一步兵团"]] * core.DECK_SIZE)
    p2 = core.Player("乙", n2, [db["第一步兵团"]] * core.DECK_SIZE)
    g = core.Game(p1, p2, interactive=False)
    g.draw_cards(p1, 3)
    g.draw_cards(p2, 3)
    return g, p1, p2, db


def deploy(g, p, card, pos="后方"):
    with contextlib.redirect_stdout(io.StringIO()):
        u = g.deploy_unit(p, card)
    u.position = pos
    return u


def main():
    print("=" * 60)
    print("召集 / 进军 词条测试")
    print("=" * 60)

    # ---------- 词条移动的基本语义 ----------
    g, p1, p2, db = make_game()
    tank = deploy(g, p1, db["四号坦克"], "前线")
    tank.moved = True                      # 先模拟"本回合已移动过"
    p1.kredits = 0                         # 没钱也要能动 —— 词条不耗行动费
    ok = g.keyword_move(tank, "后方", source="召集")
    check("已移动过的单位仍可被[召集]（不占本回合移动）",
          ok and tank.position == "后方")
    check("[召集] 不扣 Kredits", p1.kredits == 0)

    tank.position = "后方"
    ok = g.keyword_move(tank, "后方", source="召集")
    check("已在支援阵线时[召集]落空", (not ok) and tank.position == "后方")

    # ---------- 占线规则仍然生效 ----------
    g2, q1, q2, _ = make_game()
    enemy_front = deploy(g2, q2, db["第一步兵团"], "前线")   # 敌方占线
    adv = deploy(g2, q1, db["四号坦克"], "后方")
    ok = g2.keyword_move(adv, "前线", source="进军")
    check("敌方占线时[进军]被拒", (not ok) and adv.position == "后方")
    with contextlib.redirect_stdout(io.StringIO()):
        g2.destroy_unit(enemy_front)       # 清掉占线单位
    ok = g2.keyword_move(adv, "前线", source="进军")
    check("清线后[进军]成功", ok and adv.position == "前线")
    check("[进军] 不改 moved 标记", adv.moved is False)

    # ---------- 部署效果：四号坦克 [召集] 敌方最强前线单位 ----------
    g3, r1, r2, db3 = make_game("德国", "苏联")
    t1 = deploy(g3, r2, db3["T-34坦克"], "前线")
    t2 = deploy(g3, r2, db3["T-34坦克"], "前线")
    t1.attack, t1.defense = 7, 7           # t1 是最强的前线敌方单位
    t2.attack, t2.defense = 3, 3
    with contextlib.redirect_stdout(io.StringIO()):
        u4 = g3.deploy_unit(r1, db3["四号坦克"])
        g3.on_deploy(u4)                   # deploy_unit 不含部署效果，play_card 才调
    check("部署[召集]：最强的敌方前线单位被拉回支援阵线",
          t1.position == "后方" and t2.position == "前线")

    # ---------- 指令卡：总攻命令（进军）/ 战术撤退（召集） ----------
    g4, s1, s2, db4 = make_game("苏联", "英国")
    back = deploy(g4, s1, db4["第一步兵团"], "后方")
    front = deploy(g4, s1, db4["第一步兵团"], "前线")
    front.defense = 1                      # 最危急的前线单位
    front.moved = True
    order_adv = db4["总攻命令"]
    check("总攻命令注册为[进军]指令", order_adv.kind == "order"
          and "进军" in order_adv.desc)
    with contextlib.redirect_stdout(io.StringIO()):
        order_adv.effect(g4, s1)
    check("[进军] 指令：最强的后方友方单位上前线",
          back.position == "前线")

    order_rally = db4["战术撤退"]
    with contextlib.redirect_stdout(io.StringIO()):
        order_rally.effect(g4, s1)
    check("[召集] 指令：防御最低的前线友方单位撤回",
          front.position == "后方")

    # 落空路径
    with contextlib.redirect_stdout(io.StringIO()):
        for u in list(s1.board):
            g4.destroy_unit(u)
        order_rally.effect(g4, s1)
        order_adv.effect(g4, s1)
    check("没有可调动单位时指令落空不报错", True)

    # ---------- 词条登记与多语言 ----------
    names = {k for k, _, _ in core.KEYWORD_GUIDE}
    check("速查表收录[召集]/[进军]", {"召集", "进军"} <= names)
    check("关键词说明收录[召集]/[进军]",
          "召集" in core.KEYWORD_DESC and "进军" in core.KEYWORD_DESC)
    check("译文表收录 en/ja",
          core.KEYWORD_I18N["召集"]["en"] == "Rally"
          and core.KEYWORD_I18N["进军"]["ja"] == "進軍")
    check("四号坦克卡面带[召集]关键词",
          "召集" in db3["四号坦克"].keywords)
    check("kw_label/kw_desc 可取译文",
          core.kw_label("进军", "ja") == "進軍" and bool(core.kw_desc("召集", "en")))

    print("=" * 60)
    print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print("失败项:", *FAIL, sep="\n  - ")
        sys.exit(1)
    print("全部通过 ✓")


if __name__ == "__main__":
    main()
