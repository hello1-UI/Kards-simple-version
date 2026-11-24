# -*- coding: utf-8 -*-
"""kards_theme —— 主题系统（tkinter 主壳 + pygame 棋盘共用，唯一真源）

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

可切换主题（2026-11）
    历史包袱：颜色是**模块级常量**，两个渲染器在 import 时就 `from
    kards_theme import BG, …` 绑死了。要支持运行中换主题，光改本模块的
    全局变量没用 —— 对方模块里那份名字还指着旧字符串。

    所以约定两条：
        1. 本模块的 apply() 会刷新自己的模块级常量（新代码可以直接读
           `theme.BG`，也可以继续 `from`）；
        2. 渲染器在启动时和每次换主题后调用 `theme.sync(globals())`，
           把新的值灌回**自己的**模块命名空间。这样几百处 `bg=BG`
           的调用点一个都不用改。

    ⚠ 别在函数签名默认值里写颜色（`def f(color=RED)`）—— 默认值在
      def 时就绑定了，换主题不会跟着变。用 `color=None` 再在函数体里取。
"""

import json
import os
import re

import kards_engine as core

# ---------------------------------------------------------------- 颜色工具


def _rgb(color):
    """'#rrggbb' → (r, g, b)；非法值给中性灰，绝不抛异常（调用点在绘制热路径）。"""
    try:
        s = str(color).strip().lstrip("#")
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        if len(s) != 6:
            return (128, 128, 128)
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except (ValueError, TypeError):
        return (128, 128, 128)


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def mix(a, b, t):
    """a 向 b 混合 t（0=a，1=b）。用于主色调染、悬停变亮。"""
    t = max(0.0, min(1.0, float(t)))
    ra, rb = _rgb(a), _rgb(b)
    return _hex(tuple(ra[i] + (rb[i] - ra[i]) * t for i in range(3)))


def lighten(c, t):
    return mix(c, "#ffffff", t)


def darken(c, t):
    return mix(c, "#000000", t)


def _lin(ch):
    ch = ch / 255.0
    return ch / 12.92 if ch <= 0.04045 else ((ch + 0.055) / 1.055) ** 2.4


def luminance(c):
    """WCAG 相对亮度（0=黑，1=白）。"""
    r, g, b = _rgb(c)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a, b):
    """WCAG 对比度（1:1 ~ 21:1）。用来保证换主题后文字仍然看得清。"""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def readable_on(bg, prefer_light="#ffffff", prefer_dark="#15171c"):
    """在 bg 上放什么颜色的字最清楚（按亮度选，不猜）。"""
    return prefer_light if luminance(bg) < 0.42 else prefer_dark


def ensure_contrast(fg, bg, minimum=4.5):
    """对比度不足时把 fg 往黑/白推，直到达标或推到极限。

    自选主色可能很亮（比如明黄），直接拿它当按钮底色 + 白字会糊成一片。
    这里统一兜底，省得每套配色手工验算。
    """
    if contrast(fg, bg) >= minimum:
        return fg
    # 往**离当前字色最远**的那个极端推 —— 按背景亮度选会推出"白字推白"
    # 这种无效操作（亮黄底上本来就是白字，再往白推还是白）。
    target = "#000000" if luminance(fg) > 0.5 else "#ffffff"
    for step in (0.2, 0.4, 0.6, 0.8, 1.0):
        cand = mix(fg, target, step)
        if contrast(cand, bg) >= minimum:
            return cand
    return target


def best_fg(bg, light="#ffffff", dark="#15171c", tolerance=1.3):
    """在 bg 上取合适的字色。

    纯按对比度取会产生"中蓝底配黑字"这种虽然够清楚、但看着别扭的结果
    （白 4.17 / 黑 4.30）。所以白字只要**不是明显更差**（差 30% 以内）
    就优先白字 —— 深色主题的按钮就该是浅色字。
    """
    cl, cd = contrast(light, bg), contrast(dark, bg)
    if cl >= 3.0 and cd <= cl * tolerance:
        return light
    return dark if cd >= cl else light


def is_light(color):
    return luminance(color) > 0.5


def hover_of(color, amount=0.12):
    """控件的悬停色：暗底提亮、亮底压暗（亮色主题里再提亮会糊成一片）。"""
    if luminance(color) > 0.45:
        return darken(color, amount * 0.75)
    return lighten(color, amount)


# ---------------------------------------------------------------- 主题预设
# 每套预设只描述"底色骨架"，主色（accent）单独可调。
# 暗色主题的 text 必须亮、亮色主题的 text 必须暗 —— 由 _finalize() 校验。

PRESETS = {
    # 默认：钢蓝灰，接近原版配色
    "frontline": {
        "light": False,
        "accent": "#4c7fb8",
        "bg": "#1a1d23", "bg_alt": "#14171c",
        "panel": "#242831", "panel_alt": "#2b303b",
        "card": "#2e3440", "card_dim": "#252a33",
        "text": "#e6e6e6", "dim": "#9aa0a8", "mute": "#6d7480",
        "border": "#3a3f4a", "border_hi": "#4d5563",
        "red": "#e05c5c", "green": "#6fbf73", "gold": "#e0b45c",
        "btn": "#4a4f5a",
        "row_bg": "#1f232b", "row_edge": "#2a2f3a",
        "mid_bg": "#20242c", "log_bg": "#161a20", "hand_area": "#242831",
    },
    # 冷钢：偏青的钢灰，屏幕对比更强
    "steel": {
        "light": False,
        "accent": "#4f93a8",
        "bg": "#151b20", "bg_alt": "#10151a",
        "panel": "#1e262e", "panel_alt": "#26303a",
        "card": "#28333d", "card_dim": "#202a33",
        "text": "#e2ebf0", "dim": "#94a3ae", "mute": "#68757f",
        "border": "#333f4a", "border_hi": "#465563",
        "red": "#dd6262", "green": "#6cbd8a", "gold": "#dcb45f",
        "btn": "#414d58",
        "row_bg": "#1a2128", "row_edge": "#26303a",
        "mid_bg": "#1b2229", "log_bg": "#12181d", "hand_area": "#1e262e",
    },
    # 沙场：北非暖褐
    "desert": {
        "light": False,
        "accent": "#c8a04a",
        "bg": "#241f18", "bg_alt": "#1c1812",
        "panel": "#2f2820", "panel_alt": "#3a3227",
        "card": "#3a3125", "card_dim": "#2e2720",
        "text": "#f0e7d8", "dim": "#b3a48f", "mute": "#857764",
        "border": "#463b2c", "border_hi": "#5c4d39",
        "red": "#d8664c", "green": "#8fae72", "gold": "#e0bc63",
        "btn": "#574a38",
        "row_bg": "#29231b", "row_edge": "#3b3226",
        "mid_bg": "#282219", "log_bg": "#1b1711", "hand_area": "#2f2820",
    },
    # 军绿：橄榄绿野战
    "olive": {
        "light": False,
        "accent": "#7fa05a",
        "bg": "#1b2018", "bg_alt": "#151a13",
        "panel": "#252c21", "panel_alt": "#2f382a",
        "card": "#333c2d", "card_dim": "#282f23",
        "text": "#e7ebdf", "dim": "#a0a894", "mute": "#737b67",
        "border": "#3b4535", "border_hi": "#4f5b46",
        "red": "#cf6a55", "green": "#84bb6a", "gold": "#d8b45c",
        "btn": "#3f4a38",
        "row_bg": "#1f2519", "row_edge": "#2e3728",
        "mid_bg": "#1e2419", "log_bg": "#141913", "hand_area": "#252c21",
    },
    # 极地：冷蓝夜战
    "arctic": {
        "light": False,
        "accent": "#5aa8c8",
        "bg": "#141c24", "bg_alt": "#0f151b",
        "panel": "#1d2833", "panel_alt": "#25323f",
        "card": "#283544", "card_dim": "#202b38",
        "text": "#e3ecf3", "dim": "#93a3b0", "mute": "#647482",
        "border": "#2f3d4b", "border_hi": "#435365",
        "red": "#dd6666", "green": "#6dbe92", "gold": "#d9b966",
        "btn": "#3d4b58",
        "row_bg": "#18212b", "row_edge": "#26323f",
        "mid_bg": "#19222c", "log_bg": "#101820", "hand_area": "#1d2833",
    },
    # 深夜：高对比纯黑
    "midnight": {
        "light": False,
        "accent": "#6f8fd0",
        "bg": "#0b0d10", "bg_alt": "#070809",
        "panel": "#14171c", "panel_alt": "#1b1f26",
        "card": "#1e232b", "card_dim": "#171b21",
        "text": "#dfe3e8", "dim": "#8b929c", "mute": "#5f666f",
        "border": "#262b33", "border_hi": "#3a4149",
        "red": "#e06666", "green": "#63c07d", "gold": "#e2b85e",
        "btn": "#2a2f38",
        "row_bg": "#101317", "row_edge": "#1c2128",
        "mid_bg": "#111418", "log_bg": "#080a0c", "hand_area": "#14171c",
    },
    # 日间：亮色主题（办公室/投影场景）
    "paper": {
        "light": True,
        "accent": "#3f6fa8",
        "bg": "#f1efe9", "bg_alt": "#e7e4dc",
        "panel": "#ffffff", "panel_alt": "#f7f5f0",
        "card": "#ffffff", "card_dim": "#e8e5dd",
        "text": "#22262c", "dim": "#5f6672", "mute": "#8b9299",
        "border": "#d5d0c5", "border_hi": "#b9b2a3",
        "red": "#b03b3b", "green": "#2f7a45", "gold": "#a3781f",
        "btn": "#e4dfd4",
        "row_bg": "#f7f5f0", "row_edge": "#d5d0c5",
        "mid_bg": "#efece5", "log_bg": "#fbfaf7", "hand_area": "#ffffff",
    },
}

DEFAULT_PRESET = "frontline"

# 自定义模板的键前缀。用命名空间而不是直接拿名字当键：
#   1. 不会和内置 preset 撞名（用户可能就叫 "paper"）；
#   2. `preset_name()` 一眼能看出这是用户模板，落盘/删除时也好定位。
CUSTOM_PREFIX = "custom:"

# 一个模板需要描述的字段（与 PRESETS 的骨架一致）。
# _finalize() 会从这里派生 primary/border/card_sel 等全部 token。
BASE_KEYS = (
    "accent", "bg", "bg_alt", "panel", "panel_alt", "card", "card_dim",
    "text", "dim", "mute", "border", "border_hi", "red", "green", "gold",
    "btn", "row_bg", "row_edge", "mid_bg", "log_bg", "hand_area",
)

# 可选主色（键 → 色值）。名称走 i18n（theme_a_<key>）。
ACCENTS = {
    "blue": "#4c7fb8",
    "gold": "#c8a04a",
    "green": "#6aa05a",
    "red": "#c05c5c",
    "purple": "#8a6fb0",
    "teal": "#4fa3ad",
    "orange": "#c07a3a",
    "pink": "#b0568a",
}

# 全部 token（sync 按这个清单灌回调用方命名空间）
TOKENS = (
    "BG", "BG_ALT", "PANEL", "PANEL_ALT", "CARD_BG", "CARD_DIM", "CARD_SEL",
    "TEXT", "DIM", "MUTE", "BORDER", "BORDER_HI",
    "RED", "GREEN", "GOLD",
    "ROW_BG", "ROW_EDGE", "MID_BG", "LOG_BG", "HAND_AREA",
    "BTN", "BTN_HOVER",
    "PRIMARY", "PRIMARY_HOVER", "PRIMARY_FG",
    "SUCCESS", "SUCCESS_HOVER", "DANGER", "DANGER_HOVER",
    "WARN", "WARN_HOVER", "INFO", "INFO_HOVER",
    "ACCENT", "ACCENT_DIM", "ACCENT_FG",
    "LIGHT_THEME",
)


def _finalize(base, accent, raw=None):
    """把「骨架 + 主色」算成一整套 token。

    主色不是只给按钮上色 —— 它会给底色做 4%~6% 的染色，
    这样换主色时整个界面的色调都会跟着变，而不是只有几个按钮。
    """
    p = dict(base)
    light = bool(base.get("light"))
    acc = accent or base.get("accent") or ACCENTS["blue"]
    if not (isinstance(acc, str) and len(acc) == 7 and acc.startswith("#")):
        acc = base.get("accent") or ACCENTS["blue"]

    # 自定义模板按用户填的**原色**渲染：预设那套「底色向主色靠 5%」
    # 是设计上的润色，但用户手工调出来的配色再被悄悄染色，会觉得
    # 「我选的 #123456 怎么不是 #123456」。预设保持原行为。
    if raw is None:
        raw = bool(base.get("raw"))
    if not raw:
        # 底色轻微向主色靠拢：暗色 5%，亮色 3%（亮色染多了会发脏）
        tint = 0.03 if light else 0.05
        for key in ("bg", "bg_alt", "panel", "panel_alt", "card", "row_bg",
                    "hand_area"):
            p[key] = mix(p[key], acc, tint)

    p["accent"] = acc
    p["primary"] = acc
    p["primary_hover"] = mix(acc, "#ffffff" if not light else "#000000",
                             0.12 if not light else 0.10)
    p["primary_fg"] = best_fg(acc)

    # 中性按钮：向主色靠一点点，避免"灰得跟背景没关系"
    p["btn"] = base["btn"]
    p["btn_hover"] = (lighten(base["btn"], 0.10) if not light
                      else darken(base["btn"], 0.07))

    # 成功/危险/警告：语义色保持预设值（军绿/血红不随主色变），
    # 只派生悬停态；文字色统一用 readable_on 保证能看清。
    p["success"] = base["green"]
    p["success_hover"] = (lighten(base["green"], 0.10) if not light
                          else darken(base["green"], 0.08))
    p["danger"] = base["red"]
    p["danger_hover"] = (lighten(base["red"], 0.10) if not light
                         else darken(base["red"], 0.08))
    p["warn"] = base["gold"] if not light else "#c08a2a"
    p["warn_hover"] = (lighten(p["warn"], 0.10) if not light
                       else darken(p["warn"], 0.08))
    p["info"] = base["accent"]
    p["info_hover"] = p["primary_hover"]

    p["border"] = base["border"]
    p["border_hi"] = base["border_hi"]
    p["card_sel"] = mix(base["card"], acc, 0.42 if not light else 0.22)
    p["accent_dim"] = mix(base["panel"], acc, 0.22)
    p["accent_fg"] = best_fg(base["panel"])

    # 文字对底色的对比度兜底：换主题/换主色后绝不允许"看不见字"
    p["text"] = ensure_contrast(base["text"], p["bg"], 4.5)
    p["dim"] = ensure_contrast(base["dim"], p["bg"], 3.0)
    p["mute"] = ensure_contrast(base["mute"], p["bg"], 2.0)
    # 兼容别名：TOKENS 用 CARD_BG / LIGHT_THEME 这套名字
    p["card_bg"] = p["card"]
    p["light_theme"] = light
    p["light"] = light
    return p


# ---------------------------------------------------------------- 自定义模板
# 用户可以在设置里从当前配色出发，逐项调色并存成自己的模板。
# 存放位置：<数据目录>/themes/<slug>.json —— 与账号/商店同级的用户数据，
# 卸载重装不丢、也不需要写注册表。
#
# 设计取舍：
#   * **一个模板一个文件**：坏一个只丢一个，不至于整份配置读不出来；
#   * **落盘前必过 normalize_preset()**：手改坏的 JSON（少字段、颜色写成
#     "red"、多打个分号）不能让游戏起不来 —— 非法值一律回落到底色预设；
#   * **文件名走 slug，显示名另存**：允许重名显示、允许中文文件名，
#     但 `/ \ : * ? " < > |` 这些会被剔掉，防止路径穿越。
_CUSTOM_DIR_OVERRIDE = None
_custom_cache = {"sig": None, "items": {}}


def custom_dir():
    """模板目录（测试可用 set_custom_dir 改到临时目录）。"""
    if _CUSTOM_DIR_OVERRIDE:
        return _CUSTOM_DIR_OVERRIDE
    base = getattr(core, "DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "themes")


def set_custom_dir(path):
    """把模板目录指到别处（只给测试用；None 恢复真实目录）。"""
    global _CUSTOM_DIR_OVERRIDE
    _CUSTOM_DIR_OVERRIDE = path
    _custom_cache["sig"] = None
    _custom_cache["items"] = {}


def _norm_hex(value):
    """任意写法（#RGB / #RRGGBB / RRGGBB / 大小写）→ '#rrggbb'；非法返回 None。

    绝不抛异常：颜色既可能来自用户输入框，也可能来自手改的 JSON。
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if not s.startswith("#"):
        s = "#" + s
    if len(s) == 4:
        s = "#" + "".join(ch * 2 for ch in s[1:])
    if len(s) != 7:
        return None
    try:
        int(s[1:], 16)
    except ValueError:
        return None
    return s.lower()


def _slug(name):
    """显示名 → 文件名主体。去掉路径分隔符/保留字符，空白折成连字符。"""
    s = str(name or "")
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", s)
    s = re.sub(r"\s+", "-", s.strip()).strip(".-")
    return s[:40]


def _unique_name(name, exclude_key=None):
    """显示名去重（"模板" 已存在 → "模板 2"）。"""
    name = str(name or "").strip()[:40] or "模板"
    existing = {info["name"].lower() for k, info in custom_presets().items()
                if k != exclude_key}
    if name.lower() not in existing:
        return name
    for i in range(2, 100):
        cand = "%s %d" % (name, i)
        if cand.lower() not in existing:
            return cand
    return "%s %d" % (name, len(existing) + 2)


def normalize_preset(data, base=None):
    """把「用户/文件给的半成品」补成一整套合法骨架。

    - 缺字段 → 用 base（内置 preset 键或骨架 dict，默认 DEFAULT_PRESET）补齐；
    - 颜色认不出来 → 用 base 的值，**不报错**；
    - light 强制 bool；
    - 打上 raw=True：自定义模板按原色渲染，不再被主色染色。
    """
    data = data if isinstance(data, dict) else {}
    colors = data.get("colors") if isinstance(data.get("colors"), dict) else {}
    # 键大小写不敏感：手改 JSON 很容易写成 "BG"/"Panel"，不该因此被忽略
    src = {}
    for k, v in colors.items():
        src[str(k).strip().lower()] = v
    for k, v in data.items():
        if k != "colors":
            src[str(k).strip().lower()] = v

    if isinstance(base, dict):
        base_data = base
        base_key = src.get("base") if src.get("base") in PRESETS else DEFAULT_PRESET
    else:
        cand = base if (isinstance(base, str) and base in PRESETS) else src.get("base")
        base_key = cand if cand in PRESETS else DEFAULT_PRESET
        base_data = PRESETS[base_key]

    out = {"base": base_key, "raw": True}
    out["light"] = bool(src.get("light", base_data.get("light", False)))
    for key in BASE_KEYS:
        val = _norm_hex(src.get(key))
        out[key] = val if val is not None else base_data[key]
    return out


def _custom_sig():
    """目录指纹（文件名 + mtime + size）。目录变了才重读，避免每次调色都打盘。"""
    d = custom_dir()
    rows = []
    try:
        for entry in os.scandir(d):
            if not entry.is_file() or not entry.name.lower().endswith(".json"):
                continue
            try:
                st = entry.stat()
            except OSError:
                continue
            rows.append((entry.name, int(st.st_mtime_ns), int(st.st_size)))
    except OSError:
        rows = []
    rows.sort()
    return (d, tuple(rows))


def _scan_custom():
    """读盘并解析所有自定义模板；坏文件跳过（绝不因一个坏文件起不来）。"""
    sig = _custom_sig()
    if sig == _custom_cache["sig"]:
        return _custom_cache["items"]
    items = {}
    d = sig[0]
    for filename, _mtime, _size in sig[1]:
        path = os.path.join(d, filename)
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        slug = os.path.splitext(filename)[0]
        data = normalize_preset(raw)
        name = str(raw.get("name") or slug).strip()[:40] or slug
        items[CUSTOM_PREFIX + slug] = {"name": name, "data": data,
                                       "path": path, "slug": slug}
    _custom_cache["sig"] = sig
    _custom_cache["items"] = items
    return items


def custom_presets():
    """{key: {"name", "data", "path", "slug"}} —— 按文件名排序，保证界面稳定。"""
    return dict(_scan_custom())


def all_presets():
    """内置 + 自定义的全部模板骨架（键 → dict）。"""
    out = {k: dict(v) for k, v in PRESETS.items()}
    for key, info in custom_presets().items():
        out[key] = dict(info["data"])
    return out


def _valid_key(key):
    if not isinstance(key, str):
        return DEFAULT_PRESET
    if key in PRESETS:
        return key
    return key if key in custom_presets() else DEFAULT_PRESET


def _base_for(key):
    if key in PRESETS:
        return PRESETS[key]
    info = custom_presets().get(key)
    if info:
        return info["data"]
    return PRESETS[DEFAULT_PRESET]


def is_custom(key):
    return isinstance(key, str) and key in custom_presets()


def base_of(key):
    """取某个模板的骨架（键 → 颜色，未经 _finalize 派生）。

    编辑器的起点用它：自定义模板取自己的原色，内置模板取预设原色。
    """
    return dict(_base_for(_valid_key(key)))


def preset_label(key):
    """界面显示名：内置走 i18n，自定义用用户起的名字。"""
    if is_custom(key):
        return custom_presets()[key]["name"]
    try:
        import kards_i18n as i18n
        return i18n.t("theme_p_" + str(key))
    except Exception:                                        # noqa: BLE001
        return str(key)


def save_custom(name, data=None, key=None):
    """新建或更新一个自定义模板，返回模板键（`custom:<slug>`）。

    key 给定时视为「编辑现有模板」：文件名不变（改名只改显示名），
    这样即使别处已经引用了这个键也不会失效。
    """
    name = _unique_name(name, exclude_key=key)
    old = custom_presets().get(key) if key else None
    base = old["data"] if old else DEFAULT_PRESET
    norm = normalize_preset(data if data is not None else (old or {}), base=base)

    d = custom_dir()
    os.makedirs(d, exist_ok=True)
    if old:
        slug = old["slug"]
    else:
        root = _slug(name) or "theme"
        slug = root
        existing = {info["slug"].lower() for info in custom_presets().values()}
        i = 2
        while slug.lower() in existing or os.path.exists(
                os.path.join(d, slug + ".json")):
            slug = "%s-%d" % (root, i)
            i += 1

    payload = {"version": 1, "name": name, "base": norm["base"],
               "light": norm["light"],
               "colors": {k: norm[k] for k in BASE_KEYS}}
    path = os.path.join(d, slug + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    _custom_cache["sig"] = None
    return CUSTOM_PREFIX + slug


def delete_custom(key):
    """删除模板文件。删的是当前主题时自动回落到默认，避免"主题指向空"。"""
    info = custom_presets().get(key)
    if not info:
        return False
    try:
        os.remove(info["path"])
    except OSError:
        return False
    _custom_cache["sig"] = None
    if _current["preset"] == key:
        apply(DEFAULT_PRESET, None)
    return True


def export_custom(key, path):
    """把模板导出成可分享的 JSON（只含显示名与颜色，不含本机路径）。"""
    info = custom_presets().get(key)
    if not info:
        raise ValueError("unknown template: %r" % (key,))
    data = info["data"]
    payload = {"version": 1, "name": info["name"], "base": data["base"],
               "light": data["light"],
               "colors": {k: data[k] for k in BASE_KEYS}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def import_custom(path, name=None):
    """从 JSON 导入模板，返回新模板键。文件坏了抛 ValueError（界面据此提示）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(raw, dict):
        raise ValueError("not a template object")
    if not isinstance(raw.get("colors"), dict) and not any(
            k in raw for k in BASE_KEYS):
        raise ValueError("no colours in file")
    nm = name or raw.get("name") or os.path.splitext(os.path.basename(path))[0]
    return save_custom(nm, raw)


def palette(preset=None, accent=None):
    """取一整套 token（不改变当前主题，供预览/测试使用）。"""
    key = _valid_key(preset)
    return _finalize(_base_for(key), accent)


def preview(preset):
    """预设的默认外观（不管用户当前选了什么主色），用于设置界面画色卡。"""
    return palette(preset, None)


_current = {"preset": DEFAULT_PRESET, "accent": "", "palette": None}


def current():
    """当前生效的 token 字典（惰性初始化）。"""
    if _current["palette"] is None:
        _current["palette"] = palette(_current["preset"] or DEFAULT_PRESET,
                                      _current["accent"] or None)
    return _current["palette"]


def preset_name():
    return _current["preset"] or DEFAULT_PRESET


def accent_color():
    return current()["accent"]


def _write_module_globals(p):
    g = globals()
    for tok in TOKENS:
        key = tok.lower()
        if key in p:
            g[tok] = p[key]


def apply(preset=None, accent=None):
    """切换主题并刷新本模块的常量。返回新的 token 字典。

    preset 合法（内置或自定义）就用它；非法 → 回落到默认；
    preset 为 None → 保持当前。
    accent 为空 → 用模板自带主色；与模板一致则记为空（跟随模板）。
    调用方（KARDS.py / kards_board.py）还需要 `sync(globals())`。
    """
    key = _valid_key(preset) if preset else _valid_key(_current["preset"])
    accent = _norm_hex(accent) if accent else None
    p = palette(key, accent)
    _current["preset"] = key
    base_accent = _norm_hex(_base_for(key).get("accent")) or ""
    _current["accent"] = accent if (accent and accent != base_accent) else ""
    _current["palette"] = p
    _write_module_globals(p)
    return p


def sync(namespace):
    """把当前 token 灌回调用方模块的命名空间（见模块开头「可切换主题」）。"""
    p = current()
    for tok in TOKENS:
        key = tok.lower()
        if key in p:
            namespace[tok] = p[key]
    return p


def reset():
    return apply(DEFAULT_PRESET, None)


# ---------------------------------------------------------------- 持久化
# 设置项与语言共用 settings.json（i18n.get_pref / set_pref）。
# 这里延迟 import —— kards_i18n 不依赖本模块，不会循环。

_PREF_PRESET = "theme_preset"
_PREF_ACCENT = "theme_accent"


def load():
    """从 settings.json 恢复主题；没有/非法就用默认。返回 preset 名。

    自定义模板被删掉后，上次存的 `custom:xxx` 会失效 —— 这里回落到默认，
    而不是让界面带着一套不存在的模板启动。
    """
    try:
        import kards_i18n as i18n
        preset = i18n.get_pref(_PREF_PRESET, DEFAULT_PRESET)
        accent = i18n.get_pref(_PREF_ACCENT, "") or ""
    except Exception:                                        # noqa: BLE001
        preset, accent = DEFAULT_PRESET, ""
    if not isinstance(preset, str) or _valid_key(preset) != preset:
        preset = DEFAULT_PRESET
    accent = _norm_hex(accent) or ""
    apply(preset, accent or None)
    return preset


def save(preset=None, accent=None):
    """写回 settings.json（失败静默 —— 主题不该让游戏起不来）。"""
    try:
        import kards_i18n as i18n
        if preset is not None:
            i18n.set_pref(_PREF_PRESET, preset)
        if accent is not None:
            i18n.set_pref(_PREF_ACCENT, accent)
    except Exception:                                        # noqa: BLE001
        pass


# ---------------------------------------------------------------- 阵营色
# 一眼能分辨敌我阵营的色相；"中立"用于无主卡（如部分衍生物）。
# 阵营色是**语义色**，不随主题变 —— 德国永远是德军灰，否则对局中认不出敌我。

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


# 初始化：模块级常量必须立刻有值（`from kards_theme import BG` 要能取到）
_write_module_globals(current())
