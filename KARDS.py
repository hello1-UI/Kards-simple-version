# -*- coding: utf-8 -*-
"""
KARDS 简化版 - 图形界面（tkinter，纯标准库）

复用 kards.py 的游戏逻辑，提供点击式对战界面：
- 开始界面：战斗（联机预留）/ 练习（人机对战）
- 练习模式：5 大主国选阵营 → 自由组卡（39 张 + 总部卡，单卡≤3，盟国≤20）
  → 支持粘贴原版卡牌清单导入（中英文名均可）→ 随机匹配（可内战）→ 随机先手/后手
- 对战中右上角「⚙ 设置/投降」：投降 / 返回主菜单 / 安全退出；Esc 快捷退出
- 拖拽操作：手牌拖到「我方支援阵线」部署；我方单位拖到敌方单位/总部攻击；
  拖到「我方前线」行上前线、拖回「我方支援阵线」行撤后（移动/攻击均消耗行动费）
- AI 逐个动作播放（🐢慢速/🐇快速切换）；固定我方视角，AI 回合不泄露手牌
- 联机对战（⚔ 战斗）：局域网 TCP 直连，主机/加入，锁定步同步
  （开始界面 → 战斗 → 主机/加入 → 选阵营组卡 → 开打；中途退出/投降会通知对手）
- 本机自战调试：python kards_gui.py --debug-on-net（双窗口自动互联，自己打自己）

运行方式:
    python kards_gui.py
    python kards_gui.py --smoke   # 自动完整对局冒烟测试（无交互）
"""

import math
import queue
import random
import sys
import tkinter as tk
from tkinter import messagebox, simpledialog


import kards_engine as core
import kards_i18n as i18n
import kards_net as net
import kards_account as account

# ---------------------------------------------------------------- 主题配色

BG = "#1a1d23"          # 背景
PANEL = "#242831"       # 面板
CARD_BG = "#2e3440"     # 卡牌
CARD_SEL = "#4c6b8a"    # 选中
TEXT = "#e6e6e6"
DIM = "#9aa0a8"
RED = "#e05c5c"
GREEN = "#6fbf73"
GOLD = "#e0b45c"
NATION_COLOR = {
    "德国": "#6b7a8f", "苏联": "#a05a4c", "美国": "#4c7a6b",
    "英国": "#7a6b8f", "日本": "#8f6b4c",
    "意大利": "#6f8f6b", "法国": "#6b7a9f", "芬兰": "#8fb0c8",
    "波兰": "#c8a06b", "澳新军团": "#8f9f6b", "中立": "#7a7a7a",
}

APP_TITLE = "KARDS 简化版 - 二战卡牌对战"

# ---------------- 版本号 a.b.c.d ----------------
# a: 重要修复(1位数)  b: 卡牌更新(2位数)  c: 赛季更新(2位数)  d: 补丁修复(3位数)
# 升位规则: 某位 +1 后, 其右侧所有位清零（如卡牌更新 1.01.00.000）
# 升级工具: python debug/bump_version.py a|b|c|d （自动改此处并提交 git）
VERSION = (1, 1, 2, 2)

FONT = ("Microsoft YaHei UI", 12)
FONT_S = ("Microsoft YaHei UI", 10)
FONT_B = ("Microsoft YaHei UI", 13, "bold")
FONT_XL = ("Microsoft YaHei UI", 32, "bold")


def kw_text(keywords):
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
    op = getattr(c, "operate", 0)
    if op:
        lines.append(f"行动费 {op}（每次攻击额外消耗）")
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
    return "\n".join(lines)


def foe_hq_tooltip(foe):
    return f"敌方总部\n当前生命：{foe.hq}\n把我方单位拖到这里即可直攻总部"


# ---------------------------------------------------------------- 带GUI日志的Game

class GUIGame(core.Game):
    """把 log 输出重定向到回调"""

    def __init__(self, p1, p2, log_fn, event_fn=None):
        super().__init__(p1, p2, interactive=False)
        self.log_fn = log_fn
        self.event_hook = event_fn        # 动画事件钩子（部署/伤害/摧毁…）

    def log(self, msg):
        self.log_fn(msg)
        core.write_game_log(msg)


# ---------------------------------------------------------------- 卡牌小组件

class CardWidget(tk.Frame):
    def __init__(self, master, title, sub, cost, color, on_click=None,
                 atk=None, defense=None, big=False, selected=False, draggable=False,
                 rarity=None, border=None, dim=False):
        w, h = (180, 210) if big else (130, 150)
        bg = CARD_SEL if selected else ("#252a33" if dim else CARD_BG)
        hl = GOLD if selected else (border or "#111318")
        super().__init__(master, width=w, height=h, bg=bg, bd=0,
                         highlightthickness=2,
                         highlightbackground=hl, highlightcolor=hl,
                         padx=4, pady=4,
                         cursor="hand2" if (on_click or draggable) else "arrow")
        self.pack_propagate(False)
        inner_w = w - 20

        tk.Label(self, text=title, bg=bg, fg=TEXT, font=FONT_B,
                 wraplength=inner_w, justify="center").pack(pady=(2, 0))

        mid = tk.Frame(self, bg=bg)
        mid.pack(expand=True, fill="both")
        if atk is not None:
            tk.Label(mid, text=str(atk), bg=bg, fg=GOLD,
                     font=("Microsoft YaHei UI", 16, "bold")).pack(side="left", expand=True)
            tk.Label(mid, text=str(defense), bg=bg, fg=GREEN,
                     font=("Microsoft YaHei UI", 16, "bold")).pack(side="right", expand=True)
            if sub:
                tk.Label(mid, text=sub, bg=bg, fg=DIM, font=FONT_S,
                         wraplength=inner_w, justify="center").pack(side="bottom")
        else:
            tk.Label(mid, text=sub or "", bg=bg, fg=DIM, font=FONT_S,
                     wraplength=inner_w, justify="center").pack(expand=True)

        if cost is not None:
            tk.Label(self, text=f"◆{cost}", bg=bg,
                     fg=RED if dim else GOLD,
                     font=FONT_B).pack(side="bottom")
        if rarity:
            tk.Label(self, text=rarity, bg=core.RARITY_COLORS[rarity], fg="#15171c",
                     font=("Microsoft YaHei UI", 8, "bold"), padx=3).place(
                relx=1.0, x=-3, y=3, anchor="ne")
        if color:
            tk.Frame(self, bg=color, height=4).pack(side="bottom", fill="x")
        if on_click:
            for child in self.winfo_children():
                child.bind("<Button-1>", lambda e: on_click())
                if isinstance(child, tk.Frame):
                    for c2 in child.winfo_children():
                        c2.bind("<Button-1>", lambda e: on_click())
            self.bind("<Button-1>", lambda e: on_click())


# ---------------------------------------------------------------- 主界面

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.configure(bg=BG)
        self.geometry("1200x800")
        self.minsize(1024, 680)
        self.game = None
        self.busy = False          # AI 行动/动画期间锁定输入
        self.anim_enabled = ("--smoke" not in sys.argv) or ("--anim-test" in sys.argv)
        self.ai_step_ms = 0 if not self.anim_enabled else 850
        self.fast_ai = False
        self.unit_widgets = {}     # id(unit) -> 卡片控件
        self.enemy_widgets = []    # (unit, 卡片控件)，用于拖拽命中检测
        self.hq_widget = None      # 敌方总部控件（拖拽落点）
        self.drag = None           # 当前拖拽状态
        self.pending_flash = []    # 刷新后待播放入场动画的单位 (unit, color)
        self._last_drag_src = None # 最近一次拖拽起点坐标（部署入场动画的来源）
        self._anim_tokens = set()  # 存活的动画令牌（退出对局时清理）
        self._anim_count = {"entry": 0, "move": 0, "attack": 0}  # 自测统计
        # ---- 联机状态 ----
        self.mp_link = None        # net.NetLink（联机时非 None）
        self.mp_role = None        # "host" / "client"
        self.mp_mode = False       # 组卡界面是否处于联机流程
        self.mp_acceptor = None    # 主机等待中的 Acceptor
        self.mp_join = None        # 加入方的 holder dict
        self.mp_opp = None         # 对手 hello 信息 {nation, deck}
        self.mp_my_deck = None     # 我方有序卡名列表
        self._mp_game_over = False
        self._lobby_active = False
        self.db = core.card_database()
        # ---- 本地账号 ----
        self.account = account.current()
        if self.account:
            core.set_decks_dir(account.deck_dir(self.account))
        self.bind_all("<Escape>", self.on_esc)
        self._build_start()
        if not self.account and self.anim_enabled:
            self.after(300, self._account_dialog)

    def destroy(self):
        """退出前关闭联机连接"""
        if self.mp_link is not None:
            self.mp_link.close()
            self.mp_link = None
        tk.Tk.destroy(self)

    # ---------------- 日志 ----------------
    def add_log(self, msg):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    # ---------------- 开始界面：战斗 / 练习 ----------------
    def _build_start(self):
        self.start_frame = tk.Frame(self, bg=BG)
        self.start_frame.pack(expand=True, fill="both")
        tk.Label(self.start_frame, text=i18n.t("app_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(100, 8))
        tk.Label(self.start_frame, text=i18n.t("app_subtitle"), bg=BG, fg=DIM,
                 font=FONT).pack(pady=(0, 40))
        tk.Button(self.start_frame, text=i18n.t("btn_settings"), bg="#4a4f5a", fg=TEXT,
                  font=FONT_S, bd=0, padx=12, pady=6, cursor="hand2",
                  command=self.open_start_settings).pack(anchor="ne", padx=16, pady=10)
        row = tk.Frame(self.start_frame, bg=BG)
        row.pack()
        CardWidget(row, title=i18n.t("battle_title"), sub=i18n.t("battle_sub"),
                   cost=None, color="#8a3a3a", big=True,
                   on_click=self.on_battle).pack(side="left", padx=14, ipady=8)
        CardWidget(row, title=i18n.t("practice_title"), sub=i18n.t("practice_sub"),
                   cost=None, color="#3a5a80", big=True,
                   on_click=lambda: self._build_nation_select()).pack(
            side="left", padx=14, ipady=8)
        # 主页下端：版本号
        tk.Label(self.start_frame, text="v" + ".".join(map(str, VERSION)),
                 bg=BG, fg=DIM, font=FONT_S).pack(side="bottom", pady=(0, 14))
        # 左上角：账号入口
        self.account_btn = tk.Button(self.start_frame, text=self._account_btn_text(),
                                     bg="#4a4f5a", fg=TEXT, font=FONT_S, bd=0,
                                     padx=12, pady=6, cursor="hand2",
                                     command=self._account_dialog)
        self.account_btn.pack(anchor="nw", padx=16)

    # ---------------- 账号管理 ----------------
    def _account_btn_text(self):
        if self.account:
            s = account.get_stats(self.account)
            return i18n.t("account_btn", name=self.account,
                          w=s["win"], l=s["lose"], d=s["draw"])
        return i18n.t("account_nouser")

    def _refresh_account_btn(self):
        if getattr(self, "account_btn", None) and self.account_btn.winfo_exists():
            self.account_btn.configure(text=self._account_btn_text())

    def _apply_account(self, name):
        """登录/注册成功后应用账号（卡组目录 + 按钮）"""
        self.account = name
        core.set_decks_dir(account.deck_dir(name))
        self._refresh_account_btn()

    def _account_dialog(self):
        win = tk.Toplevel(self)
        win.title(i18n.t("account_title"))
        win.configure(bg=BG)
        win.geometry("380x360")
        win.transient(self)
        tk.Label(win, text=i18n.t("account_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(18, 8))
        info = tk.Label(win, text="", bg=BG, fg=RED, font=FONT_S)
        info.pack()

        if self.account:
            s = account.get_stats(self.account)
            tk.Label(win, text=i18n.t("account_stats", w=s["win"], l=s["lose"], d=s["draw"]),
                     bg=BG, fg=GOLD, font=FONT).pack(pady=10)

            def do_logout():
                account.logout()
                self.account = None
                core.set_decks_dir(None)
                self._refresh_account_btn()
                win.destroy()

            row = tk.Frame(win, bg=BG)
            row.pack(pady=14)
            tk.Button(row, text=i18n.t("account_logout"), bg="#8a3a3a", fg=TEXT,
                      font=FONT, bd=0, padx=14, pady=6, cursor="hand2",
                      command=do_logout).pack()
            return

        # 登录 / 注册表单
        tk.Label(win, text=i18n.t("account_user"), bg=BG, fg=DIM,
                 font=FONT_S).pack(pady=(10, 2))
        e_user = tk.Entry(win, font=FONT, width=22, bg=PANEL, fg=TEXT,
                          insertbackground=TEXT, relief="flat")
        e_user.pack(pady=2)
        tk.Label(win, text=i18n.t("account_pw"), bg=BG, fg=DIM,
                 font=FONT_S).pack(pady=(8, 2))
        e_pw = tk.Entry(win, font=FONT, width=22, show="*", bg=PANEL, fg=TEXT,
                        insertbackground=TEXT, relief="flat")
        e_pw.pack(pady=2)

        def done(ok, err):
            if ok:
                self._apply_account(account.current())
                win.destroy()
                self.add_log(f"账号已登录: {self.account}")
            else:
                info.configure(text=err)

        def try_login():
            done(*account.login(e_user.get(), e_pw.get()))

        def try_register():
            done(*account.register(e_user.get(), e_pw.get()))

        row = tk.Frame(win, bg=BG)
        row.pack(pady=16)
        tk.Button(row, text=i18n.t("account_login"), bg="#3a5a80", fg=TEXT,
                  font=FONT, bd=0, padx=14, pady=6, cursor="hand2",
                  command=try_login).pack(side="left", padx=8)
        tk.Button(row, text=i18n.t("account_register"), bg="#4a7a4a", fg=TEXT,
                  font=FONT, bd=0, padx=14, pady=6, cursor="hand2",
                  command=try_register).pack(side="left", padx=8)

    def open_start_settings(self):
        """主界面右上角设置：语言 / 操作说明 / 退出游戏"""
        win = tk.Toplevel(self)
        win.title(i18n.t("settings_title"))
        win.configure(bg=BG)
        win.geometry("380x400")
        win.transient(self)
        tk.Label(win, text=i18n.t("settings_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(18, 6))

        def apply_lang():
            # 切换语言：保存偏好 → 重建主界面 → 重开设置窗（立即生效）
            i18n.set_lang(i18n.get_lang())
            self.start_frame.destroy()
            self._build_start()
            win.destroy()
            self.open_start_settings()

        self._lang_buttons(win, on_change=apply_lang)

        def show_help():
            messagebox.showinfo(i18n.t("help_title"), i18n.t("help_text"))

        def quit_app():
            if messagebox.askyesno(i18n.t("quit_title"), i18n.t("quit_confirm")):
                win.destroy()
                self.destroy()

        for text, cmd, color in ((i18n.t("btn_help"), show_help, "#3a5a80"),
                                 (i18n.t("btn_quit"), quit_app, "#4a4f5a")):
            tk.Button(win, text=text, bg=color, fg=TEXT, font=FONT_B, bd=0,
                      padx=18, pady=8, cursor="hand2", command=cmd).pack(pady=6)

    def _lang_buttons(self, win, on_change):
        """设置窗中的语言切换行：三个语言按钮，当前语言置灰不可点"""
        tk.Label(win, text=i18n.t("settings_language"), bg=BG, fg=DIM,
                 font=FONT_S).pack(pady=(12, 4))
        row = tk.Frame(win, bg=BG)
        row.pack()
        for code in i18n.LANG_NAMES:
            cur = i18n.get_lang() == code
            tk.Button(row, text=i18n.LANG_NAMES[code],
                      bg="#3a5a80" if cur else "#4a4f5a",
                      fg=TEXT, font=FONT_S, bd=0, padx=12, pady=6,
                      cursor="hand2", state="disabled" if cur else "normal",
                      command=lambda c=code: (i18n.set_lang(c), on_change())
                      ).pack(side="left", padx=4)

    def on_battle(self):
        self._build_lobby()

    # ---------------- 联机大厅 ----------------
    def _build_lobby(self):
        self.start_frame.destroy()
        self.start_frame = tk.Frame(self, bg=BG)
        self.start_frame.pack(expand=True, fill="both")
        self._lobby_active = True
        tk.Label(self.start_frame, text=i18n.t("lobby_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(70, 4))
        tk.Label(self.start_frame, text=i18n.t("lobby_sub"),
                 bg=BG, fg=DIM, font=FONT).pack(pady=(0, 26))

        tk.Button(self.start_frame, text=i18n.t("btn_back"), bg="#4a4f5a", fg=TEXT,
                  font=FONT_S, bd=0, padx=14, pady=6, cursor="hand2",
                  command=self._lobby_back).pack(anchor="ne", padx=18)

        box = tk.Frame(self.start_frame, bg=PANEL, bd=1, relief="solid")
        box.pack(pady=8, ipadx=30, ipady=16, fill="x", padx=180)
        tk.Label(box, text=i18n.t("host_title"), bg=PANEL, fg=TEXT,
                 font=FONT_B).pack(anchor="w", padx=16)
        row1 = tk.Frame(box, bg=PANEL)
        row1.pack(anchor="w", padx=16, pady=6)
        tk.Label(row1, text=i18n.t("label_port"), bg=PANEL, fg=DIM, font=FONT_S).pack(side="left")
        self.host_port_var = tk.StringVar(value="5555")
        tk.Entry(row1, textvariable=self.host_port_var, width=8,
                 bg="#1a1d24", fg=TEXT, insertbackground=TEXT,
                 relief="flat").pack(side="left", padx=(4, 14))
        self.host_btn = tk.Button(row1, text=i18n.t("btn_start_wait"), bg="#2e6b46", fg=TEXT,
                                  font=FONT_S, bd=0, padx=14, pady=6,
                                  cursor="hand2", command=self._mp_begin_host)
        self.host_btn.pack(side="left")
        self.host_status = tk.Label(box, text="", bg=PANEL, fg=GOLD,
                                    font=FONT_S, anchor="w", justify="left")
        self.host_status.pack(anchor="w", padx=16)

        box2 = tk.Frame(self.start_frame, bg=PANEL, bd=1, relief="solid")
        box2.pack(pady=8, ipadx=30, ipady=16, fill="x", padx=180)
        tk.Label(box2, text=i18n.t("join_title"), bg=PANEL, fg=TEXT,
                 font=FONT_B).pack(anchor="w", padx=16)
        row2 = tk.Frame(box2, bg=PANEL)
        row2.pack(anchor="w", padx=16, pady=6)
        tk.Label(row2, text=i18n.t("label_host_ip"), bg=PANEL, fg=DIM, font=FONT_S).pack(side="left")
        self.join_ip_var = tk.StringVar(value="192.168.1.")
        tk.Entry(row2, textvariable=self.join_ip_var, width=14,
                 bg="#1a1d24", fg=TEXT, insertbackground=TEXT,
                 relief="flat").pack(side="left", padx=(4, 10))
        tk.Label(row2, text=i18n.t("label_port"), bg=PANEL, fg=DIM, font=FONT_S).pack(side="left")
        self.join_port_var = tk.StringVar(value="5555")
        tk.Entry(row2, textvariable=self.join_port_var, width=8,
                 bg="#1a1d24", fg=TEXT, insertbackground=TEXT,
                 relief="flat").pack(side="left", padx=(4, 14))
        self.join_btn = tk.Button(row2, text=i18n.t("btn_connect"), bg="#3a5a80", fg=TEXT,
                                  font=FONT_S, bd=0, padx=14, pady=6,
                                  cursor="hand2", command=self._mp_begin_join)
        self.join_btn.pack(side="left")
        self.join_status = tk.Label(box2, text="", bg=PANEL, fg=GOLD,
                                    font=FONT_S, anchor="w")
        self.join_status.pack(anchor="w", padx=16)

        ips = "\n".join("  · " + ip for ip in net.get_local_ips())
        tk.Label(self.start_frame, text=f"本机 IP（主机把下面的地址告诉好友）：\n{ips}",
                 bg=BG, fg=DIM, font=FONT_S, justify="left").pack(pady=(14, 0))
        self.after(120, self._lobby_poll)

    def _lobby_back(self):
        if self.mp_acceptor is not None:
            self.mp_acceptor.cancel()
            self.mp_acceptor = None
        self.mp_join = None
        self._lobby_active = False
        self.start_frame.destroy()
        self._build_start()

    def _lobby_poll(self):
        """轮询主机/加入结果（后台线程只写结果，GUI 线程消费）"""
        if not self._lobby_active:
            return
        if self.mp_acceptor is not None and self.mp_acceptor.result is not None:
            res = self.mp_acceptor.result
            self.mp_acceptor = None
            if res[0] == "err":
                self.host_status.configure(text=i18n.t("host_fail", err=res[1]))
                self.host_btn.configure(state="normal")
            else:
                self.mp_link, self.mp_role = res[0], "host"
                self._lobby_active = False
                self.host_status.configure(text=i18n.t("host_connected"))
                self.after(400, lambda: self._build_nation_select(mp=True))
                return
        if self.mp_join is not None and self.mp_join.get("result") is not None:
            res = self.mp_join["result"]
            self.mp_join = None
            if res[0] == "err":
                self.join_status.configure(text=i18n.t("join_fail", err=res[1]))
                self.join_btn.configure(state="normal")
            else:
                self.mp_link, self.mp_role = res[0], "client"
                self._lobby_active = False
                self.join_status.configure(text=i18n.t("join_connected"))
                self.after(400, lambda: self._build_nation_select(mp=True))
                return
        self.after(120, self._lobby_poll)

    def _mp_begin_host(self):
        try:
            port = int(self.host_port_var.get().strip() or "5555")
            assert 1 <= port <= 65535
        except (ValueError, AssertionError):
            messagebox.showwarning(i18n.t("warn_port_title"), i18n.t("warn_port_range"))
            return
        try:
            self.mp_acceptor = net.Acceptor(port)
        except OSError as e:
            messagebox.showerror(i18n.t("host_fail_title"),
                                 i18n.t("host_fail_msg", port=port, err=e))
            return
        self.host_btn.configure(state="disabled")
        self.host_status.configure(text=i18n.t("host_waiting", port=port))

    def _mp_begin_join(self):
        ip = self.join_ip_var.get().strip()
        try:
            port = int(self.join_port_var.get().strip() or "5555")
        except ValueError:
            messagebox.showwarning(i18n.t("warn_port_title"), i18n.t("warn_port_num"))
            return
        if not ip:
            messagebox.showwarning(i18n.t("warn_ip_title"), i18n.t("warn_ip"))
            return
        self.join_btn.configure(state="disabled")
        self.join_status.configure(text=i18n.t("connecting", ip=ip, port=port))
        self.mp_join = {}
        net.connect_async(ip, port, self.mp_join)

    # ---------------- 练习：选择主国 ----------------
    def _build_nation_select(self, mp=False):
        self.mp_mode = mp
        self.start_frame.destroy()
        self.start_frame = tk.Frame(self, bg=BG)
        self.start_frame.pack(expand=True, fill="both")
        tk.Label(self.start_frame, text=i18n.t("mode_mp") if mp else i18n.t("mode_sp"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(80, 6))
        tk.Label(self.start_frame, text=i18n.t("nation_sub"),
                 bg=BG, fg=DIM, font=FONT).pack(pady=(0, 26))
        row = tk.Frame(self.start_frame, bg=BG)
        row.pack()
        for i, nation in enumerate(core.MAIN_NATIONS):
            hq = core.HQ_CARDS[nation]
            CardWidget(row, title=nation,
                       sub=f"{hq.name} {hq.hp} HP\n{hq.perk_desc}",
                       cost=None, color=NATION_COLOR[nation], big=True,
                       on_click=lambda n=nation: self._build_deck_builder(n, mp=self.mp_mode)).pack(
                side="left", padx=8, ipady=8)

    # ---------------- 组卡界面 ----------------
    def _build_deck_builder(self, nation, mp=False):
        self.mp_mode = mp
        self.start_frame.destroy()
        self.deck_nation = nation
        self.deck_counts = {}   # 卡名 -> 数量
        self.builder_frame = tk.Frame(self, bg=BG)
        self.builder_frame.pack(expand=True, fill="both")

        hq = core.HQ_CARDS[nation]
        top = tk.Frame(self.builder_frame, bg=BG)
        top.pack(fill="x", padx=20, pady=(12, 4))
        left_t = tk.Frame(top, bg=BG)
        left_t.pack(side="left")
        tk.Label(left_t, text=f"组建 {nation} 卡组", bg=BG, fg=TEXT,
                 font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
        tk.Label(left_t, text=f"总部卡：{hq.name}（{hq.hp} HP）｜{hq.perk_desc}｜"
                              f"可用：{nation} + 盟国（意大利/法国/芬兰/波兰/澳新军团）",
                 bg=BG, fg=DIM, font=FONT_S).pack(anchor="w")
        right_t = tk.Frame(top, bg=BG)
        right_t.pack(side="right")
        self.deck_count_lbl = tk.Label(right_t, text="", bg=BG, fg=GOLD,
                                       font=("Microsoft YaHei UI", 16, "bold"))
        self.deck_count_lbl.pack(side="left", padx=10)
        self.ally_count_lbl = tk.Label(right_t, text="", bg=BG, fg=DIM, font=FONT_S)
        self.ally_count_lbl.pack(side="left", padx=10)
        tk.Button(right_t, text=i18n.t("btn_import"), bg="#6b4c7a", fg=TEXT, font=FONT_S,
                  bd=0, padx=12, pady=6, cursor="hand2",
                  command=self.on_import_deck).pack(side="left", padx=4)
        tk.Button(right_t, text=i18n.t("btn_save"), bg="#6b5a2a", fg=TEXT, font=FONT_S,
                  bd=0, padx=12, pady=6, cursor="hand2",
                  command=self.on_save_deck).pack(side="left", padx=4)
        tk.Button(right_t, text=i18n.t("btn_load"), bg="#4a5a6b", fg=TEXT, font=FONT_S,
                  bd=0, padx=12, pady=6, cursor="hand2",
                  command=self.on_load_deck).pack(side="left", padx=4)
        tk.Button(right_t, text=i18n.t("btn_recommend"), bg="#3a5a80", fg=TEXT, font=FONT_S,
                  bd=0, padx=12, pady=6, cursor="hand2",
                  command=self._auto_fill).pack(side="left", padx=4)
        tk.Button(right_t, text=i18n.t("btn_clear"), bg="#4a4f5a", fg=TEXT, font=FONT_S,
                  bd=0, padx=12, pady=6, cursor="hand2",
                  command=lambda: self._auto_fill(clear=True)).pack(side="left", padx=4)
        self.start_btn = tk.Button(
            right_t, text=i18n.t("btn_start_mp") if mp else i18n.t("btn_start_sp"),
            state="disabled",
            bg="#2e6b46", fg=TEXT, font=FONT_B, bd=0,
            padx=20, pady=8, cursor="hand2",
            activebackground="#3d8a5c",
            command=self._start_mp if mp else self._start_custom)
        self.start_btn.pack(side="left", padx=(10, 0))

        body = tk.Frame(self.builder_frame, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=4)

        leftw = tk.Frame(body, bg=BG)
        leftw.pack(side="left", fill="both", expand=True)
        tk.Label(leftw, text=i18n.t("label_pool"), bg=BG, fg=DIM,
                 font=FONT).pack(anchor="w")
        legend = "  ".join(f"{r}{core.RARITY_STARS[r]}"
                           for r in ("稀有", "史诗", "传说"))
        tk.Label(leftw, text=i18n.t("legend", legend=legend), bg=BG, fg=DIM,
                 font=FONT_S).pack(anchor="w")
        self._make_scroll_list(leftw, "avail")

        rightw = tk.Frame(body, bg=BG)
        rightw.pack(side="right", fill="both", expand=True, padx=(16, 0))
        tk.Label(rightw, text=i18n.t("label_deck"), bg=BG, fg=DIM,
                 font=FONT).pack(anchor="w")
        self._make_scroll_list(rightw, "deck")

        self._builder_refresh()

    def _make_scroll_list(self, parent, key):
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=inner, anchor="nw", tags="inner")
        inner.bind("<Configure>",
                   lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e, c=canvas, i=inner: c.itemconfigure("inner", width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def wheel(e, c=canvas):
            c.yview_scroll(-1 * (e.delta // 120), "units")
        for w in (canvas, inner):
            w.bind("<MouseWheel>", wheel)
            w.bind("<Button-4>", lambda e, c=canvas: c.yview_scroll(-1, "units"))
            w.bind("<Button-5>", lambda e, c=canvas: c.yview_scroll(1, "units"))

        if key == "avail":
            self.avail_inner = inner
        else:
            self.deck_inner = inner

    def _deck_total(self):
        return sum(self.deck_counts.values())

    def _deck_ally_count(self):
        return sum(n for name, n in self.deck_counts.items()
                   if name in self.db and self.db[name].nation in core.ALLY_NATIONS)

    @staticmethod
    def _card_row_text(c):
        stars = core.RARITY_STARS.get(getattr(c, "rarity", "普通"), "")
        if c.kind == "unit":
            kws = " ".join(f"[{k}]" for k in c.keywords)
            return f"◆{c.cost}  {c.name}{stars}   {c.unit_type} {c.attack}/{c.defense} {kws}"
        tag = "反制" if c.kind == "counter" else "指令"
        return f"◆{c.cost}  [{tag}]{stars} {c.name}   {c.desc}"

    def _builder_refresh(self):
        for w in self.avail_inner.winfo_children():
            w.destroy()
        for c in core.allowed_cards(self.deck_nation, self.db):
            n = self.deck_counts.get(c.name, 0)
            row = tk.Label(self.avail_inner, bg=CARD_BG if n else BG,
                           fg=GOLD if n else TEXT, font=FONT_S, anchor="w",
                           padx=10, pady=4,
                           text=self._card_row_text(c) + i18n.t("copies", n=n, max=core.MAX_COPIES))
            row.pack(fill="x", pady=1)
            row.bind("<Button-1>", lambda e, card=c: self._add_card(card))
            bind_tooltip(row, lambda c=c: card_tooltip(c))
        for w in self.deck_inner.winfo_children():
            w.destroy()
        cards = sorted((self.db[name] for name in self.deck_counts),
                       key=lambda c: (c.cost, c.name))
        if not cards:
            tk.Label(self.deck_inner, text=i18n.t("deck_empty"),
                     bg=BG, fg=DIM, font=FONT_S).pack(anchor="w", padx=10, pady=8)
        for c in cards:
            n = self.deck_counts[c.name]
            row = tk.Label(self.deck_inner, bg=PANEL, fg=TEXT, font=FONT_S,
                           anchor="w", padx=10, pady=4,
                           text=f"×{n}  {self._card_row_text(c)}")
            row.pack(fill="x", pady=1)
            row.bind("<Button-1>", lambda e, card=c: self._remove_card(card))
            bind_tooltip(row, lambda c=c: card_tooltip(c))
        total = self._deck_total()
        ally = self._deck_ally_count()
        self.deck_count_lbl.configure(text=f"{total}/{core.DECK_SIZE}")
        self.ally_count_lbl.configure(text=i18n.t("ally_count", ally=ally, limit=core.ALLY_LIMIT))
        ok = total == core.DECK_SIZE
        if ok:
            ok, _ = core.validate_deck(self._counts_to_deck(), self.deck_nation, self.db)
        self.start_btn.configure(state="normal" if ok else "disabled")

    def _add_card(self, card):
        n = self.deck_counts.get(card.name, 0)
        if n >= core.MAX_COPIES:
            return
        if self._deck_total() >= core.DECK_SIZE:
            return
        if card.nation in core.ALLY_NATIONS and self._deck_ally_count() >= core.ALLY_LIMIT:
            return
        self.deck_counts[card.name] = n + 1
        self._builder_refresh()

    def _remove_card(self, card):
        n = self.deck_counts.get(card.name, 0)
        if n <= 1:
            self.deck_counts.pop(card.name, None)
        else:
            self.deck_counts[card.name] = n - 1
        self._builder_refresh()

    def _counts_to_deck(self):
        deck = []
        for name, n in self.deck_counts.items():
            deck += [self.db[name]] * n
        return deck

    def _auto_fill(self, clear=False):
        """按推荐思路补满：低费加权，约 33 张单位 + 6 张指令/反制"""
        if clear:
            self.deck_counts = {}
        pool = core.allowed_cards(self.deck_nation, self.db)
        weights = [core.COST_WEIGHT.get(c.cost, 1) for c in pool]
        guard = 0
        while self._deck_total() < core.DECK_SIZE and guard < 100000:
            guard += 1
            c = random.choices(pool, weights=weights, k=1)[0]
            if self.deck_counts.get(c.name, 0) >= core.MAX_COPIES:
                continue
            if c.nation in core.ALLY_NATIONS and self._deck_ally_count() >= core.ALLY_LIMIT:
                continue
            self.deck_counts[c.name] = self.deck_counts.get(c.name, 0) + 1
        self._builder_refresh()

    def on_import_deck(self):
        """从原版游戏导入卡组：粘贴卡牌清单（支持英文名）"""
        win = tk.Toplevel(self)
        win.title(i18n.t("btn_import"))
        win.configure(bg=BG)
        win.geometry("640x520")
        tk.Label(win, text=i18n.t("import_prompt"), bg=BG, fg=TEXT,
                 font=FONT_B).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(win, text=i18n.t("import_hint"),
                 bg=BG, fg=DIM, font=FONT_S, justify="left").pack(anchor="w", padx=14)
        txt = tk.Text(win, width=72, height=16, bg=PANEL, fg=TEXT,
                      font=FONT_S, bd=0, padx=8, pady=6)
        txt.pack(fill="both", expand=True, padx=14, pady=8)

        def do_import():
            counts, unmatched = core.parse_deck_text(txt.get("1.0", "end"), self.db)
            self.deck_counts = {}
            for name, n in counts.items():
                self.deck_counts[name] = min(n, core.MAX_COPIES)
            win.destroy()
            self._builder_refresh()
            msg = i18n.t("import_result", n=sum(counts.values()), m=self._deck_total())
            if unmatched:
                msg += i18n.t("import_unmatched", k=len(unmatched),
                              samples="；".join(unmatched[:3]))
            messagebox.showinfo(i18n.t("import_result_title"), msg)

        tk.Button(win, text=i18n.t("btn_import_go"), bg="#2e6b46", fg=TEXT, font=FONT_B, bd=0,
                  padx=20, pady=8, cursor="hand2", command=do_import).pack(pady=(0, 12))

    def on_save_deck(self):
        """保存当前卡组（含国家标记），存到游戏目录下的 decks/ 文件夹"""
        if not self.deck_counts:
            messagebox.showinfo(i18n.t("save_title"), i18n.t("save_empty"))
            return
        name = simpledialog.askstring(i18n.t("save_title"), i18n.t("save_prompt"), parent=self)
        if not name or not name.strip():
            return
        path = core.save_deck_text(name.strip(), self.deck_counts, self.deck_nation)
        messagebox.showinfo(i18n.t("save_title"),
                            i18n.t("save_ok", name=name.strip(), path=path))

    def on_load_deck(self):
        """载入已保存的卡组（只显示当前国家的卡组）"""
        names = core.list_saved_decks(self.deck_nation)
        win = tk.Toplevel(self)
        win.title(i18n.t("btn_load"))
        win.configure(bg=BG)
        win.geometry("420x420")
        tk.Label(win, text=i18n.t("load_title", nation=self.deck_nation),
                 bg=BG, fg=TEXT, font=FONT_B).pack(anchor="w", padx=14, pady=(12, 6))
        if not names:
            tk.Label(win, text=i18n.t("load_none"),
                     bg=BG, fg=DIM, font=FONT_S, justify="left").pack(anchor="w", padx=14)
            tk.Button(win, text=i18n.t("btn_close"), bg="#4a4f5a", fg=TEXT, font=FONT_S, bd=0,
                      padx=14, pady=6, cursor="hand2",
                      command=win.destroy).pack(pady=10)
            return

        def do_load(nm):
            counts, _ = core.load_deck_counts(nm, self.db)
            win.destroy()
            if counts is None:
                messagebox.showwarning(i18n.t("btn_load"), i18n.t("load_missing"))
                return
            self.deck_counts = dict(counts)
            self._builder_refresh()
            messagebox.showinfo(i18n.t("btn_load"),
                                i18n.t("load_ok", name=nm, n=self._deck_total(),
                                       size=core.DECK_SIZE))

        for nm in names:
            row = tk.Label(win, text=f"📄 {nm}", bg=PANEL, fg=TEXT, font=FONT,
                           anchor="w", padx=12, pady=8)
            row.pack(fill="x", padx=14, pady=2)
            row.bind("<Button-1>", lambda e, n=nm: do_load(n))

    def _start_mp(self):
        """联机：校验卡组 → 发 hello → 等双方就绪 → 主机发种子开局"""
        if self.mp_link is None:
            messagebox.showerror(i18n.t("mp_title"), i18n.t("mp_disconnected"))
            return
        deck = self._counts_to_deck()
        ok, msg = core.validate_deck(deck, self.deck_nation, self.db)
        if not ok:
            messagebox.showwarning(i18n.t("deck_invalid_title"), msg)
            return
        random.shuffle(deck)
        self.mp_my_deck = [c.name for c in deck]
        self.mp_opp = None
        self.mp_link.send({"t": "hello", "nation": self.deck_nation,
                           "deck": self.mp_my_deck})
        self.start_btn.configure(state="disabled", text=i18n.t("waiting_opponent"))
        self.after(200, self._mp_poll_hello)

    def _mp_poll_hello(self):
        if self.game is not None or self.mp_link is None:
            return
        if not self.mp_link.alive:
            messagebox.showerror(i18n.t("mp_title"), i18n.t("mp_peer_left_prep"))
            self._mp_cleanup_to_menu()
            return
        try:
            while True:
                m = self.mp_link.inbox.get_nowait()
                if m.get("t") == "hello":
                    self.mp_opp = m
                elif m.get("t") == "start" and self.mp_role == "client":
                    self._mp_launch(m["seed"])
                    return
                elif m.get("t") == "concede":
                    self._mp_cleanup_to_menu()
                    return
        except queue.Empty:
            pass
        if self.mp_role == "host" and self.mp_opp is not None:
            seed = random.SystemRandom().randrange(10 ** 9)
            self.mp_link.send({"t": "start", "seed": seed})
            self._mp_launch(seed)
            return
        self.after(200, self._mp_poll_hello)

    def _mp_launch(self, seed):
        """双方用同一种子同步开局：先手随机、发牌一致"""
        opp = self.mp_opp or {}
        try:
            my_deck = [self.db[n] for n in self.mp_my_deck]
            opp_deck = [self.db[n] for n in opp.get("deck", [])]
        except KeyError as e:
            messagebox.showerror("联机", f"对手卡组包含未知卡牌 {e}，"
                                        "请确认双方游戏版本一致。")
            self._mp_cleanup_to_menu()
            return
        if len(opp_deck) != core.DECK_SIZE:
            messagebox.showerror(i18n.t("mp_title"), i18n.t("mp_bad_deck"))
            self._mp_cleanup_to_menu()
            return
        random.seed(seed)
        me = core.Player("你", self.deck_nation, my_deck)
        foe = core.Player(f"对手·{opp.get('nation', '?')}", opp.get("nation", "德国"), opp_deck)
        self.game = GUIGame(me, foe, self.add_log, self.on_game_event)
        for attr in ("start_frame", "builder_frame"):
            fr = getattr(self, attr, None)
            if fr is not None and fr.winfo_exists():
                fr.destroy()
        self._build_main()
        # 先手按 host/client 角色判定：双方同种子 → 角色结果一致，不会都认为自己是先手
        first_role = random.choice(["host", "client"])
        i_am_first = (first_role == self.mp_role)
        second = foe if i_am_first else me
        self.game.draw_cards(me, core.START_HP)
        self.game.draw_cards(foe, core.START_HP)
        self.game.draw_cards(second, 1)                   # 后手多抽一张
        if not i_am_first:
            self.game.current = foe                       # 对手先手：回合归属交给对手
        self.add_log(f"联机对战：你({self.deck_nation}) vs {foe.name}({opp.get('nation')})")
        self.add_log(f"先手：{'你' if i_am_first else '对手'}。祝你好运，指挥官！")
        self.busy = not i_am_first
        self.game.start_turn()      # 第 1 回合准备（双方对称各执行一次）
        self.refresh()
        self.after(80, self._mp_poll_net)
        if i_am_first:
            self.show_banner("你的回合", GREEN, 900)
        else:
            self.show_banner("敌方回合", RED, 900)

    # ---------------- 联机：网络轮询与行动应用 ----------------
    def _mp_send_act(self, act):
        if self.mp_link is not None:
            self.mp_link.send({"t": "act", **act})

    def _mp_poll_net(self):
        link = self.mp_link
        if self.game is None or link is None:
            return
        try:
            while True:
                msg = link.inbox.get_nowait()
                self._mp_handle(msg)
                if self.game is None or self.mp_link is None:
                    return
        except queue.Empty:
            pass
        if not link.alive:
            self._mp_disconnected()
            return
        self.after(80, self._mp_poll_net)

    def _mp_handle(self, msg):
        g = self.game
        if g is None:
            return
        t = msg.get("t")
        if t == "concede":
            self.add_log("  🏳 对手选择了投降！")
            self.finish(winner=g.players[0])
            return
        if t != "act":
            return
        foe = g.players[1]
        k = msg.get("k")
        anim = None
        if k == "end":
            g.end_turn()
            if g.over or g.players[0].hq <= 0:
                self.finish()
                return
            g.start_turn()
            if g.current is g.players[0]:
                self.busy = False
                self.show_banner("你的回合", GREEN, 900)
        elif k == "play":
            if isinstance(msg.get("i"), int) and 0 <= msg["i"] < len(foe.hand):
                g.play_card(foe, msg["i"])
        elif k == "attack":
            att = next((u for u in foe.board if u.slot == msg.get("s")), None)
            tgt = next((u for u in g.players[0].board if u.slot == msg.get("t")), None)
            if att is not None and tgt is not None:
                g.do_attack(att, tgt)
                tw = self.unit_widgets.get(id(tgt))
                if (self.anim_enabled and tw is not None and tw.winfo_exists()
                        and self._wcenter(tw) is not None):
                    anim = lambda a=att, w=tw: self._anim_attack(
                        a, w, on_done=self._mp_replay_tail)
        elif k == "hq":
            att = next((u for u in foe.board if u.slot == msg.get("s")), None)
            if att is not None:
                g.do_hq_attack(att)
                if (self.anim_enabled and self.hq_widget is not None
                        and self.hq_widget.winfo_exists()):
                    anim = lambda a=att: self._anim_attack(
                        a, self.hq_widget, on_done=self._mp_replay_tail)
        elif k == "move":
            u = next((u for u in foe.board if u.slot == msg.get("s")), None)
            if u is not None:
                g.move_unit(u, msg.get("p", "前线"))
                if self.anim_enabled:
                    anim = lambda uu=u: self._anim_move(uu, on_done=self._mp_replay_tail)
        if anim is not None:
            self.busy = True
            anim()          # 动画落地后由回调刷新棋盘并解锁
            return
        self.cleanup_dead()
        self.check_over()
        if self.game:
            self.refresh()

    def _mp_replay_tail(self):
        """联机对手动作动画落地后的收尾"""
        if self.game is None:
            return
        self.cleanup_dead()
        self.check_over()
        if self.game:
            self.refresh()
        self.busy = False

    def _mp_disconnected(self):
        link = self.mp_link
        self.mp_link = None
        if link is not None:
            link.close()
        if self.game is not None:
            self.add_log("  ⚠ 对手已断线！")
            self._mp_game_over = True
            self.finish(winner=self.game.players[0])
        else:
            messagebox.showinfo(i18n.t("mp_title"), i18n.t("mp_lost"))

    def _mp_cleanup_to_menu(self):
        """准备阶段出错：断开连接回主菜单"""
        if self.mp_link is not None:
            self.mp_link.close()
            self.mp_link = None
        self.mp_role = None
        self.mp_opp = None
        self.mp_my_deck = None
        self.start_frame.destroy()
        self._build_start()

    def _start_custom(self):
        deck = self._counts_to_deck()
        ok, msg = core.validate_deck(deck, self.deck_nation, self.db)
        if not ok:
            messagebox.showwarning(i18n.t("deck_invalid_title"), msg)
            return
        random.shuffle(deck)
        self.builder_frame.destroy()
        self.new_game(self.deck_nation, deck)

    # ---------------- 开新对局（随机匹配 + 随机先手）----------------
    def new_game(self, nation, deck=None):
        ai_nation = random.choice(core.MAIN_NATIONS)  # 随机匹配，可能内战
        p1 = core.Player("你", nation, deck if deck is not None else core.build_deck(nation, self.db))
        p2 = core.Player("AI", ai_nation, core.build_deck(ai_nation, self.db))
        self.game = GUIGame(p1, p2, self.add_log, self.on_game_event)
        if hasattr(self, "start_frame") and self.start_frame.winfo_exists():
            self.start_frame.destroy()
        if hasattr(self, "builder_frame") and self.builder_frame.winfo_exists():
            self.builder_frame.destroy()
        self._build_main()

        self.initiative = random.choice(["你", "AI"])
        second = p2 if self.initiative == "你" else p1
        self.game.draw_cards(p1, core.START_HP)
        self.game.draw_cards(p2, core.START_HP)
        self.game.draw_cards(second, 1)  # 后手多抽一张

        mirror = "（内战！）" if nation == ai_nation else ""
        self.add_log(f"你选择了 {nation}（{p1.hq_card.name}），对手是 {ai_nation} 阵营{mirror}")
        self.add_log(f"本轮先手: {self.initiative}。指挥官，祝你好运！")
        self.busy = True
        self.refresh()
        if self.initiative == "AI":
            self.game.current = p2    # AI 先手：回合归属交给 AI（start_turn/ai_steps 都以 current 为准）
            self.show_banner("敌方回合", RED, 900)
            self.after(1000, self._ai_phase_then_human)
        else:
            self.show_banner("你的回合", GREEN, 900)
            self.after(1000, self.begin_human_turn)

    # ---------------- 主界面布局 ----------------
    def _build_main(self):
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=(12, 4), pady=10)
        self.main_frame = main

        left = tk.Frame(main, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(main, bg=BG)
        right.pack(side="right", fill="y", padx=(4, 8))

        self.foe_info = tk.Label(left, bg=BG, fg=RED, font=FONT_B, anchor="w")
        self.foe_info.pack(fill="x")

        # 五段式战场：敌支援阵线 / 敌前线 / ⚔前线条 / 我方前线 / 我方支援阵线
        self.foe_rear_row = self._board_row(left, i18n.t("row_foe_rear"))
        self.foe_front_row = self._board_row(left, i18n.t("row_foe_front"))
        self.mid_frame = tk.Frame(left, bg="#20242c")
        self.mid_frame.pack(fill="x", pady=6, ipady=5)
        self.my_front_row = self._board_row(left, i18n.t("row_my_front"))
        self.my_rear_row = self._board_row(left, i18n.t("row_my_rear"))

        self.my_info = tk.Label(left, bg=BG, fg=TEXT, font=FONT_B, anchor="w")
        self.my_info.pack(fill="x")

        # 右侧：设置/投降 + 战场记录
        tk.Button(right, text=i18n.t("btn_ingame_settings"), bg="#4a4f5a", fg=TEXT, font=FONT_S,
                  bd=0, padx=12, pady=6, cursor="hand2",
                  command=self.open_settings).pack(anchor="e", pady=(0, 8))
        tk.Label(right, text=i18n.t("log_title"), bg=BG, fg=DIM, font=FONT).pack(anchor="w")
        self.logbox = tk.Text(right, width=36, bg=PANEL, fg=TEXT, font=FONT_S,
                              state="disabled", wrap="word", bd=0, padx=8, pady=6)
        self.logbox.pack(fill="both", expand=True)

        bottom = tk.Frame(self, bg=PANEL)
        bottom.pack(fill="x", side="bottom")
        self.bottom_frame = bottom
        self.hand_frame = tk.Frame(bottom, bg=PANEL)
        self.hand_frame.pack(side="left", fill="x", expand=True, padx=10, pady=8)
        self.speed_btn = tk.Button(bottom, text=i18n.t("btn_slow"), bg="#4a4f5a", fg=TEXT,
                                   font=FONT_S, bd=0, padx=12, pady=8, cursor="hand2",
                                   command=self.toggle_speed)
        self.speed_btn.pack(side="right", padx=(0, 10))
        self.end_btn = tk.Button(bottom, text=i18n.t("btn_end_turn"), bg="#3a5a80", fg=TEXT,
                                 font=FONT_B, bd=0, padx=22, pady=10,
                                 activebackground="#4c6b8a", cursor="hand2",
                                 command=self.on_end_turn)
        self.end_btn.pack(side="right", padx=(10, 4))

    def _board_row(self, parent, caption):
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="x")
        tk.Label(wrap, text=caption, bg=BG, fg=DIM,
                 font=("Microsoft YaHei UI", 9), width=11,
                 anchor="w").pack(side="left", fill="y")
        row = tk.Frame(wrap, bg="#1f232b", highlightthickness=1,
                       highlightbackground="#2a2f3a")
        row.pack(side="left", fill="x", expand=True, padx=(0, 2), ipady=8)
        return row

    def toggle_speed(self):
        self.fast_ai = not self.fast_ai
        self.ai_step_ms = 300 if self.fast_ai else 850
        self.speed_btn.configure(text=i18n.t("btn_fast") if self.fast_ai else i18n.t("btn_slow"))

    # ---------------- 渲染 ----------------
    def refresh(self):
        g = self.game
        if g is None:
            return
        me, foe = g.players[0], g.players[1]   # 固定我方视角，AI 回合不泄露手牌
        human_turn = g.current is me
        fc = NATION_COLOR.get(foe.nation, "#666")
        mc = NATION_COLOR.get(me.nation, "#666")
        turn_tag = "" if human_turn else i18n.t("turn_tag")
        self.foe_info.configure(
            text=i18n.t("foe_info", name=foe.name, nation=foe.nation, hq=foe.hq,
                        hand=len(foe.hand), kr=foe.kredits,
                        cnt=len(foe.counters), tag=turn_tag), fg=RED)
        counter_txt = (i18n.t("counter_zone") + " | ".join(c.name for c in me.counters)) if me.counters else ""
        self.my_info.configure(
            text=i18n.t("my_info", name=me.name, nation=me.nation, hq=me.hq,
                        kr=me.kredits, deck=len(me.deck),
                        perk=me.hq_card.perk_desc, counters=counter_txt), fg=TEXT)

        for f in (self.foe_rear_row, self.foe_front_row, self.my_front_row,
                  self.my_rear_row, self.hand_frame):
            for w in f.winfo_children():
                w.destroy()
        self.unit_widgets = {}
        self.enemy_widgets = []
        self.hq_widget = None

        # ---- 敌方支援阵线：总部 + 后排单位 ----
        hq = CardWidget(self.foe_rear_row, title=i18n.t("foe_hq"),
                        sub=i18n.t("hq_hint"), cost=None, color="#8a3a3a",
                        draggable=True, defense=foe.hq)
        hq.pack(side="left", padx=(8, 14), ipady=6)
        self.hq_widget = hq
        bind_tooltip_tree(hq, lambda f=foe: foe_hq_tooltip(f))
        foe_front = [u for u in foe.board if u.position == "前线"]
        foe_rear = [u for u in foe.board if u.position != "前线"]
        if not foe.board:
            tk.Label(self.foe_rear_row, text=i18n.t("foe_no_units"), bg="#1f232b", fg=DIM,
                     font=FONT_S).pack(side="left", padx=8)
        for u in foe_rear:
            self._enemy_card(u, fc, self.foe_rear_row)
        # ---- 敌方前线 ----
        if not foe_front:
            tk.Label(self.foe_front_row, text=i18n.t("foe_front_empty"), bg="#1f232b", fg="#5a616b",
                     font=FONT_S).pack(side="left", padx=8)
        for u in foe_front:
            self._enemy_card(u, fc, self.foe_front_row)

        # ---- ⚔ 前线占领状态条 ----
        for w in self.mid_frame.winfo_children():
            w.destroy()
        owner = g.frontline_owner()
        own_front = sum(1 for u in me.board if u.position == "前线")
        if owner is None:
            front_txt, front_fg = i18n.t("front_none"), DIM
        elif owner is me:
            front_txt, front_fg = i18n.t("front_mine", n=own_front, total=core.FRONTLINE_SLOTS), GOLD
        else:
            front_txt, front_fg = i18n.t("front_foe"), RED
        tk.Label(self.mid_frame, text=front_txt, bg="#20242c", fg=front_fg,
                 font=FONT).pack(expand=True)

        # ---- 我方前线 / 支援阵线 ----
        my_front = [u for u in me.board if u.position == "前线"]
        my_rear = [u for u in me.board if u.position != "前线"]
        if not me.board:
            tk.Label(self.my_rear_row, text=i18n.t("my_rear_empty"),
                     bg="#1f232b", fg=DIM, font=FONT_S).pack(side="left", padx=8)
        for u in my_front:
            self._my_card(u, mc, self.my_front_row)
        if not my_front:
            tk.Label(self.my_front_row, text=i18n.t("my_front_empty"),
                     bg="#1f232b", fg="#5a616b", font=FONT_S).pack(side="left", padx=8)
        for u in my_rear:
            self._my_card(u, mc, self.my_rear_row)

        # ---- 入场动画：新部署单位先在牌桌外待命，等令牌飞到位再落地 ----
        for u, _color in self.pending_flash:
            w = self.unit_widgets.get(id(u))
            if w is not None and w.winfo_exists():
                w.pack_forget()

        # ---- 手牌（仅我方回合显示，AI 手牌保密）----
        if not human_turn:
            tk.Label(self.hand_frame, text=i18n.t("hand_hidden"), bg=PANEL, fg=DIM,
                     font=FONT_S).pack(side="left", padx=8)
        elif not me.hand:
            tk.Label(self.hand_frame, text=i18n.t("hand_empty"), bg=PANEL, fg=DIM,
                     font=FONT_S).pack(side="left", padx=8)
        else:
            for i, c in enumerate(me.hand):
                eff = g.get_cost(c, me)
                playable = eff <= me.kredits
                if c.kind == "unit":
                    sub = f"{c.unit_type} {c.attack}/{c.defense} {kw_text(c.keywords)}"
                    if eff != c.cost:
                        sub += f"（原 {c.cost}）"
                    can = playable and g.can_deploy(me)
                elif c.kind == "counter":
                    sub = f"【反制】{c.desc}"
                    can = playable and len(me.counters) < core.COUNTER_SLOTS
                else:
                    sub = c.desc
                    can = playable
                cw = CardWidget(self.hand_frame, title=c.name, sub=sub, cost=eff,
                                color=NATION_COLOR.get(c.nation, "#666") if can else "#555",
                                draggable=True, rarity=c.rarity, dim=not can)
                if not can:
                    for child in cw.winfo_children():
                        try:
                            child.configure(fg="#777")
                        except tk.TclError:
                            pass
                cw.pack(side="left", padx=4, ipady=4)
                self._bind_drag(cw, ("hand", i))
                bind_tooltip_tree(cw, lambda c=c, eff=eff: card_tooltip(c, eff))

        # 入场动画补播（真身已在上面 pack_forget，令牌飞到位才落地）
        for u, color in self.pending_flash:
            self._anim_entry(u)
        self.pending_flash = []

    def _enemy_card(self, u, color, parent):
        slot_tag = f"#{u.slot}⌂" if u.slot == 0 else f"#{u.slot}"
        cw = CardWidget(parent, title=u.name,
                        sub=f"{slot_tag} {u.unit_type} " + kw_text(u.keywords),
                        cost=None, color=color, atk=u.attack, defense=u.defense,
                        draggable=True, rarity=u.card.rarity)
        cw.pack(side="left", padx=5, ipady=6)
        self.enemy_widgets.append((u, cw))
        self.unit_widgets[id(u)] = cw
        bind_tooltip_tree(cw, lambda u=u: card_tooltip(u.card, unit=u))

    def _my_card(self, u, color, parent):
        ready = self.game.unit_ready(u) if self.game else u.can_attack
        slot_tag = f"#{u.slot}⌂" if u.slot == 0 else f"#{u.slot}"
        sub = f"{slot_tag} {u.unit_type} " + kw_text(u.keywords)
        if u.operate:
            sub += f" ⚡{u.operate}"
        if ready:
            sub += "（可攻击）"
        cw = CardWidget(parent, title=u.name, sub=sub, cost=None, color=color,
                        atk=u.attack, defense=u.defense, draggable=True,
                        rarity=u.card.rarity, border=GREEN if ready else None)
        cw.pack(side="left", padx=5, ipady=6)
        self.unit_widgets[id(u)] = cw
        self._bind_drag(cw, ("unit", u))
        bind_tooltip_tree(cw, lambda u=u: card_tooltip(u.card, unit=u))

    # ---------------- 拖拽操作 ----------------
    def _bind_drag(self, widget, payload):
        """把拖拽事件绑定到卡片及其所有子控件。
        卡片内部是标题/属性等子 Label，若只绑定外框，点在文字上就完全无法拖动。"""
        def descendants(w):
            for c in w.winfo_children():
                yield c
                yield from descendants(c)
        targets = [widget] + list(descendants(widget))

        def press(e, p=payload, ww=widget):
            self._drag_start(p, e, ww)
        for w in targets:
            w.bind("<Button-1>", press)
            w.bind("<B1-Motion>", self._drag_motion)
            w.bind("<ButtonRelease-1>", self._drag_drop)
            try:
                w.configure(cursor="hand2")
            except tk.TclError:
                pass

    def _drag_ok(self):
        return (self.game is not None and not self.busy
                and self.game.current is self.game.players[0])

    def _drag_start(self, payload, e, widget=None):
        if not self._drag_ok():
            return
        if widget is not None:
            self._last_drag_src = self._wcenter(widget)   # 部署入场动画的起飞点
        self.drag = {"payload": payload, "ghost": None,
                     "sx": e.x_root, "sy": e.y_root}

    def _drag_motion(self, e):
        d = self.drag
        if d is None:
            return
        if d["ghost"] is None:
            if abs(e.x_root - d["sx"]) < 6 and abs(e.y_root - d["sy"]) < 6:
                return
            g = self.game
            p = d["payload"]
            if p[0] == "hand" and p[1] < len(g.players[0].hand):
                txt = f"打出：{g.players[0].hand[p[1]].name}"
            elif p[0] == "unit" and p[1] in g.players[0].board:
                txt = f"{p[1].name} → 拖到目标"
            else:
                return
            ghost = tk.Toplevel(self)
            ghost.overrideredirect(True)
            try:
                ghost.attributes("-topmost", True)
            except tk.TclError:
                pass
            tk.Label(ghost, text=txt, bg=GOLD, fg="#15171c", font=FONT_B,
                     padx=10, pady=6).pack()
            d["ghost"] = ghost
        d["ghost"].geometry(f"+{e.x_root + 12}+{e.y_root + 12}")

    def _drag_drop(self, e):
        d = self.drag
        self.drag = None
        if d is None:
            return
        if d["ghost"] is not None:
            d["ghost"].destroy()
        self._resolve_drop(d["payload"], e.x_root, e.y_root)

    def _hit(self, x, y, widget):
        try:
            wx, wy = widget.winfo_rootx(), widget.winfo_rooty()
            return (wx <= x < wx + widget.winfo_width()
                    and wy <= y < wy + widget.winfo_height())
        except tk.TclError:
            return False

    def _resolve_drop(self, payload, x, y):
        g = self.game
        if g is None or self.busy:
            return
        me = g.players[0]
        if payload[0] == "hand":
            idx = payload[1]
            if idx >= len(me.hand):
                return
            card = me.hand[idx]
            rows = (self.foe_rear_row, self.foe_front_row,
                    self.my_front_row, self.my_rear_row)
            hit_row = next((r for r in rows if self._hit(x, y, r)), None)
            if hit_row is None:
                return  # 拖回原处 = 取消
            if card.kind == "unit" and hit_row is not self.my_rear_row:
                self.add_log("  新单位只能部署在我方支援阵线。")
                return
            if g.play_card(me, idx) and self.mp_link is not None:
                self._mp_send_act({"k": "play", "i": idx})
            self.cleanup_dead()
            self.check_over()
            if self.game:
                self.refresh()
            # 万岁冲锋：强制结束回合
            if self.game and self.game.force_end and not self.game.over:
                self.after(400, self.on_end_turn)
            return
        unit = payload[1]
        if unit not in me.board:
            return
        for u, w in self.enemy_widgets:
            if self._hit(x, y, w):
                self._attack_unit(unit, u)
                return
        if self.hq_widget is not None and self._hit(x, y, self.hq_widget):
            self._attack_hq(unit)
            return
        if self._hit(x, y, self.my_front_row) or self._hit(x, y, self.my_rear_row):
            dest = "前线" if self._hit(x, y, self.my_front_row) else "后方"
            moved = g.move_unit(unit, dest)
            if moved and self.mp_link is not None:
                self._mp_send_act({"k": "move", "s": unit.slot, "p": dest})
            self.cleanup_dead()
            if moved and self.anim_enabled:
                self.busy = True
                self._anim_move(unit, on_done=self._refresh_unlock)
            elif self.game:
                self.refresh()
            return

    def _refresh_unlock(self):
        """动画落地后的统一收尾：刷新棋盘并解锁输入"""
        if self.game:
            self.refresh()
        self.busy = False

    def _attack_unit(self, attacker, target):
        g = self.game
        if not g.unit_ready(attacker):
            self.add_log(f"  {attacker.name} 本回合无法攻击（部署当回合需[闪击]；"
                         f"步兵移动过不能攻击；或行动费不足/攻击次数用完）。")
            return
        if target not in g.players[1].board or target not in g.attack_targets(attacker):
            if attacker.position == "后方":
                self.add_log("  支援线只有空军/炮兵能攻击，且仅限敌方前线单位！")
            else:
                self.add_log("  该目标被相邻位置的[警卫]保护，必须先攻击警卫！")
            return
        if self.anim_enabled:
            self.busy = True
            self._anim_attack(attacker, self.unit_widgets.get(id(target)),
                              on_done=lambda: self._attack_resolve(attacker, target))
        else:
            self._attack_resolve(attacker, target)

    def _attack_resolve(self, attacker, target):
        g = self.game
        if g is None:
            return
        self.flash_widget(self.unit_widgets.get(id(attacker)), GOLD)
        if self.mp_link is not None:
            self._mp_send_act({"k": "attack", "s": attacker.slot, "t": target.slot})
        g.do_attack(attacker, target)
        self.cleanup_dead()
        self.check_over()
        if self.game:
            self.refresh()
        self.busy = False

    def _attack_hq(self, attacker):
        g = self.game
        if not g.unit_ready(attacker):
            self.add_log(f"  {attacker.name} 本回合无法攻击。")
            return
        ok, msg = g.can_hit_hq(attacker)
        if not ok:
            self.add_log(f"  {msg}")
            return
        if self.anim_enabled:
            self.busy = True
            self._anim_attack(attacker, self.hq_widget,
                              on_done=lambda: self._attack_hq_resolve(attacker))
        else:
            self._attack_hq_resolve(attacker)

    def _attack_hq_resolve(self, attacker):
        g = self.game
        if g is None:
            return
        self.flash_widget(self.unit_widgets.get(id(attacker)), GOLD)
        if self.mp_link is not None:
            self._mp_send_act({"k": "hq", "s": attacker.slot})
        g.do_hq_attack(attacker)
        self.cleanup_dead()
        self.check_over()
        if self.game:
            self.refresh()
        self.busy = False

    # ---------------- 动画 ----------------
    def _guard(self):
        return self.busy or self.game is None

    def flash_widget(self, w, color=RED, times=3, interval=110):
        if not self.anim_enabled or w is None:
            return
        try:
            orig = w.cget("highlightbackground")
        except tk.TclError:
            return

        def tick(i):
            if not w.winfo_exists():
                return
            if i < times * 2:
                w.configure(highlightbackground=color if i % 2 == 0 else orig)
                self.after(interval, lambda: tick(i + 1))
            else:
                w.configure(highlightbackground=orig)

        tick(0)

    def float_text(self, anchor, text, color, ms=900):
        if not self.anim_enabled or anchor is None:
            return
        try:
            x = anchor.winfo_rootx() + anchor.winfo_width() // 2 - self.winfo_rootx()
            y = anchor.winfo_rooty() - self.winfo_rooty()
        except tk.TclError:
            return
        lbl = tk.Label(self, text=text, bg=BG, fg=color,
                       font=("Microsoft YaHei UI", 16, "bold"))
        lbl.place(x=max(0, x - 40), y=max(0, y - 20), width=80, height=26)
        steps = 10

        def tick(i):
            if not lbl.winfo_exists():
                return
            if i < steps:
                lbl.place(y=max(0, y - 20 - i * 3))
                self.after(ms // steps, lambda: tick(i + 1))
            else:
                lbl.destroy()

        tick(0)

    def shake(self, times=6, amp=7, interval=40):
        if not self.anim_enabled:
            return
        gx, gy = self.winfo_x(), self.winfo_y()

        def tick(i):
            dx = amp if i % 2 == 0 else -amp
            self.geometry(f"+{gx + dx}+{gy}")
            if i + 1 < times:
                self.after(interval, lambda: tick(i + 1))
            else:
                self.geometry(f"+{gx}+{gy}")

        tick(0)

    def show_banner(self, text, color, ms=900):
        if not self.anim_enabled:
            return
        lbl = tk.Label(self, text=text, bg="#10131a", fg=color,
                       font=("Microsoft YaHei UI", 28, "bold"),
                       padx=48, pady=18, bd=2, relief="solid")
        lbl.place(relx=0.5, rely=0.45, anchor="center")
        shades = [color, "#8a93a5", "#4a5260"]

        def fade(i=0):
            if not lbl.winfo_exists():
                return
            if i < len(shades):
                lbl.configure(fg=shades[i])
                self.after(ms // 3, lambda: fade(i + 1))
            else:
                lbl.destroy()

        self.after(ms // 3, fade)

    # ---------------- 战术动画：部署入场 / 行军 / 进攻冲刺 ----------------
    UNIT_ICON = {"步兵": "🚶", "坦克": "🚜", "战斗机": "✈", "轰炸机": "🛩", "炮兵": "💣"}

    def _wcenter(self, w):
        """控件中心相对主窗口的坐标（动画令牌用绝对定位）"""
        try:
            return (w.winfo_rootx() - self.winfo_rootx() + w.winfo_width() // 2,
                    w.winfo_rooty() - self.winfo_rooty() + w.winfo_height() // 2)
        except tk.TclError:
            return None

    def _profile(self, u):
        """按兵种选运动风格"""
        return {"步兵": "infantry", "坦克": "tank",
                "战斗机": "air", "轰炸机": "air"}.get(u.unit_type, "flat")

    def _spawn_token(self, text, color):
        lbl = tk.Label(self, text=text, bg=color, fg="#f2f4f8",
                       font=("Microsoft YaHei UI", 10, "bold"), bd=0, padx=8, pady=3)
        lbl.place(x=-300, y=-300)
        lbl.lift()
        self._anim_tokens.add(lbl)
        return lbl

    def _fly(self, lbl, path, step_ms=28, on_done=None):
        """令牌沿路径点移动，走完销毁并回调（坐标为令牌中心点）"""
        self._anim_tokens.add(lbl)

        def cleanup():
            self._anim_tokens.discard(lbl)
            if lbl.winfo_exists():
                lbl.destroy()
            if on_done:
                on_done()

        if not self.anim_enabled or not path:
            cleanup()
            return
        hw, hh = lbl.winfo_reqwidth() / 2, lbl.winfo_reqheight() / 2

        def step(i):
            if not lbl.winfo_exists():
                self._anim_tokens.discard(lbl)
                return
            if i >= len(path):
                cleanup()
                return
            x, y = path[i]
            lbl.place(x=int(x - hw), y=int(y - hh))
            self.after(step_ms, lambda: step(i + 1))

        step(0)

    def _path(self, src, dst, profile, n=14):
        """按兵种生成路径点：步兵颠簸跑动 / 坦克震动推进 / 空军弧线 / 炮弹抛物线"""
        (x1, y1), (x2, y2) = src, dst
        pts = []
        for i in range(n + 1):
            t = i / n
            x = x1 + (x2 - x1) * t
            y = y1 + (y2 - y1) * t
            if profile == "infantry":
                y -= abs(math.sin(t * math.pi * 4)) * 8     # 跑步上下颠簸
            elif profile == "tank":
                x += math.sin(t * math.pi * 12) * 1.5       # 引擎震动
            elif profile in ("air", "artillery"):
                y -= math.sin(t * math.pi) * (55 if profile == "air" else 40)
            pts.append((x, y))
        return pts

    def _land(self, u, w, color, text):
        """部署落地：单位现身 + 闪光"""
        if self.game is None or u not in u.owner.board or not w.winfo_exists():
            return
        w.pack(side="left", padx=5, ipady=6)
        self.flash_widget(w, color)
        if text:
            self.float_text(w, text, color)

    def _anim_entry(self, u):
        """部署入场：令牌从来源飞到部署位，落地亮绿框。
        新单位必在行尾，藏起真身不会挤动同排其他卡"""
        if not self.anim_enabled:
            return
        w = self.unit_widgets.get(id(u))
        dst = self._wcenter(w) if w is not None else None
        if w is None or dst is None:
            return
        src = self._deploy_source(u, dst)
        self._anim_count["entry"] += 1
        w.pack_forget()
        token = self._spawn_token(f"{self.UNIT_ICON.get(u.unit_type, '⚔')} {u.name}",
                                  NATION_COLOR.get(u.card.nation, "#4a5260"))
        self._fly(token, self._path(src, dst, self._profile(u)), step_ms=28,
                  on_done=lambda: self._land(u, w, GREEN, "部署！"))

    def _deploy_source(self, u, dst):
        """部署动画起点：我方=手牌拖拽起点，敌方=从屏幕上方压入"""
        if u.owner is self.game.players[0]:
            if self._last_drag_src is not None:
                src = self._last_drag_src
                self._last_drag_src = None
                return src
            c = self._wcenter(self.hand_frame)
            if c is not None:
                return c
            return (dst[0], self.winfo_height() - 40)
        return (dst[0], -30)

    def _anim_move(self, u, on_done=None):
        """行军动画：令牌从原位置开到目标行，落地后刷新棋盘（刷新前先藏起原控件）"""
        if not self.anim_enabled:
            if on_done:
                on_done()
            return
        w = self.unit_widgets.get(id(u))
        src = self._wcenter(w) if w is not None and w.winfo_exists() else None
        dst = None
        if src is not None and self.game is not None:
            mine = u.owner is self.game.players[0]
            row_attr = ("my_front_row" if u.position == "前线" else "my_rear_row") \
                if mine else ("foe_front_row" if u.position == "前线" else "foe_rear_row")
            dst = self._wcenter(getattr(self, row_attr))
        if src is None or dst is None:
            if on_done:
                on_done()
            return
        if w is not None and w.winfo_exists():
            w.pack_forget()
        self._anim_count["move"] += 1
        token = self._spawn_token(f"{self.UNIT_ICON.get(u.unit_type, '⚔')} {u.name}",
                                  NATION_COLOR.get(u.card.nation, "#4a5260"))
        self._fly(token, self._path(src, dst, self._profile(u)), step_ms=28,
                  on_done=on_done)

    def _anim_attack(self, att, tgt_w, on_done=None):
        """进攻动画：坦克两段冲刺（咣咣），步兵冲锋颠簸，空军俯冲，
        炮兵原地开火发射抛物线炮弹。命中后闪红 + 震动 + 💥，再回调"""
        if not self.anim_enabled:
            if on_done:
                on_done()
            return
        aw = self.unit_widgets.get(id(att))
        src = self._wcenter(aw) if aw is not None and aw.winfo_exists() else None
        dst = self._wcenter(tgt_w) if tgt_w is not None and tgt_w.winfo_exists() else None
        if src is None or dst is None:
            if on_done:
                on_done()
            return
        if aw is not None and aw.winfo_exists():
            self.flash_widget(aw, GOLD)
        self._anim_count["attack"] += 1
        if att.unit_type == "炮兵":
            shell = self._spawn_token("●", "#ff9c54")
            self._fly(shell, self._path(src, dst, "artillery", n=8), step_ms=22,
                      on_done=lambda: self._impact(tgt_w, on_done))
            return

        def seg(a, b, n=7):
            return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
                    for i in range(1, n + 1)]

        if att.unit_type == "坦克":
            p70 = (src[0] + (dst[0] - src[0]) * 0.7, src[1] + (dst[1] - src[1]) * 0.7)
            p45 = (src[0] + (dst[0] - src[0]) * 0.45, src[1] + (dst[1] - src[1]) * 0.45)
            path = seg(src, p70, 6) + seg(p70, p45, 3) + seg(p45, dst, 6)
        else:
            profile = "air" if att.unit_type in ("战斗机", "轰炸机") else "infantry"
            path = self._path(src, dst, profile, n=12)
        token = self._spawn_token(f"{self.UNIT_ICON.get(att.unit_type, '⚔')} {att.name}",
                                  NATION_COLOR.get(att.card.nation, "#4a5260"))
        self._fly(token, path, step_ms=24, on_done=lambda: self._impact(tgt_w, on_done))

    def _impact(self, tgt_w, on_done=None):
        """命中效果：目标闪红 + 💥 + 短促震动，然后回调"""
        if tgt_w is not None and tgt_w.winfo_exists():
            self.flash_widget(tgt_w, RED)
            self.float_text(tgt_w, "💥", "#ffb347")
            if tgt_w is self.hq_widget:
                self.shake()
            else:
                self.shake(times=2, amp=3, interval=30)
        if on_done:
            on_done()

    def _draw_end_emblem(self, cv, nation, won):
        """国家专属徽章：英国皇冠 / 美国白鹰 / 德国黑鹰 / 苏联锤子镰刀 / 日本太阳。
        胜利：金色调 + 脉冲光环；失败：灰色 + 裂纹贯穿 + 缓缓倾塌"""
        gold, gold_hi, gold_lo = "#d4af37", "#fff1b8", "#8a6a1a"
        gray, gray_hi, gray_lo = "#6a7076", "#9aa2ad", "#3a3f45"
        cx, cy = 100, 88
        main = gold if won else gray
        hi = gold_hi if won else gray_hi
        lo = gold_lo if won else gray_lo

        if nation == "日本":
            # 太阳：白底圆盘 + 红日
            disc = "#f2f2f2" if won else "#8a919b"
            sun = "#d9453d" if won else "#5a616b"
            cv.create_oval(cx - 52, cy - 52, cx + 52, cy + 52, fill=disc, outline=lo, width=3)
            cv.create_oval(cx - 30, cy - 30, cx + 30, cy + 30, fill=sun, outline=lo)
        elif nation == "苏联":
            # 锤子镰刀：红底圆盘 + 金色交叉
            disc = "#b03a34" if won else "#5a616b"
            tools = gold if won else gray_lo
            cv.create_oval(cx - 52, cy - 52, cx + 52, cy + 52, fill=disc, outline=lo, width=3)
            cv.create_oval(cx - 32, cy - 36, cx + 20, cy + 16, fill=tools, outline="")
            cv.create_oval(cx - 20, cy - 26, cx + 32, cy + 26, fill=disc, outline="")
            cv.create_line(cx - 20, cy + 24, cx + 0, cy + 42, fill=tools,
                           width=6, capstyle="round")
            cv.create_polygon([cx - 36, cy - 4, cx - 18, cy - 22, cx - 4, cy - 8,
                               cx - 22, cy + 10], fill=tools, outline="")
            cv.create_line(cx - 14, cy - 2, cx + 26, cy + 38, fill=tools,
                           width=7, capstyle="round")
        elif nation in ("德国", "美国"):
            # 鹰：德国黑鹰 / 美国白鹰（展开双翼）
            if nation == "美国":
                body_c = "#f2f2f2" if won else gray
                beak = gold if won else gray_lo
            else:
                body_c = "#1a1d22"
                beak = gold if won else gray
            for s in (-1, 1):
                wing = [cx + s * 8, cy - 16, cx + s * 34, cy - 40, cx + s * 30, cy - 26,
                        cx + s * 52, cy - 24, cx + s * 40, cy - 12, cx + s * 56, cy - 4,
                        cx + s * 34, cy + 2, cx + s * 10, cy - 4]
                cv.create_polygon(wing, fill=body_c, outline=beak, width=2)
            cv.create_polygon([cx, cy - 34, cx + 10, cy - 14, cx + 8, cy + 22,
                               cx, cy + 42, cx - 8, cy + 22, cx - 10, cy - 14],
                              fill=body_c, outline=beak, width=2)
            cv.create_oval(cx - 9, cy - 48, cx + 9, cy - 30, fill=body_c,
                           outline=beak, width=2)
            cv.create_polygon([cx + 7, cy - 44, cx + 20, cy - 39, cx + 7, cy - 34],
                              fill=beak, outline="")
        elif nation == "英国":
            # 皇冠：底座 + 五尖 + 顶珠 + 宝石
            cv.create_rectangle(cx - 46, cy + 14, cx + 46, cy + 34,
                                fill=main, outline=lo, width=2)
            for px in (-40, -20, 0, 20, 40):
                h = 34 if px == 0 else (26 if abs(px) == 20 else 20)
                cv.create_polygon([cx + px - 8, cy + 14, cx + px + 8, cy + 14,
                                   cx + px, cy + 14 - h], fill=main, outline=lo, width=2)
                cv.create_oval(cx + px - 5, cy + 4 - h, cx + px + 5, cy + 14 - h,
                               fill=hi, outline=lo)
            for jx in (-24, 0, 24):
                cv.create_oval(cx + jx - 5, cy + 19, cx + jx + 5, cy + 29,
                               fill="#b03a34" if won else gray_lo, outline=lo)
        else:
            # 兜底：盾形 + 首字
            pts = [cx - 64, cy - 54, cx + 64, cy - 54, cx + 64, cy + 10,
                   cx, cy + 66, cx - 64, cy + 10]
            cv.create_polygon(pts, fill=main, outline=hi, width=4)
            cv.create_text(cx, cy, text=nation[0], fill=lo,
                           font=("Microsoft YaHei UI", 46, "bold"))

        if not won:
            # 裂纹贯穿 + 徽章缓缓倾塌
            cv.create_line([cx - 56, cy - 50, cx - 24, cy - 16, cx - 38, cy + 8,
                            cx - 6, cy + 38, cx + 6, cy + 70],
                           fill="#23262b", width=3, smooth=True)
            cv.create_line([cx + 50, cy - 48, cx + 22, cy - 14, cx + 38, cy + 6,
                            cx + 12, cy + 30],
                           fill="#23262b", width=3, smooth=True)

            def sag(i=0):
                if not cv.winfo_exists() or i >= 8:
                    return
                cv.move("all", 0, 2)
                cv.after(120, lambda: sag(i + 1))
            cv.after(400, sag)
        else:
            # 胜利：金色脉冲光环
            glow = cv.create_oval(cx - 80, cy - 74, cx + 80, cy + 84,
                                  outline=gold_hi, width=3)

            def pulse(i=0):
                if not cv.winfo_exists():
                    return
                cv.itemconfigure(glow, outline=[gold_hi, gold, gold_lo][i % 3])
                cv.after(220, lambda: pulse(i + 1))
            pulse()

    def on_game_event(self, ev):
        if not self.anim_enabled:
            return
        t = ev["type"]
        if t == "unit_damage":
            w = self.unit_widgets.get(id(ev["unit"]))
            if w is not None and w.winfo_exists():
                self.float_text(w, f"-{ev['amount']}", RED)
                self.flash_widget(w, RED)
        elif t == "destroy":
            w = self.unit_widgets.get(id(ev["unit"]))
            if w is not None and w.winfo_exists():
                self.float_text(w, "✖", "#c0c6d0")
        elif t == "hq_damage":
            self.shake()
        elif t == "counter":
            self.show_banner(f"⚡ 反制 [ {ev['card'].name} ] 触发！", GOLD, 1100)
            self.shake()
        elif t == "attack":
            self.flash_widget(self.unit_widgets.get(id(ev["attacker"])), GOLD)
            self.flash_widget(self.unit_widgets.get(id(ev["target"])), RED)
        elif t == "confiscate":
            self.show_banner(f"📦 [收缴] 缴获 {ev['card'].name}！", GOLD, 900)
        elif t == "deploy":
            self.pending_flash.append((ev["unit"], GREEN))
        elif t == "move":
            pass    # 行军动画由 _ai_play_next / 联机 msg 回放负责

    # ---------------- 设置 / 投降 / 退出 ----------------
    def open_settings(self):
        win = tk.Toplevel(self)
        win.title(i18n.t("settings_title"))
        win.configure(bg=BG)
        win.geometry("340x380")
        win.transient(self)
        tk.Label(win, text=i18n.t("settings_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(16, 6))
        # 对局中切语言：偏好立即保存，界面文本随下次界面重建生效
        self._lang_buttons(win, on_change=win.destroy)

        def surrender():
            if messagebox.askyesno(i18n.t("surrender_title"), i18n.t("surrender_confirm")):
                win.destroy()
                self.add_log(i18n.t("log_surrender"))
                if self.mp_link is not None:
                    self.mp_link.send({"t": "concede"})
                self.finish(winner=self.game.players[1] if self.game else None)

        def to_menu():
            if messagebox.askyesno(i18n.t("to_menu_title"), i18n.t("to_menu_confirm")):
                win.destroy()
                self.back_to_menu()

        def quit_app():
            if messagebox.askyesno(i18n.t("quit_title"), i18n.t("quit_safe_confirm")):
                win.destroy()
                self.destroy()

        for text, cmd, color in ((i18n.t("btn_surrender"), surrender, "#8a3a3a"),
                                 (i18n.t("btn_to_menu"), to_menu, "#3a5a80"),
                                 (i18n.t("btn_quit"), quit_app, "#4a4f5a")):
            tk.Button(win, text=text, bg=color, fg=TEXT, font=FONT_B, bd=0,
                      padx=18, pady=8, cursor="hand2", command=cmd).pack(pady=5)

    def on_esc(self, event=None):
        """Esc：对局中安全退出到主菜单；主菜单则退出游戏"""
        if self.game is not None:
            if messagebox.askyesno(i18n.t("leave_title"), i18n.t("leave_confirm")):
                self.back_to_menu()
        else:
            if messagebox.askyesno(i18n.t("quit_title"), i18n.t("quit_confirm")):
                self.destroy()

    def back_to_menu(self):
        """安全回到主菜单（放弃当前对局）"""
        self._finishing = False
        if self.mp_link is not None:
            if self.game is not None and not self._mp_game_over:
                self.mp_link.send({"t": "concede"})   # 中途退出 = 投降
            self.mp_link.close()
            self.mp_link = None
        self._mp_game_over = False
        self.mp_role = None
        self.mp_opp = None
        self.mp_my_deck = None
        self.game = None
        self.busy = False
        self.selected = None
        self.unit_widgets = {}
        self.pending_flash = []
        # 清理残留的动画令牌
        for t in list(self._anim_tokens):
            if t.winfo_exists():
                t.destroy()
        self._anim_tokens.clear()
        self._last_drag_src = None
        for attr in ("main_frame", "bottom_frame", "builder_frame", "start_frame"):
            fr = getattr(self, attr, None)
            if fr is not None and fr.winfo_exists():
                fr.destroy()
        self._build_start()

    # ---------------- 回合流转 ----------------
    def on_end_turn(self):
        if self._guard():
            return
        self.busy = True
        g = self.game
        if self.mp_link is not None:
            # 联机：结束回合双方对称执行 end_turn + start_turn
            self._mp_send_act({"k": "end"})
            g.end_turn()
            if g.over or g.players[0].hq <= 0:
                self.finish()
                return
            g.start_turn()
            if g.over or g.players[1].hq <= 0:
                self.finish()
                return
            self.show_banner("敌方回合", RED, 900)
            self.refresh()
            return
        g.end_turn()
        if g.over or g.players[0].hq <= 0:
            self.finish()
            return
        self.refresh()          # 固定我方视角，切到敌方回合也不泄露 AI 手牌
        self.after(500, self._ai_phase_then_human)

    def _ai_phase_then_human(self):
        g = self.game
        if g is None:
            return
        g.start_turn()
        self.refresh()
        if g.over or g.players[1].hq <= 0:
            self.finish()
            return
        self.add_log("  [AI 行动中]")
        self.busy = True
        self._ai_iter = g.ai_steps()
        self.after(max(1, self.ai_step_ms), self._ai_play_next)

    def _ai_play_next(self):
        g = self.game
        if g is None:
            return
        step = None
        try:
            while True:
                step = next(self._ai_iter)
                # 打出卡牌 → 等 refresh 播放入场动画后再继续
                if step.get("type") in ("play", "end"):
                    self.cleanup_dead()
                    self.refresh()
                    self.after(max(60, self.ai_step_ms), self._ai_play_next)
                    return
                break       # move / attack / hq_attack：走下面的动画分支
        except StopIteration:
            self._ai_iter = None
            self.cleanup_dead()
            g.end_turn()
            if g.over or g.players[0].hq <= 0:
                self.finish()
                return
            if self.anim_enabled:
                self.show_banner("你的回合", GREEN, 800)
            self.after(900, self.begin_human_turn)
            return
        # move / attack：先播令牌动画（令牌结束后 refresh），再等一拍继续下一步
        if self.anim_enabled:
            continue_next = lambda: self.after(
                max(40, int(self.ai_step_ms * 0.5)), self._ai_play_next)
            if step.get("type") == "attack":
                tw = self.unit_widgets.get(id(step.get("target")))
                if tw is not None and tw.winfo_exists() and self._wcenter(tw) is not None:
                    self._anim_attack(step["unit"], tw, on_done=self.refresh)
                    continue_next()
                    return
            elif step.get("type") == "hq_attack":
                if self.hq_widget is not None and self.hq_widget.winfo_exists():
                    self._anim_attack(step["unit"], self.hq_widget, on_done=self.refresh)
                    continue_next()
                    return
            elif step.get("type") == "move":
                self._anim_move(step["unit"], on_done=self.refresh)
                continue_next()
                return
        else:
            self.refresh()
        self.after(max(1, self.ai_step_ms), self._ai_play_next)

    # ---------------- 回合与胜负 ----------------
    def begin_human_turn(self):
        if self.game is None:
            return
        self.game.start_turn()
        self.selected = None
        if self.game.current.hq <= 0:
            self.finish()
            return
        self.busy = False
        self.refresh()
        if getattr(self, "_ai_replay", False):
            self.after(150, self._ai_replay)

    def cleanup_dead(self):
        for pl in self.game.players:
            for u in list(pl.board):
                if u.defense <= 0:
                    self.game.destroy_unit(u)

    def check_over(self):
        if self.game.current.hq <= 0 or self.game.opponent_of(self.game.current).hq <= 0:
            self.finish()

    def finish(self, winner=None):
        if self.game is None or getattr(self, "_finishing", False):
            return
        self._finishing = True
        g = self.game
        self._mp_game_over = True
        if winner is None:
            if g.players[0].hq <= 0 and g.players[1].hq <= 0:
                winner = None            # 同归于尽：平局
            else:
                winner = g.players[0] if g.players[1].hq <= 0 else g.players[1]
        me = g.players[0]
        if winner is None:
            won = None
            self.add_log("战斗结束！双方总部同时陷落——平局！")
        else:
            won = winner is me
            self.add_log(f"战斗结束！{winner.name} 获胜！")
        # 账号战绩
        if self.account:
            account.stats_add(self.account,
                              "draw" if won is None else ("win" if won else "lose"))
            self._refresh_account_btn()
        self.refresh()

        def after_click():
            self._finishing = False
            self.back_to_menu()

        self.show_end_animation(won, after_click, nation=me.nation)

    # ---------------- 胜利 / 失败结算动画 ----------------
    def show_end_animation(self, won, on_done=None, nation=None):
        """全屏结算动画：胜利金色大字放大+粒子庆祝；失败暗场震动+裂纹徽章。
        顶部绘制国家专属徽章（胜利金色发光 / 失败灰色裂开）。
        动画播完后出现提示，点击屏幕任意处才执行 on_done 回到大厅"""
        if not self.anim_enabled:
            if on_done:
                on_done()
            return
        overlay = tk.Frame(self, bg="#0d1017")
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        cv = tk.Canvas(overlay, width=200, height=180, bg="#0d1017",
                       highlightthickness=0)
        cv.place(relx=0.5, rely=0.16, anchor="center")
        self._draw_end_emblem(cv, nation or "国", won)
        if won is None:
            txt, color = i18n.t("draw_big"), DIM
        else:
            txt, color = (i18n.t("win_big"), GOLD) if won else (i18n.t("lose_big"), RED)
        lbl = tk.Label(overlay, text=txt, bg="#0d1017", fg=color,
                       font=("Microsoft YaHei UI", 12, "bold"))
        lbl.place(relx=0.5, rely=0.42, anchor="center")
        sub = tk.Label(overlay,
                       text=i18n.t("win_sub") if won is True
                       else (i18n.t("lose_sub") if won is False else i18n.t("draw_sub")),
                       bg="#0d1017", fg=DIM, font=FONT_B)
        sub.place(relx=0.5, rely=0.60, anchor="center")
        parts = []
        self._end_click_ready = False   # 动画播完前点击无效

        def show_click_hint():
            hint = tk.Label(overlay, text=i18n.t("click_hint"), bg="#0d1017",
                            fg=DIM, font=FONT_B)
            hint.place(relx=0.5, rely=0.78, anchor="center")
            self._end_click_ready = True

            def blink(i=0):
                if not self._end_click_ready or not hint.winfo_exists():
                    return
                hint.configure(fg=[DIM, TEXT][i % 2])
                self.after(600, lambda: blink(i + 1))
            blink()

        def on_click(event=None):
            if not self._end_click_ready:
                return                      # 动画播放中：忽略点击
            self._end_click_ready = False
            try:
                self.unbind_all("<Button-1>")
            except tk.TclError:
                pass
            if overlay.winfo_exists():
                overlay.destroy()
            if on_done:
                on_done()

        self.bind_all("<Button-1>", on_click, add="+")

        def cleanup_star(star):
            if star.winfo_exists():
                star.destroy()

        if won is None:
            pass                      # 平局：无庆祝/无震动
        elif won:
            # 粒子庆祝：小星星从下往上飘散
            rng = random.Random()
            marks = ("✦", "★", "✧", "✨")
            wh = max(200, self.winfo_height())
            for k in range(16):
                x = rng.randint(40, max(60, self.winfo_width() - 40))
                star = tk.Label(overlay, text=rng.choice(marks),
                                fg=rng.choice([GOLD, "#e8c96a", "#fff1b8"]),
                                bg="#0d1017", font=("Microsoft YaHei UI", rng.randint(12, 22)))
                star.place(x=x, y=wh)
                parts.append(star)

                def rise(star=star, y0=wh, x0=x, delay=k * 120):
                    def step(i=0):
                        if not star.winfo_exists():
                            return
                        if i < 22:
                            star.place(x=x0 + (i - 8) * 2, y=y0 - i * (y0 // 26))
                            star.configure(fg=["#fff1b8", GOLD, "#8a6a1a"][i // 8])
                            self.after(55, lambda: step(i + 1))
                        else:
                            cleanup_star(star)
                    self.after(delay, step)
                rise()
        else:
            self.shake(times=8, amp=9, interval=50)

        sizes = [14, 20, 27, 34, 41, 47, 52]

        def grow(i=0):
            if not overlay.winfo_exists():
                return
            if i < len(sizes):
                lbl.configure(font=("Microsoft YaHei UI", sizes[i], "bold"))
                self.after(85, lambda: grow(i + 1))
            else:
                self.after(2200, show_click_hint)

        grow()

    # ---------------- 冒烟测试 ----------------
    def smoke_test(self):
        """自动完整对局：双方都用 AI 策略，验证 GUI 渲染与逻辑无异常"""
        self.new_game_smoke()
        g = self.game
        rounds = 0
        while not g.over and rounds < 500:
            g.start_turn()
            g.ai_turn()
            g.end_turn()
            self.selected = None
            self.refresh()
            self.update()
            rounds += 1
        self.after(50, self.destroy)
        self.mainloop()
        print(f"SMOKE OK: {rounds} rounds")

    def anim_test(self):
        """动画链路自测：开启动画跑 AI 对战回放（部署入场/行军/进攻冲刺全链路），定时自动结束"""
        self.ai_step_ms = 120
        self.new_game_smoke()
        self._ai_replay = self._run_ai_replay
        self.after(150, self._ai_replay)
        self.after(40000, self.destroy)
        self.mainloop()
        self._ai_replay = None
        c = self._anim_count
        total = c["entry"] + c["move"] + c["attack"]
        print(f"ANIM TEST OK: 入场 {c['entry']} / 行军 {c['move']} / 进攻 {c['attack']}，共 {total} 次")
        missing = [k for k in ("entry", "move", "attack") if c[k] == 0]
        if missing:
            raise SystemExit(f"[FAIL] 未触发动画类型: {missing}（检查 anim_enabled / 事件钩子 / _anim_* 调用链）")

    def _run_ai_replay(self):
        """双方都由 AI 驱动、开启动画：用于自测部署/行军/进攻全链路"""
        g = self.game
        if g is None or g.over or g.players[0].hq <= 0:
            self.finish()
            return
        self.busy = True
        self._ai_iter = g.ai_steps()
        self.after(80, self._ai_play_next)

    def new_game_smoke(self):
        nations = random.choices(core.MAIN_NATIONS, k=2)
        p1 = core.Player("AI-红军", nations[0], core.build_deck(nations[0], self.db))
        p2 = core.Player("AI-蓝军", nations[1], core.build_deck(nations[1], self.db))
        self.game = GUIGame(p1, p2, lambda m: None, self.on_game_event)
        self.start_frame.destroy()
        self._build_main()
        self.game.draw_cards(p1, core.START_HP)
        self.game.draw_cards(p2, core.START_HP + 1)
        self.refresh()


def run_debug_net(port=5555):
    """--debug-on-net：本机双开自战（一个进程跑两个窗口，自动互联）
    用于在一台电脑上体验/调试联机流程：主机窗（德国）vs 客户窗（苏联）"""
    import time as _time
    core.setup_error_log()
    print("[调试自战] 正在启动两个窗口：主机(德国) vs 客户端(苏联)…")
    a = App()
    a.title("KARDS 联机调试 · 主机（德国）")
    a.geometry("+60+60")
    b = App()
    b.title("KARDS 联机调试 · 客户端（苏联）")
    b.geometry("+780+60")

    def pump(n=1):
        for _ in range(n):
            for w in (a, b):
                try:
                    if w.winfo_exists():
                        w.update()
                except tk.TclError:
                    return False
            _time.sleep(0.01)
        return True

    a.on_battle()
    b.on_battle()
    pump(3)
    a.host_port_var.set(str(port))
    a._mp_begin_host()
    b.join_ip_var.set("127.0.0.1")
    b.join_port_var.set(str(port))
    b._mp_begin_join()

    # 等待互联（_lobby_poll 自动进入选阵营）
    t0 = _time.time()
    while (a.mp_link is None or b.mp_link is None) and _time.time() - t0 < 15:
        if not pump(1):
            return
    pump(45)   # 等 after(400ms) 调度选阵营界面

    for app, nation in ((a, "德国"), (b, "苏联")):
        app._build_deck_builder(nation, mp=True)
        deck = core.build_deck(nation, app.db)
        app.deck_counts = {}
        for c in deck:
            app.deck_counts[c.name] = app.deck_counts.get(c.name, 0) + 1
        app._start_mp()

    t0 = _time.time()
    while (a.game is None or b.game is None) and _time.time() - t0 < 15:
        if not pump(1):
            return
    print("[调试自战] 就绪！两个窗口分属联机双方，自己操作两边即可对打。")

    try:
        while pump(1):
            pass
    except tk.TclError:
        pass
    print("[调试自战] 已退出。")


def _another_instance_running():
    """Windows 下用命名互斥体检测是否已有实例在运行；若有则提示并聚焦旧窗口"""
    if sys.platform != "win32":
        return False
    import ctypes
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.CreateMutexW(None, False, "KARDS_SIMPLE_SINGLETON")
    if k32.GetLastError() != 183:      # ERROR_ALREADY_EXISTS
        return False
    hwnd = u32.FindWindowW(None, APP_TITLE)
    if hwnd:
        u32.ShowWindow(hwnd, 9)        # SW_RESTORE
        u32.SetForegroundWindow(hwnd)
        u32.FlashWindow(hwnd, True)
    u32.MessageBoxW(None, "游戏已经在运行了！已为你切换到已打开的窗口。",
                    APP_TITLE, 0x40)   # MB_ICONINFORMATION
    return True


def main():
    core.setup_error_log()
    if "--debug-on-net" in sys.argv:
        run_debug_net()
        return
    if "--smoke" not in sys.argv and "--anim-test" not in sys.argv and _another_instance_running():
        return
    app = App()
    if "--smoke" in sys.argv:
        app.after(100, app.smoke_test)
        app.mainloop()
    elif "--anim-test" in sys.argv:
        app.after(100, app.anim_test)
        app.mainloop()
    else:
        app.mainloop()


if __name__ == "__main__":
    main()
