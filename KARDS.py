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
import os
import queue
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog


import kards_engine as core
import kards_i18n as i18n
import kards_net as net
import kards_account as account
import kards_host
import kards_update as net_update

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
VERSION = (1, 3, 0, 2)

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
        d = core.kw_desc(kw, i18n.get_lang())
        if d:
            lines.append(f"[{core.kw_label(kw, i18n.get_lang())}] {d}")
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
        # ---- 联机状态（服务器中转模式）----
        self.mp_link = None        # net.ServerLink（连上服务器后非 None）
        self.mp_role = None        # "host" / "client"
        self.mp_mode = False       # 组卡界面是否处于联机流程
        self.mp_opp = None         # 对手 hello 信息 {nation, deck}
        self.mp_my_deck = None     # 我方有序卡名列表
        self._mp_game_over = False
        self._lobby_active = False
        # 服务器 / 大厅
        self.mp_server_addr = net.DEFAULT_SERVER   # 记住上次填的服务器地址
        self.mp_user = None        # 服务器账号名（未登录为 None）
        self.mp_matching = False   # 快速匹配等待中
        self.mp_room_code = None   # 自己开的邀请码房间
        self.mp_opp_name = None    # 匹配到的对手名
        self.mp_room_id = None     # 服务器分配的房间号
        self.mp_lobby_players = [] # 最近一次大厅快照
        self.mp_lobby_log = []     # 大厅日志（重建界面时回填）
        self._srv_poll = None      # net.ServerPoller（连接中）
        self._srv_addr = ""        # 当前连接的地址
        self._srv_error = ""       # 最近一次连接失败原因
        self._srv_ready = False    # 是否曾经连接成功过
        self._lobby_track = set()  # 上一份大厅名单（用于算进出）
        self._lobby_rows = {}
        # 具名定时器（统一取消 + 代号防串台，见 _schedule 注释）
        self._timer_gen = {}
        self._timers = {}
        self._t_lobby = None
        self._t_hello = None
        self._t_net = None
        self._t_prep = None
        self.db = core.card_database()
        # ---- 账号 / 游客 ----
        # 产品规则：未登录即「游客」——能打人机，不能联机。
        # 游客是临时会话（不落盘），所以这里只设个内存标志，不建目录、不写文件。
        self.account = account.current()
        if self.account:
            core.set_decks_dir(account.deck_dir(self.account))
        else:
            account.start_guest()
            self.account = None
            # 游客卡组放临时目录，退出即弃（不污染用户数据目录）
            core.set_decks_dir(account.guest_decks_dir())
        self.bind_all("<Escape>", self.on_esc)
        self.bind_all("<F1>", self.on_f1)
        self._build_start()
        if not self.account and self.anim_enabled:
            self.after(300, self._account_dialog)
        # 启动后静默检查更新（后台线程，不阻塞界面；没更新就自己消失）
        self._update_win = None
        self._update_task = None
        if self.anim_enabled and "--no-update-check" not in sys.argv:
            self.after(1500, lambda: self.open_update_dialog(auto=True))

    def destroy(self):
        """退出前关闭联机连接"""
        # 更新任务在后台线程（下载/解压）。这里只置取消标志，不 join ——
        # 解压到一半就强杀反而会留下半个文件；让它自然结束更安全。
        if getattr(self, "_update_task", None) is not None:
            self._update_task.cancel()
        if self.mp_link is not None:
            self.mp_link.close()
            self.mp_link = None
        account.set_remote(None)
        # ⚠ 必须取消所有 after 定时器。tkinter 的 after 回调注册在解释器级别，
        # 窗口销毁后**定时器仍会触发**，于是控制台刷屏
        # `invalid command name "..._lobby_poll"`，且回调里可能访问已销毁控件。
        self._cancel_timers()
        self._close_update_dialog()
        # 如果服务器是本机用「建立服务器」拉起来的，退出时一并收掉；
        # 不是我们拉的不动（可能是别人开的、或玩家自己想留着）。
        try:
            kards_host.stop()
        except Exception:                        # noqa: BLE001
            pass
        tk.Tk.destroy(self)

    def _cancel_timers(self):
        """取消本窗口登记的全部 after 定时器（幂等，可在任意阶段调用）"""
        for key in ("_t_lobby", "_t_hello", "_t_net", "_t_prep"):
            tid = getattr(self, key, None)
            if tid:
                try:
                    self.after_cancel(tid)
                except (tk.TclError, ValueError):
                    pass
                setattr(self, key, None)

    def _schedule(self, key, delay, fn, _gen=None):
        """登记一个具名定时器，便于统一取消（同一 key 重复调度会顶掉旧的）。

        `_gen` 是「代号」：调用方传入 `self._timer_gen[key]`。回调真正执行时
        先比对代号，不一致就直接放弃 —— 防止**正在执行**的那次轮询在
        链路已被重建（例如中途重连服务器）之后，把陈旧定时器又挂回去，
        导致轮询彻底停摆（实测踩过的死循环：定时器永远丢失，事件堆在队列里）。
        """
        self._cancel_timer(key)
        gen = self._timer_gen.get(key, 0) if _gen is None else _gen
        timer = {"id": None, "gen": gen, "fn": fn}

        def fire(k=key, t=timer):
            cur = self._timer_gen.get(k, 0)
            if t["gen"] != cur:
                return                     # 链路已重建，本次调度作废
            setattr(self, k, None)
            t["fn"]()

        try:
            timer["id"] = self.after(delay, fire)
        except tk.TclError:
            timer["id"] = None
            return
        self._timers[key] = timer
        setattr(self, key, timer["id"])

    def _cancel_timer(self, key):
        """取消具名定时器 —— 并且**让在途的那一次作废**。

        ⚠ 只 after_cancel 是不够的：如果此刻回调**正在执行**（比如
        `_lobby_poll` 刚取到包、正要走最后的 `_schedule`），after_cancel
        无法阻止它在返回前把定时器重新挂上，于是「停不掉」。所以这里
        同时把代号 +1，在途回调尾部的 `_schedule` 会因代号不符被丢弃。
        """
        self._bump_timer_gen(key)
        timer = self._timers.pop(key, None)
        if timer and timer.get("id"):
            try:
                self.after_cancel(timer["id"])
            except (tk.TclError, ValueError):
                pass
        setattr(self, key, None)

    def _bump_timer_gen(self, key):
        """代号 +1：让所有在途的旧调度作废（重连时调用）"""
        self._timer_gen[key] = self._timer_gen.get(key, 0) + 1

    # ---------------- 日志 ----------------
    def add_log(self, msg):
        """对局日志。

        ⚠ self.logbox 只在 _build_main()（对局界面）里创建，因此**主菜单 /
        大厅 / 组卡阶段调用本方法时它并不存在** —— 直接 configure 会抛
        AttributeError。大厅有自己的日志框（_lobby_log），这里的规则是：
        对局中写对局框；不在对局中则回落到大厅日志框；都没有就静默丢弃。
        """
        box = getattr(self, "logbox", None)
        if box is None or not box.winfo_exists():
            if self._lobby_active:
                self._lobby_log(msg, echo=False)
            return
        box.configure(state="normal")
        box.insert("end", msg + "\n")
        box.see("end")
        box.configure(state="disabled")

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
        # 游客规则（产品指定）：未登录即游客 —— 能打人机，不能联机。
        # 界面上显式写出「游客」并给出「登录」按钮，避免用户不知道自己在什么状态。
        box = tk.Frame(self.start_frame, bg=BG)
        box.pack(anchor="nw", padx=16)
        self.account_btn = tk.Button(box, text=self._account_btn_text(),
                                     bg="#4a4f5a", fg=TEXT, font=FONT_S, bd=0,
                                     padx=12, pady=6, cursor="hand2",
                                     command=self._account_dialog)
        self.account_btn.pack(side="left")
        self.guest_hint = tk.Label(box, text="", bg=BG, fg=DIM, font=FONT_S)
        self.guest_hint.pack(side="left", padx=8)
        self._refresh_account_btn()

    # ---------------- 账号管理 ----------------
    def _account_btn_text(self):
        if self.account:
            s = account.get_stats(self.account)
            return i18n.t("account_btn", name=self.account,
                          w=s["win"], l=s["lose"], d=s["draw"])
        # 未登录 → 游客
        return i18n.t("account_nouser")

    def _refresh_account_btn(self):
        """刷新账号按钮文字 + 游客提示。

        ⚠ 必须同时判 winfo_exists() 并吞掉 TclError：账号按钮只在主菜单里
        创建，窗口销毁后这个控件引用会变成"幽灵"——此时调 winfo_exists()
        会抛 `can't invoke "winfo" command: application has been destroyed`
        （实测踩过）。销毁后刷新账号按钮本身是合法操作，不该让程序崩。
        """
        btn = getattr(self, "account_btn", None)
        if btn is None:
            return
        try:
            if not btn.winfo_exists():
                return
            btn.configure(text=self._account_btn_text())
            hint = getattr(self, "guest_hint", None)
            if hint is not None and hint.winfo_exists():
                # 游客时给一行说明，登录后清空
                hint.configure(text="" if self.account else i18n.t("guest_note"))
        except tk.TclError:
            pass

    def _apply_account(self, name):
        """登录/注册成功后应用账号（卡组目录 + 按钮）"""
        self.account = name
        core.set_decks_dir(account.deck_dir(name))
        self._refresh_account_btn()

    def _account_dialog(self, for_server=False):
        # 单实例：反复点击（或启动定时器与手动点击撞车）时不再叠开多个窗口
        for w in self.winfo_children():
            if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == "account":
                try:
                    w.deiconify()
                    w.lift()
                    w.focus_force()
                    return
                except tk.TclError:
                    pass
        win = tk.Toplevel(self)
        win.role = "account"                # 便于查找/测试定位
        win.title(i18n.t("account_title"))
        win.configure(bg=BG)
        win.geometry("380x360")
        win.transient(self)
        tk.Label(win, text=i18n.t("account_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(18, 8))
        info = tk.Label(win, text="", bg=BG, fg=RED, font=FONT_S)
        info.pack()
        if for_server and self.mp_link is not None:
            tk.Label(win, text=i18n.t("srv_connected_nouser", addr=self._srv_addr),
                     bg=BG, fg=GOLD, font=FONT_S).pack(pady=(2, 0))
        if not self.account:
            # 游客说明：让人一眼看懂"现在能干什么、不能干什么"
            tk.Label(win, text=i18n.t("guest_note"), bg=BG, fg=DIM,
                     font=FONT_S).pack(pady=(2, 0))
        elif for_server:
            # 本地已登录 + 联机要求登录 → 说明「同名密码可直接迁移」，
            # 用户不会误以为要换一套新账号（2026-10-04 账号分裂修复）
            tk.Label(win, text=i18n.t("srv_migrate_hint", name=self.account),
                     bg=BG, fg=DIM, font=FONT_S,
                     wraplength=340, justify="left").pack(pady=(4, 0), padx=8)

        if self.account:
            s = account.get_stats(self.account)
            tk.Label(win, text=i18n.t("account_stats", w=s["win"], l=s["lose"], d=s["draw"]),
                     bg=BG, fg=GOLD, font=FONT).pack(pady=10)

            def do_logout():
                # account.logout() 会把身份切回游客（游客不落盘，所以不丢数据）
                account.logout()
                self.account = None
                self.mp_user = None
                core.set_decks_dir(account.guest_decks_dir())
                self._refresh_account_btn()
                win.destroy()
                # 在大厅里退出登录：刷新按钮可用性，让用户重新登录
                if self._lobby_active:
                    self._lobby_sync()
                    self.after(200, lambda: self._account_dialog(for_server=True))

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
        if self.account:
            # 已有本地账号（联机场景）→ 预填用户名，只输密码即可
            e_user.insert(0, self.account)
        tk.Label(win, text=i18n.t("account_pw"), bg=BG, fg=DIM,
                 font=FONT_S).pack(pady=(8, 2))
        e_pw = tk.Entry(win, font=FONT, width=22, show="*", bg=PANEL, fg=TEXT,
                        insertbackground=TEXT, relief="flat")
        e_pw.pack(pady=2)

        def done(ok, err):
            if ok:
                # 服务器链路已断时会走本地回退，此时 current()（读服务器
                # 会话）可能拿不到名字 —— 用输入框里的用户名兜底
                name = account.current() or (e_user.get() or "").strip() or None
                self._apply_account(name)
                win.destroy()
                # 注意用 _lobby_log 而不是 add_log：此时多半还没进对局，
                # self.logbox 不存在（add_log 已做兜底，这里显式走大厅日志更清晰）
                if self._lobby_active:
                    self._lobby_log(f"账号已登录: {name}", echo=False)
                if self.mp_link is not None:
                    # 服务器模式下把登录结果同步到大厅，并主动拉一次在线名单
                    self.mp_user = name
                    self.mp_lobby_players = []
                    self._lobby_track = set()
                    self._srv_send({"m": "lobby"})
                    if self._lobby_active:
                        self._lobby_log(i18n.t("srv_connected", addr=self._srv_addr,
                                               name=name))
                        self._lobby_sync()
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
        win.role = "start_settings"
        win.title(i18n.t("settings_title"))
        win.configure(bg=BG)
        win.geometry("380x460")
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

        def show_keywords():
            self.open_keyword_guide()

        def quit_app():
            if messagebox.askyesno(i18n.t("quit_title"), i18n.t("quit_confirm")):
                win.destroy()
                self.destroy()

        def check_update():
            win.destroy()
            self.open_update_dialog()

        for text, cmd, color in ((i18n.t("btn_check_update"), check_update, "#4a7a5a"),
                                 (i18n.t("btn_help"), show_help, "#3a5a80"),
                                 (i18n.t("btn_keywords"), show_keywords, "#4a6b8a"),
                                 (i18n.t("btn_quit"), quit_app, "#4a4f5a")):
            tk.Button(win, text=text, bg=color, fg=TEXT, font=FONT_B, bd=0,
                      padx=18, pady=8, cursor="hand2", command=cmd).pack(pady=6)

    # ---------------- 自动更新 ----------------

    def open_update_dialog(self, auto=False):
        """检查更新窗口。

        auto=True 表示这是**启动时静默检查**发现的更新，只提示不打扰
        （用户可以选择稍后）。检查与下载都在后台线程，界面靠 after 轮询刷新，
        绝不阻塞主线程 —— 否则窗口会在下载期间假死。
        """
        if getattr(self, "_update_win", None) is not None:
            try:
                self._update_win.deiconify()
                self._update_win.lift()
                return
            except tk.TclError:
                self._update_win = None

        win = tk.Toplevel(self)
        self._update_win = win
        win.role = "update"
        win.title(i18n.t("update_title"))
        win.configure(bg=BG)
        win.geometry("440x400")
        win.transient(self)
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_update_dialog())

        tk.Label(win, text=i18n.t("update_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(16, 4))
        cur = net_update.version_str(VERSION)
        tk.Label(win, text=f"v{cur}", bg=BG, fg=DIM, font=FONT_S).pack()

        status = tk.Label(win, text="", bg=BG, fg=GOLD, font=FONT,
                          wraplength=390, justify="left")
        status.pack(pady=(10, 4), padx=16)

        bar_holder = tk.Frame(win, bg=BG)
        bar_holder.pack(fill="x", padx=16)
        bar = tk.Frame(bar_holder, bg="#2a2f38", height=10)
        bar.pack(fill="x")
        bar_fill = tk.Frame(bar, bg="#2e6b46", height=10)
        bar_fill.place(x=0, y=0, relwidth=0.0, relheight=1.0)

        notes_box = tk.Text(win, height=7, bg=PANEL, fg=DIM, font=FONT_S,
                            relief="flat", wrap="word")
        notes_box.pack(fill="both", expand=True, padx=16, pady=(8, 4))
        notes_box.configure(state="disabled")

        btns = tk.Frame(win, bg=BG)
        btns.pack(pady=10)

        task = net_update.UpdateTask(VERSION, auto_install=False)
        self._update_task = task
        # ⚠ 必须自己记 after id 并在关窗时 after_cancel：
        # tkinter 的 after 挂在**解释器**上，窗口销毁后仍会触发，回调里
        # 访问已销毁控件 → `invalid command name "...poll"` 刷屏（实测）。
        state = {"polling": True, "installed": False, "aid": None}

        def stop_poll():
            state["polling"] = False
            for key in ("aid", "aid2"):
                aid = state.get(key)
                if aid:
                    try:
                        self.after_cancel(aid)
                    except (tk.TclError, ValueError):
                        pass
                    state[key] = None

        self._update_stop_poll = stop_poll

        def set_status(text, fg=GOLD):
            if state["polling"]:
                try:
                    status.configure(text=text, fg=fg)
                except tk.TclError:
                    state["polling"] = False

        def rebuild_buttons():
            for w in btns.winfo_children():
                w.destroy()

        def do_download():
            rebuild_buttons()
            task.auto_install = True
            task.state = "downloading"
            task.progress = 0.0
            threading.Thread(target=lambda: task._download_and_install(task.asset),
                             daemon=True).start()

        def do_restart():
            self._restart_after_update()

        def open_page():
            url = (task.info or {}).get("page")
            if url:
                try:
                    import webbrowser
                    webbrowser.open(url)
                except Exception:                # noqa: BLE001
                    pass

        def close():
            self._close_update_dialog()

        def poll():
            state["aid"] = None
            if not state["polling"]:
                return
            try:
                if not win.winfo_exists():
                    stop_poll()
                    return
            except tk.TclError:
                stop_poll()
                return

            st = task.state
            if st == "checking":
                set_status(i18n.t("update_checking"))
            elif st in ("found", "no_update", "error", "done", "downloading", "extracting"):
                pass

            if st == "found":
                info = task.info or {}
                set_status(i18n.t("update_new", ver=info.get("version", "?"),
                                  cur=net_update.version_str(VERSION)))
                try:
                    notes_box.configure(state="normal")
                    notes_box.delete("1.0", "end")
                    notes_box.insert("1.0", (info.get("notes") or "").strip()[:4000])
                    notes_box.configure(state="disabled")
                except tk.TclError:
                    pass
                rebuild_buttons()
                tk.Button(btns, text=i18n.t("update_btn_do"), bg="#2e6b46", fg=TEXT,
                          font=FONT_B, bd=0, padx=16, pady=7, cursor="hand2",
                          command=do_download).pack(side="left", padx=5)
                tk.Button(btns, text=i18n.t("update_btn_open_page"), bg="#3a5a80",
                          fg=TEXT, font=FONT_S, bd=0, padx=12, pady=7, cursor="hand2",
                          command=open_page).pack(side="left", padx=5)
                tk.Button(btns, text=i18n.t("update_later_btn"), bg="#4a4f5a", fg=TEXT,
                          font=FONT_S, bd=0, padx=12, pady=7, cursor="hand2",
                          command=close).pack(side="left", padx=5)
                state["phase"] = "found"
            elif st == "no_update":
                set_status(i18n.t("update_none", cur=net_update.version_str(VERSION)), GREEN)
                if state.get("phase") != "no_update":
                    state["phase"] = "no_update"
                    rebuild_buttons()
                    tk.Button(btns, text=i18n.t("btn_close"), bg="#4a4f5a", fg=TEXT,
                              font=FONT_B, bd=0, padx=16, pady=7, cursor="hand2",
                              command=close).pack()
            elif st == "error":
                set_status(i18n.t("update_fail", err=task.message), RED)
                if state.get("phase") != "error":
                    state["phase"] = "error"
                    rebuild_buttons()
                    tk.Button(btns, text=i18n.t("btn_close"), bg="#4a4f5a", fg=TEXT,
                              font=FONT_B, bd=0, padx=16, pady=7, cursor="hand2",
                              command=close).pack()
            elif st in ("downloading", "extracting"):
                pct = int(task.progress * 100)
                key = "update_downloading" if st == "downloading" else "update_extracting"
                set_status(i18n.t(key, done=pct))
                try:
                    bar_fill.place_configure(relwidth=max(0.0, min(1.0, task.progress)))
                except tk.TclError:
                    pass
                if state.get("phase") != "busy":
                    state["phase"] = "busy"
                    rebuild_buttons()
                    tk.Button(btns, text=i18n.t("update_btn_cancel"), bg="#4a4f5a",
                              fg=TEXT, font=FONT_S, bd=0, padx=12, pady=7,
                              cursor="hand2", command=close).pack()
            elif st == "done":
                set_status(i18n.t("update_ready", ver=net_update.version_str(VERSION)), GREEN)
                if not state.get("installed"):
                    state["installed"] = True
                    rebuild_buttons()
                    tk.Button(btns, text=i18n.t("update_restart_btn"), bg="#2e6b46",
                              fg=TEXT, font=FONT_B, bd=0, padx=16, pady=7,
                              cursor="hand2", command=do_restart).pack(side="left", padx=5)
                    tk.Button(btns, text=i18n.t("update_later_btn"), bg="#4a4f5a",
                              fg=TEXT, font=FONT_S, bd=0, padx=12, pady=7,
                              cursor="hand2", command=close).pack(side="left", padx=5)

            try:
                state["aid"] = win.after(120, poll)
            except tk.TclError:
                stop_poll()

        task.start()
        if auto:
            # 静默检查：查完发现没有新版本就自己关掉，不打扰用户。
            # 有新版（state == "found"）就留着让用户决定；出错也静默关掉
            # （启动时弹「检查更新失败」很烦人，用户想查可手动点）。
            def auto_close_if_nothing():
                if not state["polling"]:
                    return
                if task.state == "found":
                    return                       # 有更新 → 停在这里等用户操作
                if task.state in ("no_update", "error"):
                    self._close_update_dialog()
                    return
                try:
                    state["aid2"] = win.after(150, auto_close_if_nothing)
                except tk.TclError:
                    stop_poll()
            try:
                state["aid2"] = win.after(200, auto_close_if_nothing)
            except tk.TclError:
                stop_poll()
        try:
            state["aid"] = win.after(120, poll)
        except tk.TclError:
            stop_poll()

    def _close_update_dialog(self):
        """关掉更新窗（幂等；窗口已销毁/未创建都安全）"""
        stopper = getattr(self, "_update_stop_poll", None)
        if stopper is not None:
            try:
                stopper()
            except Exception:                    # noqa: BLE001
                pass
            self._update_stop_poll = None
        win = getattr(self, "_update_win", None)
        self._update_win = None
        if win is None:
            return
        try:
            win.destroy()
        except tk.TclError:
            pass

    def _restart_after_update(self):
        """重启游戏以应用更新。

        打包成 exe 时，更新可能覆盖了正在运行的 exe —— Windows 会锁文件，
        所以这里用一个小 bat ：「等本进程退出 → 再启动」。源码运行直接重启即可。
        """
        if not messagebox.askyesno(i18n.t("update_title"), i18n.t("update_restart_needed")):
            return
        exe = sys.executable
        args = [a for a in sys.argv[1:] if not a.startswith("--debug")]
        if getattr(sys, "frozen", False):
            bat = net_update.write_update_bat(pid=os.getpid(), exe=exe, args=args)
            if bat:
                try:
                    os.startfile(bat)            # noqa: S606 — Windows 专用
                except (OSError, AttributeError):
                    pass
        else:
            # 源码运行：解压出来的文件已经就位，直接重启进程
            try:
                subprocess.Popen([exe] + sys.argv, cwd=os.getcwd())
            except OSError:
                pass
        self.destroy()

    def open_keyword_guide(self):
        """关键词说明：分组列出全部关键词与规则术语，可滚动。"""
        win = tk.Toplevel(self)
        win.role = "keyword_guide"          # 便于查找/测试定位本类窗口
        win.title(i18n.t("kw_title"))
        win.configure(bg=BG)
        win.geometry("620x660")
        win.minsize(520, 420)
        win.transient(self)
        tk.Label(win, text=i18n.t("kw_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(16, 4))
        tk.Label(win, text=i18n.t("kw_sub"), bg=BG, fg=DIM,
                 font=FONT_S).pack(pady=(0, 10))

        # ---- 可滚动区域 ----
        outer = tk.Frame(win, bg=BG)
        outer.pack(fill="both", expand=True, padx=16)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        bar = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        # 让滚动区宽度跟随窗口（否则说明文字不会随窗口变宽换行）
        def _fit(_e=None):
            canvas.itemconfigure(cw, width=canvas.winfo_width())
        cw = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", _fit)

        lang = i18n.get_lang()
        for gkey, rows in core.keyword_guide(lang):
            # 「未实装」分组用暗金色 + 分隔线区分，避免玩家误以为卡池里有这些词
            planned = (gkey == "kw_group_planned")
            if planned:
                tk.Frame(inner, bg="#3a3f4a", height=1).pack(fill="x", pady=(18, 0))
            tk.Label(inner, text=i18n.t(gkey), bg=BG,
                     fg="#8a7a4a" if planned else GOLD,
                     font=FONT_B, anchor="w").pack(fill="x", pady=(12, 4))
            for name, desc in rows:
                row = tk.Frame(inner, bg=PANEL if not planned else "#20242c")
                row.pack(fill="x", pady=1)
                tk.Label(row, text=name, bg=row["bg"], fg=DIM if planned else TEXT,
                         font=FONT_B, width=12, anchor="w",
                         padx=8, pady=4).pack(side="left")
                tk.Label(row, text=desc, bg=row["bg"], fg=DIM, font=FONT_S,
                         anchor="w", justify="left", wraplength=430,
                         padx=4, pady=4).pack(side="left", fill="x", expand=True)

        tk.Button(win, text=i18n.t("kw_close"), bg="#3a5a80", fg=TEXT,
                  font=FONT_B, bd=0, padx=20, pady=8, cursor="hand2",
                  command=win.destroy).pack(pady=12)

        # 鼠标滚轮：只在指针位于本窗口时生效
        def on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", on_wheel)
        win.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

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

    # ---------------- 联机大厅（服务器模式） ----------------
    def _build_lobby(self):
        """大厅：① 连服务器 ② 在线玩家 ③ 出击（快速匹配 / 邀请码房间）

        轮询由 `_lobby_poll` 统一驱动，所有服务器事件走 `ServerLink.inbox`。
        这里只负责把「连上服务器 + 已登录」之后才该出现的东西置灰/激活。
        """
        self.start_frame.destroy()
        self.start_frame = tk.Frame(self, bg=BG)
        self.start_frame.pack(expand=True, fill="both")
        self._lobby_active = True

        tk.Label(self.start_frame, text=i18n.t("lobby_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(18, 2))
        tk.Label(self.start_frame, text=i18n.t("lobby_sub"),
                 bg=BG, fg=DIM, font=FONT_S).pack(pady=(0, 8))
        tk.Button(self.start_frame, text=i18n.t("btn_back"), bg="#4a4f5a", fg=TEXT,
                  font=FONT_S, bd=0, padx=14, pady=6, cursor="hand2",
                  command=self._lobby_back).place(relx=1.0, rely=0.0,
                                                  anchor="ne", x=-16, y=10)

        cols = tk.Frame(self.start_frame, bg=BG)
        cols.pack(fill="both", expand=True, padx=22)
        left = tk.Frame(cols, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(cols, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        self._lobby_build_server(left)
        self._lobby_build_players(left)
        self._lobby_build_battle(right)
        self._lobby_build_log(right)

        self._lobby_sync()
        self._lobby_track = set()
        # 连上服务器（若已有连接则直接复用，不再重复连）
        if self._srv_link_obj() is None and self._srv_poll is None:
            self._lobby_connect()
        else:
            self._schedule("_t_lobby", 120, self._lobby_poll)

    # ---- ① 服务器连接 ----

    def _lobby_build_server(self, parent):
        box = tk.Frame(parent, bg=PANEL, bd=1, relief="solid")
        box.pack(fill="x")
        tk.Label(box, text=i18n.t("srv_title"), bg=PANEL, fg=TEXT,
                 font=FONT_B).pack(anchor="w", padx=14, pady=(10, 4))
        row = tk.Frame(box, bg=PANEL)
        row.pack(anchor="w", padx=14)
        tk.Label(row, text=i18n.t("label_server"), bg=PANEL, fg=DIM,
                 font=FONT_S).pack(side="left")
        self.srv_addr_var = tk.StringVar(value=self.mp_server_addr)
        self.srv_addr_entry = tk.Entry(row, textvariable=self.srv_addr_var, width=18,
                                       bg="#1a1d24", fg=TEXT, insertbackground=TEXT,
                                       relief="flat")
        self.srv_addr_entry.pack(side="left", padx=(4, 10), ipady=3)
        self.srv_btn = tk.Button(row, text=i18n.t("btn_srv_connect"), bg="#2e6b46",
                                 fg=TEXT, font=FONT_S, bd=0, padx=14, pady=5,
                                 cursor="hand2", command=self._lobby_connect)
        self.srv_btn.pack(side="left")
        # 「建立服务器」：本机一键起一个服务器（不用命令行）。
        # 只在具备条件时出现：有 kards_server.py 且没有被别的东西占用端口。
        self.srv_host_btn = tk.Button(row, text=i18n.t("btn_host_server"),
                                      bg="#6b5a2a", fg=TEXT, font=FONT_S, bd=0,
                                      padx=10, pady=5, cursor="hand2",
                                      command=self._lobby_host_server)
        if kards_host.can_host():
            self.srv_host_btn.pack(side="left", padx=(6, 0))
        tk.Label(box, text=i18n.t("srv_default_hint", addr=net.DEFAULT_SERVER),
                 bg=PANEL, fg=DIM, font=FONT_S).pack(anchor="w", padx=14, pady=(4, 0))
        self.srv_status = tk.Label(box, text="", bg=PANEL, fg=GOLD, font=FONT_S,
                                   anchor="w", justify="left", wraplength=290)
        self.srv_status.pack(anchor="w", padx=14, pady=(2, 4))
        # 游客（未登录）时给一个显眼的登录入口：联机按钮此时是灰的，
        # 光靠状态栏一行小字用户找不到出路（产品规则：游客不能联机）
        self.srv_login_btn = tk.Button(box, text=i18n.t("btn_login_or_reg"),
                                       bg="#3a5a80", fg=TEXT, font=FONT_S, bd=0,
                                       padx=14, pady=5, cursor="hand2",
                                       command=lambda: self._account_dialog(for_server=True))
        self.srv_login_btn.pack(anchor="w", padx=14, pady=(0, 10))

    # ---- ② 在线玩家 ----

    def _lobby_build_players(self, parent):
        box = tk.Frame(parent, bg=PANEL, bd=1, relief="solid")
        box.pack(fill="both", expand=True, pady=(10, 0))
        head = tk.Frame(box, bg=PANEL)
        head.pack(fill="x", padx=14, pady=(10, 2))
        tk.Label(head, text=i18n.t("lobby_players"), bg=PANEL, fg=TEXT,
                 font=FONT_B).pack(side="left")
        self.lobby_count_lbl = tk.Label(head, text="", bg=PANEL, fg=DIM, font=FONT_S)
        self.lobby_count_lbl.pack(side="right")
        # 玩家列表：滚动 Canvas（人数多时也不挤爆布局）
        cv = tk.Canvas(box, bg=PANEL, highlightthickness=0, height=150)
        sb = tk.Scrollbar(box, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=(0, 10))
        cv.pack(fill="both", expand=True, padx=(14, 0), pady=(0, 10))
        inner = tk.Frame(cv, bg=PANEL)
        cv.create_window((0, 0), window=inner, anchor="nw", tags="inner")
        inner.bind("<Configure>",
                   lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>",
                lambda e: cv.itemconfigure("inner", width=e.width))
        self.lobby_players_box = inner
        self._lobby_players_canvas = cv
        self._lobby_rows = {}
        # 首屏占位（首次收到 lobby 快照后会重建）
        self.lobby_empty_lbl = tk.Label(inner, text=i18n.t("lobby_no_players"),
                                        bg=PANEL, fg=DIM, font=FONT_S, anchor="w")
        self.lobby_empty_lbl.pack(fill="x", pady=6)

    # ---- ③ 出击 ----

    def _lobby_build_battle(self, parent):
        box = tk.Frame(parent, bg=PANEL, bd=1, relief="solid")
        box.pack(fill="x")
        tk.Label(box, text=i18n.t("match_title"), bg=PANEL, fg=TEXT,
                 font=FONT_B).pack(anchor="w", padx=14, pady=(10, 6))
        self.match_btn = tk.Button(box, text=i18n.t("btn_quick_match"), bg="#2e6b46",
                                   fg=TEXT, font=FONT_B, bd=0, padx=16, pady=8,
                                   cursor="hand2", command=self._mp_quick_match)
        self.match_btn.pack(anchor="w", padx=14)
        self.room_btn = tk.Button(box, text=i18n.t("btn_create_room"), bg="#3a5a80",
                                  fg=TEXT, font=FONT_S, bd=0, padx=14, pady=6,
                                  cursor="hand2", command=self._mp_toggle_room)
        self.room_btn.pack(anchor="w", padx=14, pady=(8, 2))
        self.room_lbl = tk.Label(box, text=i18n.t("room_none"), bg=PANEL, fg=DIM,
                                 font=FONT_S, anchor="w", justify="left",
                                 wraplength=290)
        self.room_lbl.pack(anchor="w", padx=14)
        sep = tk.Frame(box, bg="#3a3f4a", height=1)
        sep.pack(fill="x", padx=14, pady=8)
        row = tk.Frame(box, bg=PANEL)
        row.pack(anchor="w", padx=14, pady=(0, 12))
        tk.Label(row, text=i18n.t("label_join_code"), bg=PANEL, fg=DIM,
                 font=FONT_S).pack(side="left")
        self.join_code_var = tk.StringVar(value="")
        e = tk.Entry(row, textvariable=self.join_code_var, width=10,
                     bg="#1a1d24", fg=TEXT, insertbackground=TEXT, relief="flat")
        e.pack(side="left", padx=(4, 8), ipady=3)
        e.bind("<Return>", lambda ev: self._mp_join_by_code())
        self.join_code_btn = tk.Button(row, text=i18n.t("btn_join_code"), bg="#4a4f5a",
                                       fg=TEXT, font=FONT_S, bd=0, padx=12, pady=5,
                                       cursor="hand2", command=self._mp_join_by_code)
        self.join_code_btn.pack(side="left")

    # ---- 日志 ----

    def _lobby_build_log(self, parent):
        box = tk.Frame(parent, bg=PANEL, bd=1, relief="solid")
        box.pack(fill="both", expand=True, pady=(10, 0))
        tk.Label(box, text=i18n.t("lobby_log"), bg=PANEL, fg=TEXT,
                 font=FONT_B).pack(anchor="w", padx=14, pady=(10, 2))
        self.lobby_logbox = tk.Text(box, height=6, bg="#1a1d24", fg=TEXT,
                                    font=FONT_S, bd=0, highlightthickness=0,
                                    wrap="word", state="disabled")
        self.lobby_logbox.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        for line in self.mp_lobby_log[-40:]:
            self._lobby_log(line, echo=False)

    def _lobby_log(self, text, echo=True):
        """大厅日志：写进右侧日志框，同时记入 mp_lobby_log 以便重建界面时恢复"""
        if echo:
            self.mp_lobby_log.append(text)
            del self.mp_lobby_log[:-80]
        box = getattr(self, "lobby_logbox", None)
        if box is None or not box.winfo_exists():
            return
        box.configure(state="normal")
        box.insert("end", text + "\n")
        box.see("end")
        box.configure(state="disabled")

    # ---- 界面状态同步（连上/未连上、匹配中/空闲） ----

    def _srv_link_obj(self):
        return self.mp_link

    def _lobby_sync(self):
        """根据「连接 / 登录 / 匹配」状态刷新按钮可用性"""
        link = self._srv_link_obj()
        online = link is not None and getattr(link, "alive", False)
        logged = bool(self.mp_user)
        busy = self.mp_matching or self.mp_room_code
        can_play = online and logged and not busy

        def set_btn(btn, state):
            if btn is not None and btn.winfo_exists():
                btn.configure(state=state)

        set_btn(self.srv_btn, "normal" if not self._srv_poll else "disabled")
        set_btn(self.match_btn, "normal" if can_play else "disabled")
        set_btn(self.room_btn, "normal" if (can_play or self.mp_room_code) else "disabled")
        set_btn(self.join_code_btn, "normal" if can_play else "disabled")
        if self.match_btn is not None and self.match_btn.winfo_exists():
            self.match_btn.configure(
                text=i18n.t("btn_cancel_match") if self.mp_matching
                else i18n.t("btn_quick_match"),
                bg="#8a3a3a" if self.mp_matching else "#2e6b46")
        if self.room_btn is not None and self.room_btn.winfo_exists():
            self.room_btn.configure(
                text=i18n.t("btn_leave_room") if self.mp_room_code
                else i18n.t("btn_create_room"),
                bg="#8a3a3a" if self.mp_room_code else "#3a5a80")
        if self.room_lbl is not None and self.room_lbl.winfo_exists():
            if self.mp_room_code:
                self.room_lbl.configure(text=i18n.t("room_code", code=self.mp_room_code),
                                        fg=GOLD)
            else:
                self.room_lbl.configure(text=i18n.t("room_none"), fg=DIM)
        if self.srv_status is not None and self.srv_status.winfo_exists():
            if not online:
                if self._srv_error:
                    self.srv_status.configure(
                        text=i18n.t("srv_fail", err=self._srv_error), fg=RED)
                else:
                    self.srv_status.configure(text="", fg=GOLD)
            elif logged:
                self.srv_status.configure(
                    text=i18n.t("srv_connected", addr=self._srv_addr, name=self.mp_user),
                    fg=GREEN)
            else:
                # 连上了但没登录 = 游客：明确写出「游客不能联机」，
                # 否则用户会以为按钮坏了（按钮确实是 disabled 的）
                self.srv_status.configure(
                    text=i18n.t("srv_connected_nouser", addr=self._srv_addr), fg=GOLD)
        # 登录入口：仅在「已连接但未登录」时出现（登录后没意义，未连接时点了也没用）
        lb = getattr(self, "srv_login_btn", None)
        if lb is not None and lb.winfo_exists():
            if online and not logged:
                lb.pack(anchor="w", padx=14, pady=(0, 10))
            else:
                lb.pack_forget()

    # ---- 本机开服 ----

    def _lobby_host_server(self):
        """在大厅里一键把服务器拉起来（本机当主机）。

        玩家机器上通常只有这个 exe，不会去开命令行，所以「建立服务器」
        必须是按钮级操作：起进程 → 等端口起来 → 自动连上 → 把本机
        局域网地址填进输入框（好念给同屋的人）。
        """
        port = net.DEFAULT_SERVER.split(":")[-1]
        if not kards_host.running() and kards_host.port_in_use(
                port=int(port) if port.isdigit() else 6000):
            # 端口已被占用：多半是别人（或上一次）已经开好了，直接连上去
            self._lobby_log(i18n.t("host_already"))
        elif not kards_host.running():
            ok, err = kards_host.start(int(port) if port.isdigit() else 6000)
            if not ok:
                messagebox.showerror(i18n.t("host_fail_title"),
                                     i18n.t("host_fail", err=err))
                return
            self._lobby_log(i18n.t("host_started"))
        else:
            self._lobby_log(i18n.t("host_running"))

        addr = kards_host.local_addr(int(port) if port.isdigit() else 6000)
        if getattr(self, "srv_addr_var", None) is not None:
            self.srv_addr_var.set(addr)
        # 局域网的其他人要连过来，得知道这个地址；顺带提醒防火墙
        self._lobby_log(i18n.t("host_firewall_hint"))
        # 服务器进程刚起来时端口可能还没 listen 完，等一拍再连
        self.after(700, self._lobby_connect)

    def _lobby_connect(self):
        parsed = net.parse_addr(self.srv_addr_var.get()
                                if getattr(self, "srv_addr_var", None) else self.mp_server_addr)
        if parsed is None:
            messagebox.showwarning(i18n.t("srv_warn_addr_title"), i18n.t("srv_warn_addr"))
            return
        host, port = parsed
        addr = f"{host}:{port}"
        self._close_server_link()
        self.mp_server_addr = addr
        self._srv_addr = addr
        self._srv_error = ""
        # 链路重建 → 旧代号作废，避免在途的旧轮询把定时器挂回来
        self._bump_timer_gen("_t_lobby")
        self._srv_poll = net.ServerPoller(addr)
        if self.srv_status is not None and self.srv_status.winfo_exists():
            self.srv_status.configure(text=i18n.t("srv_connecting"), fg=GOLD)
        self.mp_lobby_players = []
        self._lobby_sync()
        self._schedule("_t_lobby", 80, self._lobby_poll)

    def _close_server_link(self):
        """断开并复位所有联机状态（回主菜单 / 重连前调用）"""
        link = self.mp_link
        self.mp_link = None
        if link is not None:
            try:
                link.close()
            except Exception:
                pass
        account.set_remote(None)
        self.mp_user = None
        self.mp_matching = False
        self.mp_room_code = None
        self.mp_lobby_players = []
        self._srv_ready = False

    # ---- 轮询：连接结果 + 服务器事件 ----

    def _lobby_poll(self):
        self._t_lobby = None
        if not self._lobby_active:
            return
        # 1) 连接结果
        if self._srv_poll is not None and self._srv_poll.ready:
            res = self._srv_poll.take()
            self._srv_poll = None
            if res and res[0] == "err":
                self._srv_error = res[1]
                self._lobby_sync()
                messagebox.showerror(i18n.t("srv_fail_hint").split("\n")[0],
                                     i18n.t("srv_fail_hint", err=res[1]))
            elif res:
                self.mp_link = res[0]
                self.mp_link.on_event = None
                self._srv_ready = True
                link = self.mp_link
                # 账号代理到服务器：能免密 resume 就直接进大厅
                account.set_remote(link, self._srv_addr)
                ok, who = account.connect()
                if ok:
                    self.mp_user = who
                    self._apply_account(who)
                    self._lobby_log(i18n.t("srv_connected", addr=self._srv_addr,
                                           name=who))
                    self._srv_send({"m": "lobby"})
                elif not link.alive:
                    # resume 被服务器拒绝 → 协议上服务器会**切断连接**。
                    # 必须重连一条新链路供登录对话框使用：否则之后所有
                    # login/register rpc 都会在 _rpc 开头因 alive=False
                    # 静默返回 None，掉进本地回退，用户还是被判成游客。
                    # （重连后 session 缓存已被 resume 失败清掉，不会再死循环）
                    self.mp_user = None
                    self._srv_ready = False
                    self.mp_link = None
                    account.set_remote(None)
                    self._srv_poll = net.ServerPoller(self._srv_addr)
                else:
                    self.mp_user = None
                    self._lobby_sync()
                    self.after(300, self._lobby_login_dialog)
                self._schedule("_t_lobby", 120, self._lobby_poll)
                return
        # 2) 服务器事件
        self._lobby_drain_events()
        # ⚠ 这一步必须**重新判断**：`_lobby_drain_events()` 里收到 matched
        # 会把 `_lobby_active` 置 False（匹配成功=已离开大厅），此时若还
        # 无条件 reschedule，大厅轮询就永远停不下来 —— 之后它会以 120ms
        # 的频率去碰已被销毁的大厅控件（实测：`a._t_lobby` 一直非 None，
        # 且控制台刷屏 invalid command name）。
        if not self._lobby_active:
            return
        self._schedule("_t_lobby", 120, self._lobby_poll)

    def _lobby_drain_events(self, limit=200):
        """把服务器推来的事件全部消费掉。

        单独成方法是为了让「实时轮询」和「对局中/准备阶段的兜底轮询」
        共用同一套消费逻辑 —— 匹配成功那一刻大厅轮询会停掉，如果完全
        没人再消费 inbox，开局后服务器送来的 seed / act 就会一直躺在
        队列里（必须在 `_mp_poll_hello` / `_mp_poll_net` 里兜底调用本方法）。
        """
        link = self.mp_link
        if link is None:
            return
        n = 0
        while n < limit:
            try:
                msg = link.inbox.get_nowait()
            except queue.Empty:
                break
            n += 1
            if not isinstance(msg, dict):
                continue
            if self.game is not None:
                self._mp_handle(msg)         # 对局中：交给对局处理
            else:
                self._lobby_handle_event(msg)
        # 连接断了：复位大厅状态
        if not getattr(link, "alive", False) and self._srv_ready:
            self._srv_ready = False
            self.mp_link = None
            self.mp_matching = False
            self.mp_room_code = None
            self.mp_lobby_players = []
            self._lobby_log(i18n.t("log_srv_down"))
            if self.game is not None:
                self._mp_teardown_game()
            self._lobby_sync()

    def _srv_send(self, obj):
        link = self.mp_link
        if link is None or not getattr(link, "alive", False):
            return False
        return link.send(obj)

    def _lobby_handle_event(self, msg):
        """处理大厅里的服务器推送"""
        m = msg.get("m")
        if m == "lobby":
            self._lobby_set_players(msg.get("players") or [])
        elif m == "matched":
            self.mp_matching = False
            self.mp_room_code = None
            self.mp_role = "host" if msg.get("role") == "host" else "client"
            self.mp_opp_name = msg.get("opp")
            self.mp_room_id = msg.get("room")
            self._lobby_log(i18n.t("matched", opp=msg.get("opp") or "?"))
            self._lobby_sync()
            self._lobby_active = False
            # ⚠ 匹配成功就等于**离开大厅**了，必须停掉大厅轮询：否则它会继续
            # 以 120ms 的频率访问已被 _build_nation_select 销毁的控件
            # （实测会刷 invalid command name），而且它只在开头判断
            # _lobby_active，一旦本次回调是"在途"的，就会把定时器又挂回来。
            self._cancel_timer("_t_lobby")
            self.after(500, lambda: self._build_nation_select(mp=True))
        elif m == "matching":
            self.mp_matching = True
            self._lobby_log(i18n.t("matching"))
            self._lobby_sync()
        elif m == "match_cancelled":
            self.mp_matching = False
            self._lobby_log(i18n.t("match_cancelled"))
            self._lobby_sync()
        elif m == "room_created":
            self.mp_room_code = msg.get("code")
            self._lobby_log(i18n.t("room_created", code=self.mp_room_code))
            self._lobby_sync()
        elif m == "join_err":
            self._lobby_log("⚠ " + str(msg.get("err") or "join_err"))
        elif m == "peer_left":
            self._lobby_log(i18n.t("log_peer_left"))
        elif m == "kick":
            self._lobby_log(i18n.t("log_kicked"))
        elif m == "err":
            self._lobby_log("⚠ " + str(msg.get("err") or "err"))
        elif m in ("act", "seed", "ready", "concede", "chat", "ping"):
            # 对局中的中转消息：直接交给对局处理
            self._mp_route_in_game(msg)

    def _lobby_set_players(self, players):
        """重建在线玩家列表（同时把进出大厅的人写进日志）"""
        names = {p.get("name") for p in players if p.get("name")}
        for n in sorted(names - self._lobby_track):
            self._lobby_log(i18n.t("log_lobby_in", name=n))
        for n in sorted(self._lobby_track - names):
            self._lobby_log(i18n.t("log_lobby_out", name=n))
        self._lobby_track = names
        self.mp_lobby_players = players
        box = getattr(self, "lobby_players_box", None)
        if box is None or not box.winfo_exists():
            return
        for w in box.winfo_children():
            w.destroy()
        if self.lobby_count_lbl is not None and self.lobby_count_lbl.winfo_exists():
            self.lobby_count_lbl.configure(text=i18n.t("lobby_count", n=len(players)))
        if not players:
            tk.Label(box, text=i18n.t("lobby_no_players"), bg=PANEL, fg=DIM,
                     font=FONT_S, anchor="w").pack(fill="x", pady=6)
            return
        for p in players:
            row = tk.Frame(box, bg=PANEL)
            row.pack(fill="x", pady=1)
            name = p.get("name") or "?"
            me = (name == self.mp_user)
            st = p.get("stats") or {}
            tk.Label(row, text=("⭐ " if me else "· ") + name, bg=PANEL,
                     fg=GOLD if me else TEXT, font=FONT_S, anchor="w"
                     ).pack(side="left")
            tk.Label(row, text=(i18n.t("player_ingame") if p.get("in_game")
                                else i18n.t("player_idle")), bg=PANEL, fg=DIM,
                     font=FONT_S).pack(side="right")
            tk.Label(row, text=i18n.t("player_stats", w=st.get("win", 0),
                                      l=st.get("lose", 0), d=st.get("draw", 0)),
                     bg=PANEL, fg=DIM, font=FONT_S).pack(side="right", padx=10)

    def _lobby_login_dialog(self):
        """连上服务器但还没登录：把服务器账号登录框弹出来（沿用账号窗逻辑）"""
        if not self._lobby_active or self.mp_link is None:
            return
        self._account_dialog(for_server=True)
        self._lobby_sync()

    # ---- ② → 出击：快速匹配 / 邀请码房间 ----

    def _mp_require_login(self):
        """联机门禁：必须「已连服务器 + 已登录正式账号」。

        游客（未登录）**不能联机** —— 这是产品明确规则。此时给出提示并
        直接把登录窗弹出来，用户登录完就能接着点原来那个按钮。
        """
        if self.mp_link is None or not getattr(self.mp_link, "alive", False):
            messagebox.showwarning(i18n.t("srv_offline_title"), i18n.t("srv_offline"))
            return False
        if not self.mp_user:
            messagebox.showwarning(i18n.t("srv_need_login_title"), i18n.t("srv_need_login"))
            self._account_dialog(for_server=True)
            return False
        return True

    def _mp_quick_match(self):
        if self.mp_matching:
            self._srv_send({"m": "cancel_match"})
            self.mp_matching = False
            self._lobby_sync()
            return
        if not self._mp_require_login():
            return
        if not self._srv_send({"m": "match"}):
            self._lobby_log(i18n.t("log_srv_down"))
            return
        self.mp_matching = True
        self._lobby_log(i18n.t("matching"))
        self._lobby_sync()

    def _mp_toggle_room(self):
        if self.mp_room_code:
            self._srv_send({"m": "leave_room"})
            self.mp_room_code = None
            self._lobby_log(i18n.t("match_cancelled"))
            self._lobby_sync()
            return
        if not self._mp_require_login():
            return
        if not self._srv_send({"m": "create_room"}):
            self._lobby_log(i18n.t("log_srv_down"))

    def _mp_join_by_code(self):
        code = (self.join_code_var.get() or "").strip().upper()
        if not code:
            messagebox.showwarning(i18n.t("warn_code_title"), i18n.t("warn_code"))
            return
        if not self._mp_require_login():
            return
        if not self._srv_send({"m": "join_room", "code": code}):
            self._lobby_log(i18n.t("log_srv_down"))
            return
        self.mp_matching = True          # 等 matched
        self._lobby_sync()

    def _lobby_back(self):
        self._lobby_active = False
        self.mp_matching = False
        self.mp_room_code = None
        self.mp_opp_name = None
        self._cancel_timer("_t_lobby")       # 停掉大厅轮询，避免访问已销毁控件
        self.start_frame.destroy()
        self._build_start()

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
        # ⚠ 联机时从「匹配成功」到「双方都点开始」之间可能停留很久（组卡很慢）。
        # 这段时间大厅轮询已经停了，如果对手掉线 / 服务器断开，界面会一直停在
        # 这里没有任何反馈，直到用户点了开始才发现（实测如此）。所以这里起一个
        # 轻量看门狗，只负责"发现链路死了就把界面退回主菜单并提示"。
        if mp:
            self._schedule("_t_prep", 500, self._mp_prep_watch)

    def _mp_prep_watch(self):
        """准备阶段的看门狗：只关心「连接是否还在」。

        真正的 seed / ready 交换由 `_mp_poll_hello`（点了开始之后）负责，
        所以本方法**必须**让步：一旦 _t_hello 起来了就自己停掉，避免
        两条轮询同时抢占 inbox（会互相抢走对方的包）。
        """
        self._t_prep = None
        if self.game is not None or self._t_hello is not None:
            return                                  # 已进对局 / 已交给 hello 轮询
        link = self.mp_link
        if link is None:
            return
        self._lobby_drain_events()                  # 兜底消费，顺带更新链路状态
        if self.game is not None or self._t_hello is not None:
            return
        if self.mp_link is None or not self.mp_link.alive:
            messagebox.showerror(i18n.t("mp_title"), i18n.t("mp_peer_left_prep"))
            self._mp_cleanup_to_menu()
            return
        self._schedule("_t_prep", 500, self._mp_prep_watch)

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
        """联机：校验卡组 → 发 ready（带国家与卡组）→ 等双方就绪 → 主机发种子开局

        ⚠ 协议约定：信封字段一律用 "m"（见 kards_net 模块头注释）。
        "t" 在行动指令里表示「目标槽位」，用 "t" 做信封会被 unpack 覆盖，
        导致攻击指令丢失目标而静默失效 —— 历史 bug，此处及以下全部用 "m"。
        """
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
        self.mp_link.send({"m": "ready", "nation": self.deck_nation,
                           "deck": self.mp_my_deck})
        self.start_btn.configure(state="disabled", text=i18n.t("waiting_opponent"))
        self._cancel_timer("_t_prep")       # 交给 hello 轮询，看门狗退场
        self._schedule("_t_hello", 200, self._mp_poll_hello)

    def _mp_poll_hello(self):
        self._t_hello = None
        if self.game is not None or self.mp_link is None:
            return
        # ⚠ 兜底消费：匹配成功那一刻大厅轮询会停掉，此后 seed / ready 只能
        # 靠这里收 —— 否则双方会一直卡在"等待对手准备"（实测踩过）。
        self._lobby_drain_events()
        if self.game is not None or self.mp_link is None:
            return
        if not self.mp_link.alive:
            messagebox.showerror(i18n.t("mp_title"), i18n.t("mp_peer_left_prep"))
            self._mp_cleanup_to_menu()
            return
        try:
            while True:
                m = self.mp_link.inbox.get_nowait()
                if m.get("m") == "ready":
                    self.mp_opp = m
                elif m.get("m") == "seed" and self.mp_role == "client":
                    self._mp_launch(m["seed"])
                    return
                elif m.get("m") == "peer_left":
                    messagebox.showerror(i18n.t("mp_title"), i18n.t("mp_peer_left_prep"))
                    self._mp_cleanup_to_menu()
                    return
                elif m.get("m") == "concede":
                    self._mp_cleanup_to_menu()
                    return
                elif m.get("m") == "kick":
                    messagebox.showerror(i18n.t("mp_title"), i18n.t("log_kicked"))
                    self._mp_cleanup_to_menu()
                    return
        except queue.Empty:
            pass
        if self.mp_role == "host" and self.mp_opp is not None:
            seed = random.SystemRandom().randrange(10 ** 9)
            self.mp_link.send({"m": "seed", "seed": seed})
            self._mp_launch(seed)
            return
        self._schedule("_t_hello", 200, self._mp_poll_hello)

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
        foe_name = self.mp_opp_name or f"对手·{opp.get('nation', '?')}"
        me = core.Player("你", self.deck_nation, my_deck)
        foe = core.Player(foe_name, opp.get("nation", "德国"), opp_deck)
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
        self.add_log(f"联机对战：你({self.deck_nation}) vs {foe.name}"
                     f"({opp.get('nation')})")
        self.add_log(f"先手：{'你' if i_am_first else '对手'}。祝你好运，指挥官！")
        self.busy = not i_am_first
        self.game.start_turn()      # 第 1 回合准备（双方对称各执行一次）
        self.refresh()
        self._schedule("_t_net", 80, self._mp_poll_net)
        if i_am_first:
            self.show_banner("你的回合", GREEN, 900)
        else:
            self.show_banner("敌方回合", RED, 900)

    # ---------------- 联机：网络轮询与行动应用 ----------------
    def _mp_send_act(self, act):
        """发一条行动指令。

        ⚠ 这里**只能**用 {"m": "act", ...}。曾经写成 {"t": "act", **act}，
        但 act 里 "t" 是目标槽位（攻击指令），dict 字面量展开顺序会让
        后面的 "t" 覆盖掉 "act" → 服务器看不懂信封 → 攻击指令静默失效。
        """
        if self.mp_link is not None:
            self.mp_link.send({"m": "act", **act})

    def _mp_poll_net(self):
        self._t_net = None
        link = self.mp_link
        if self.game is None or link is None:
            return
        self._lobby_drain_events()      # 兜底 + 感知服务器断线
        if self.game is None or self.mp_link is None:
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
        self._schedule("_t_net", 80, self._mp_poll_net)

    def _mp_route_in_game(self, msg):
        """对局中的中转消息：交给 _mp_handle；准备阶段交给 hello 轮询"""
        if self.game is not None:
            self._mp_handle(msg)

    def _mp_handle(self, msg):
        g = self.game
        if g is None:
            return
        m = msg.get("m")
        if m in ("peer_left", "kick"):
            self.add_log("  ⚠ 对手已断线！")
            self._mp_game_over = True
            self.finish(winner=g.players[0])
            return
        if m == "concede":
            self.add_log("  🏳 对手选择了投降！")
            self.finish(winner=g.players[0])
            return
        if m != "act":
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
        """服务器连接断开：对局中判负回菜单，否则只提示"""
        link = self.mp_link
        self.mp_link = None
        if link is not None:
            try:
                link.close()
            except Exception:
                pass
        account.set_remote(None)
        self._srv_ready = False
        self.mp_user = None
        self.mp_matching = False
        self.mp_room_code = None
        if self.game is not None:
            self.add_log("  ⚠ 与服务器的连接已断开！")
            self._mp_game_over = True
            self.finish(winner=self.game.players[0])
        else:
            messagebox.showinfo(i18n.t("mp_title"), i18n.t("log_srv_down"))

    def _mp_teardown_game(self):
        """服务器掉线时清掉对局界面（不弹窗，由调用方负责提示）"""
        self._mp_game_over = True
        if self.game is not None:
            try:
                self.finish(winner=self.game.players[0])
            except Exception:
                self.game = None
                self.back_to_menu()

    def _mp_cleanup_to_menu(self):
        """准备阶段出错：断开连接回主菜单"""
        self._close_server_link()
        self.mp_role = None
        self.mp_opp = None
        self.mp_opp_name = None
        self.mp_my_deck = None
        self._lobby_active = False
        for attr in ("start_frame", "builder_frame"):
            fr = getattr(self, attr, None)
            if fr is not None and fr.winfo_exists():
                fr.destroy()
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
        # 刷新会重建所有卡片控件，先清掉拖拽残留（高亮/幽灵卡），
        # 否则旧控件的引用会留在 _hl_saved 里，且幽灵卡可能浮在死控件上
        self._clear_highlights()
        self._hl_saved = {}
        self._lift_saved = {}
        d = self.drag
        if d is not None and d.get("ghost") is not None:
            try:
                if d["ghost"].winfo_exists():
                    d["ghost"].destroy()
            except tk.TclError:
                pass
            d["ghost"] = None
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

    # ---- 拖拽：幽灵卡直接挂主窗口 ----
    def _drop_zones(self):
        """返回 [(widget, 类型)] —— 拖拽时可以落下的区域。

        类型用于判定合法性：
          "deploy" 部署单位（我方支援阵线）
          "front"  我方前线（移动 / 部署到前线）
          "enemy"  敌方单位卡（攻击目标）
          "hq"     敌方总部（攻击目标）
        """
        zones = []
        for attr, kind in (("foe_rear_row", "enemy"),
                           ("foe_front_row", "enemy"),
                           ("my_front_row", "front"),
                           ("my_rear_row", "deploy")):
            w = getattr(self, attr, None)
            if w is not None and w.winfo_exists():
                zones.append((w, kind))
        if self.hq_widget is not None and self.hq_widget.winfo_exists():
            zones.append((self.hq_widget, "hq"))
        for _u, w in self.enemy_widgets:
            if w.winfo_exists():
                zones.append((w, "enemy_card"))
        return zones

    def _drag_start(self, payload, e, widget=None):
        if not self._drag_ok():
            return
        if widget is not None:
            self._last_drag_src = self._wcenter(widget)   # 部署入场动画的起飞点
        self.drag = {"payload": payload, "ghost": None,
                     "sx": e.x_root, "sy": e.y_root,
                     "widget": widget, "hot": None,
                     "unbind": None}
        # 抬起效果：源卡描边高亮，明确"这张正在被拖动"
        # 注意：这是拖拽的基本反馈，不受 anim_enabled（动画开关）影响
        if widget is not None:
            self._lift_widget(widget)

    def _lift_widget(self, w):
        """拖拽中的源卡加一圈金色描边（松手/刷新时自动还原）"""
        try:
            if not w.winfo_exists():
                return
            if not hasattr(self, "_lift_saved"):
                self._lift_saved = {}
            if w not in self._lift_saved:
                # 同时记下原描边色和原描边宽度，还原时一模一样放回去
                self._lift_saved[w] = (w.cget("highlightbackground"),
                                       w.cget("highlightthickness"))
            w.configure(highlightbackground=GOLD, highlightthickness=3)
        except tk.TclError:
            pass

    def _unlift_all(self):
        for w, saved in list(getattr(self, "_lift_saved", {}).items()):
            try:
                if w.winfo_exists():
                    bg, th = saved if isinstance(saved, tuple) else (saved, 2)
                    w.configure(highlightbackground=bg, highlightthickness=th)
            except tk.TclError:
                pass
        self._lift_saved = {}

    def _ghost_text(self, payload):
        """拖动时显示的文案 + 颜色（非法操作给出不同配色）"""
        g = self.game
        p = payload
        if p[0] == "hand":
            if p[1] >= len(g.players[0].hand):
                return None, None
            card = g.players[0].hand[p[1]]
            eff = g.get_cost(card, g.players[0])
            playable = eff <= g.players[0].kredits
            if card.kind == "unit":
                ok = playable and g.can_deploy(g.players[0])
                return f"{card.name}  ◆{eff}  拖到支援阵线", (GOLD if ok else "#8a5a3a")
            return f"{card.name}  ◆{eff}  拖到桌面", (GOLD if playable else "#8a5a3a")
        if p[0] == "unit" and p[1] in g.players[0].board:
            u = p[1]
            return f"{u.name}  {u.attack}/{u.defense}  拖到目标或阵线", GOLD
        return None, None

    def _valid_drop(self, payload, x, y):
        """当前落点是否是可执行的操作（决定高亮颜色）"""
        g = self.game
        if g is None:
            return False
        me = g.players[0]
        for w, kind in self._drop_zones():
            if not self._hit(x, y, w):
                continue
            if payload[0] == "hand":
                idx = payload[1]
                if idx >= len(me.hand):
                    return False
                card = me.hand[idx]
                if card.kind == "unit":
                    # 单位只能落在支援阵线（部署）
                    return kind == "deploy"
                return kind in ("deploy", "front")
            unit = payload[1]
            if unit not in me.board:
                return False
            if kind == "enemy_card":
                u = next((uu for uu, ww in self.enemy_widgets if ww is w), None)
                return u is not None and g.unit_ready(unit) \
                    and u in g.attack_targets(unit)
            if kind == "hq":
                return g.unit_ready(unit)
            if kind in ("front", "deploy"):
                return True     # 机动不要求"可攻击"，引擎内部会再校验
            return False
        return False

    def _drag_motion(self, e):
        d = self.drag
        if d is None:
            return
        if d["ghost"] is None:
            # 阈值放宽到 4px，兼顾"轻点"与"随手拖"
            if abs(e.x_root - d["sx"]) < 4 and abs(e.y_root - d["sy"]) < 4:
                return
            txt, color = self._ghost_text(d["payload"])
            if txt is None:
                # 这张牌当前打不出去（费用/回合等），静默放弃，
                # 但要撤掉源卡的金描边，否则会一直亮着
                self.drag = None
                self._drag_cancel()
                return
            # 幽灵卡的父级必须是主窗口（self），**不能**放原容器里
            # （会被手牌区裁剪），也**不能**套一层铺满窗口的遮罩 Frame ——
            # 那样会把整个界面盖成黑屏并吃掉所有点击（v1.3.0.2 前的
            # 「拖卡黑屏」事故）。place() 的绝对坐标以父容器为基准，
            # 挂在主窗口上就等于全窗口自由定位，且 lift() 后压在所有
            # 兄弟控件之上，无需任何中间层。
            ghost = tk.Label(self, text=txt, bg=color,
                             fg="#15171c", font=FONT_B, bd=0, padx=12, pady=7)
            ghost.place(x=-500, y=-500)
            ghost.lift()
            d["ghost"] = ghost
            d["base_color"] = color
        # 幽灵卡跟随鼠标，并做边界收拢，保证始终可见
        gh = d["ghost"]
        if not gh.winfo_exists():        # 幽灵卡被 refresh() 意外销毁
            self.drag = None
            self._drag_cancel()
            return
        w, h = gh.winfo_reqwidth(), gh.winfo_reqheight()
        gx = min(max(0, e.x_root - self.winfo_rootx() - w // 2),
                 max(0, self.winfo_width() - w))
        gy = min(max(0, e.y_root - self.winfo_rooty() - h // 2),
                 max(0, self.winfo_height() - h))
        gh.place(x=gx, y=gy)

        # 高亮当前落点：绿=可执行，红=不可执行
        ok = self._valid_drop(d["payload"], e.x_root, e.y_root)
        zone = self._zone_at(e.x_root, e.y_root)
        if zone is not d["hot"]:
            self._unhighlight(d["hot"])
            d["hot"] = zone
            self._highlight(zone, GREEN if ok else RED)
        gh.configure(bg=GOLD if ok else "#7a4a4a")

    def _zone_at(self, x, y):
        """落点命中的区域控件（用于高亮）"""
        for w, _kind in self._drop_zones():
            if self._hit(x, y, w):
                return w
        return None

    def _highlight(self, w, color):
        if w is None or not w.winfo_exists():
            return
        try:
            if not hasattr(self, "_hl_saved"):
                self._hl_saved = {}
            if w not in self._hl_saved:
                self._hl_saved[w] = (w.cget("highlightbackground"),
                                     w.cget("highlightthickness"))
            w.configure(highlightbackground=color, highlightthickness=3)
        except tk.TclError:
            pass

    def _unhighlight(self, w):
        if w is None:
            return
        try:
            if w.winfo_exists():
                orig = getattr(self, "_hl_saved", {}).pop(w, None)
                if orig:
                    w.configure(highlightbackground=orig[0],
                                highlightthickness=orig[1])
                else:
                    w.configure(highlightthickness=0)
        except tk.TclError:
            pass

    def _clear_highlights(self):
        for w in list(getattr(self, "_hl_saved", {}).keys()):
            self._unhighlight(w)

    def _drag_drop(self, e):
        d = self.drag
        self.drag = None
        if d is None:
            return
        # 注意：这里不要清高亮/抬起。_resolve_drop 里可能需要给"被拒绝的落点"
        # 闪一下红框（_shake_widget），先还原再闪会看到闪不出来。
        # 真正打出/移动时 refresh() 会统一清场，取消时会走下面的 _drag_cancel。
        if d["ghost"] is not None and d["ghost"].winfo_exists():
            d["ghost"].destroy()
        self._resolve_drop(d["payload"], e.x_root, e.y_root)

    def _drag_cancel(self):
        """没有真的打出/移动（拖到桌外、非法落点、或状态被打断）→ 恢复视觉"""
        self._clear_highlights()
        self._unlift_all()

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
            self._drag_cancel()
            return
        me = g.players[0]
        # 记录落点命中的区域与合法性，便于给出"为什么没反应"的提示
        hit_kind, hit_widget = None, None
        for w, kind in self._drop_zones():
            if self._hit(x, y, w):
                hit_kind, hit_widget = kind, w
                break
        ok = self._valid_drop(payload, x, y)

        if payload[0] == "hand":
            idx = payload[1]
            if idx >= len(me.hand):
                return
            card = me.hand[idx]
            if hit_kind is None:
                # 拖到牌桌外 = 取消，但给一句回馈，避免用户以为卡丢了
                self.add_log("  已取消（把卡拖到支援阵线即可部署）。")
                self._drag_cancel()
                return
            if not ok:
                if card.kind == "unit":
                    self.add_log("  新单位只能部署在我方支援阵线（绿色高亮处）。")
                else:
                    self.add_log("  该落点无法使用这张牌。")
                # 顺序很重要：先撤掉全部高亮/抬起，让落点回到"出厂描边"，
                # 再闪红。否则 _shake_widget 记下的"原值"其实是红色高亮，
                # 320ms 后会把红框又还原成红色——看起来像卡住了。
                self._drag_cancel()
                self._shake_widget(hit_widget)
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
            self._drag_cancel()
            return
        if hit_kind == "enemy_card":
            u = next((uu for uu, ww in self.enemy_widgets if ww is hit_widget), None)
            if u is not None:
                self._attack_unit(unit, u)
            return
        if hit_kind == "hq":
            self._attack_hq(unit)
            return
        if hit_kind in ("front", "deploy"):
            dest = "前线" if hit_kind == "front" else "后方"
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
        # 拖回自己的阵线以外 → 取消
        self.add_log("  已取消机动。")
        self._drag_cancel()

    def _shake_widget(self, w):
        """无效落点时，给目标区域一个轻微的左右抖动，替代沉默失败"""
        if not self.anim_enabled or w is None:
            return
        try:
            if not w.winfo_exists():
                return
            # 记下原值（颜色 + 宽度），闪完原样还回去。
            # 不能写死 1：手牌 CardWidget 静止态是 2px，写死会把它永久改坏。
            base = (w.cget("highlightbackground"), w.cget("highlightthickness"))
            w.configure(highlightbackground=RED, highlightthickness=3)
        except tk.TclError:
            return

        def restore():
            try:
                if w.winfo_exists():
                    w.configure(highlightbackground=base[0],
                                highlightthickness=base[1])
            except tk.TclError:
                pass

        self.after(320, restore)

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
        win.role = "ingame_settings"
        win.title(i18n.t("settings_title"))
        win.configure(bg=BG)
        win.geometry("340x460")
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
                    self.mp_link.send({"m": "concede"})
                self.finish(winner=self.game.players[1] if self.game else None)

        def to_menu():
            if messagebox.askyesno(i18n.t("to_menu_title"), i18n.t("to_menu_confirm")):
                win.destroy()
                self.back_to_menu()

        def keywords():
            self.open_keyword_guide()

        def quit_app():
            if messagebox.askyesno(i18n.t("quit_title"), i18n.t("quit_safe_confirm")):
                win.destroy()
                self.destroy()

        for text, cmd, color in ((i18n.t("btn_keywords"), keywords, "#4a6b8a"),
                                 (i18n.t("btn_surrender"), surrender, "#8a3a3a"),
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

    def on_f1(self, event=None):
        """F1：随时打开关键词说明（对局中也能查）"""
        try:
            self.open_keyword_guide()
        except Exception:
            pass

    def back_to_menu(self):
        """安全回到主菜单（放弃当前对局）。

        ⚠ 注意：这里是**回主菜单**，不是断服务器 —— 服务器连接要保留，
        否则用户每打一局都得重连 + 重新登录。
        """
        self._finishing = False
        if self.mp_link is not None:
            if self.game is not None and not self._mp_game_over:
                self.mp_link.send({"m": "concede"})   # 中途退出 = 投降
                self.mp_link.send({"m": "leave_room"})
        self._mp_game_over = False
        self.mp_role = None
        self.mp_opp = None
        self.mp_opp_name = None
        self.mp_my_deck = None
        self.mp_matching = False
        self.mp_room_code = None
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

    def _ai_concede(self, step=None):
        """AI 认定没胜算，主动投降 → 直接判我方获胜"""
        g = self.game
        self._ai_iter = None
        if g is None:
            return
        reason = (step or {}).get("reason", "")
        self.add_log(i18n.t("ai_concede_log"))
        if reason:
            self.add_log(i18n.t("ai_concede_reason", reason=reason))
        g.over = True
        # 记录投降方：engine 的 winner_of() 靠它区分"投降"和"被打死"
        g.conceded = (step or {}).get("player") or g.players[1]
        self.busy = False
        self.refresh()
        # 用引擎判定胜者（= 投降方的对手），比写死 players[0] 更稳
        self.finish(winner=g.winner_of() or g.players[0])

    def _ai_play_next(self):
        g = self.game
        if g is None:
            return
        step = None
        try:
            while True:
                step = next(self._ai_iter)
                # AI 认输：直接结算（我方获胜）
                if step.get("type") == "concede":
                    self._ai_concede(step)
                    return
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
            # 交给引擎统一判定（区分平局 / 投降 / 被打死）。
            # 注意：winner_of() 在"没人死"时也返回 None，所以不能直接拿来
            # 当平局用 —— 只有双方总部都倒下才是真平局。
            winner = g.winner_of()
            if winner is None and not (g.players[0].hq <= 0 and g.players[1].hq <= 0):
                # 既没分胜负也不是双死：说明是对手断线之类的提前结算。
                # 我方还在 → 判我方获胜。
                winner = g.players[0] if g.players[0].hq > 0 else g.players[1]
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

    def anim_test(self, seed=20261002):
        """动画链路自测：开启动画跑 AI 对战回放（部署入场/行军/进攻冲刺全链路）

        必须固定随机种子：随机牌组下 AI 有可能 40 秒内一次都不移动/进攻，
        导致"未触发 move/attack"的假失败（也偶发卡死跑不完）。
        固定种子后每次牌局一致，结果可复现。
        """
        random.seed(seed)
        self.ai_step_ms = 120
        self.new_game_smoke()
        self._ai_replay = self._run_ai_replay
        self.after(150, self._ai_replay)
        self.after(60000, self.destroy)
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


def run_debug_net(addr=None):
    """--debug-on-net：本机双开自战（一个进程跑两个窗口，自动连同一服务器）

    用于在一台电脑上体验/调试**服务器中转**联机流程：
    两个窗口各注册一个临时账号 → 自动匹配 → 各自组卡 → 开局对打。
    前提：先启动 `python kards_server.py`（默认 6000 端口）。

    地址也可从命令行给：`python KARDS.py --debug-on-net 127.0.0.1:6001`
    （自动化测试就是这么带着随机端口起服务器的）。
    """
    import time as _time
    core.setup_error_log()
    if addr is None:
        # 找 --debug-on-net 后面那个「长得像 host:port」的参数
        for arg in sys.argv[1:]:
            if arg.startswith("--"):
                continue
            if net.parse_addr(arg) is not None:
                addr = arg
                break
    addr = addr or net.DEFAULT_SERVER
    print(f"[调试自战] 正在启动两个窗口，服务器 {addr} …")
    a = App()
    a.title("KARDS 联机调试 · 窗口A")
    a.geometry("+60+60")
    b = App()
    b.title("KARDS 联机调试 · 窗口B")
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
    # ⚠ kards_account 的会话缓存(session.json)是**模块级全局**。两个窗口
    # 同进程自战，如果不作废缓存：窗口B 连上后 `_lobby_poll` 会用窗口A
    # 刚拿到的令牌自动 resume，服务器判「同账号异地登录」把 A 踢下线
    # → A 的 mp_link.alive 变 False → 匹配静默失败（探针已实证）。
    # 真实游戏一个进程只有一个窗口，不会遇到；自战模式必须手动处理。
    for app in (a, b):
        account._drop_session()
        app.srv_addr_var.set(addr)
        app._lobby_connect()
        # 等到「连上并且自动 resume 判定结束」再动下一个窗口，
        # 否则两个窗口的 resume 会互相踩
        t0 = _time.time()
        while app.mp_link is None and _time.time() - t0 < 8:
            if not pump(1):
                return
    # 等两个窗口都连上服务器
    t0 = _time.time()
    while (a.mp_link is None or b.mp_link is None) and _time.time() - t0 < 12:
        if not pump(1):
            return
    if a.mp_link is None or b.mp_link is None:
        print("[调试自战] 连不上服务器，请先运行 python kards_server.py")
        return

    # 两个窗口各自注册临时账号（登录框会自动弹出，这里直接走账号模块）
    for app, who in ((a, "DebugA"), (b, "DebugB")):
        account.set_remote(app.mp_link, addr)
        pw = "debug1234"
        ok, err = account.login(who, pw)
        if not ok:
            ok, err = account.register(who, pw)
        if not ok:
            print(f"[调试自战] {who} 账号失败：{err}")
            return
        app.mp_user = account.current()
        app._apply_account(app.mp_user)
        app._srv_send({"m": "lobby"})
    # 关掉可能弹出的账号窗（避免挡住调试视线）
    pump(20)
    for app in (a, b):
        for w in app.winfo_children():
            if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == "account":
                w.destroy()
    pump(3)

    a._mp_quick_match()
    pump(2)
    b._mp_quick_match()

    # 等匹配成功（_lobby_poll 收到 matched 后自动进入选阵营）
    t0 = _time.time()
    while (a.mp_role is None or b.mp_role is None) and _time.time() - t0 < 15:
        if not pump(1):
            return
    pump(60)   # 等 after(500ms) 调度选阵营界面

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


def _server_default_db(srvmod):
    """服务器模式的默认数据库路径。

    优先级：
      1. `KARDS_DATA_DIR`（测试/便携用，最高优先）
      2. 打包运行 → 用户数据目录（安装目录常在 Program Files，只读）
      3. 源码运行 → 项目根目录的 kards_server.db（与 kards_server.py 一致）

    ⚠ 第 2、3 步顺序不能反：frozen 下 `__file__` 指向 _internal 里的
    数据文件，那个目录属于程序安装目录，不能当数据库目录。
    """
    env_dir = os.environ.get("KARDS_DATA_DIR")
    if env_dir:
        try:
            os.makedirs(env_dir, exist_ok=True)
        except OSError:
            pass
        return os.path.join(env_dir, "kards_server.db")
    if getattr(sys, "frozen", False):
        return srvmod.user_data_db()
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "kards_server.db")


def run_server_entry(argv):
    """`KARDS.exe --server [--port N]` → 就地变成联机服务器。

    为什么让主程序兼任服务器入口：玩家手上只有这一个 exe，
    没有 Python、也不会开命令行。大厅里的「建立服务器」按钮就是
    用这个入口把自己拉起来的（见 kards_host.py）。

    ⚠ 必须在**创建 Tk 窗口之前**分流，否则会先弹出游戏主界面。
    ⚠ 这是无界面程序（console=False），所以错误只能弹窗 + 写日志。
    """
    import argparse
    ap = argparse.ArgumentParser(prog="KARDS --server", add_help=False)
    ap.add_argument("--server", action="store_true")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--db", default=None)
    args, _unknown = ap.parse_known_args(argv[1:])

    rc = 1
    try:
        import kards_server as srvmod
    except Exception as e:                       # noqa: BLE001
        _server_fatal(f"无法加载服务器模块：{type(e).__name__}: {e}")
        return 1

    db_path = args.db or _server_default_db(srvmod)
    port = args.port or srvmod.DEFAULT_PORT
    try:
        srvmod.DB = srvmod.Store(db_path)
        server = srvmod.Server((args.host, port), srvmod.ClientHandler)
    except OSError as e:
        _server_fatal(f"端口 {port} 无法监听（可能已被占用）：\n{e}")
        return 1
    except Exception as e:                       # noqa: BLE001
        _server_fatal(f"服务器启动失败：{type(e).__name__}: {e}")
        return 1

    try:
        server.serve_forever()
        rc = 0
    except KeyboardInterrupt:
        rc = 0
    except Exception as e:                       # noqa: BLE001
        _server_fatal(f"服务器异常退出：{type(e).__name__}: {e}")
    finally:
        try:
            server.server_close()
        except Exception:                        # noqa: BLE001
            pass
    return rc


def _server_fatal(msg, silent=None):
    """服务器模式下的致命错误提示（无控制台，只能弹窗 + 写日志）。

    ⚠ 弹窗是**模态**的：如果调用方（比如自动化测试）不点它，进程会一直挂着。
    所以只要带 `--silent-server-errors` 就跳过弹窗，只写日志。
    默认规则：有控制台的（源码调试）不弹，无控制台的（打包 exe）才弹 ——
    打包后用户看不到任何输出，不弹窗就完全不知道为什么没反应。
    """
    try:
        core.setup_error_log()
        with open(os.path.join(core.LOGS_DIR, "error.log"), "a", encoding="utf-8") as f:
            f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} [服务器] =====\n{msg}\n")
    except Exception:                            # noqa: BLE001
        pass
    if silent is None:
        silent = "--silent-server-errors" in sys.argv
        if not silent:
            # console 属性由 PyInstaller 注入；源码运行时不存在 → 视为有控制台
            silent = not getattr(sys, "frozen", False)
    if silent:
        try:
            print(f"[服务器] {msg}")
        except Exception:                        # noqa: BLE001
            pass
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, f"{msg}\n\n（端口被占用时可换一个端口重试）",
            f"{APP_TITLE} · 服务器", 0x30)       # MB_ICONWARNING
    except Exception:                            # noqa: BLE001
        pass


def host_selftest():
    """`KARDS.exe --host-selftest`：验证本机开服这条路走得通。

    打包后最容易坏的就是「资源在 _internal、exe 在上一层」这种布局
    （kards_host.resource_dir() 找错地方 → 找不到 kards_server.py →
    大厅的「建立服务器」按钮直接不显示）。这个自检把整条链路走一遍：
    定位脚本 → 起进程 → 等端口 → 连上 → 注册 → 收尾。
    """
    import socket
    import tempfile
    import time as _t
    print(f"[自检] frozen={getattr(sys, 'frozen', False)} "
          f"_MEIPASS={getattr(sys, '_MEIPASS', None)}")
    print(f"[自检] resource_dir = {kards_host.resource_dir()}")
    print(f"[自检] server_script = {kards_host.server_script()}")
    print(f"[自检] can_host = {kards_host.can_host()}")
    if not kards_host.can_host():
        print("SELFTEST FAIL: 找不到 kards_server.py，打包不完整")
        return 1
    # 用随机端口，避免撞上开发机上已有的 6000
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    tmp = tempfile.mkdtemp(prefix="kards_selftest_")
    old = os.environ.get("KARDS_DATA_DIR")
    os.environ["KARDS_DATA_DIR"] = tmp
    ok, err = kards_host.start(port=port)
    print(f"[自检] start() -> {ok} {err}")
    if not ok:
        print("SELFTEST FAIL: 服务器进程起不来")
        return 1
    try:
        up = False
        for _ in range(80):
            if kards_host.port_in_use(port=port):
                up = True
                break
            _t.sleep(0.1)
        print(f"[自检] 端口 {port} 已监听 = {up}")
        if not up:
            print("SELFTEST FAIL: 服务器没监听端口")
            return 1
        import kards_net
        sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        link = kards_net.ServerLink(sock, ("127.0.0.1", port))
        name = "SelfTest" + str(int(_t.time()) % 10000)
        link.send({"m": "register", "user": name, "pw": "pw123456"})
        got = None
        deadline = _t.time() + 6
        while _t.time() < deadline:
            try:
                msg = link.inbox.get(timeout=0.3)
            except Exception:                     # noqa: BLE001
                continue
            if isinstance(msg, dict) and msg.get("m") in ("auth_ok", "auth_err"):
                got = msg
                break
        link.close()
        print(f"[自检] 注册应答 = {got}")
        if not (got and got.get("m") == "auth_ok"):
            print("SELFTEST FAIL: 服务器没能注册账号")
            return 1
        print(f"[自检] 数据库目录 = {tmp}（含 db="
              f"{os.path.isfile(os.path.join(tmp, 'kards_server.db'))}）")
    finally:
        kards_host.stop()
        if old is None:
            os.environ.pop("KARDS_DATA_DIR", None)
        else:
            os.environ["KARDS_DATA_DIR"] = old
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("SELFTEST OK: 开服链路完整")
    return 0


def main():
    core.setup_error_log()
    if "--server" in sys.argv:
        sys.exit(run_server_entry(sys.argv))
    if "--host-selftest" in sys.argv:
        # 打包后自检：确认「建立服务器」这条路在安装目录里真的走得通
        # （资源定位、脚本存在、能起进程、端口能连）
        sys.exit(host_selftest())
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
