# -*- coding: utf-8 -*-
"""主题常量测试：kards_theme 是唯一真源，两套渲染器不许再各抄一份

背景（真事）
    稀有度宝石曾经恒为灰色：棋盘用 {1: 色, 2: 色, …} 这种数字键的字典，
    而卡牌上存的是 "传说"/"史诗" 中文名，`get(card.rarity or 3)` 永远取不到，
    于是每次都落到兜底的 DIM 灰。这种 bug 不会崩、不会报错，只是"看起来
    有点朴素"，所以能活很久 —— 靠人眼看是发现不了的，得靠断言。

运行:
    python debug/test_theme.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_engine as core      # noqa: E402
import kards_theme as theme      # noqa: E402

PASS, FAIL = [], []


def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [!!] ") + label + (f"  {extra}" if extra else ""))


def main():
    print("1. 基础配色齐全且是 #rrggbb")
    for name in ("BG", "PANEL", "CARD_BG", "CARD_SEL", "TEXT", "DIM",
                 "RED", "GREEN", "GOLD", "ROW_BG", "ROW_EDGE", "MID_BG",
                 "LOG_BG", "HAND_AREA"):
        v = getattr(theme, name, None)
        ok = isinstance(v, str) and len(v) == 7 and v.startswith("#")
        check(f"{name} = {v}", ok)

    print("2. 阵营色覆盖全部阵营")
    nations = core.MAIN_NATIONS + core.ALLY_NATIONS
    missing = [n for n in nations if n not in theme.NATION_COLOR]
    check("主国+盟国都有颜色", not missing, missing or "")
    check("中立也有颜色", "中立" in theme.NATION_COLOR)

    print("3. 稀有度配色与引擎一致（唯一真源）")
    check("RARITY_COLORS 就是引擎那份", theme.RARITY_COLORS is core.RARITY_COLORS)
    for lv in core.RARITY_LEVELS:
        check(f"{lv} → 色值可查", theme.rarity_color(lv) == core.RARITY_COLORS[lv],
              theme.rarity_color(lv))
    colors = {theme.rarity_color(lv) for lv in core.RARITY_LEVELS}
    check("四档颜色互不相同（否则等于没区分）", len(colors) == 4, colors)

    print("4. 稀有度解析：中文名 / 旧数字档位 / 未知值")
    check("旧编号 1 = 传说", theme.rarity_color(1) == theme.RARITY_COLOR[1])
    check("旧编号与中文名等价",
          theme.rarity_color(1) == theme.rarity_color("传说"))
    check("空值走兜底", theme.rarity_color("", "#123456") == "#123456")
    check("None 走兜底", theme.rarity_color(None, "#123456") == "#123456")
    check("未知稀有度走兜底", theme.rarity_color("神话", "#123456") == "#123456")
    check("★ 回归锁：传说不再回落到灰色", theme.rarity_color("传说") != theme.DIM)

    print("5. 两套渲染器不许再自带调色板（防止重复定义回潮）")
    for fn in ("KARDS.py", "kards_board.py"):
        src = open(os.path.join(ROOT, fn), encoding="utf-8").read()
        check(f"{fn} 不再内联 NATION_COLOR 字典", "NATION_COLOR = {" not in src)
        check(f"{fn} 引用了 kards_theme", "kards_theme" in src)

    print()
    print("=" * 50)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
