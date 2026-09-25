# -*- coding: utf-8 -*-
"""UI 优化补丁：
1. 悬停提示（Tooltip）：手牌/场上单位/敌方总部/组卡行显示卡牌详情+关键词说明
2. 可攻击的我方单位用绿色边框高亮
3. 资源不足/无法打出的手牌：整体置暗 + 费用标红
"""
import ast
import io

SRC = "kards_gui.py"
src = io.open(SRC, encoding="utf-8").read()
applied = []


def rep(old, new, tag, expect=1):
    global src
    n = src.count(old)
    if n != expect:
        raise SystemExit(f"[{tag}] 期望 {expect} 处，实际 {n} 处")
    src = src.replace(old, new)
    applied.append(tag)


# ---- 1. Tooltip 工具 + 卡牌详情文本 ----
rep('''def kw_text(keywords):
    return " ".join(f"[{k}]" for k in keywords)
''',
'''def kw_text(keywords):
    return " ".join(f"[{k}]" for k in keywords)


def bind_tooltip(widget, get_text, delay=420):
    """给单个控件挂悬停提示（延迟弹出，跟随鼠标）"""
    state = {"after": None, "tip": None}

    def hide(e=None):
        if state["after"]:
            try:
                widget.after_cancel(state["after"])
            except Exception:
                pass
            state["after"] = None
        if state["tip"]:
            try:
                state["tip"].destroy()
            except Exception:
                pass
            state["tip"] = None

    def show():
        try:
            text = get_text()
        except Exception:
            text = None
        if not text:
            return
        tip = tk.Toplevel(widget)
        tip.wm_overrideredirect(True)
        box = tk.Frame(tip, bg=GOLD, padx=1, pady=1)
        box.pack()
        tk.Label(box, text=text, bg="#10131a", fg=TEXT, font=FONT_S,
                 justify="left", wraplength=340, padx=9, pady=6).pack()
        tip.wm_geometry(f"+{widget.winfo_pointerx() + 16}+{widget.winfo_pointery() + 18}")
        state["tip"] = tip

    def enter(e=None):
        hide()
        state["after"] = widget.after(delay, show)

    widget.bind("<Enter>", enter, add="+")
    widget.bind("<Leave>", hide, add="+")
    widget.bind("<Button-1>", hide, add="+")


def bind_tooltip_tree(widget, get_text, delay=420):
    """把悬停提示递归绑定到控件及其全部子控件（卡牌内部是多个 Label）"""
    bind_tooltip(widget, get_text, delay)

    def rec(w):
        for c in w.winfo_children():
            bind_tooltip(c, get_text, delay)
            rec(c)
    rec(widget)


def card_tooltip(c, cost=None, unit=None):
    """卡牌详情提示文本：名称/国家/类型/费用/效果/关键词说明/稀有度"""
    lines = [c.name]
    if c.kind == "unit":
        if unit is not None:
            lines.append(f"{c.nation} · {unit.unit_type} · 当前 {unit.attack}/{unit.defense}")
        else:
            lines.append(f"{c.nation} · {c.unit_type} · {c.attack}/{c.defense}")
    else:
        tag = "反制" if c.kind == "counter" else "指令"
        lines.append(f"{c.nation} · [{tag}]")
    eff = cost if cost is not None else c.cost
    lines.append(f"费用 {eff}" + (f"（原 {c.cost}）" if eff != c.cost else ""))
    desc = getattr(c, "desc", "")
    if desc:
        lines.append("—— " + desc)
    for kw in getattr(c, "keywords", []):
        d = core.KEYWORD_DESC.get(kw)
        if d:
            lines.append(f"[{kw}] {d}")
    rar = getattr(c, "rarity", "")
    if rar:
        lines.append("★ " + rar)
    return "\\n".join(lines)


def foe_hq_tooltip(foe):
    return f"敌方总部\\n当前生命：{foe.hq}\\n把我方单位拖到这里即可直攻总部"
''',
    "tooltip-helpers")

# ---- 2. CardWidget: border / dim 参数 ----
rep('''    def __init__(self, master, title, sub, cost, color, on_click=None,
                 atk=None, defense=None, big=False, selected=False, draggable=False,
                 rarity=None):
        w, h = (180, 210) if big else (130, 150)
        bg = CARD_SEL if selected else CARD_BG
        hl = GOLD if selected else "#111318"''',
'''    def __init__(self, master, title, sub, cost, color, on_click=None,
                 atk=None, defense=None, big=False, selected=False, draggable=False,
                 rarity=None, border=None, dim=False):
        w, h = (180, 210) if big else (130, 150)
        bg = CARD_SEL if selected else ("#252a33" if dim else CARD_BG)
        hl = GOLD if selected else (border or "#111318")''',
    "cardwidget-params")

rep('''        if cost is not None:
            tk.Label(self, text=f"◆{cost}", bg=bg, fg=GOLD,
                     font=FONT_B).pack(side="bottom")''',
'''        if cost is not None:
            tk.Label(self, text=f"◆{cost}", bg=bg,
                     fg=RED if dim else GOLD,
                     font=FONT_B).pack(side="bottom")''',
    "cardwidget-cost")

# ---- 3. 手牌：dim 参数 + 悬停提示 ----
rep('''                cw = CardWidget(self.hand_frame, title=c.name, sub=sub, cost=eff,
                                color=NATION_COLOR.get(c.nation, "#666") if can else "#555",
                                draggable=True, rarity=c.rarity)''',
'''                cw = CardWidget(self.hand_frame, title=c.name, sub=sub, cost=eff,
                                color=NATION_COLOR.get(c.nation, "#666") if can else "#555",
                                draggable=True, rarity=c.rarity, dim=not can)''',
    "hand-dim")

rep('''                cw.pack(side="left", padx=4, ipady=4)
                self._bind_drag(cw, ("hand", i))''',
'''                cw.pack(side="left", padx=4, ipady=4)
                self._bind_drag(cw, ("hand", i))
                bind_tooltip_tree(cw, lambda c=c, eff=eff: card_tooltip(c, eff))''',
    "hand-tooltip")

# ---- 4. 敌方单位：悬停提示 ----
rep('''        cw = CardWidget(parent, title=u.name,
                        sub=f"{slot_tag} {u.unit_type} " + kw_text(u.keywords),
                        cost=None, color=color, atk=u.attack, defense=u.defense,
                        draggable=True, rarity=u.card.rarity)
        cw.pack(side="left", padx=5, ipady=6)
        self.enemy_widgets.append((u, cw))
        self.unit_widgets[id(u)] = cw''',
'''        cw = CardWidget(parent, title=u.name,
                        sub=f"{slot_tag} {u.unit_type} " + kw_text(u.keywords),
                        cost=None, color=color, atk=u.attack, defense=u.defense,
                        draggable=True, rarity=u.card.rarity)
        cw.pack(side="left", padx=5, ipady=6)
        self.enemy_widgets.append((u, cw))
        self.unit_widgets[id(u)] = cw
        bind_tooltip_tree(cw, lambda u=u: card_tooltip(u.card, unit=u))''',
    "enemy-tooltip")

# ---- 5. 我方单位：可攻击绿框 + 悬停提示 ----
rep('''        cw = CardWidget(parent, title=u.name, sub=sub, cost=None, color=color,
                        atk=u.attack, defense=u.defense, draggable=True,
                        rarity=u.card.rarity)
        cw.pack(side="left", padx=5, ipady=6)
        self.unit_widgets[id(u)] = cw
        self._bind_drag(cw, ("unit", u))''',
'''        cw = CardWidget(parent, title=u.name, sub=sub, cost=None, color=color,
                        atk=u.attack, defense=u.defense, draggable=True,
                        rarity=u.card.rarity, border=GREEN if ready else None)
        cw.pack(side="left", padx=5, ipady=6)
        self.unit_widgets[id(u)] = cw
        self._bind_drag(cw, ("unit", u))
        bind_tooltip_tree(cw, lambda u=u: card_tooltip(u.card, unit=u))''',
    "my-card")

# ---- 6. 敌方总部：悬停提示 ----
rep('''        hq.pack(side="left", padx=(8, 14), ipady=6)
        self.hq_widget = hq''',
'''        hq.pack(side="left", padx=(8, 14), ipady=6)
        self.hq_widget = hq
        bind_tooltip_tree(hq, lambda f=foe: foe_hq_tooltip(f))''',
    "hq-tooltip")

# ---- 7. 组卡界面：可用卡/已选卡行悬停提示 ----
rep('''            row.pack(fill="x", pady=1)
            row.bind("<Button-1>", lambda e, card=c: self._add_card(card))''',
'''            row.pack(fill="x", pady=1)
            row.bind("<Button-1>", lambda e, card=c: self._add_card(card))
            bind_tooltip(row, lambda c=c: card_tooltip(c))''',
    "builder-avail")

rep('''            row.pack(fill="x", pady=1)
            row.bind("<Button-1>", lambda e, card=c: self._remove_card(card))''',
'''            row.pack(fill="x", pady=1)
            row.bind("<Button-1>", lambda e, card=c: self._remove_card(card))
            bind_tooltip(row, lambda c=c: card_tooltip(c))''',
    "builder-deck")

ast.parse(src)
io.open(SRC, "w", encoding="utf-8", newline="").write(src)
print("OK, 应用补丁:", ", ".join(applied))
