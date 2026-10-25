# -*- coding: utf-8 -*-
"""把 pygame 对战界面渲染成 PNG，用来**肉眼检查**排版/数字。

    python debug/shot_board.py [输出目录]

为什么要有：棋盘是画出来的，断言只能测逻辑，测不出"费用圆里数字不对"
"按钮压在别的东西上"这类问题。截图 + 人眼看是最快的验证方式。
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame  # noqa: E402

import kards_board as B  # noqa: E402
import kards_engine as core  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "shots")
os.makedirs(OUT, exist_ok=True)


class App:
    def __init__(self, g):
        self.game = g
        self.busy = False
        self.anim_enabled = True
        self.fast_ai = False
        self.intents = []

    def pyboard_intent(self, act):
        self.intents.append(act)

    def add_log(self, msg):
        pass


def make(seed=7):
    random.seed(seed)
    db = core.card_database()
    p1 = core.Player("你", "德国", core.build_deck("德国", db))
    p2 = core.Player("AI", "苏联", core.build_deck("苏联", db))
    g = core.Game(p1, p2, interactive=False)
    g.log = lambda *a, **k: None
    g.draw_cards(p1, core.START_HP)
    g.draw_cards(p2, core.START_HP)
    g.current = p1
    g.start_turn()
    return g


def unit(g, p, t="步兵", pos="后方"):
    card = next(c for c in core.card_database().values()
                if getattr(c, "kind", "") == "unit" and c.unit_type == t)
    u = g.deploy_unit(p, card)
    u.fresh_deploy = False
    u.can_attack = True
    u.attacks_made = 0
    u.operate = 0
    u.position = pos
    return u


def main():
    pygame.init()
    g = make()
    me, foe = g.players[0], g.players[1]
    me.kredits = 4
    unit(g, foe, "步兵", "前线")
    unit(g, foe, "坦克", "后方")
    unit(g, me, "步兵", "前线")
    app = App(g)
    b = B.PygameBoard(app, game=g, on_intent=app.pyboard_intent)
    b.anim_enabled = True
    b.sync()
    surf = pygame.Surface((b.W, b.H))

    print("手牌费用（引擎 get_cost / 卡面 cost）:")
    for i, c in enumerate(me.hand):
        print(f"  [{i}] {c.name:<16} kind={c.kind:<8} cost={c.cost}"
              f" get_cost={g.get_cost(c, me)} ready={b.hand_refs[i].ready}")
    print(f"我方 kredits={me.kredits}  敌方 kredits={foe.kredits}")

    def shot(name):
        b.draw(surf)
        pygame.image.save(surf, os.path.join(OUT, name))
        print("  写出", name)

    shot("01_常规.png")
    b.drag = {"kind": "hand", "idx": b.hand_refs[0].idx,
              "card": b.hand_refs[0].card, "pos": (500, 300),
              "sx": 100, "sy": 700, "moved": True}
    shot("02_拖拽中.png")
    b.drag = None
    b.hover_ref = b.hand_refs[0]
    shot("03_悬停提示.png")
    b.hover_ref = None
    b.pause = True
    shot("04_暂停菜单.png")
    b.pause = False
    # 结算：先炸总部（爆炸阶段），再出胜负大字（full 阶段）
    b.show_end_animation(True, None, nation="德国")
    b.step(260)              # 爆炸中（火球/冲击波最亮的时候）
    shot("05_结算爆炸.png")
    b.step(b.EXPLODE_MS)     # 推进到 full 阶段
    shot("06_结算胜利.png")
    # 失败：炸我方总部
    b2 = B.PygameBoard(app, game=g, on_intent=app.pyboard_intent)
    b2.anim_enabled = True
    b2.sync()
    b2.show_end_animation(False, None, nation="德国")
    b2.step(260)
    b2.draw(surf)
    pygame.image.save(surf, os.path.join(OUT, "07_战败爆炸_我方总部.png"))
    print("  写出 07_战败爆炸_我方总部.png")
    # 投降：我方总部同样爆炸，但文案是「举旗投降」
    b3 = B.PygameBoard(app, game=g, on_intent=app.pyboard_intent)
    b3.anim_enabled = True
    b3.sync()
    g.conceded = g.players[0]        # 我方投降
    b3.show_end_animation(False, None, nation="德国")
    b3.step(260)
    b3.draw(surf)
    pygame.image.save(surf, os.path.join(OUT, "08_投降爆炸_我方总部.png"))
    print("  写出 08_投降爆炸_我方总部.png")

    # 开场动画（两军对冲）：滑入 / 对撞 / VS 三帧
    b4 = B.PygameBoard(app, game=g, on_intent=app.pyboard_intent)
    b4.anim_enabled = True
    b4.sync()
    b4.start_intro()
    b4.step(350)
    b4.draw(surf)
    pygame.image.save(surf, os.path.join(OUT, "09_开场_滑入.png"))
    print("  写出 09_开场_滑入.png")
    b4.step(board_intro_to_clash(b4))
    b4.draw(surf)
    pygame.image.save(surf, os.path.join(OUT, "10_开场_对撞.png"))
    print("  写出 10_开场_对撞.png")
    b4.step(500)
    b4.draw(surf)
    pygame.image.save(surf, os.path.join(OUT, "11_开场_VS.png"))
    print("  写出 11_开场_VS.png")
    b4.intro = None

    # 部署飞行令牌（卡牌造型 + 拖尾）半途帧
    b5 = B.PygameBoard(app, game=g, on_intent=app.pyboard_intent)
    b5.anim_enabled = True
    b5.sync()
    u5 = me.board[0]
    b5.anim_entry(u5)
    b5.step(240)                 # 飞到一半
    b5.draw(surf)
    pygame.image.save(surf, os.path.join(OUT, "12_部署飞行中.png"))
    print("  写出 12_部署飞行中.png")
    print("输出目录:", OUT)


def board_intro_to_clash(b):
    """距离对撞时刻还差多少毫秒（截图工具用）"""
    el = b.t_now - b.intro["t0"]
    return max(0, b.INTRO_CLASH_MS - el)


if __name__ == "__main__":
    main()
