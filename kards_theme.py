# -*- coding: utf-8 -*-
"""kards_theme —— 两套渲染器共用的视觉常量（唯一真源）

为什么单独拆出来
    主壳是 tkinter（KARDS.py），对战棋盘是 pygame（kards_board.py），
    两套渲染但必须长得一样。以前两边各抄一份调色板，注释里写着
    「拷贝一份避免循环 import；改动需两边同步」—— 这种约定迟早会破，
    事实上它已经破了：

        kards_board.py 里稀有度宝石用的是 {1: 色, 2: 色, …} 这种**数字键**，
        而卡牌上存的是 "传说"/"史诗" 这类**中文名**，于是
        `RARITY_COLOR.get(card.rarity or 3)` 永远取不到值，
        宝石一直是兜底的灰色 —— 没人发现，因为"灰色也算个颜色"。

    所以这里做成唯一来源：要颜色就 import，不要再抄。改一处，两边同时生效。

分层约定
    本模块可以被 KARDS.py / kards_board.py 随意 import，但它只依赖
    kards_engine（拿稀有度的语义色），不依赖 tkinter / pygame ——
    这样它既能在没有 Tk 的环境里被单测，也不会被任何 GUI 反过来依赖。
"""

import kards_engine as core

# ---------------------------------------------------------------- 基础配色
# 深色主题。BG 是页面底，PANEL 是浮起来的面板，CARD_BG 是卡面。

BG = "#1a1d23"          # 页面背景
PANEL = "#242831"       # 面板 / 弹窗
CARD_BG = "#2e3440"     # 卡牌底色
CARD_SEL = "#4c6b8a"    # 卡牌选中态
TEXT = "#e6e6e6"
DIM = "#9aa0a8"
RED = "#e05c5c"
GREEN = "#6fbf73"
GOLD = "#e0b45c"

# 棋盘专用（tkinter 版没有这些分区，只有 pygame 版画「阵线」时用）
ROW_BG = "#1f232b"
ROW_EDGE = "#2a2f3a"
MID_BG = "#20242c"
LOG_BG = "#161a20"
HAND_AREA = "#242831"

# ---------------------------------------------------------------- 阵营色
# 一眼能分辨敌我阵营的色相；"中立"用于无主卡（如部分衍生物）。

NATION_COLOR = {
    "德国": "#6b7a8f", "苏联": "#a05a4c", "美国": "#4c7a6b",
    "英国": "#7a6b8f", "日本": "#8f6b4c",
    "意大利": "#6f8f6b", "法国": "#6b7a9f", "芬兰": "#8fb0c8",
    "波兰": "#c8a06b", "澳新军团": "#8f9f6b", "中立": "#7a7a7a",
}

# ---------------------------------------------------------------- 稀有度色
# 语义色以引擎的 RARITY_COLORS 为准（组卡界面、日志、卡面共用一套），
# 这里只是转发，避免第二份色值。
RARITY_COLORS = core.RARITY_COLORS

# 数字档位 → 稀有度名。历史原因：pygame 棋盘早期用 1~4 表示稀有度
# （1 传说 / 2 史诗 / 3 普通 / 4 稀有），卡牌数据改用中文名后这层映射
# 就成了"只在一处用、却写错没人发现"的坑。保留映射供旧代码/测试使用，
# **画卡面请直接用 RARITY_COLORS[card.rarity]**。
RARITY_LEVEL_BY_NUM = {1: "传说", 2: "史诗", 3: "普通", 4: "稀有"}
RARITY_COLOR = {n: RARITY_COLORS[lv] for n, lv in RARITY_LEVEL_BY_NUM.items()}


def rarity_color(rarity, default=None):
    """稀有度（中文名，或 1~4 的旧编号）→ 颜色；认不出来给 default。

    ⚠ 别在调用点手写 `RARITY_COLOR.get(x or 3)`：x 是中文名时那样取不到值，
      而且 `or 3` 会把空字符串/None 悄悄当成"普通"。
    """
    if isinstance(rarity, int):
        return RARITY_COLOR.get(rarity, default)
    return RARITY_COLORS.get((rarity or "").strip(), default)


# ---------------------------------------------------------------- 字体
# 随游戏捆绑的开源中文字体（SIL OFL，见 assets/fonts/）。
# tkinter 侧用 AddFontResourceExW 私有加载，pygame 侧用 Font(路径)。
BUNDLED_FONT_FILES = ["NotoSansCJKsc-Regular.otf", "NotoSansSC-Regular.otf"]
BUNDLED_FONT_FAMILY = "Noto Sans CJK SC"
