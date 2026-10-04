# -*- coding: utf-8 -*-
"""拖拽逻辑测试（不依赖鼠标，直接驱动 _drag_* 内部方法）

验证重点：
  1. 幽灵卡挂在覆盖全窗口的拖拽层上（能拖出手牌区之外）
  2. 合法性判定 _valid_drop：单位只能部署到我方支援阵线
  3. 落点高亮 / 抬起效果 / 拖拽取消后的清理
  4. 拖到牌桌外不会误出牌，只记一条日志

用法: python debug/test_drag.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import tkinter as tk  # noqa: E402

import KARDS as K  # noqa: E402
import kards_engine as core  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


class FakeEvent:
    def __init__(self, x_root, y_root):
        self.x_root = x_root
        self.y_root = y_root


class Silent:
    """把日志窗口的写入变成 no-op，避免测试输出被刷屏"""

    def insert(self, *a, **kw):
        pass

    def see(self, *a, **kw):
        pass

    def yview(self, *a, **kw):
        pass

    def delete(self, *a, **kw):
        pass


def autostart():
    """建一个 App 并开一局，直接进入\"我方回合、可操作\"状态

    真实流程里 new_game() 会先 busy=True 并 after(1000, begin_human_turn)；
    测试不等定时器，直接手工完成开局（start_turn 抽牌 + 发 kredits），
    否则 _drag_ok() 恒为 False，拖拽根本没启动。
    """
    app = K.App()
    nation = core.MAIN_NATIONS[0]
    deck = core.build_deck(nation, app.db)
    app.new_game(nation, deck)
    app.update()

    # 撤掉 new_game 排队的开局回调：AI 先手分支 _ai_phase_then_human 会
    # 重新把 busy 设成 True，之后所有拖拽都会被静默拒绝（本测试最容易踩的坑）
    try:
        for cb in app.tk.call("after", "info"):
            try:
                app.after_cancel(cb)
            except tk.TclError:
                pass
    except tk.TclError:
        pass

    app.anim_enabled = False          # 关掉动画，避免额外加锁/重建控件
    app.anim_queue = []
    app.log_widget = Silent()         # 日志窗口不存在时的兜底

    # 手工补上我方回合（等价 begin_human_turn，但不依赖 after 定时器）
    g = app.game
    g.current = g.players[0]
    g.start_turn()
    app.busy = False
    app.refresh()
    app.update()

    # 冻结所有落点/手牌控件的"出厂描边"，供后面断言还原效果。
    # 必须在这里读——任何一次 _highlight/_lift 都会改写这些属性。
    app._baseline = {}
    for w in (app.foe_rear_row, app.foe_front_row,
              app.my_front_row, app.my_rear_row):
        if w is not None and w.winfo_exists():
            app._baseline[w] = (w.cget("highlightbackground"),
                                int(w.cget("highlightthickness")))
    app._baseline_hand = [
        (w.cget("highlightbackground"), int(w.cget("highlightthickness")))
        for w in app.hand_frame.winfo_children() if w.winfo_exists()]
    return app


def settle(app, note=""):
    """泵事件直到 App 解锁（busy=False）。

    部署/移动成功会走入场动画：动画期间 self.busy=True，靠 after() 回调解锁。
    测试不泵事件就会卡在 busy=True，后面所有拖拽都会被静默拒绝。
    """
    deadline = time.time() + 4.0
    while time.time() < deadline:
        app.update()
        if not app.busy:
            return True
        time.sleep(0.02)
    print(f"    [warn] settle 超时（{note}）：busy 仍为 True")
    return False


def center_of(app, widget):
    """控件中心 → 屏幕坐标（与 _hit 同坐标系）"""
    return (widget.winfo_rootx() + widget.winfo_width() // 2,
            widget.winfo_rooty() + widget.winfo_height() // 2)


def main():
    app = None
    try:
        app = autostart()
        app.update()
        g = app.game
        me = g.players[0]

        print("\n=== 1. 手牌拖拽：幽灵卡挂在全窗口层上 ===")
        # 找一张单位牌
        idx = next((i for i, c in enumerate(me.hand) if c.kind == "unit"), None)
        check("手牌里有单位牌", idx is not None, f"手牌={[c.name for c in me.hand]}")
        if idx is None:
            return 1
        hand_w = app.hand_frame.winfo_children()[idx]

        sx, sy = center_of(app, hand_w)
        # 用 autostart 里冻结的出厂值（此刻现场读可能已被改写，不可靠）
        base_hl, base_th = app._baseline_hand[idx]
        app._drag_start(("hand", idx), FakeEvent(sx, sy), hand_w)
        check("拖拽状态已建立", app.drag is not None)
        # CardWidget 静止时本来就是 #111318/2px（不是 0px），所以只验证"变了"
        check("源卡被抬起（金描边加粗）",
              hand_w.cget("highlightbackground") == K.GOLD
              and int(hand_w.cget("highlightthickness")) > base_th,
              f"{hand_w.cget('highlightbackground')}/"
              f"{hand_w.cget('highlightthickness')} (原本 {base_hl}/{base_th})")

        # 拖到窗口左上角（完全在手牌区之外）
        app._drag_motion(FakeEvent(app.winfo_rootx() + 30,
                                   app.winfo_rooty() + 30))
        app.update()
        gh = app.drag["ghost"] if app.drag else None
        check("幽灵卡已创建", gh is not None and gh.winfo_exists())
        if gh is not None and gh.winfo_exists():
            # 幽灵卡的父级必须是主窗口（不是 hand_frame，也不是遮罩层）
            check("幽灵卡父级是主窗口（可拖出原容器）",
                  gh.master is app,
                  f"父级={gh.master}")
            # 拖到左上角时幽灵卡应仍然可见（被收拢进窗口内）
            gx, gy = gh.winfo_x(), gh.winfo_y()
            check("拖到窗口角落幽灵卡仍可见",
                  0 <= gx and 0 <= gy, f"位置=({gx},{gy})")
            check("幽灵卡显示了卡名",
                  me.hand[idx].name in gh.cget("text"), gh.cget("text"))

        print("\n=== 2. 拖到牌桌外松手 → 取消，不出牌 ===")
        n_hand = len(me.hand)
        app._drag_motion(FakeEvent(app.winfo_rootx() + 5, app.winfo_rooty() + 5))
        app._drag_drop(FakeEvent(app.winfo_rootx() + 5, app.winfo_rooty() + 5))
        app.update()
        check("手牌数量不变（未误出牌）", len(me.hand) == n_hand,
              f"{n_hand} → {len(me.hand)}")
        check("拖拽状态已清空", app.drag is None)
        check("抬起效果已还原", not getattr(app, "_lift_saved", {}))
        check("高亮已清理", not getattr(app, "_hl_saved", {}))
        # 黑屏回归（v1.3.0.2 前的事故）：拖拽层是铺满窗口的不透明 Frame，
        # 松手后没人销毁 → 整个界面被盖住、点哪都没反应。
        # 用 winfo_containing 验证：松手后手牌中心的最顶层控件仍是手牌本身，
        # 而不是任何全窗口遮罩。
        hx = hand_w.winfo_rootx() + hand_w.winfo_width() // 2
        hy = hand_w.winfo_rooty() + hand_w.winfo_height() // 2
        top = app.winfo_containing(hx, hy)
        # 顶层控件沿父链应能走回手牌卡（卡内部有子件，命中其孙级也算）
        chain, w = [], top
        while w is not None and w is not app:
            chain.append(w)
            w = getattr(w, "master", None)
        check("松手后无全窗口遮罩挡住界面（黑屏回归）",
              top is not None and hand_w in chain,
              f"顶层控件={top} 父链长={len(chain)}")

        print("\n=== 3. 合法性判定：单位只能部署到支援阵线 ===")
        me.kredits = 99                      # 保证费用足够
        idx = next((i for i, c in enumerate(me.hand) if c.kind == "unit"), None)
        if idx is None:
            check("仍有单位牌可测", False)
        else:
            cx, cy = center_of(app, app.my_rear_row)
            ok_rear = app._valid_drop(("hand", idx), cx, cy)
            check("拖到支援阵线 → 合法（绿）", ok_rear is True)

            fx, fy = center_of(app, app.my_front_row)
            ok_front = app._valid_drop(("hand", idx), fx, fy)
            check("单位拖到我方前线 → 非法（红）", ok_front is False)

            ex, ey = center_of(app, app.foe_front_row)
            ok_foe = app._valid_drop(("hand", idx), ex, ey)
            check("单位拖到敌方阵线 → 非法", ok_foe is False)

            ox, oy = app.winfo_rootx() + 5, app.winfo_rooty() + 5
            check("拖到牌桌外 → 非法", app._valid_drop(("hand", idx), ox, oy) is False)

        print("\n=== 4. 高亮跟随落点 ===")
        ah, dh = app._hl_saved if hasattr(app, "_hl_saved") else {}, None
        # 重新开始一次拖拽，检查高亮
        app.drag = None
        app._hl_saved = {}
        app._drag_start(("hand", idx), FakeEvent(sx, sy), hand_w)
        cx, cy = center_of(app, app.my_rear_row)
        app._drag_motion(FakeEvent(cx, cy))
        app.update()
        check("合法落点被高亮为绿色",
              app.my_rear_row.cget("highlightbackground") == K.GREEN,
              str(app.my_rear_row.cget("highlightbackground")))

        fx, fy = center_of(app, app.my_front_row)
        app._drag_motion(FakeEvent(fx, fy))
        app.update()
        check("非法落点被高亮为红色",
              app.my_front_row.cget("highlightbackground") == K.RED,
              str(app.my_front_row.cget("highlightbackground")))
        rear_base = app._baseline[app.my_rear_row]
        app._drag_drop(FakeEvent(5, 5))
        app.update()
        check("松手后高亮全部还原", not getattr(app, "_hl_saved", {}))
        # 还原成牌桌行原本的描边（_board_row 建行时是 1px / #2a2f3a）
        check("落点边框粗细已还原",
              int(app.my_rear_row.cget("highlightthickness")) == rear_base[1],
              f"{app.my_rear_row.cget('highlightthickness')} (原本 {rear_base[1]})")
        # 源卡描边也要还原（拖到桌外=取消）。
        # 注意：第 5 节部署成功会 refresh() 重建手牌，所以重新取一次控件，
        # 否则读到的是已被销毁的旧控件（Tk 会返回陈旧值）。
        alive = [c for c in app.hand_frame.winfo_children() if c.winfo_exists()]
        if alive:
            hw0 = alive[0]
            _th = int(hw0.cget("highlightthickness"))
            check("取消后源卡描边已还原（当前手牌控件）",
                  _th == base_th,
                  f"th={_th} bg={hw0.cget('highlightbackground')} "
                  f"(原本 {base_hl}/{base_th})")

        print("\n=== 4b. 非法落点闪红后原样还原 ===")
        me.kredits = 99
        app.anim_enabled = True      # 闪红由 _shake_widget 提供，受动画开关控制
        idx = next((i for i, c in enumerate(me.hand) if c.kind == "unit"), None)
        if idx is not None and app.my_front_row.winfo_exists():
            row_before = app._baseline[app.my_front_row]
            hw2 = app.hand_frame.winfo_children()[idx]
            hw2_before = app._baseline_hand[idx][1]
            ux, uy = center_of(app, hw2)
            fx, fy = center_of(app, app.my_front_row)
            app._drag_start(("hand", idx), FakeEvent(ux, uy), hw2)
            app._drag_motion(FakeEvent(fx, fy))
            app._drag_drop(FakeEvent(fx, fy))     # 单位落到前线 → 非法 → 闪红
            app.update()
            check("非法落点闪红（源卡描边已先归位）",
                  int(hw2.cget("highlightthickness")) == hw2_before,
                  f"{hw2.cget('highlightthickness')} (原本 {hw2_before})")
            check("闪红时落点为红框",
                  app.my_front_row.cget("highlightbackground") == K.RED)
            # 等 320ms 的还原定时器（不能用 mainloop+quit：App 自己会重挂 after
            # 回调，quit 之后 update() 不会立刻派发；手动泵事件更可靠）
            deadline = time.time() + 1.2
            while time.time() < deadline:
                app.update()
                if app.my_front_row.cget("highlightbackground") != K.RED:
                    break
                time.sleep(0.03)
            check("闪红结束后落点描边原样还原（不是写死的 1px）",
                  app.my_front_row.cget("highlightbackground") == row_before[0]
                  and int(app.my_front_row.cget("highlightthickness")) == row_before[1],
                  f"{app.my_front_row.cget('highlightbackground')}/"
                  f"{app.my_front_row.cget('highlightthickness')} "
                  f"(原本 {row_before[0]}/{row_before[1]})")
        app.anim_enabled = False     # 后面的用例回到"关动画"的确定性环境

        print("\n=== 4c. 拖拽中途被锁（busy）不留残影 ===")
        # 必须挑一张能拖起来的牌：非单位牌（反制/指令）的 _ghost_text 返回 None，
        # 拖拽会立刻被放弃，金描边自然也不会加，断言就会假失败
        idx = next((i for i, c in enumerate(me.hand)
                    if c.kind == "unit" and c.cost <= me.kredits), None)
        if idx is None:
            check("4c 有可拖拽的单位牌", False,
                  f"kredits={me.kredits} hand={[c.name for c in me.hand]}")
        else:
            hw3 = app.hand_frame.winfo_children()[idx]
            hw3_before = app._baseline_hand[idx][1]
            ux, uy = center_of(app, hw3)
            app._drag_start(("hand", idx), FakeEvent(ux, uy), hw3)
            _after_start = app.drag is not None
            app.update()
            check("已进入拖拽（金描边已加）",
                  int(hw3.cget("highlightthickness")) == hw3_before + 1,
                  f"{hw3.cget('highlightthickness')} (原本 {hw3_before}) "
                  f"card={me.hand[idx].name}/{me.hand[idx].kind} "
                  f"drag={_after_start} busy={app.busy} "
                  f"exists={hw3.winfo_exists()}")
            app.busy = True                     # 模拟动画/对手回合把输入锁掉
            app._drag_drop(FakeEvent(ux, uy))   # 松手时已被锁 → 走 _drag_cancel
            app.update()
            check("被锁时松手不留残影",
                  int(hw3.cget("highlightthickness")) == hw3_before
                  and not getattr(app, "_hl_saved", {}),
                  f"{hw3.cget('highlightthickness')} (原本 {hw3_before})")
            app.busy = False

        print("\n=== 5. 合法部署：真的能打出 ===")
        me.kredits = 99
        idx = next((i for i, c in enumerate(me.hand) if c.kind == "unit"), None)
        if idx is not None:
            before_hand = len(me.hand)
            before_board = len(me.board)
            cx, cy = center_of(app, app.my_rear_row)
            app._drag_start(("hand", idx), FakeEvent(cx, cy),
                            app.hand_frame.winfo_children()[idx])
            app._drag_motion(FakeEvent(cx, cy))
            app._drag_drop(FakeEvent(cx, cy))
            app.update()
            check("单位已部署到场上",
                  len(me.board) == before_board + 1,
                  f"场上 {before_board} → {len(me.board)}")
            check("手牌减少一张",
                  len(me.hand) == before_hand - 1,
                  f"手牌 {before_hand} → {len(me.hand)}")
            check("部署后拖拽状态干净", app.drag is None)
            settle(app, "部署动画")          # 等入场动画结束、输入解锁

        print("\n=== 6. 刷新时清理拖拽残留 ===")
        me.kredits = 99
        settle(app, "第6节前")
        check("进入第6节时已解锁（否则拖拽会被静默拒绝）",
              app.busy is False, f"busy={app.busy}")
        app.busy = False
        if me.hand:
            hw = app.hand_frame.winfo_children()[0]
            app._drag_start(("hand", 0), FakeEvent(sx, sy), hw)
            app._drag_motion(FakeEvent(app.winfo_rootx() + 100,
                                       app.winfo_rooty() + 100))
            app.update()
            had_ghost = app.drag and app.drag.get("ghost") is not None
            app.refresh()
            app.update()
            check("刷新前确实有幽灵卡", had_ghost)
            check("刷新后幽灵卡已销毁",
                  app.drag is None or app.drag.get("ghost") is None)
            check("刷新后高亮表已清空", not getattr(app, "_hl_saved", {}))
            check("刷新后抬起表已清空", not getattr(app, "_lift_saved", {}))

        print("\n=== 7. 我方单位拖拽（机动/攻击） ===")
        if me.board:
            u = me.board[0]
            uw = app.unit_widgets.get(id(u))
            check("单位有对应控件", uw is not None)
            if uw is not None:
                ux, uy = center_of(app, uw)
                app._drag_start(("unit", u), FakeEvent(ux, uy), uw)
                app._drag_motion(FakeEvent(ux + 40, uy - 40))
                app.update()
                check("单位拖拽有幽灵卡",
                      app.drag and app.drag.get("ghost") is not None)
                if app.drag and app.drag.get("ghost"):
                    txt = app.drag["ghost"].cget("text")
                    check("幽灵卡显示攻防",
                          f"{u.attack}/{u.defense}" in txt, txt)
                fx, fy = center_of(app, app.my_front_row)
                check("拖到我方前线 → 合法",
                      app._valid_drop(("unit", u), fx, fy) is True)
                app._drag_drop(FakeEvent(5, 5))
                app.update()

        print("\n=== 8. 非我方回合不可拖拽 ===")
        g.current = g.players[1]
        app.drag = None
        hw = app.hand_frame.winfo_children()
        app._drag_start(("hand", 0), FakeEvent(sx, sy), hw[0] if hw else None)
        check("敌方回合拖拽被拒绝", app.drag is None)
        g.current = g.players[0]

    finally:
        if app is not None:
            try:
                app.destroy()
            except Exception:
                pass

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
