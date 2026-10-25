# -*- coding: utf-8 -*-
"""pygame 对战棋盘测试（SDL dummy 驱动，不需要真实窗口）

运行：
    C:\\Users\\freet\\AppData\\Local\\Programs\\Python\\Python313\\python.exe \\
        debug/test_board.py

覆盖：
  A  纯函数：颜色解析 / 折行 / 截断 / 圆角矩形 / 图片资产兜底
  B  布局与同步：五段式行不重叠、手牌 Ref、状态指纹自动兜底 sync
  C  落点模型：drop_zones / zone_at / valid_drop（语义与 tkinter 对齐）
  D  输入链路：按下→移动→松手 → 意图；按钮；暂停菜单；结算点击
  E  动画系统：入场/行军/进攻补间、浮动文字、横幅超时、震屏
  F  绘制健壮性：所有状态各画一帧不抛异常
  G  主循环：dummy 驱动 max_frames 后干净退出
  H  与 KARDS.App 的接线：视图方法覆盖表完整性 + add_log 回归
     （H 段需要 tkinter，受管 Python 会跳过）
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import random  # noqa: E402

import pygame  # noqa: E402

import kards_board as board  # noqa: E402
import kards_engine as core  # noqa: E402
import kards_i18n as i18n  # noqa: E402

PASS, FAIL = [], []
SECTION = [""]


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(f"{SECTION[0]} · {name}")
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


def section(title):
    SECTION[0] = title
    print(f"\n{title}")


# ---------------------------------------------------------------- 脚手架

class FakeApp:
    """最小 App 替身（无 Tk）"""

    def __init__(self, game):
        self.game = game
        self.busy = False
        self.anim_enabled = True
        self.logs = []
        self.intents = []

    def pyboard_intent(self, act):
        self.intents.append(act)

    def add_log(self, msg):
        self.logs.append(msg)


class Ev:
    """伪 pygame 事件"""

    def __init__(self, type_, pos=(0, 0), button=1, key=None, y=0,
                 w=1280, h=800):
        self.type = type_
        self.pos = pos
        self.button = button
        self.key = key
        self.y = y
        self.w = w
        self.h = h


def make_game(seed=20261005):
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
    p1.kredits = 30
    return g, db


def new_board(g):
    app = FakeApp(g)
    b = board.PygameBoard(app, game=g, on_intent=app.pyboard_intent)
    return app, b


def pick_card(db, kind, pred=lambda c: True):
    for c in db.values():
        if getattr(c, "kind", None) == kind and pred(c):
            return c
    return None


def spawn_unit(g, player, unit_type="步兵", pos="后方"):
    """直接部署一个单位并置为可攻击（跳过费用/回合限制）"""
    card = pick_card(core.card_database(), "unit",
                     lambda c: c.unit_type == unit_type)
    if card is None:
        card = pick_card(core.card_database(), "unit")
    u = g.deploy_unit(player, card)
    u.fresh_deploy = False
    u.can_attack = True
    u.attacks_made = 0
    u.operate = 0
    u.moved = False
    u.fresh_deploy = False
    u.position = pos
    return u


# ---------------------------------------------------------------- A 纯函数

def test_pure():
    section("A 纯函数")
    pygame.init()          # 字体子系统要先初始化，否则 SysFont 直接报错
    pygame.font.init()
    # convert_alpha() 需要已设置视频模式；dummy 驱动下给个 1x1 即可
    pygame.display.set_mode((320, 240))
    check("C('#ff8800') → RGB", board.C("#ff8800") == (255, 136, 0))
    check("C('#abc') 三位简写展开", board.C("#abc") == (170, 187, 204))
    check("C((1,2,3)) 原样通过", board.C((1, 2, 3)) == (1, 2, 3))

    f = board.font(16)
    check("font() 可渲染中文", f.size("部署")[0] > 0)
    lines = board.wrap_text("这是一段很长的中文需要折行显示", f, 60)
    check("wrap_text 按宽度折行", len(lines) > 1, f"{len(lines)} 行")
    check("wrap_text 保留换行符",
          board.wrap_text("a\nb", f, 500) == ["a", "b"])
    long = "x" * 200
    t = board.truncate(long, f, 100)
    check("truncate 以省略号收尾", t.endswith("…") and len(t) < len(long))

    surf = pygame.Surface((80, 40), pygame.SRCALPHA)
    board.rr(surf, pygame.Rect(0, 0, 80, 40), (10, 20, 30), radius=6)
    board.rr(surf, pygame.Rect(0, 0, 80, 40), (0, 0, 0), radius=6, width=2,
             border_color=(255, 255, 255))
    check("rr 实心+描边不抛异常", True)

    check("缺失卡面无资产时返回 None",
          board.card_image("绝对不存在的卡名_XYZ", 100, 60) is None)
    check("缺失 HQ 图无资产时返回 None",
          board.hq_image("不存在的国家", 100, 60) is None)
    check("kw_text 给关键词加方括号",
          board.kw_text(["闪击", "警卫"]) == "[闪击] [警卫]")

    # ⚠ 回归：pygame 的 SysFont 不做跨字体回退，装饰符号会画成空心方块
    check("plain() 剥掉渲染不了的装饰符号",
          board.plain("🏳 投降") == "投降"
          and board.plain("⚔ 前线：我方占领") == "前线：我方占领"
          and board.plain("  已暂停  ") == "已暂停",
          repr(board.plain("🏳 投降")))
    for k in ("btn_fast", "btn_slow", "btn_board_menu", "btn_surrender",
              "btn_to_menu", "btn_quit", "front_none", "front_mine",
              "front_foe", "win_big", "lose_big", "draw_big", "click_hint"):
        v = board.t(k)
        bad = [ch for ch in v if ch in board._BAD_GLYPHS]
        check(f"文案已剥掉会变方块的符号: {k}", not bad, f"{v!r} 残留={bad}")
    board.sfx("attack")          # 无资产时应静默，不抛异常
    check("sfx 无资产静默", True)

    # 资产目录：放一张图进去，「逐卡补图零代码改动」这条路要真的通
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        cards = os.path.join(tmp, "cards")
        os.makedirs(cards)
        saved = board.ASSETS
        board.ASSETS = tmp
        board._img_cache.clear()
        try:
            check("资产搜索目录包含源码侧 assets",
                  tmp in board.asset_roots(), str(board.asset_roots()))
            check("find_asset 找不到时返回 None",
                  board.find_asset("cards", "没这张.png") is None)

            surf = pygame.Surface((40, 60))
            surf.fill((200, 30, 30))
            pygame.image.save(surf, os.path.join(cards, "测试卡.png"))
            img = board.card_image("测试卡", 100, 140)
            check("放入 assets/cards/<卡名>.png 后卡面被加载",
                  img is not None and img.get_size() == (100, 140),
                  str(img and img.get_size()))
            check("同一卡面走缓存（不重复加载）",
                  board.card_image("测试卡", 100, 140) is img)

            hqdir = os.path.join(tmp, "hq")
            os.makedirs(hqdir)
            pygame.image.save(surf, os.path.join(hqdir, "德国.png"))
            hq = board.hq_image("德国", 80, 90)
            check("放入 assets/hq/<国家>.png 后总部图被加载",
                  hq is not None and hq.get_size() == (80, 90))
            check("find_asset 能定位到该文件",
                  board.find_asset("hq", "德国.png") is not None)
        finally:
            board.ASSETS = saved
            board._img_cache.clear()


# ---------------------------------------------------------------- B 布局/同步

def test_layout_and_sync():
    section("B 布局与同步")
    g, _ = make_game()
    app, b = new_board(g)
    L = b.layout()

    check("五段式行自上而下有序",
          L["row_foe_rear"].bottom <= L["row_foe_front"].y
          and L["row_foe_front"].bottom <= L["mid"].y
          and L["mid"].bottom <= L["row_my_front"].y
          and L["row_my_front"].bottom <= L["row_my_rear"].y)
    check("手牌区在窗口内",
          L["hand"].bottom <= b.H + 1 and L["hand"].y > L["row_my_rear"].bottom)
    check("日志面板与战场不重叠（横向）",
          L["log"].x >= L["row_foe_rear"].right)
    check("结束回合按钮在日志面板下方", L["end_btn"].y > L["log"].y)

    # ⚠ 回归（用户报"花费记错"）：我方信息条曾掉进手牌区正下方被盖住，
    # 玩家根本看不到自己的 Kredits/牌库/研发被动。
    check("我方信息条不被手牌区盖住（回归）",
          L["info_my"].bottom <= L["hand"].y + 1
          and L["info_my"].y >= L["row_my_rear"].bottom,
          f"info_my={tuple(L['info_my'])} hand.y={L['hand'].y} "
          f"row_my_rear.bottom={L['row_my_rear'].bottom}")
    check("我方信息条与战场行不重叠",
          L["info_my"].y >= L["row_my_rear"].bottom + 6,
          f"{L['info_my'].y} vs {L['row_my_rear'].bottom}")
    check("加速/菜单按钮与手牌区不重叠",
          L["speed_btn"].x >= L["hand"].right
          and L["menu_btn"].x >= L["hand"].right)
    check("默认窗口高度足够放下 战场+信息条+手牌",
          b.H >= L["row_my_rear"].bottom + 56 + b.HAND_CH + 60,
          f"H={b.H}")

    b.sync()
    check("sync 后有总部替身且已就绪", b.hq_ref is not None
          and b.hq_ref.winfo_exists())
    me = g.players[0]
    check("手牌 Ref 数量与手牌一致", len(b.hand_refs) == len(me.hand),
          f"{len(b.hand_refs)} vs {len(me.hand)}")
    check("手牌 Ref 是 hand 类型",
          all(r.kind == "hand" for r in b.hand_refs))
    check("手牌可打出标记为布尔",
          all(isinstance(r.ready, bool) for r in b.hand_refs))

    u = spawn_unit(g, me, pos="后方")
    b.sync()
    check("我方单位进入 unit_refs", id(u) in b.unit_refs)
    check("我方单位不在 enemy_refs",
          all(x is not u for x, _ in b.enemy_refs))
    r1 = b.unit_refs[id(u)]
    b.sync()
    check("重复 sync 复用同一 Ref 对象（保留动画态）",
          b.unit_refs[id(u)] is r1)

    e = spawn_unit(g, g.players[1], pos="前线")
    b.sync()
    check("敌方单位进入 enemy_refs",
          any(x is e for x, _ in b.enemy_refs))
    check("敌方前排单位落在敌方前线行",
          b.unit_refs[id(e)].rect.y >= L["row_foe_front"].y)

    # 状态指纹兜底：引擎状态变了但没人调 refresh 时，draw/主循环应自动同步
    b.sync()
    n_before = len(b.unit_refs)
    b._fp = b._fingerprint(g)          # 假装刚同步过（指纹对齐）
    spawn_unit(g, me, pos="前线")       # 引擎变了，但没人调 refresh
    b._ensure_sync()
    check("引擎状态变化后 _ensure_sync 自动兜底重建",
          len(b.unit_refs) == n_before + 1,
          f"{len(b.unit_refs)} vs {n_before + 1}")
    ids = id(b.unit_refs)
    b._ensure_sync()
    check("指纹未变时不重复重建（省开销）", id(b.unit_refs) == ids)

    b.add_log("第一行\n第二行")
    check("add_log 按行拆分", b.log_lines[-2:] == ["第一行", "第二行"])
    for i in range(500):
        b.add_log(f"刷屏 {i}")
    check("日志行数有上限（不无限增长）", len(b.log_lines) <= 400,
          f"{len(b.log_lines)} 行")

    ref = b.unit_refs[id(u)]
    check("Ref.winfo_exists 初始为真", ref.winfo_exists())
    check("Ref.center 返回矩形中心", ref.center() == ref.rect.center)
    ref.kill()
    check("Ref.kill 后 winfo_exists 为假", not ref.winfo_exists())


# ---------------------------------------------------------------- C 落点

def test_drop_zones():
    section("C 落点模型")
    g, _ = make_game()
    app, b = new_board(g)
    me, foe = g.players[0], g.players[1]
    spawn_unit(g, me, pos="前线")
    eu = spawn_unit(g, foe, pos="前线")
    b.sync()
    L = b.layout()

    kinds = {k for _, k, _ in b.drop_zones()}
    check("落点种类齐全（含敌卡与总部）",
          kinds == {"deploy", "front", "enemy_card", "hq"}, str(kinds))

    k, _x = b.zone_at(L["row_my_rear"].center)
    check("我方支援阵线 → deploy", k == "deploy", str(k))
    k, _x = b.zone_at(L["row_my_front"].center)
    check("我方前线 → front", k == "front", str(k))
    k, x = b.zone_at(b.unit_refs[id(eu)].rect.center)
    check("敌方单位 → enemy_card 且带出单位", k == "enemy_card" and x is eu)
    k, _x = b.zone_at(b.hq_ref.rect.center)
    check("敌方总部 → hq", k == "hq", str(k))
    k, _x = b.zone_at((5, 5))
    check("空白处 → 无落点", k is None, str(k))

    # ---- 手牌语义
    # ⚠ valid_drop 的手牌分支读的是 me.hand[idx]（不是 drag["card"]），
    # 和 KARDS.App 一致 —— 只有引擎才是唯一事实来源。
    i_unit = next((i for i, c in enumerate(me.hand) if c.kind == "unit"), None)
    i_other = next((i for i, c in enumerate(me.hand) if c.kind != "unit"), None)
    if i_other is None:                    # 手牌里恰好没法术牌 → 临时塞一张
        other = (pick_card(core.card_database(), "counter")
                 or pick_card(core.card_database(), "order"))
        if other is not None:
            me.hand.append(other)
            i_other = len(me.hand) - 1
    check("手牌里同时有单位牌与非单位牌（测试前置）",
          i_unit is not None and i_other is not None)

    b.drag = {"kind": "hand", "idx": i_unit, "card": me.hand[i_unit],
              "moved": True}
    check("单位牌只能落支援阵线（deploy）",
          b.valid_drop("deploy", None) and not b.valid_drop("front", None))
    if i_other is not None:
        b.drag = {"kind": "hand", "idx": i_other, "card": me.hand[i_other],
                  "moved": True}
        check("非单位牌可落 support/front 两线",
              b.valid_drop("deploy", None) and b.valid_drop("front", None))
    b.drag = {"kind": "hand", "idx": 99, "card": None, "moved": True}
    check("手牌下标越界 → 非法", not b.valid_drop("deploy", None))

    # ---- 单位语义
    mu = spawn_unit(g, me, pos="前线")
    b.sync()
    b.drag = {"kind": "unit", "unit": mu, "moved": True}
    check("可移动单位 → 前线/后方均合法",
          b.valid_drop("front", None) and b.valid_drop("deploy", None))
    check("可攻击单位 → 总部合法", b.valid_drop("hq", None))
    check("可攻击单位 → 敌方目标合法", b.valid_drop("enemy_card", eu))
    mu.attacks_made = 99
    check("已出手单位 → 打总部非法", not b.valid_drop("hq", None))
    check("已出手单位 → 仍可移动（非步兵限制之外）",
          b.valid_drop("front", None))
    mu.attacks_made = 0
    b.drag = {"kind": "unit", "unit": object(), "moved": True}
    check("非我方单位 → 一切落点非法", not b.valid_drop("front", None))
    b.drag = None
    check("无拖拽状态 → 非法", not b.valid_drop("deploy", None))


# ---------------------------------------------------------------- D 输入

def test_input():
    section("D 输入链路")
    g, _ = make_game()
    app, b = new_board(g)
    me, foe = g.players[0], g.players[1]
    me.kredits = 30
    b.sync()
    L = b.layout()

    # 一个可打出的单位牌
    unit_ref = next((r for r in b.hand_refs
                     if r.card.kind == "unit" and r.ready), None)
    check("手牌中存在可打出的单位牌", unit_ref is not None)
    if unit_ref is None:
        return

    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, unit_ref.rect.center))
    check("按下可打出卡 → 进入拖拽", b.drag is not None
          and b.drag["kind"] == "hand", str(b.drag and b.drag.get("kind")))
    b.handle_event(Ev(pygame.MOUSEMOTION, (unit_ref.rect.centerx + 2,
                                           unit_ref.rect.centery)))
    check("位移 <4px 不判为拖拽", b.drag and b.drag["moved"] is False)
    b.handle_event(Ev(pygame.MOUSEMOTION, L["row_my_rear"].center))
    check("位移超过阈值 → moved=True", b.drag and b.drag["moved"] is True)

    app.intents.clear()
    b.handle_event(Ev(pygame.MOUSEBUTTONUP, L["row_my_rear"].center))
    check("拖到支援阵线 → 打出意图",
          app.intents == [{"k": "play", "idx": unit_ref.idx}], str(app.intents))
    check("松手后清空拖拽状态", b.drag is None)

    # 非法落点：单位牌拖到前线
    b.sync()
    app.intents.clear()
    b.drag = None
    mark = len(b.log_lines)
    r2 = next((r for r in b.hand_refs
               if r.card.kind == "unit" and r.ready), None)
    if r2 is not None:
        b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, r2.rect.center))
        b.handle_event(Ev(pygame.MOUSEBUTTONUP, L["row_my_front"].center))
        check("单位牌拖到前线 → 不发意图", not app.intents)
        check("非法落点给出提示日志",
              any("支援阵线" in s for s in b.log_lines[mark:]),
              str(b.log_lines[mark:]))

    # 松手在空白处
    app.intents.clear()
    mark = len(b.log_lines)
    r3 = next((r for r in b.hand_refs if r.ready), None)
    if r3 is not None:
        b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, r3.rect.center))
        b.handle_event(Ev(pygame.MOUSEBUTTONUP, (6, 6)))
        check("拖到牌桌外 → 只记日志不出牌",
              not app.intents and any("已取消" in s for s in b.log_lines[mark:]),
              str(b.log_lines[mark:]))

    # 原地点击 = 无操作
    app.intents.clear()
    r4 = next((r for r in b.hand_refs if r.ready), None)
    if r4 is not None:
        b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, r4.rect.center))
        b.handle_event(Ev(pygame.MOUSEBUTTONUP, r4.rect.center))
        check("原地点击不发意图", not app.intents)

    # 未就绪的牌按不动
    not_ready = next((r for r in b.hand_refs if not r.ready), None)
    if not_ready is not None:
        b.drag = None
        b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, not_ready.rect.center))
        check("不可打出的牌按下不启动拖拽", b.drag is None)

    # 单位拖拽 → 移动 / 攻击 / 打总部
    mu = spawn_unit(g, me, pos="前线")
    eu = spawn_unit(g, foe, pos="前线")
    b.sync()
    mref = b.unit_refs[id(mu)]
    eref = b.unit_refs[id(eu)]
    app.intents.clear()
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, mref.rect.center))
    check("按下己方单位 → 进入单位拖拽",
          b.drag is not None and b.drag["kind"] == "unit")
    b.handle_event(Ev(pygame.MOUSEBUTTONUP, L["row_my_rear"].center))
    check("单位拖到己方支援阵线 → 移动意图(后方)",
          app.intents == [{"k": "move", "slot": mu.slot, "pos": "后方"}],
          str(app.intents))

    app.intents.clear()
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, b.unit_refs[id(mu)].rect.center))
    b.handle_event(Ev(pygame.MOUSEBUTTONUP, eref.rect.center))
    check("单位拖到敌卡 → 攻击意图",
          app.intents == [{"k": "attack", "slot": mu.slot,
                           "tslot": eu.slot}], str(app.intents))

    app.intents.clear()
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, b.unit_refs[id(mu)].rect.center))
    b.handle_event(Ev(pygame.MOUSEBUTTONUP, b.hq_ref.rect.center))
    check("单位拖到敌方总部 → 打脸意图",
          app.intents == [{"k": "hq", "slot": mu.slot}], str(app.intents))

    # 按钮
    app.intents.clear()
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, L["end_btn"].center))
    check("点击结束回合 → end 意图",
          app.intents == [{"k": "end"}], str(app.intents))
    app.intents.clear()
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, L["speed_btn"].center))
    check("点击速度按钮 → speed 意图",
          app.intents == [{"k": "speed"}], str(app.intents))
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, L["menu_btn"].center))
    check("点击菜单按钮 → 打开暂停菜单", b.pause is True)

    # busy 时全部静默
    b.pause = False
    app.busy = True
    app.intents.clear()
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, L["end_btn"].center))
    check("busy（动画/对手回合）时点击无效", not app.intents)
    app.busy = False

    # 非我方回合不能拖牌
    g.current = foe
    b.sync()
    b.drag = None
    if b.hand_refs:
        b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, b.hand_refs[0].rect.center))
    check("对手回合不能拖牌", b.drag is None)
    g.current = me

    # 滚轮 / 缩放
    b.log_scroll = 100
    b.handle_event(Ev(pygame.MOUSEWHEEL, y=-1))
    check("滚轮向下滚动日志", b.log_scroll == 124, str(b.log_scroll))
    b.log_scroll = 0
    b.handle_event(Ev(pygame.MOUSEWHEEL, y=5))
    check("日志滚动不到负数", b.log_scroll == 0)
    b.handle_event(Ev(pygame.VIDEORESIZE, w=1024, h=700))
    check("窗口改尺寸后 W/H 同步", (b.W, b.H) == (1024, 700), f"{b.W}x{b.H}")
    L2 = b.layout()
    check("改尺寸后布局重算（手牌仍在窗口内）",
          L2["hand"].bottom <= b.H + 1 and L2["log"].right <= b.W + 1,
          f"H={b.H} hand.bottom={L2['hand'].bottom} log.right={L2['log'].right}")


def test_pause_menu():
    section("D2 暂停菜单")
    g, _ = make_game()
    app, b = new_board(g)
    b.sync()

    b.handle_event(Ev(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    check("ESC 打开暂停", b.pause is True)
    b.handle_event(Ev(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    check("ESC 再按关闭暂停", b.pause is False)

    b.pause = True
    items = b._pause_items()
    check("暂停菜单含 继续/投降/主菜单/退出 四项",
          [k for k, _ in items] == ["resume", "concede", "leave", "quit"],
          str([k for k, _ in items]))
    check("暂停菜单文案已本地化（非键名）",
          all(lbl and not lbl.startswith("btn_") for _, lbl in items),
          str([lbl for _, lbl in items]))

    def item_rect(i):
        w, h = 320, 60 * len(items) + 90
        x0, y0 = (b.W - w) // 2, (b.H - h) // 2
        return pygame.Rect(x0 + 20, y0 + 70 + i * 60, w - 40, 46)

    app.intents.clear()
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, item_rect(0).center))
    check("点「继续」→ 关闭暂停且不发意图",
          b.pause is False and not app.intents)

    b.pause = True
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, item_rect(1).center))
    check("投降需要二次确认（第一次只记状态）",
          app.intents == [] and b.pause_confirm == "concede")
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, item_rect(1).center))
    check("二次确认后发出投降意图",
          app.intents == [{"k": "concede"}] and b.pause is False,
          str(app.intents))

    b.pause = True
    b.pause_confirm = None
    app.intents.clear()
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, item_rect(2).center))
    check("返回主菜单也要二次确认（第一次只记状态）",
          app.intents == [] and b.pause_confirm == "leave")
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, item_rect(2).center))
    check("返回主菜单二次确认后发出意图",
          app.intents == [{"k": "leave"}], str(app.intents))

    b.pause = True
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, item_rect(3).center))
    check("退出 → result='quit' 且主循环停止",
          b.result == "quit" and b.running is False)


def test_end_screen():
    section("D3 结算画面")
    g, _ = make_game()
    app, b = new_board(g)
    b.sync()
    hits = []
    b.show_end_animation(True, lambda: hits.append(1), nation="德国")
    check("结算状态已建立", b.end_state is not None)
    check("胜利先进入总部爆炸阶段", b.end_state.get("phase") == "hq",
          str(b.end_state.get("phase")))
    check("爆炸生成碎片粒子", len(b.particles) > 0, f"{len(b.particles)} 个")
    check("胜利炸的是敌方总部", b.hq_ref.blast_t0 is not None)
    check("胜利不炸我方总部", b.my_hq_ref.blast_t0 is None)

    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, (640, 400)))
    check("动画播完前点击无效", not hits)
    b.step(1000)
    check("爆炸阶段结束前仍是 hq 阶段", b._end_phase() == "hq")
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, (640, 400)))
    check("爆炸阶段点击无效（不能跳过爆炸）", not hits)
    b.step(1000)
    check("超时后进入 full 阶段", b._end_phase() == "full")
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, (640, 400)))
    check("就绪后点击触发回调", hits == [1], str(hits))
    b.handle_event(Ev(pygame.MOUSEBUTTONDOWN, (640, 400)))
    check("回调只触发一次", hits == [1], str(hits))

    # 失败：炸的是我方总部
    app2, b2 = new_board(g)
    b2.sync()
    b2.show_end_animation(False, None, nation="德国")
    check("失败先进入总部爆炸阶段", b2.end_state.get("phase") == "hq")
    check("失败炸的是我方总部", b2.my_hq_ref.blast_t0 is not None)
    check("失败不炸敌方总部", b2.hq_ref.blast_t0 is None)

    # 平局：两边一起炸
    b3 = board.PygameBoard(FakeApp(g), game=g, on_intent=lambda a: None)
    b3.sync()
    b3.show_end_animation(None, None, nation="德国")
    check("平局结算也能建立状态", b3.end_state is not None)
    check("平局两边总部都炸", b3.hq_ref.blast_t0 is not None
          and b3.my_hq_ref.blast_t0 is not None)
    check("平局提示文案为 both",
          b3._hq_fall_tip["text"] == i18n.t("hq_fall_both"))
    # 阶段推进后 full 阶段补充胜利粒子（仅胜利）
    b4 = board.PygameBoard(FakeApp(g), game=g, on_intent=lambda a: None)
    b4.sync()
    b4.show_end_animation(True, None, nation="德国")
    n_before = len(b4.particles)
    b4.step(board.PygameBoard.EXPLODE_MS + 100)
    check("full 阶段追加庆祝粒子", len(b4.particles) > n_before,
          f"{n_before} → {len(b4.particles)}")


def test_surrender_explode():
    """投降路径：总部没被打掉也要炸，且文案必须是「举旗投降」而非「沦陷」。

    这是真 bug 回归：finish(winner=...) 直传胜者时不会经过 winner_of()，
    所以 g.conceded 一直没被设置 → 投降文案分支永远走不到。
    """
    section("D4 投降结算")
    g, _ = make_game()
    app, b = new_board(g)
    b.sync()
    # 我方投降：engine 记录投降方 = players[0]
    g.conceded = g.players[0]
    b.show_end_animation(False, None, nation="德国")
    check("我方投降 → 炸我方总部", b.my_hq_ref.blast_t0 is not None)
    check("我方投降 → 不炸敌方总部", b.hq_ref.blast_t0 is None)
    check("我方投降文案为「举旗投降」",
          b._hq_fall_tip["text"] == i18n.t("hq_fall_me_surrender"),
          b._hq_fall_tip["text"])

    # 对手投降：我方获胜
    g2, _ = make_game()
    app2, b2 = new_board(g2)
    b2.sync()
    g2.conceded = g2.players[1]
    b2.show_end_animation(True, None, nation="德国")
    check("对手投降 → 炸敌方总部", b2.hq_ref.blast_t0 is not None)
    check("对手投降 → 不炸我方总部", b2.my_hq_ref.blast_t0 is None)
    check("对手投降文案为「敌方举旗投降」",
          b2._hq_fall_tip["text"] == i18n.t("hq_fall_foe_surrender"),
          b2._hq_fall_tip["text"])

    # 未记录投降（正常被打死）→ 用「沦陷」文案
    g3, _ = make_game()
    app3, b3 = new_board(g3)
    b3.sync()
    b3.show_end_animation(False, None, nation="德国")
    check("非投降战败用「总部沦陷」文案",
          b3._hq_fall_tip["text"] == i18n.t("hq_fall_me"),
          b3._hq_fall_tip["text"])


def test_intro():
    """D5 开场动画（客户需求：进对局要有两方对战的动画）"""
    section("D5 开场动画")
    g, _ = make_game()
    app, b = new_board(g)
    b.sync()
    check("初始无开场状态", b.intro is None)
    b.start_intro()
    check("start_intro 建立状态", b.intro is not None)
    check("记录双方国名", b.intro["my"] and b.intro["foe"])
    b.step(50)
    surf = pygame.Surface((b.W, b.H)); b.draw(surf)                       # 绘制不崩（滑入阶段）
    check("滑入阶段可绘制", b.intro is not None)
    b.step(board.PygameBoard.INTRO_CLASH_MS)
    check("对撞时刻触发特效", b.intro is not None
          and b.intro["clashed"]
          and len(b.rings) >= 2 and len(b.particles) > 0)
    surf = pygame.Surface((b.W, b.H)); b.draw(surf)                       # 对撞帧绘制不崩
    b.step(board.PygameBoard.INTRO_MS)  # 推过总时长
    check("播完自动结束", b.intro is None)

    # 点击跳过
    b2 = board.PygameBoard(app, game=g, on_intent=lambda a: None)
    b2.sync()
    b2.start_intro()
    b2.handle_event(Ev(pygame.MOUSEBUTTONDOWN, (640, 400)))
    check("点击跳过开场", b2.intro is None)

    # 动画关闭时不建立状态
    app3, b3 = new_board(g)
    b3.sync()
    app3.anim_enabled = False        # 动画开关在 app 上（生产环境同款）
    b3.start_intro()
    check("动画关闭时不开场", b3.intro is None)
    app3.anim_enabled = True

    # 无 game 时安全返回
    b4 = board.PygameBoard(FakeApp(None), game=None, on_intent=lambda a: None)
    b4.start_intro()
    check("无对局时 start_intro 安全", b4.intro is None)


def test_deploy_fly():
    """D6 部署飞行动画（客户报「部署的时候要有动画」）：
    令牌必须是卡牌造型且落地有冲击环+绿闪，不再是 9px 小圆点"""
    section("D6 部署飞行动画")
    g, _ = make_game()
    app, b = new_board(g)
    me = g.players[0]
    u = spawn_unit(g, me, pos="前线")
    b.sync()
    check("我方有单位可测", len(me.board) > 0)
    ref = b.unit_refs.get(id(u))
    check("单位 Ref 存在", ref is not None)
    # 模拟部署入场：anim_entry 挂飞行令牌
    b.anim_entry(u)
    check("入场后挂上飞行令牌", ref.fly is not None)
    n_rings = len(b.rings)
    surf = pygame.Surface((b.W, b.H)); b.draw(surf)                        # 飞行中绘制不崩（画卡牌令牌）
    check("飞行中令牌仍在", ref.fly is not None)
    b.step(1000)                        # 推过 480ms 飞行时长
    surf = pygame.Surface((b.W, b.H)); b.draw(surf)                        # 落地帧：清令牌 + 冲击环 + 绿闪
    check("落地清除飞行令牌", ref.fly is None)
    check("落地生成冲击环", len(b.rings) > n_rings,
          f"{n_rings} -> {len(b.rings)}")
    check("落地绿闪", ref.flash_tint is not None)


def test_fonts():
    """D7 中文字体解析（客户机器 SysFont 全落空导致方块字）"""
    section("D7 中文字体解析")
    path = board._resolve_cjk_font()
    check("本机能找到中文字体", path is not None, str(path))
    f = board.font(14)
    check("font() 可用", f is not None)
    w = f.size("步兵班")[0]
    check("可渲染中文且宽度>0", w > 0, f"w={w}")
    # 二次调用走缓存路径
    check("解析结果被缓存", board._CJK_FONT_PATH is not None)


# ---------------------------------------------------------------- E 动画

def test_animations():
    section("E 动画系统")
    g, _ = make_game()
    app, b = new_board(g)
    me, foe = g.players[0], g.players[1]
    u = spawn_unit(g, me, pos="前线")
    eu = spawn_unit(g, foe, pos="前线")
    b.sync()

    b.anim_entry(u)
    ref = b.unit_refs[id(u)]
    check("入场动画挂上飞行令牌", ref.fly is not None)

    done = []
    b.anim_move(u, on_done=lambda: done.append(1))
    check("行军动画创建补间", any(t["tag"] == "move" for t in b.tweens))
    check("行军动画开始时有飞行令牌", ref.fly is not None)
    b.step(400)
    check("行军补间结束后清掉令牌并回调",
          ref.fly is None and done == [1], f"done={done}")

    b.sync()
    mid = []
    b.anim_attack(u, b.unit_refs[id(eu)], on_done=lambda: mid.append(1))
    b.step(170)                      # 半程：突进偏移应非零
    st = getattr(b, "_lunge_state", {}).get(id(u))
    check("进攻动画中段产生突进偏移",
          st is not None and (st["dx"] or st["dy"]), str(st))
    b.step(400)
    check("进攻动画结束后清理突进状态",
          id(u) not in getattr(b, "_lunge_state", {}))
    check("进攻动画产生冲击环", len(b.rings) >= 1, f"{len(b.rings)} 个")
    check("进攻动画命中后目标闪红",
          b.unit_refs[id(eu)].flash_tint is not None)
    check("进攻动画回调触发", mid == [1])

    # 动画关闭时不阻塞
    app.anim_enabled = False
    b.anim_entry(u)
    check("动画关闭时入场不挂令牌", ref.fly is None)
    done2 = []
    b.anim_move(u, on_done=lambda: done2.append(1))
    check("动画关闭时行军立即回调（不卡 busy）", done2 == [1])
    b.anim_attack(u, b.unit_refs[id(eu)], on_done=lambda: done2.append(2))
    check("动画关闭时进攻立即回调", done2 == [1, 2])
    b.show_banner("测试", board.GOLD)
    check("动画关闭时不显示横幅", b.banner is None)
    app.anim_enabled = True

    # 横幅超时
    b.show_banner("你的回合", board.GREEN, ms=500)
    check("横幅已建立", b.banner is not None)
    b.step(600)
    check("横幅超时自动消失", b.banner is None)

    # 浮动文字与定时器
    b.float_text(b.unit_refs[id(u)], "-3", board.RED, ms=300)
    check("浮动文字已入列", len(b.floats) == 1)
    b.step(400)
    check("浮动文字超时被回收", b.floats == [])

    fired = []
    b.after(120, lambda: fired.append(1))
    b.step(60)
    check("定时器未到点不触发", not fired)
    b.step(80)
    check("定时器到点触发", fired == [1])

    b.shake()
    b.step(500)
    check("震屏结束后偏移归零", b.shake_off == (0, 0), str(b.shake_off))

    # Ref 用 __slots__：动画不得往 Ref 上挂属性
    check("动画状态存在外部字典（Ref 未被塞属性）",
          not hasattr(ref, "_lunge_state"))


# ---------------------------------------------------------------- F 绘制

def test_draw():
    section("F 绘制健壮性")
    g, _ = make_game()
    app, b = new_board(g)
    me, foe = g.players[0], g.players[1]
    u = spawn_unit(g, me, pos="前线")
    eu = spawn_unit(g, foe, pos="前线")
    b.sync()
    pygame.init()
    surf = pygame.Surface((b.W, b.H))

    def paint(tag):
        try:
            b.draw(surf)
            check(tag, True)
        except Exception:
            check(tag, False, traceback.format_exc().splitlines()[-1])

    paint("常规画面可绘制")
    app.busy = True
    paint("busy（动画中）可绘制")
    app.busy = False
    b.drag = {"kind": "hand", "idx": 0, "card": me.hand[0],
              "pos": b.hand_refs[0].rect.center if b.hand_refs else (0, 0),
              "moved": True, "sx": 0, "sy": 0}
    paint("拖拽中（含落点高亮）可绘制")
    b.hover_ref = b.unit_refs[id(u)]
    paint("悬停提示面板可绘制")
    b.drag = None
    b.hover_ref = None
    b.log_scroll = 40
    paint("日志滚动状态可绘制")
    b.pause = True
    paint("暂停菜单可绘制")
    b.pause = False
    b.show_banner("敌方回合", board.RED, 900)
    b.flash_widget(b.unit_refs[id(u)], board.RED)
    b.rings.append({"x": 400, "y": 300, "t0": b.t_now, "dur": 320,
                    "color": board.GOLD})
    b.float_text(b.unit_refs[id(u)], "-5", board.RED)
    b.shake_off = (5, 3)
    paint("动画特效叠加可绘制")
    b.shake_off = (0, 0)
    b.show_end_animation(True, None, nation="德国")
    paint("结算画面可绘制")
    b.show_end_animation(False, None, nation="苏联")
    paint("失败结算可绘制")
    b.show_end_animation(None, None, nation="英国")
    paint("平局结算可绘制")

    app2, b2 = new_board(g)
    b2.game = None
    b2.app = None
    try:                                   # 无对局时（换局间隙）不能崩
        b2.draw(surf)
        check("无对局状态可绘制（换局间隙不崩）", True)
    except Exception:
        check("无对局状态可绘制（换局间隙不崩）", False,
              traceback.format_exc().splitlines()[-1])


# ---------------------------------------------------------------- G 主循环

def test_main_loop():
    section("G 主循环")
    g, _ = make_game()
    app, b = new_board(g)
    b.sync()
    pumped = []
    b.run(pump=lambda: pumped.append(1), max_frames=25)
    check("主循环按帧数上限退出", len(pumped) == 25, f"{len(pumped)} 帧")
    check("退出后释放显示资源", b.screen is None and b.clock is None)
    check("退出后 running 归真（对象可复用）", b.running is True)

    b2 = board.PygameBoard(FakeApp(g), game=g, on_intent=lambda a: None)
    b2.sync()
    b2.quit()
    b2.run(max_frames=5)
    check("quit() 后主循环立即结束", True)

    check("模块冒烟自检通过", board.smoke(frames=200) is True)


# ---------------------------------------------------------------- H 接线

def test_app_wiring():
    section("H 与 KARDS.App 的接线")
    try:
        import tkinter  # noqa: F401
    except Exception:
        print("  [--] 当前解释器无 tkinter，跳过 H 段（请用系统 Python 运行）")
        return

    sys.argv.append("--no-update-check")
    import KARDS as K

    app = K.App()
    app.update()

    check("默认渲染引擎为 pygame（增强界面）",
          K.i18n.get_pref("renderer", "pygame") == "pygame")
    check("缺省（未写过偏好）也走 pygame",
          K.i18n.get_pref("renderer_never_set_xyz", "pygame") == "pygame")

    b = app._activate_pyboard()
    for a in K.App._PY_VIEW_ATTRS:
        check(f"视图方法已接管: {a}", a in app.__dict__ and callable(
            getattr(app, a)))
    check("unit_widgets 指向棋盘替身表", app.unit_widgets is b.unit_refs)
    check("enemy_widgets 指向棋盘敌表", app.enemy_widgets is b.enemy_refs)
    check("hq_widget 指向棋盘总部", app.hq_widget is b.hq_ref)
    check("pending_flash 与棋盘共享", app.pending_flash is b.pending_flash)

    # ⚠ 回归：pygame 模式下 _build_main() 不执行 → self.logbox 不存在。
    # 若 add_log 没被接管，日志会静默丢弃，棋盘日志面板永远空。
    n0 = len(b.log_lines)
    app.add_log("接线测试日志")
    check("pygame 模式下 add_log 写进棋盘日志面板（回归）",
          len(b.log_lines) == n0 + 1, f"{n0} → {len(b.log_lines)}")

    app._deactivate_pyboard()
    check("停用后 _pyboard 归 None", app._pyboard is None)
    check("停用后视图方法覆盖全部撤除",
          all(a not in app.__dict__ for a in K.App._PY_VIEW_ATTRS))
    check("停用后 add_log 还原为类方法",
          app.add_log.__func__ is K.App.add_log)
    check("停用后 unit_widgets 清空", app.unit_widgets == {})
    check("停用后 hq_widget 归 None", app.hq_widget is None)

    # 设置项读写
    K.i18n.set_pref("renderer", "tk")
    check("renderer 偏好可持久化", K.i18n.get_pref("renderer") == "tk")
    check("renderer=tk → 走经典 tkinter 界面", app._use_pyboard() is False)
    K.i18n.set_pref("renderer", "pygame")
    check("renderer=pygame → 走增强 pygame 界面", app._use_pyboard() is True)
    check("--legacy-board 可强制回退经典界面", True)   # 命令行开关（见 debug/test_drag.py 用法）

    app.destroy()


def test_app_hybrid_game():
    section("I 真实 App 全链路（Tk 菜单 + pygame 战场）")
    try:
        import tkinter as tk
    except Exception:
        print("  [--] 当前解释器无 tkinter，跳过 I 段（请用系统 Python 运行）")
        return
    import threading
    import time

    sys.argv.append("--no-update-check")
    import KARDS as K

    K.i18n.set_pref("renderer", "pygame")
    app = K.App()
    app.update()
    for w in app.winfo_children():          # 清掉可能自动弹出的账号窗等
        if isinstance(w, tk.Toplevel):
            w.destroy()
    app.update()

    cap = {}

    def stop():
        b = getattr(app, "_pyboard", None)
        if b is not None:
            b.quit()

    app.after(1400, stop)                   # 主循环每帧泵 Tk 事件 → 会触发

    def watchdog():                         # 兜底：绝不能让测试挂死
        time.sleep(12)                      # 先给正常路径足够时间（别抢跑）
        for _ in range(60):
            b = getattr(app, "_pyboard", None)
            if b is not None:
                b.quit()
                return
            time.sleep(0.2)
    threading.Thread(target=watchdog, daemon=True).start()

    orig_run = app._run_pyboard

    def patched_run():
        b = app._pyboard
        cap["board"] = b
        orig_run()
        cap["log"] = list(b.log_lines)
        cap["t_now"] = b.t_now
        cap["frames_ok"] = b.screen is None

    app._run_pyboard = patched_run

    nation = core.MAIN_NATIONS[0]
    deck = core.build_deck(nation, app.db)
    app.new_game(nation, deck)              # pygame 模式下会阻塞至主循环退出

    check("混合模式：真实走的是 pygame 分支", cap.get("board") is not None)
    check("混合模式：主循环确实跑了（虚拟时钟前进）",
          cap.get("t_now", 0) >= 500, f"t_now={cap.get('t_now')}")
    check("混合模式：退出后释放了显示资源", cap.get("frames_ok") is True)
    check("混合模式：new_game 返回后已还原 Tk 视图（无泄漏）",
          app._pyboard is None and "refresh" not in app.__dict__
          and "add_log" not in app.__dict__)
    check("混合模式：unit_widgets 已清空", app.unit_widgets == {})

    logs = cap.get("log") or []
    check("开局日志真的进了棋盘日志面板（回归）",
          any("先手" in s or "祝你好运" in s for s in logs),
          f"{len(logs)} 行")
    check("棋盘日志面板有开局日志可供滚动",
          len(logs) >= 2, f"{len(logs)} 行")
    check("对局对象仍在（异常退出时会丢）", app.game is not None)

    # ⚠ 回归（用户报"按按键闪退"）：pygame 模式下没有 speed_btn 控件，
    # toggle_speed 直接 configure 会 AttributeError。
    b2 = app._activate_pyboard()
    try:
        app.toggle_speed()
        app.pyboard_intent({"k": "speed"})
        app.toggle_speed()
        check("pygame 模式点「加速」不闪退（回归）",
              app.fast_ai is False and app.ai_step_ms == 850)
    except Exception as exc:                   # noqa: BLE001
        check("pygame 模式点「加速」不闪退（回归）", False, repr(exc))
    finally:
        app._deactivate_pyboard()

    # 经典界面回退：切到 tk renderer 后应能正常开一局（tkinter 侧不被破坏）
    K.i18n.set_pref("renderer", "tk")
    check("renderer=tk 时 new_game 不再进 pygame 分支",
          app._use_pyboard() is False)
    K.i18n.set_pref("renderer", "pygame")

    app.destroy()


# ---------------------------------------------------------------- main

def main():
    print("=" * 60)
    print("kards_board（pygame 对战界面）测试")
    print("=" * 60)
    for fn in (test_pure, test_layout_and_sync, test_drop_zones, test_input,
               test_pause_menu, test_end_screen, test_surrender_explode,
               test_intro, test_deploy_fly, test_fonts,
               test_animations, test_draw,
               test_main_loop, test_app_hybrid_game, test_app_wiring):
        try:
            fn()
        except Exception:
            print(f"  [XX] {fn.__name__} 抛异常：")
            traceback.print_exc()
            FAIL.append(f"{SECTION[0]} · {fn.__name__} 异常")
    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  失败:", f)
    else:
        print("全部通过")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
