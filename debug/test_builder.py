# -*- coding: utf-8 -*-
"""卡组编辑器 GUI 测试（系统 Python + tkinter）

这一块以前**完全没有测试覆盖**，于是「清空」按钮被接成了
`_auto_fill(clear=True)`：先 `deck_counts = {}` 紧接着又跑推荐填卡循环，
点「清空」等于点「推荐卡组」，玩家永远清不掉卡组（用户实测报障）。
本测试把按钮行为逐条锁死。

运行：
    C:\\Users\\freet\\AppData\\Local\\Programs\\Python\\Python313\\python.exe \\
        debug/test_builder.py
"""
import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# 本测试验证 tkinter 侧按钮接线，固定走经典界面（避免 pygame 主循环阻塞）
sys.argv.append("--legacy-board")

import kards_engine as core        # noqa: E402
import KARDS as gui                # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


def pump(root, times=3):
    for _ in range(times):
        try:
            root.update_idletasks()
            root.update()
        except tk.TclError:
            return


def find_buttons(w, out=None):
    """递归收集所有 tk.Button（含子孙容器）"""
    if out is None:
        out = []
    for c in w.winfo_children():
        if isinstance(c, tk.Button):
            out.append(c)
        find_buttons(c, out)
    return out


def button_by_text(root, text):
    for b in find_buttons(root):
        try:
            if str(b.cget("text")) == text:
                return b
        except tk.TclError:
            continue
    return None


def open_builder(app, nation="德国"):
    """打开组卡界面（_build_deck_builder 会 destroy start_frame）"""
    app.start_frame = tk.Frame(app)
    app.start_frame.pack()
    app._build_deck_builder(nation)
    pump(app)
    return nation


def main():
    app = gui.App()
    app.withdraw()
    pump(app)

    nat = open_builder(app)
    btns = find_buttons(app.builder_frame)
    names = [str(b.cget("text")) for b in btns]
    print("\n=== 1. 组卡界面按钮齐备 ===")
    check("按钮数量 >= 6", len(btns) >= 6, f"{len(btns)} 个: {names}")
    for label in ("推荐卡组", "清空"):
        check(f"有「{label}」按钮", button_by_text(app.builder_frame, label) is not None)

    print("\n=== 2. 「清空」必须真的清空（用户报的 bug） ===")
    app.deck_counts = {"步兵班": 4}
    pump(app)
    check("初始非空", app._deck_total() == 4, str(app._deck_total()))
    btn_clear = button_by_text(app.builder_frame, "清空")
    check("找到清空按钮", btn_clear is not None)
    btn_clear.invoke()
    pump(app)
    check("点「清空」后卡组为 0 张", app._deck_total() == 0,
          f"实际 {app._deck_total()} 张 —— 若 != 0 说明又被自动填满了")
    check("清空后 deck_counts 为空", not app.deck_counts, str(app.deck_counts))
    check("清空后卡组列表面板已重建",
          app.deck_inner.winfo_exists() and not find_buttons(app.deck_inner))

    print("\n=== 3. 「推荐卡组」仍然要填满 ===")
    btn_rec = button_by_text(app.builder_frame, "推荐卡组")
    check("找到推荐卡组按钮", btn_rec is not None)
    btn_rec.invoke()
    pump(app)
    total = app._deck_total()
    check("推荐卡组填满到 DECK_SIZE", total == core.DECK_SIZE,
          f"{total} / {core.DECK_SIZE}")
    check("单卡不超过 MAX_COPIES",
          all(n <= core.MAX_COPIES for n in app.deck_counts.values()),
          str(sorted(set(app.deck_counts.values()))))
    ally = app._deck_ally_count()
    check("盟国卡不超过 ALLY_LIMIT", ally <= core.ALLY_LIMIT,
          f"{ally} / {core.ALLY_LIMIT}")
    check("推荐卡组合法", core.validate_deck(
        core.counts_to_deck(app.deck_counts, nat, app.db), nat, app.db)[0])

    print("\n=== 4. 两个按钮不能再串线 ===")
    btn_rec.invoke()
    pump(app)
    filled = app._deck_total()
    btn_clear.invoke()
    pump(app)
    check("先推荐再清空 → 必须真的空掉", app._deck_total() == 0,
          f"推荐后 {filled} 张，清空后 {app._deck_total()} 张")
    btn_rec.invoke()
    pump(app)
    check("再点推荐 → 又能填满", app._deck_total() == core.DECK_SIZE,
          str(app._deck_total()))

    print("\n=== 5. 加卡 / 减卡与上限 ===")
    btn_clear.invoke()
    pump(app)
    card = core.allowed_cards(nat, app.db)[0]
    for _ in range(core.MAX_COPIES + 2):
        app._add_card(card)
    pump(app)
    check(f"单卡最多 {core.MAX_COPIES} 张",
          app.deck_counts.get(card.name, 0) == core.MAX_COPIES,
          f"{card.name}={app.deck_counts.get(card.name, 0)}")
    for _ in range(core.MAX_COPIES + 1):
        app._remove_card(card)
    pump(app)
    check("减到 0 后不再出现", card.name not in app.deck_counts,
          str(app.deck_counts))

    print("\n=== 6. 开始对战按钮随张数启停 ===")
    check("空卡组时开始按钮 disabled",
          str(app.start_btn.cget("state")) == "disabled",
          str(app.start_btn.cget("state")))
    btn_rec.invoke()
    pump(app)
    check("满卡组时开始按钮 normal",
          str(app.start_btn.cget("state")) == "normal",
          str(app.start_btn.cget("state")))

    print("\n=== 7. 切换国家后卡组重置 ===")
    try:
        app.builder_frame.destroy()
    except tk.TclError:
        pass
    open_builder(app, "日本")
    check("换国家后卡组为空", app._deck_total() == 0, str(app._deck_total()))
    check("deck_nation 已切换", app.deck_nation == "日本", app.deck_nation)
    jp_card = core.allowed_cards("日本", app.db)[0]
    app._add_card(jp_card)
    pump(app)
    check("新国家可正常加卡", app.deck_counts.get(jp_card.name) == 1,
          str(app.deck_counts))

    app.destroy()
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
