# -*- coding: utf-8 -*-
"""
KARDS 简化版 - 图形界面（tkinter，纯标准库）

复用 kards.py 的游戏逻辑，提供点击式对战界面：
- 开始界面：战斗（联机预留）/ 练习（人机对战）
- 练习模式：5 大主国选阵营 → 自由组卡（39 张 + 总部卡，单卡上限按稀有度
  普通4/稀有3/史诗2/传说1，盟国≤20）
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
import kards_rank as rank
import kards_host
import kards_update as net_update
import kards_music as music
# 配色/字体清单的唯一真源（与 kards_board.py 共用，别再抄第二份）
import kards_theme as theme
from kards_theme import (BG, BG_ALT, PANEL, PANEL_ALT, CARD_BG, CARD_DIM,
                         CARD_SEL, TEXT, DIM, MUTE, BORDER, BORDER_HI,
                         RED, GREEN, GOLD,
                         BTN, BTN_HOVER, PRIMARY, PRIMARY_HOVER, PRIMARY_FG,
                         SUCCESS, SUCCESS_HOVER, DANGER, DANGER_HOVER,
                         WARN, WARN_HOVER, INFO, INFO_HOVER,
                         ACCENT, ACCENT_DIM, ACCENT_FG,
                         NATION_COLOR,
                         BUNDLED_FONT_FILES as _BUNDLED_FONT_FILES,
                         BUNDLED_FONT_FAMILY as _BUNDLED_FONT_FAMILY)

# ---------------------------------------------------------------- 主题配色
# 色值定义见 kards_theme.py（tkinter 与 pygame 共用一份，改一处两边生效）
# 运行中换主题：theme.apply() → theme.sync(globals())，然后重建当前界面。

APP_TITLE = "KARDS 简化版 - 二战卡牌对战"

# ---------------- 版本号 a.b.c.d ----------------
# a: 重要修复(1位数)  b: 卡牌更新(2位数)  c: 赛季更新(2位数)  d: 补丁修复(3位数)
# 升位规则: 某位 +1 后, 其右侧所有位清零（如卡牌更新 1.01.00.000）
# 升级工具: python debug/bump_version.py a|b|c|d （自动改此处并提交 git）
VERSION = (1, 6, 1, 3)

# 字族：客户机器可能没有微软雅黑（精简版/英文 Windows），tkinter 显式指定
# 字族时不会跨族回退，中文会渲染成方块。App 启动时 ensure_tk_cjk_font()
# 会检测并按需切到游戏自带的 Noto Sans CJK（assets/fonts/）。
FONT_FAMILY = "Microsoft YaHei UI"
FONT = (FONT_FAMILY, 12)
FONT_S = (FONT_FAMILY, 10)
FONT_B = (FONT_FAMILY, 13, "bold")
FONT_XL = (FONT_FAMILY, 32, "bold")

# 系统可能存在的 CJK 字族（覆盖简繁日韩常见字体）
_TK_CJK_FAMILIES = [
    "microsoft yahei ui", "microsoft yahei", "微软雅黑", "msyh",
    "simhei", "黑体", "simsun", "宋体", "nsimsun", "新宋体",
    "dengxian", "等线", "kaiti", "楷体", "fangsong", "仿宋",
    "noto sans cjk sc", "noto sans sc", "source han sans sc",
    "wenquanyi micro hei", "pingfang sc", "heiti sc",
    "microsoft jhenghei", "pmingliu", "mingliu",
    "yu gothic ui", "malgun gothic",
]


def ensure_tk_cjk_font(root):
    """系统缺中文字体时的 tkinter 兜底（客户机器实测出现过全屏方块）。

    tkinter 显式指定字族时不会跨族回退 —— 英文/精简版 Windows 没有
    Microsoft YaHei UI，主菜单、组卡、对局里所有中文都变成 □。
    检测：系统字族里找到任一 CJK 字族就直接用；一个都没有则把游戏
    自带的 Noto Sans CJK 私有加载进进程（AddFontResourceExW FR_PRIVATE，
    不写系统注册表），再全局切换字族。必须在构建任何 UI 之前调用。
    """
    import tkinter.font as tkfont
    global FONT_FAMILY, FONT, FONT_S, FONT_B, FONT_XL
    try:
        fams = {f.lower() for f in tkfont.families(root)}
    except Exception:
        return
    for fam in _TK_CJK_FAMILIES:
        if fam in fams:
            return                      # 系统有中文字体，保持默认
    import os
    import ctypes
    here = os.path.dirname(os.path.abspath(__file__))
    for fn in _BUNDLED_FONT_FILES:
        p = os.path.join(here, "assets", "fonts", fn)
        if not os.path.exists(p):
            continue
        try:
            FR_PRIVATE = 0x10           # 仅本进程可见，不污染系统
            if ctypes.windll.gdi32.AddFontResourceExW(p, FR_PRIVATE, 0):
                FONT_FAMILY = _BUNDLED_FONT_FAMILY
                FONT = (FONT_FAMILY, 12)
                FONT_S = (FONT_FAMILY, 10)
                FONT_B = (FONT_FAMILY, 13, "bold")
                FONT_XL = (FONT_FAMILY, 32, "bold")
        except Exception:
            pass
        break


def kw_text(keywords):
    return " ".join(f"[{k}]" for k in keywords)


# ---------------------------------------------------------------- 悬停反馈
# tkinter 的 Button 没有 CSS 那种 :hover —— 默认只有按下时变色，鼠标扫过去
# 毫无反应，一整屏按钮看着像静态图片。这里统一补上悬停高亮。
#
# ⚠ 悬停色**按进入时的实际底色现算**（不是建控件时算），因为按钮颜色会
#   随状态变（比如「快速匹配」在等待中变红、公网按钮在打通中变灰）。
#   若用建控件时的快照，恢复时会把旧颜色塞回去，状态色就被抹掉了。

def bind_hover(widget, amount=0.12, fg_hover=None):
    """给控件加悬停高亮（幂等，重复绑定无副作用）。"""
    state = {}

    def on_enter(_e=None):
        try:
            if str(widget.cget("state")) == "disabled":
                return
            base = widget.cget("bg")
            state["bg"] = base
            state["fg"] = widget.cget("fg")
        except tk.TclError:
            return
        try:
            widget.configure(bg=theme.hover_of(base, amount))
            if fg_hover:
                widget.configure(fg=fg_hover)
        except tk.TclError:
            pass

    def on_leave(_e=None):
        try:
            if "bg" in state:
                widget.configure(bg=state.pop("bg"))
            if "fg" in state:
                widget.configure(fg=state.pop("fg"))
        except tk.TclError:
            pass

    widget.bind("<Enter>", on_enter, add="+")
    widget.bind("<Leave>", on_leave, add="+")
    return widget


def bind_hover_tree(widget):
    """给容器和它的全部子控件加悬停（卡牌这种「整块都能点」的控件用）。

    子控件自己会遮挡鼠标事件，只绑父控件的话，鼠标压在子 Label 上
    就收不到 <Enter> 了。
    """
    bind_hover(widget)
    for child in widget.winfo_children():
        bind_hover(child)
        if child.winfo_children():
            bind_hover_tree(child)
    return widget


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
        tk.Label(box, text=text, bg=BG_ALT, fg=TEXT, font=FONT_S,
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
                 rarity=None, border=None, dim=False, hint=None):
        w, h = (200, 230) if big else (130, 150)
        bg = CARD_SEL if selected else (CARD_DIM if dim else CARD_BG)
        hl = GOLD if selected else (border or BORDER)
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
                     font=(FONT_FAMILY, 16, "bold")).pack(side="left", expand=True)
            tk.Label(mid, text=str(defense), bg=bg, fg=GREEN,
                     font=(FONT_FAMILY, 16, "bold")).pack(side="right", expand=True)
            if sub:
                tk.Label(mid, text=sub, bg=bg, fg=DIM, font=FONT_S,
                         wraplength=inner_w, justify="center").pack(side="bottom")
        else:
            tk.Label(mid, text=sub or "", bg=bg, fg=DIM, font=FONT_S,
                     wraplength=inner_w, justify="center").pack(expand=True)

        # 入口卡底部的一行小字（例如「联机 / 邀请码」），普通卡牌不传就不显示
        if hint:
            tk.Label(self, text=hint, bg=bg, fg=MUTE, font=(FONT_FAMILY, 9)
                     ).pack(side="bottom", pady=(0, 2))

        if cost is not None:
            tk.Label(self, text=f"◆{cost}", bg=bg,
                     fg=RED if dim else GOLD,
                     font=FONT_B).pack(side="bottom")
        if rarity:
            rc = core.RARITY_COLORS[rarity]
            tk.Label(self, text=rarity, bg=rc, fg=theme.best_fg(rc),
                     font=(FONT_FAMILY, 8, "bold"), padx=3).place(
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
        ensure_tk_cjk_font(self)   # 缺中文字体的机器：切到自带字体（必须在建 UI 前）
        # 恢复上次选的主题，并把新色值灌回本模块的命名空间（必须在建 UI 前，
        # 否则第一屏还是默认配色，切主题时才"跳"一下）。
        theme.load()
        theme.sync(globals())
        self.title(APP_TITLE)
        self.configure(bg=BG)
        self.geometry("1200x800")
        self.minsize(1024, 680)
        # 启动即全屏（F11 随时切回窗口模式）。调试双开 / 自动化测试用
        # --no-fullscreen 跳过，否则测试会把真机屏幕整个占掉。
        if ("--debug-on-net" not in sys.argv
                and "--no-fullscreen" not in sys.argv):
            self.attributes("-fullscreen", True)
        self.bind("<F11>", self._toggle_fullscreen)
        self.game = None
        self.busy = False          # AI 行动/动画期间锁定输入
        self.anim_enabled = True     # 经典界面已删，动画一律由 pygame 棋盘播放
        self.ai_step_ms = 850
        self.fast_ai = False
        self.unit_widgets = {}     # id(unit) -> 卡片控件
        self.enemy_widgets = []    # (unit, 卡片控件)，用于拖拽命中检测
        self.hq_widget = None      # 敌方总部控件（拖拽落点）
        self.my_hq_widget = None   # 我方总部控件（结算爆炸时也要炸）
        self.drag = None           # 当前拖拽状态
        self.pending_flash = []    # 刷新后待播放入场动画的单位 (unit, color)
        self._anim_tokens = set()  # 存活的动画令牌（退出对局时清理）
        self._pyboard = None       # pygame 对战视图（非 None 时接管视图方法）
        # ---- 联机状态（服务器中转模式）----
        self.mp_link = None        # net.ServerLink（连上服务器后非 None）
        self.mp_role = None        # "host" / "client"
        self.mp_mode = False       # 组卡界面是否处于联机流程
        self.mp_opp = None         # 对手 hello 信息 {nation, deck}
        self.mp_my_deck = None     # 我方有序卡名列表
        self._mp_me_ready = False  # 我方是否已点「准备」（对手可能先到，见 _start_mp）
        self._mp_pending_seed = None  # 先收到种子、还没收到对手 ready 时暂存
        self._mp_game_over = False
        self._lobby_active = False
        # 服务器 / 大厅
        self.mp_server_addr = net.DEFAULT_SERVER   # 记住上次填的服务器地址
        self._pub_addr = ""                        # 公网可连地址（打通才有）
        self._pub_lan = ""                         # 局域网地址（复制用兜底）
        self._pub_ok_addr = ""      # UPnP 打通后的公网地址（"" = 还没打通）
        self._pub_switched = False  # 地址框当前是否已切到公网地址
        self._pub_auto_switch = False  # 一键公网：映射完成后自动切换地址框
        self._resume_retry = 0      # 会话校验超时后的自动重试次数（防死循环）
        self._connect_retry = 0     # 连接失败后的自动重试次数（服务器启动慢）
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
        # ---- 段位 / 排行榜 ----
        # 段位是服务器权威数据，但界面上要频繁显示（账号按钮/大厅）。
        # 每次刷新都走一次 RPC 会卡 UI，所以缓存一份，登录/结算后失效重取。
        self.rank_state = None
        self._rank_last = None       # 最近一场的段位变化（结算页展示）
        self._game_online = False    # 当前对局是否联机 —— 只有联机才结算段位
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
        self._music_play("menu", fade_ms=1200)   # 进来先淡入主菜单曲
        if not self.account and self.anim_enabled:
            self.after(300, self._account_dialog)
        # 启动后静默检查更新（后台线程，不阻塞界面；没更新就自己消失）
        self._update_win = None
        self._update_task = None
        if self.anim_enabled and "--no-update-check" not in sys.argv:
            self.after(1500, lambda: self.open_update_dialog(auto=True))

    def _toggle_fullscreen(self, event=None):
        """F11 全屏/窗口切换（attributes 返回 '1'/'0'，直接取非即可）"""
        try:
            self.attributes("-fullscreen", not self.attributes("-fullscreen"))
        except tk.TclError:
            pass

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
        try:
            music.stop(fade_ms=250)
        except Exception:                        # noqa: BLE001
            pass
        tk.Tk.destroy(self)

    def _cancel_timers(self):
        """取消本窗口登记的全部 after 定时器（幂等，可在任意阶段调用）"""
        for key in ("_t_lobby", "_t_hello", "_t_net", "_t_prep",
                    "_t_pub", "_t_reconnect", "_t_retry", "_t_host"):
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

        对局中视图方法被 pygame 棋盘接管（实例属性覆盖），日志写进棋盘的
        日志面板。**主菜单 / 大厅 / 组卡阶段**走本类方法：logbox 已不存在，
        大厅有自己的日志框（_lobby_log），都没有就静默丢弃。
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
        """主菜单。

        视觉分层（自上而下）：顶部强调条 → 账号/工具条 → 标题区 → 两张入口卡
        → 底部版本水印。所有颜色都走主题 token，换主题时整体跟着变。
        """
        self.start_frame = tk.Frame(self, bg=BG)
        self.start_frame.pack(expand=True, fill="both")

        # 顶部强调条：一像素级别的"贵气"，成本极低但整屏不再是一块死板的底
        tk.Frame(self.start_frame, bg=ACCENT, height=4).pack(fill="x")

        # ---- 工具条：左账号、右设置/主题/音乐 ----
        top = tk.Frame(self.start_frame, bg=BG)
        top.pack(fill="x", padx=18, pady=(12, 0))
        left = tk.Frame(top, bg=BG)
        left.pack(side="left")
        self.account_btn = tk.Button(left, text=self._account_btn_text(),
                                     bg=BTN, fg=TEXT, font=FONT_S, bd=0,
                                     padx=14, pady=7, cursor="hand2",
                                     activebackground=BTN_HOVER,
                                     activeforeground=TEXT,
                                     command=self._account_dialog)
        self.account_btn.pack(side="left")
        bind_hover(self.account_btn)
        self.guest_hint = tk.Label(left, text="", bg=BG, fg=DIM, font=FONT_S)
        self.guest_hint.pack(side="left", padx=8)
        self.currency_lbl = tk.Label(left, text="", bg=BG, fg=GOLD, font=FONT_S)
        self.currency_lbl.pack(side="left", padx=(16, 0))

        right = tk.Frame(top, bg=BG)
        right.pack(side="right")
        self.music_btn = tk.Button(right, text=self._music_btn_text(), bg=BTN,
                                   fg=TEXT, font=FONT_S, bd=0, padx=11, pady=7,
                                   cursor="hand2", activebackground=BTN_HOVER,
                                   activeforeground=TEXT, command=self._toggle_music)
        self.music_btn.pack(side="right")
        tk.Button(right, text=i18n.t("btn_rank"), bg=BTN, fg=TEXT,
                  font=FONT_S, bd=0, padx=12, pady=7, cursor="hand2",
                  activebackground=BTN_HOVER, activeforeground=TEXT,
                  command=self.open_rank_dialog).pack(side="right", padx=(0, 8))
        tk.Button(right, text=i18n.t("btn_theme"), bg=BTN, fg=TEXT,
                  font=FONT_S, bd=0, padx=12, pady=7, cursor="hand2",
                  activebackground=BTN_HOVER, activeforeground=TEXT,
                  command=self._home_theme_switch).pack(side="right", padx=(0, 8))
        tk.Button(right, text=i18n.t("btn_settings"), bg=BTN, fg=TEXT,
                  font=FONT_S, bd=0, padx=12, pady=7, cursor="hand2",
                  activebackground=BTN_HOVER, activeforeground=TEXT,
                  command=self.open_start_settings).pack(side="right", padx=(0, 8))
        for w in right.winfo_children():
            bind_hover(w)

        # ---- 标题区 ----
        hero = tk.Frame(self.start_frame, bg=BG)
        hero.pack(expand=True)
        tk.Label(hero, text=i18n.t("app_title"), bg=BG, fg=TEXT,
                 font=(FONT_FAMILY, 46, "bold")).pack()
        # 强调下划线：Canvas 画两段，左粗右细，比一根纯色横线有层次
        line = tk.Canvas(hero, width=220, height=5, bg=BG,
                         highlightthickness=0, bd=0)
        line.create_rectangle(0, 0, 150, 3, fill=ACCENT, outline="")
        line.create_rectangle(156, 0, 220, 3, fill=theme.mix(ACCENT, BG, 0.55),
                              outline="")
        line.pack(pady=(6, 10))
        tk.Label(hero, text=i18n.t("app_subtitle"), bg=BG, fg=DIM,
                 font=FONT).pack(pady=(0, 34))

        # ---- 两张入口卡 ----
        row = tk.Frame(hero, bg=BG)
        row.pack()
        battle = CardWidget(row, title=i18n.t("battle_title"),
                            sub=i18n.t("battle_sub"), cost=None,
                            color=DANGER, big=True, on_click=self.on_battle,
                            hint=i18n.t("home_card_battle_hint"))
        battle.pack(side="left", padx=16, ipady=10)
        practice = CardWidget(row, title=i18n.t("practice_title"),
                              sub=i18n.t("practice_sub"), cost=None,
                              color=PRIMARY, big=True,
                              on_click=lambda: self._build_nation_select(),
                              hint=i18n.t("home_card_practice_hint"))
        practice.pack(side="left", padx=16, ipady=10)
        bind_hover_tree(battle)
        bind_hover_tree(practice)

        tk.Label(hero, text=i18n.t("home_hint"), bg=BG, fg=MUTE,
                 font=FONT_S).pack(pady=(26, 0))

        # ---- 底部：版本水印 ----
        foot = tk.Frame(self.start_frame, bg=BG)
        foot.pack(side="bottom", fill="x", pady=(0, 12))
        badge = tk.Frame(foot, bg=PANEL_ALT, padx=10, pady=3)
        badge.pack()
        tk.Label(badge, text="v" + ".".join(map(str, VERSION)), bg=PANEL_ALT,
                 fg=DIM, font=FONT_S).pack()

        self._refresh_account_btn()
        self._refresh_music_btn()
        # 立即应用一次主题（重建界面时也要走到，保证新控件拿到当前配色）
        theme.sync(globals())

    def _home_theme_switch(self):
        """主菜单直接换主题：打开设置窗并停在「外观」页。"""
        self.open_start_settings(tab="appearance")

    # ---------------- 账号管理 ----------------
    def _rank_state(self, force=False):
        """当前账号的段位（带缓存）。

        段位在服务器上，每刷新一次按钮就发一次 RPC 会明显卡顿；
        缓存到 `self.rank_state`，登录换号或对局结算后置空重取。
        """
        if not self.account:
            return None
        if force or self.rank_state is None:
            try:
                self.rank_state = account.get_rank(self.account)
            except Exception:                          # noqa: BLE001
                self.rank_state = None
        return self.rank_state

    @staticmethod
    def _stars_text(n, total=5):
        n = max(0, min(int(n), int(total)))
        return "★" * n + "☆" * (total - n)

    def _account_btn_text(self):
        if self.account:
            st = self._rank_state()
            if st:
                return i18n.t("account_btn_rank", name=self.account,
                              tier=st["tier"],
                              stars=self._stars_text(st["stars"]))
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
            self._refresh_currency_lbl()
        except tk.TclError:
            pass

    def _refresh_currency_lbl(self):
        """主菜单的货币显示（金币/钻石）。

        控件只在主菜单里创建，销毁后引用会变"幽灵"，同账号按钮一样要
        winfo_exists() + 吞 TclError（见 _refresh_account_btn 的注释）。
        """
        lbl = getattr(self, "currency_lbl", None)
        if lbl is None:
            return
        try:
            if not lbl.winfo_exists():
                return
            c = account.get_currency(self.account)
            lbl.configure(text=f"{i18n.t('currency_gold', n=c['gold'])}   "
                               f"{i18n.t('currency_diamonds', n=c['diamonds'])}")
        except tk.TclError:
            pass

    # ---------------- 段位 / 排行榜 ----------------

    def open_rank_dialog(self):
        """段位详情 + 排行榜。

        数据来源：`account.get_rank()`（服务器权威，离线退回本地副本）
        与 `account.leaderboard()`。两者都可能走网络，所以先取数据再建
        控件 —— 别在回调里取，否则窗口先画出来再卡住更难看。
        """
        # 同角色窗口只留一个（连点按钮不会开一堆）
        for w in self.winfo_children():
            if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == "rank":
                w.lift()
                return

        st = self._rank_state(force=True)
        board = None
        if self.account:
            try:
                board = account.leaderboard(20)
            except Exception:                          # noqa: BLE001
                board = None

        win = tk.Toplevel(self)
        win.role = "rank"
        win.title(i18n.t("rank_title"))
        win.configure(bg=BG)
        win.geometry("880x740")
        win.minsize(820, 680)
        win.transient(self)

        tk.Label(win, text=i18n.t("rank_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(16, 2))
        season = (board or {}).get("season") or rank.season_id()
        tk.Label(win, text=i18n.t("rank_season_line", year=season,
                                  days=rank.season_days_left()),
                 bg=BG, fg=DIM, font=FONT_S).pack(pady=(0, 12))

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=18)

        left = tk.Frame(body, bg=PANEL, padx=18, pady=16)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg=PANEL, padx=16, pady=14, width=380)
        right.pack(side="right", fill="both", padx=(14, 0))
        right.pack_propagate(False)

        if not self.account:
            # 游客：没有段位可言，给登录引导
            tk.Label(left, text=i18n.t("rank_guest_title"), bg=PANEL, fg=GOLD,
                     font=FONT_B).pack(anchor="w", pady=(40, 6))
            tk.Label(left, text=i18n.t("rank_guest"), bg=PANEL, fg=DIM,
                     font=FONT, wraplength=360, justify="left").pack(anchor="w")
        elif st is None:
            tk.Label(left, text=i18n.t("rank_unavailable"), bg=PANEL, fg=WARN,
                     font=FONT, wraplength=360, justify="left"
                     ).pack(anchor="w", pady=40)
        else:
            self._rank_left_panel(left, st, board)

        self._rank_board_panel(right, board)
        self._rank_rules(win)
        tk.Button(win, text=i18n.t("btn_close"), bg=BTN, fg=TEXT, font=FONT_B,
                  bd=0, padx=24, pady=8, cursor="hand2",
                  activebackground=BTN_HOVER, activeforeground=TEXT,
                  command=win.destroy).pack(pady=(10, 16))

    def _rank_left_panel(self, parent, st, board):
        """左栏：当前段位、星数、连胜、保护位、榜单状态。"""
        tk.Label(parent, text=i18n.t("rank_current"), bg=PANEL, fg=DIM,
                 font=FONT_S).pack(anchor="w")

        head = tk.Frame(parent, bg=PANEL)
        head.pack(anchor="w", pady=(2, 6))
        num = tk.Label(head, text=str(st["tier"]), bg=PANEL, fg=GOLD,
                       font=(FONT_FAMILY, 52, "bold"))
        unit = tk.Label(head, text=i18n.t("rank_tier_unit"), bg=PANEL, fg=TEXT,
                        font=FONT_B)
        # 中文/日文是「12 段」，英文是「Tier 12」—— 单位放前放后各一处
        if i18n.get_lang() == "en":
            unit.pack(side="left", anchor="s", pady=(0, 14))
            num.pack(side="left", padx=(4, 14))
        else:
            num.pack(side="left")
            unit.pack(side="left", anchor="s", pady=(0, 14), padx=(2, 14))
        # 5 颗星逐颗画：实心金色 / 空心暗色，比一串文字更直观
        pips = tk.Frame(head, bg=PANEL)
        pips.pack(side="left", anchor="s", pady=(0, 16))
        for i in range(rank.STARS_PER_TIER):
            tk.Label(pips, text="★", bg=PANEL,
                     fg=GOLD if i < st["stars"] else BORDER,
                     font=(FONT_FAMILY, 22)).pack(side="left")

        # 进度条：本段 5 星的完成度
        bar = tk.Canvas(parent, height=8, bg=BORDER, highlightthickness=0, bd=0)
        bar.pack(fill="x", pady=(2, 6))
        prog = max(0.0, min(1.0, st["stars"] / float(rank.STARS_PER_TIER)))
        bar.bind("<Configure>", lambda e, c=bar, p=prog: (
            c.delete("all"),
            c.create_rectangle(0, 0, max(1, int(c.winfo_width() * p)), 8,
                               fill=ACCENT, outline="")))
        nxt = st["tier"] - 1
        tk.Label(parent,
                 text=(i18n.t("rank_to_next", tier=nxt,
                              n=rank.STARS_PER_TIER - st["stars"])
                       if st["tier"] > 1 else i18n.t("rank_top")),
                 bg=PANEL, fg=TEXT, font=FONT_S).pack(anchor="w", pady=(0, 12))

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(0, 10))

        streak = i18n.t("rank_streak", n=st["streak"])
        zero = i18n.t("rank_zero_losses", n=st["zero_losses"],
                      need=rank.DEMOTE_LOSSES)
        tk.Label(parent, text=streak, bg=PANEL, fg=TEXT, font=FONT_S
                 ).pack(anchor="w", pady=1)
        tk.Label(parent, text=zero, bg=PANEL,
                 fg=WARN if st["zero_losses"] else DIM,
                 font=FONT_S).pack(anchor="w", pady=1)
        fl = rank.floor_tier(st)
        tk.Label(parent, text=i18n.t("rank_floor", tier=fl), bg=PANEL,
                 fg=DIM, font=FONT_S).pack(anchor="w", pady=(1, 10))

        # 榜单状态
        me = (board or {}).get("me") if board else None
        if st["tier"] == 1:
            txt = (i18n.t("rank_lb_me", pos=me["pos"], pts=me["pts"])
                   if me else i18n.t("rank_lb_top_ok"))
            fg = GOLD
        else:
            txt = i18n.t("rank_lb_locked")
            fg = DIM
        tk.Label(parent, text=txt, bg=PANEL, fg=fg, font=FONT_S,
                 wraplength=380, justify="left").pack(anchor="w", pady=(0, 6))
        if not (board or {}).get("online", True):
            tk.Label(parent, text=i18n.t("rank_lb_offline"), bg=PANEL, fg=WARN,
                     font=FONT_S, wraplength=380, justify="left"
                     ).pack(anchor="w", pady=(0, 4))
        tk.Label(parent, text=i18n.t("rank_ai_note"), bg=PANEL, fg=MUTE,
                 font=FONT_S, wraplength=380, justify="left").pack(anchor="w")

    def _rank_board_panel(self, parent, board):
        """右栏：排行榜（前 20 名，自己不在其中时单独补一行）。"""
        tk.Label(parent, text=i18n.t("rank_lb_title"), bg=PANEL, fg=TEXT,
                 font=FONT_B).pack(anchor="w")
        if board is None:
            tk.Label(parent, text=i18n.t("rank_lb_need_login"), bg=PANEL,
                     fg=DIM, font=FONT_S).pack(anchor="w", pady=10)
            return
        rows = board.get("rows") or []
        tk.Label(parent, text=i18n.t("rank_lb_total", n=board.get("total", 0)),
                 bg=PANEL, fg=DIM, font=FONT_S).pack(anchor="w", pady=(1, 8))
        if not rows:
            tk.Label(parent, text=i18n.t("rank_lb_empty"), bg=PANEL, fg=DIM,
                     font=FONT_S).pack(anchor="w", pady=10)
        for r in rows[:20]:
            mine = bool(self.account) and r.get("name") == self.account
            row = tk.Frame(parent, bg=PANEL_ALT if mine else PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"{r['pos']:>2}", bg=row["bg"],
                     fg=GOLD if mine else DIM, font=FONT_S, width=3,
                     anchor="e").pack(side="left", padx=(4, 6))
            tk.Label(row, text=r["name"], bg=row["bg"],
                     fg=GOLD if mine else TEXT, font=FONT_S, anchor="w"
                     ).pack(side="left")
            tk.Label(row, text=f"{r['lose']}负", bg=row["bg"], fg=DIM,
                     font=FONT_S).pack(side="right", padx=(0, 6))
            tk.Label(row, text=f"{r['win']}胜", bg=row["bg"], fg=DIM,
                     font=FONT_S).pack(side="right", padx=(0, 6))
            tk.Label(row, text=i18n.t("rank_pts", n=r["pts"]), bg=row["bg"],
                     fg=GOLD if mine else TEXT, font=FONT_B
                     ).pack(side="right", padx=(0, 8))
        me = board.get("me")
        if me and me.get("pos", 0) > len(rows[:20]):
            tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=6)
            tk.Label(parent, text=i18n.t("rank_lb_me", pos=me["pos"],
                                         pts=me["pts"]),
                     bg=PANEL, fg=GOLD, font=FONT_S).pack(anchor="w")

    def _rank_rules(self, win):
        tk.Label(win, text=i18n.t("rank_rules"), bg=BG, fg=MUTE, font=FONT_S,
                 wraplength=820, justify="left").pack(padx=20, pady=(12, 0))

    def _apply_account(self, name):
        """登录/注册成功后应用账号（卡组目录 + 按钮）"""
        self.account = name
        core.set_decks_dir(account.deck_dir(name))
        self.rank_state = None          # 换号 → 段位缓存作废
        self._refresh_account_btn()

    # ---------------- 背景音乐 ----------------
    # 播放/切歌统一走 kards_music（细节见该模块）。这里只做两件事：
    # ① 把「界面」翻译成「场景曲目」；② 保证任何异常都不会冒到界面层。
    def _music_play(self, scene, fade_ms=700):
        """切换场景音乐。缺资源 / 没装 pygame / 声卡异常都静默降级。"""
        try:
            music.play(scene, fade_ms=fade_ms)
        except Exception:                                  # noqa: BLE001
            pass
        self._refresh_music_btn()

    def _music_btn_text(self):
        if music.is_enabled():
            return i18n.t("music_on")
        return i18n.t("music_off")

    def _refresh_music_btn(self):
        """刷新主菜单的 ♪ 按钮（控件可能已随界面重建销毁，同货币标签的写法）"""
        btn = getattr(self, "music_btn", None)
        if btn is None:
            return
        try:
            if not btn.winfo_exists():
                return
            btn.configure(text=self._music_btn_text(),
                          fg=TEXT if music.is_enabled() else DIM)
        except tk.TclError:
            pass

    def _toggle_music(self):
        """主菜单一键开关音乐（开了就续放当前界面该放的曲子）"""
        try:
            music.toggle(resume_track="menu" if self.game is None else "battle")
        except Exception:                                  # noqa: BLE001
            pass
        self._refresh_music_btn()

    def _music_row(self, win):
        """设置窗内的音乐区块：开关 + 音量 + 三个场景各选一首曲子。

        做成共用方法，主菜单设置窗和对局内设置窗各调一次，避免两处逻辑漂移。
        曲库来自 assets/music（随包）与玩家音乐目录（自选），见 kards_music。
        """
        tk.Label(win, text=i18n.t("settings_music"), bg=BG, fg=DIM,
                 font=FONT_S).pack(pady=(10, 2))
        row = tk.Frame(win, bg=BG)
        row.pack()
        btn = tk.Button(row, bg=PRIMARY if music.is_enabled() else BTN,
                        fg=TEXT, font=FONT_S, bd=0, padx=12, pady=6,
                        cursor="hand2", width=10)

        def flip():
            # 对局中关掉再开：续放对局曲；在菜单就续放菜单曲
            music.toggle(resume_track=self._music_scene())
            btn.configure(text=self._music_btn_text(),
                          bg=PRIMARY if music.is_enabled() else BTN)
            self._refresh_music_btn()

        btn.configure(text=self._music_btn_text(), command=flip)
        btn.pack(side="left", padx=(0, 10))

        tk.Label(row, text=i18n.t("music_volume"), bg=BG, fg=TEXT,
                 font=FONT_S).pack(side="left", padx=(0, 6))

        def on_scale(v):
            try:
                music.set_volume(int(float(v)))
            except (TypeError, ValueError):
                pass

        scale = tk.Scale(row, from_=0, to=100, orient="horizontal", length=130,
                         bg=BG, fg=TEXT, troughcolor=BORDER, highlightthickness=0,
                         bd=0, sliderrelief="flat", showvalue=0,
                         command=on_scale)
        scale.set(music.get_volume())
        scale.pack(side="left")

        # ---- 三个场景各挑一首（菜单 / 对战 / 结算）----
        self._music_scene_btns = {}
        for scene in music.SCENES:
            self._music_scene_row(win, scene, i18n.t("music_pick_" + scene))

        foot = tk.Frame(win, bg=BG)
        foot.pack(pady=(8, 0))
        tk.Button(foot, text=i18n.t("music_open_dir"), bg=PANEL, fg=TEXT,
                  font=FONT_S, bd=0, padx=10, pady=4, cursor="hand2",
                  command=self._music_open_dir).pack(side="left", padx=(0, 6))
        # 手动重扫：换过文件但想立刻生效时用（正常情况下丢了歌会自动扫到）
        tk.Button(foot, text=i18n.t("music_rescan"), bg=PANEL, fg=TEXT,
                  font=FONT_S, bd=0, padx=10, pady=4, cursor="hand2",
                  command=self._music_rescan).pack(side="left")
        tk.Label(win, text=i18n.t("music_fmt_hint"), bg=BG, fg=DIM,
                 font=FONT_S).pack(pady=(6, 0))
        if not music.available():
            tk.Label(win, text=i18n.t("music_no_files"), bg=BG, fg=DIM,
                     font=FONT_S, wraplength=320, justify="left").pack(pady=(2, 0))
        else:
            bad = music.scan_problems()
            if bad:
                tk.Label(win, text=i18n.t("music_bad_format", n=len(bad)),
                         bg=BG, fg=GOLD, font=FONT_S, wraplength=320,
                         justify="left").pack(pady=(2, 0))
        failed = music.last_error()
        if failed:
            tk.Label(win, text=i18n.t("music_play_failed", name=failed),
                     bg=BG, fg=RED, font=FONT_S, wraplength=320,
                     justify="left").pack(pady=(2, 0))
        return btn

    def _music_scene(self):
        """当前界面属于哪个场景（决定切歌与试听回到哪里）。"""
        return "battle" if self.game is not None else "menu"

    def _music_scene_text(self, scene):
        """按钮上显示的当前选曲文案。"""
        choice = music.scene_choice(scene)
        name = music.scene_track(scene)
        if choice == music.PICK_NONE or not name:
            return i18n.t("music_opt_none")
        if choice == music.PICK_RANDOM:
            return i18n.t("music_opt_random") + " · " + name
        return name

    def _music_scene_row(self, win, scene, label):
        """一个场景一行：场景名 + 当前曲目（点击换）+ 试听。"""
        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", padx=24, pady=1)
        tk.Label(row, text=label, bg=BG, fg=TEXT, font=FONT_S,
                 width=7, anchor="w").pack(side="left")
        btn = tk.Button(row, text=self._music_scene_text(scene), bg=CARD_BG,
                        fg=TEXT, font=FONT_S, bd=0, padx=8, pady=3,
                        cursor="hand2", width=15, anchor="w")
        btn.configure(command=lambda s=scene: self._music_pick_dialog(
            s, on_done=lambda: self._music_refresh_row(s)))
        btn.pack(side="left")
        self._music_scene_btns[scene] = btn
        tk.Button(row, text="\u25b6", bg=PANEL, fg=TEXT, font=FONT_S, bd=0,
                  padx=8, pady=3, cursor="hand2",
                  command=lambda s=scene: self._music_try_play(s)).pack(
                      side="left", padx=(5, 0))
        return row

    def _music_refresh_row(self, scene):
        btn = getattr(self, "_music_scene_btns", {}).get(scene)
        if btn is None:
            return
        try:
            if btn.winfo_exists():
                btn.configure(text=self._music_scene_text(scene))
        except tk.TclError:
            pass

    def _music_refresh_rows(self):
        for scene in music.SCENES:
            self._music_refresh_row(scene)

    def _music_try_play(self, scene):
        """试听该场景的曲子。当前场景直接切过去循环放；别的场景放一遍再收回来。"""
        cur = self._music_scene()
        if scene == cur:
            music.play(scene, fade_ms=200, force=True)
            return
        name = music.scene_track(scene)
        if not name or not music.preview(name):
            return

        def poll(n=[0]):
            n[0] += 1
            busy = music.status()["preview"] and music.status()["busy"]
            if busy and n[0] < 600:            # 最多盯 5 分钟（一首歌足够）
                self.after(500, poll)
            else:
                music.end_preview(cur)

        self.after(500, poll)

    def _music_open_dir(self):
        """打开音乐文件夹（顺便重扫曲库，丢完歌切回来就能选）。"""
        d = music.user_music_dir(create=True)
        try:
            os.startfile(d)                    # Windows
        except Exception:                      # noqa: BLE001
            try:
                import subprocess
                subprocess.Popen(["explorer", d])
            except Exception:                  # noqa: BLE001
                pass
        music.refresh()
        self._music_refresh_rows()

    def _music_rescan(self):
        """手动重扫曲库：换过文件、或系统把 mtime 归一时用它强制重载。"""
        lib = music.refresh()
        self._music_refresh_rows()
        for w in self.winfo_children():
            if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == "music_pick_menu":
                w.destroy()                # 老旧的选择器列表已过期，关掉让玩家重开
        try:
            self._lobby_log(i18n.t("music_rescan_done", n=len(lib)))
        except Exception:                  # noqa: BLE001
            pass

    def _music_pick_dialog(self, scene, on_done=None):
        """曲目选择器：默认 / 随机 / 静音 + 曲库全部曲目，可逐个试听。"""
        # 同一场景不叠开多个选择窗
        for w in self.winfo_children():
            if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == "music_pick_%s" % scene:
                try:
                    w.deiconify()
                    w.lift()
                    w.focus_force()
                    return
                except tk.TclError:
                    pass

        lib = music.refresh()          # 每次打开都重扫：换过 / 新丢的曲子立刻可见
        items = [("", i18n.t("music_opt_default")),
                 (music.PICK_RANDOM, i18n.t("music_opt_random")),
                 (music.PICK_NONE, i18n.t("music_opt_none"))]
        for e in lib:
            label = e["name"]
            if e["user"]:
                label += "   " + i18n.t("music_tag_user")
            items.append((e["name"], label))
        cur = music.scene_choice(scene)

        win = tk.Toplevel(self)
        win.role = "music_pick_%s" % scene
        win.title(i18n.t("music_pick_title"))
        win.configure(bg=BG)
        win.geometry("400x470")
        win.transient(self)
        tk.Label(win, text="%s · %s" % (i18n.t("music_pick_title"),
                                        i18n.t("music_pick_" + scene)),
                 bg=BG, fg=TEXT, font=FONT_B).pack(pady=(14, 8))

        box = tk.Frame(win, bg=BG)
        box.pack(fill="both", expand=True, padx=18)
        lb = tk.Listbox(box, bg=PANEL, fg=TEXT, font=FONT_S, bd=0,
                        highlightthickness=0, activestyle="none",
                        selectbackground=PRIMARY, selectforeground=TEXT,
                        exportselection=False)
        sb = tk.Scrollbar(box, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for _, label in items:
            lb.insert("end", "  " + label)
        sel = 0
        for i, (val, _) in enumerate(items):
            if val == cur:
                sel = i
                break
        lb.selection_set(sel)
        lb.see(sel)

        def picked():
            try:
                i = lb.curselection()[0]
            except IndexError:
                return None
            return items[i][0]

        def do_preview(_evt=None):
            val = picked()
            if val is None:
                return
            if val == music.PICK_NONE:
                music.stop(fade_ms=150)
                return
            if val == music.PICK_RANDOM:
                music.preview(music._pick_random())
                return
            if val == "":
                music.preview(music.scene_track(scene))
                return
            music.preview(val)

        def do_apply(_evt=None):
            val = picked()
            if val is None:
                return "break"
            music.set_scene_choice(scene, val)
            self._music_refresh_row(scene)      # 设置窗里那行文案立刻跟着变
            if on_done:
                on_done()
            music.end_preview(self._music_scene())
            close()
            return "break"

        def do_apply_all(_evt=None):
            """三个场景一次设成同一首：不必来回切场景手动换歌。"""
            val = picked()
            if val is None:
                return "break"
            music.set_all_choices(val)
            self._music_refresh_rows()
            if on_done:
                on_done()
            music.end_preview(self._music_scene())
            close()
            return "break"

        def close():
            try:
                music.end_preview(self._music_scene())
            except Exception:                  # noqa: BLE001
                pass
            win.destroy()

        lb.bind("<Double-Button-1>", do_apply)
        lb.bind("<Return>", do_apply)

        btns = tk.Frame(win, bg=BG)
        btns.pack(pady=(10, 6))
        tk.Button(btns, text=i18n.t("music_preview"), bg=PANEL, fg=TEXT,
                  font=FONT_S, bd=0, padx=14, pady=6, cursor="hand2",
                  command=do_preview).pack(side="left", padx=4)
        tk.Button(btns, text=i18n.t("music_apply"), bg=PRIMARY, fg=TEXT,
                  font=FONT_S, bd=0, padx=18, pady=6, cursor="hand2",
                  command=do_apply).pack(side="left", padx=4)
        tk.Button(btns, text=i18n.t("music_apply_all"), bg=PRIMARY, fg=TEXT,
                  font=FONT_S, bd=0, padx=14, pady=6, cursor="hand2",
                  command=do_apply_all).pack(side="left", padx=4)
        tk.Button(btns, text=i18n.t("music_cancel"), bg=BTN, fg=TEXT,
                  font=FONT_S, bd=0, padx=14, pady=6, cursor="hand2",
                  command=close).pack(side="left", padx=4)
        tk.Label(win, text=i18n.t("music_fmt_hint") + "  " + i18n.t("music_tracks", n=len(lib)),
                 bg=BG, fg=DIM, font=FONT_S).pack(pady=(0, 10))
        win.protocol("WM_DELETE_WINDOW", close)
        win.bind("<Escape>", lambda e: close())
        return win

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
                     bg=BG, fg=GOLD, font=FONT).pack(pady=(10, 2))
            st = self._rank_state()
            if st:
                tk.Label(win, text=i18n.t("account_rank", tier=st["tier"],
                                          stars=self._stars_text(st["stars"])),
                         bg=BG, fg=ACCENT, font=FONT_S).pack(pady=(0, 8))
            else:
                tk.Frame(win, bg=BG, height=10).pack()

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
            tk.Button(row, text=i18n.t("account_logout"), bg=DANGER, fg=TEXT,
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
        tk.Button(row, text=i18n.t("account_login"), bg=PRIMARY, fg=TEXT,
                  font=FONT, bd=0, padx=14, pady=6, cursor="hand2",
                  command=try_login).pack(side="left", padx=8)
        tk.Button(row, text=i18n.t("account_register"), bg=SUCCESS, fg=TEXT,
                  font=FONT, bd=0, padx=14, pady=6, cursor="hand2",
                  command=try_register).pack(side="left", padx=8)

    # ---------------- 设置（分页） ----------------

    def _theme_controls(self, parent, on_change=None):
        """外观控件：配色方案色卡 + 主色色板 + 恢复默认。

        做成共用方法：主菜单设置窗、对局内设置窗都调它，避免两套 UI 漂移。
        色卡用**预设自己的颜色**画（不是当前主题的颜色）—— 否则七张卡片
        长得一模一样，玩家没法挑。
        """
        cur = theme.preset_name()
        cur_acc = (theme.accent_color() or "").lower()

        def pick(preset=None, accent=None):
            self._pick_theme(preset, accent)
            if on_change is not None:
                on_change()

        tk.Label(parent, text=i18n.t("theme_section"), bg=BG, fg=TEXT,
                 font=FONT_B).pack(anchor="w")
        tk.Label(parent, text=i18n.t("theme_hint"), bg=BG, fg=DIM,
                 font=FONT_S, wraplength=860, justify="left").pack(
            anchor="w", pady=(3, 12))

        grid = tk.Frame(parent, bg=BG)
        grid.pack(anchor="w")
        for i, key in enumerate(theme.PRESETS):
            pv = theme.preview(key)
            chosen = (key == cur)
            card = tk.Frame(grid, bg=pv["bg"], width=212, height=94,
                            cursor="hand2", highlightthickness=2,
                            highlightbackground=ACCENT if chosen else pv["border"])
            # 4 列 × 2 行：3 列会把 7 张卡排成 3 行，连同主色区一起把
            # 640px 的窗口顶爆（「恢复默认」被裁掉 —— 截图实测）。
            card.grid(row=i // 4, column=i % 4, padx=(0, 10), pady=(0, 10))
            card.pack_propagate(False)
            name = tk.Label(card, text=i18n.t("theme_p_" + key), bg=pv["bg"],
                            fg=pv["text"], font=(FONT_FAMILY, 11, "bold"))
            name.pack(anchor="w", padx=10, pady=(9, 3))
            strip = tk.Frame(card, bg=pv["bg"])
            strip.pack(anchor="w", padx=10)
            swatches = []
            for col in (pv["accent"], pv["panel"], pv["card"], pv["dim"]):
                sw = tk.Frame(strip, bg=col, width=26, height=16,
                              highlightthickness=1,
                              highlightbackground=pv["border"])
                sw.pack(side="left", padx=(0, 4))
                sw.pack_propagate(False)
                swatches.append(sw)
            if chosen:
                tk.Label(card, text="\u2713", bg=pv["bg"], fg=pv["accent"],
                         font=(FONT_FAMILY, 12, "bold")).place(
                    relx=1.0, x=-7, y=5, anchor="ne")
            for w in [card, name, strip] + swatches:
                w.bind("<Button-1>", lambda e, k=key: pick(k, None))
                bind_hover(w, amount=0.06)

        tk.Label(parent, text=i18n.t("theme_accent"), bg=BG, fg=TEXT,
                 font=FONT_B).pack(anchor="w", pady=(6, 6))
        acc_row = tk.Frame(parent, bg=BG)
        acc_row.pack(anchor="w")
        for key, col in theme.ACCENTS.items():
            chosen = (col.lower() == cur_acc)
            sw = tk.Frame(acc_row, bg=col, width=38, height=38, cursor="hand2",
                          highlightthickness=2,
                          highlightbackground=TEXT if chosen else BORDER)
            sw.pack(side="left", padx=(0, 8))
            sw.pack_propagate(False)
            if chosen:
                tk.Label(sw, text="\u2713", bg=col, fg=theme.best_fg(col),
                         font=(FONT_FAMILY, 12, "bold")).pack(expand=True)
            for w in [sw] + list(sw.winfo_children()):
                w.bind("<Button-1>",
                       lambda e, c=col: pick(None, c))
                bind_hover(w, amount=0.10)

        tk.Button(parent, text=i18n.t("theme_reset"), bg=BTN, fg=TEXT,
                  font=FONT_S, bd=0, padx=14, pady=6, cursor="hand2",
                  activebackground=BTN_HOVER, activeforeground=TEXT,
                  command=lambda: pick(theme.DEFAULT_PRESET, None)
                  ).pack(anchor="w", pady=(14, 0))

    def _pick_theme(self, preset=None, accent=None):
        """应用主题（并落盘），然后把所有已经打开的界面换成新配色。"""
        theme.apply(preset or theme.preset_name(), accent or None)
        theme.save(theme.preset_name(), theme.accent_color())
        theme.sync(globals())
        try:
            self.configure(bg=BG)
        except tk.TclError:
            return
        self._refresh_views_after_theme()

    def _refresh_views_after_theme(self):
        """换主题后刷新视图。

        - pygame 棋盘：颜色是**绘制时**读模块全局的，sync 之后下一帧就变；
        - 主菜单 / 大厅：控件颜色在创建时就固定了，只能重建；
        - 组卡 / 选国：同样重建（它们自己会判断 start_frame 是否存在）。
        """
        try:
            import kards_board
            theme.sync(vars(kards_board))
            board = getattr(self, "_pyboard", None)
            if board is not None and hasattr(board, "apply_theme"):
                board.apply_theme()
        except Exception:                                  # noqa: BLE001
            pass

        frame = getattr(self, "start_frame", None)
        try:
            if frame is None or not frame.winfo_exists():
                return
            if getattr(self, "_lobby_active", False):
                self._build_lobby()      # 内部会 destroy start_frame 并重建
            else:
                frame.destroy()
                self._build_start()
        except tk.TclError:
            pass

    def open_start_settings(self, tab="appearance"):
        """主界面设置窗：外观 / 声音 / 其它 三个分页。

        为什么分页：外观面板本身就有 7 套配色 + 8 个主色，竖着堆会顶到
        屏幕外（原窗口已经 700px 高，再加就没法看了）。
        """
        win = tk.Toplevel(self)
        win.role = "start_settings"
        win.title(i18n.t("settings_title"))
        win.configure(bg=BG)
        win.geometry("980x700")
        win.minsize(920, 620)
        win.transient(self)
        try:
            win.attributes("-topmost", True)
            win.after(200, lambda: win.attributes("-topmost", False))
        except tk.TclError:
            pass

        head = tk.Frame(win, bg=BG)
        head.pack(fill="x", padx=22, pady=(18, 8))
        tk.Label(head, text=i18n.t("settings_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(side="left")
        x_btn = tk.Button(head, text="\u2715", bg=BTN, fg=TEXT, font=FONT_S,
                          bd=0, padx=10, pady=3, cursor="hand2",
                          activebackground=BTN_HOVER, activeforeground=TEXT,
                          command=win.destroy)
        x_btn.pack(side="right")
        bind_hover(x_btn)

        tabs = ("appearance", "sound", "more")

        def tab_label(key):
            return {"appearance": i18n.t("settings_tab_look"),
                    "sound": i18n.t("settings_tab_sound"),
                    "more": i18n.t("settings_tab_more")}[key]

        state = {"tab": tab if tab in tabs else "appearance"}
        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=22)
        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=22, pady=(12, 16))

        tab_btns = {}

        def render():
            for w in body.winfo_children():
                w.destroy()
            for k, b in tab_btns.items():
                active = (k == state["tab"])
                b.configure(bg=ACCENT if active else PANEL,
                            fg=ACCENT_FG if active else DIM,
                            activebackground=ACCENT if active else PANEL)
            {"appearance": build_appearance,
             "sound": build_sound,
             "more": build_more}[state["tab"]]()

        def switch(key):
            state["tab"] = key
            render()

        for key in tabs:
            b = tk.Button(bar, text=tab_label(key), bg=PANEL, fg=DIM, font=FONT_S,
                          bd=0, padx=18, pady=8, cursor="hand2",
                          activeforeground=TEXT,
                          command=lambda k=key: switch(k))
            b.pack(side="left", padx=(0, 6))
            bind_hover(b)
            tab_btns[key] = b
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", padx=22, pady=(8, 0))

        def rebuild_self():
            """换主题后重开本窗口（控件颜色创建时固定，只能重建）。"""
            try:
                keep = state["tab"]
                win.destroy()
                self.open_start_settings(tab=keep)
            except tk.TclError:
                pass

        def build_appearance():
            self._theme_controls(body, on_change=rebuild_self)

        def build_sound():
            self._music_row(body)

        def build_more():
            def apply_lang():
                i18n.set_lang(i18n.get_lang())
                self.start_frame.destroy()
                self._build_start()
                win.destroy()
                self.open_start_settings(tab="more")

            self._lang_buttons(body, on_change=apply_lang)

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

            row = tk.Frame(body, bg=BG)
            row.pack(pady=(18, 0))
            for text, cmd, color in ((i18n.t("btn_check_update"), check_update, SUCCESS),
                                     (i18n.t("btn_help"), show_help, PRIMARY),
                                     (i18n.t("btn_keywords"), show_keywords, INFO),
                                     (i18n.t("btn_quit"), quit_app, BTN)):
                b = tk.Button(row, text=text, bg=color, fg=TEXT, font=FONT_B, bd=0,
                              padx=16, pady=8, cursor="hand2",
                              activebackground=theme.hover_of(color),
                              activeforeground=TEXT, command=cmd)
                b.pack(side="left", padx=5)
                bind_hover(b)

        render()

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

        # 完整性校验的说明行：整件事的重点是"玩家知道这次到底校验没校验"，
        # 所以单独一行常驻，而不是塞进随时会被刷新的 status 里。
        verify_lbl = tk.Label(win, text="", bg=BG, fg=DIM, font=FONT_S,
                              wraplength=390, justify="left")
        verify_lbl.pack(padx=16)

        bar_holder = tk.Frame(win, bg=BG)
        bar_holder.pack(fill="x", padx=16)
        bar = tk.Frame(bar_holder, bg=PANEL_ALT, height=10)
        bar.pack(fill="x")
        bar_fill = tk.Frame(bar, bg=SUCCESS, height=10)
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

        def set_verify(text, fg=DIM):
            if state["polling"]:
                try:
                    verify_lbl.configure(text=text, fg=fg)
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
                if task.checksum:
                    set_verify(i18n.t("update_verify_will"), DIM)
                else:
                    set_verify(i18n.t("update_verify_none"), GOLD)
                try:
                    notes_box.configure(state="normal")
                    notes_box.delete("1.0", "end")
                    notes_box.insert("1.0", (info.get("notes") or "").strip()[:4000])
                    notes_box.configure(state="disabled")
                except tk.TclError:
                    pass
                rebuild_buttons()
                tk.Button(btns, text=i18n.t("update_btn_do"), bg=SUCCESS, fg=TEXT,
                          font=FONT_B, bd=0, padx=16, pady=7, cursor="hand2",
                          command=do_download).pack(side="left", padx=5)
                tk.Button(btns, text=i18n.t("update_btn_open_page"), bg=PRIMARY,
                          fg=TEXT, font=FONT_S, bd=0, padx=12, pady=7, cursor="hand2",
                          command=open_page).pack(side="left", padx=5)
                tk.Button(btns, text=i18n.t("update_later_btn"), bg=BTN, fg=TEXT,
                          font=FONT_S, bd=0, padx=12, pady=7, cursor="hand2",
                          command=close).pack(side="left", padx=5)
                state["phase"] = "found"
            elif st == "no_update":
                set_status(i18n.t("update_none", cur=net_update.version_str(VERSION)), GREEN)
                if state.get("phase") != "no_update":
                    state["phase"] = "no_update"
                    rebuild_buttons()
                    tk.Button(btns, text=i18n.t("btn_close"), bg=BTN, fg=TEXT,
                              font=FONT_B, bd=0, padx=16, pady=7, cursor="hand2",
                              command=close).pack()
            elif st == "error":
                set_status(i18n.t("update_fail", err=task.message), RED)
                if state.get("phase") != "error":
                    state["phase"] = "error"
                    rebuild_buttons()
                    tk.Button(btns, text=i18n.t("btn_close"), bg=BTN, fg=TEXT,
                              font=FONT_B, bd=0, padx=16, pady=7, cursor="hand2",
                              command=close).pack()
            elif st in ("downloading", "verifying", "extracting"):
                pct = int(task.progress * 100)
                key = {"downloading": "update_downloading",
                       "verifying": "update_verifying",
                       "extracting": "update_extracting"}[st]
                set_status(i18n.t(key, done=pct))
                try:
                    bar_fill.place_configure(relwidth=max(0.0, min(1.0, task.progress)))
                except tk.TclError:
                    pass
                if state.get("phase") != "busy":
                    state["phase"] = "busy"
                    rebuild_buttons()
                    tk.Button(btns, text=i18n.t("update_btn_cancel"), bg=BTN,
                              fg=TEXT, font=FONT_S, bd=0, padx=12, pady=7,
                              cursor="hand2", command=close).pack()
            elif st == "done":
                set_status(i18n.t("update_ready", ver=net_update.version_str(VERSION)), GREEN)
                if task.verified:
                    set_verify(i18n.t("update_verify_ok"), GREEN)
                else:
                    set_verify(i18n.t("update_verify_skip"), GOLD)
                if not state.get("installed"):
                    state["installed"] = True
                    rebuild_buttons()
                    tk.Button(btns, text=i18n.t("update_restart_btn"), bg=SUCCESS,
                              fg=TEXT, font=FONT_B, bd=0, padx=16, pady=7,
                              cursor="hand2", command=do_restart).pack(side="left", padx=5)
                    tk.Button(btns, text=i18n.t("update_later_btn"), bg=BTN,
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
                tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=(18, 0))
            tk.Label(inner, text=i18n.t(gkey), bg=BG,
                     fg=MUTE if planned else GOLD,
                     font=FONT_B, anchor="w").pack(fill="x", pady=(12, 4))
            for name, desc in rows:
                row = tk.Frame(inner, bg=PANEL if not planned else BG_ALT)
                row.pack(fill="x", pady=1)
                tk.Label(row, text=name, bg=row["bg"], fg=DIM if planned else TEXT,
                         font=FONT_B, width=12, anchor="w",
                         padx=8, pady=4).pack(side="left")
                tk.Label(row, text=desc, bg=row["bg"], fg=DIM, font=FONT_S,
                         anchor="w", justify="left", wraplength=430,
                         padx=4, pady=4).pack(side="left", fill="x", expand=True)

        tk.Button(win, text=i18n.t("kw_close"), bg=PRIMARY, fg=TEXT,
                  font=FONT_B, bd=0, padx=20, pady=8, cursor="hand2",
                  command=win.destroy).pack(pady=12)

        # 鼠标滚轮：只在指针位于本窗口时生效
        def on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", on_wheel)
        win.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))
        return win

    def _lang_buttons(self, win, on_change):
        """设置窗中的语言切换行：三个语言按钮，当前语言置灰不可点"""
        tk.Label(win, text=i18n.t("settings_language"), bg=BG, fg=DIM,
                 font=FONT_S).pack(pady=(12, 4))
        row = tk.Frame(win, bg=BG)
        row.pack()
        for code in i18n.LANG_NAMES:
            cur = i18n.get_lang() == code
            tk.Button(row, text=i18n.LANG_NAMES[code],
                      bg=PRIMARY if cur else BTN,
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
        tk.Button(self.start_frame, text=i18n.t("btn_back"), bg=BTN, fg=TEXT,
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
                                       bg=BG_ALT, fg=TEXT, insertbackground=TEXT,
                                       relief="flat")
        self.srv_addr_entry.pack(side="left", padx=(4, 10), ipady=3)
        self.srv_btn = tk.Button(row, text=i18n.t("btn_srv_connect"), bg=SUCCESS,
                                 fg=TEXT, font=FONT_S, bd=0, padx=14, pady=5,
                                 cursor="hand2", command=self._lobby_connect)
        self.srv_btn.pack(side="left")
        # 「建立服务器」：本机一键起一个服务器（不用命令行）。
        # 只在具备条件时出现：有 kards_server.py 且没有被别的东西占用端口。
        self.srv_host_btn = tk.Button(row, text=i18n.t("btn_host_server"),
                                      bg=WARN, fg=TEXT, font=FONT_S, bd=0,
                                      padx=10, pady=5, cursor="hand2",
                                      command=self._lobby_host_server)
        if kards_host.can_host():
            self.srv_host_btn.pack(side="left", padx=(6, 0))
        tk.Label(box, text=i18n.t("srv_default_hint", addr=net.DEFAULT_SERVER),
                 bg=PANEL, fg=DIM, font=FONT_S).pack(anchor="w", padx=14, pady=(4, 0))
        self.srv_status = tk.Label(box, text="", bg=PANEL, fg=GOLD, font=FONT_S,
                                   anchor="w", justify="left", wraplength=290)
        self.srv_status.pack(anchor="w", padx=14, pady=(2, 4))
        # 公网地址行：「建立服务器」打通 UPnP 后把外网可连的地址放这儿。
        # 默认是空的（连别人服务器时不该出现）。
        self.srv_public_var = tk.StringVar(value="")
        self.srv_public_lbl = tk.Label(box, textvariable=self.srv_public_var, bg=PANEL,
                                       fg=GREEN, font=FONT_S, anchor="w",
                                       justify="left", wraplength=290)
        self.srv_public_lbl.pack(anchor="w", padx=14)
        # 公网操作区：复制地址 + 一键改公网。
        # 「一键」按钮**常驻**：玩家不必先点「建立服务器」再等映射，直接点它
        # 就能走完 开服 → 申请端口 → 把地址框换成公网地址 的全流程。
        self.srv_pub_btns = tk.Frame(box, bg=PANEL)
        self.srv_copy_btn = tk.Button(self.srv_pub_btns, text=i18n.t("btn_copy_addr"),
                                      bg=PANEL_ALT, fg=TEXT, font=FONT_S, bd=0,
                                      padx=10, pady=3, cursor="hand2",
                                      command=self._lobby_copy_addr)
        self.srv_pub_toggle = tk.Button(self.srv_pub_btns,
                                        text=i18n.t("btn_pub_onekey"),
                                        bg=PRIMARY, fg=TEXT, font=FONT_S, bd=0,
                                        padx=10, pady=3, cursor="hand2",
                                        command=self._lobby_pub_toggle)
        self.srv_pub_toggle.pack(side="left")
        self.srv_pub_btns.pack(anchor="w", padx=14, pady=(2, 6))
        self._pub_addr = ""          # 当前可复制的地址（公网优先，其次局域网）
        self._lobby_pub_btn_refresh()
        # 游客（未登录）时给一个显眼的登录入口：联机按钮此时是灰的，
        # 光靠状态栏一行小字用户找不到出路（产品规则：游客不能联机）
        self.srv_login_btn = tk.Button(box, text=i18n.t("btn_login_or_reg"),
                                       bg=PRIMARY, fg=TEXT, font=FONT_S, bd=0,
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
        self.match_btn = tk.Button(box, text=i18n.t("btn_quick_match"), bg=SUCCESS,
                                   fg=TEXT, font=FONT_B, bd=0, padx=16, pady=8,
                                   cursor="hand2", command=self._mp_quick_match)
        self.match_btn.pack(anchor="w", padx=14)
        self.room_btn = tk.Button(box, text=i18n.t("btn_create_room"), bg=PRIMARY,
                                  fg=TEXT, font=FONT_S, bd=0, padx=14, pady=6,
                                  cursor="hand2", command=self._mp_toggle_room)
        self.room_btn.pack(anchor="w", padx=14, pady=(8, 2))
        self.room_lbl = tk.Label(box, text=i18n.t("room_none"), bg=PANEL, fg=DIM,
                                 font=FONT_S, anchor="w", justify="left",
                                 wraplength=290)
        self.room_lbl.pack(anchor="w", padx=14)
        sep = tk.Frame(box, bg=BORDER, height=1)
        sep.pack(fill="x", padx=14, pady=8)
        row = tk.Frame(box, bg=PANEL)
        row.pack(anchor="w", padx=14, pady=(0, 12))
        tk.Label(row, text=i18n.t("label_join_code"), bg=PANEL, fg=DIM,
                 font=FONT_S).pack(side="left")
        self.join_code_var = tk.StringVar(value="")
        e = tk.Entry(row, textvariable=self.join_code_var, width=10,
                     bg=BG_ALT, fg=TEXT, insertbackground=TEXT, relief="flat")
        e.pack(side="left", padx=(4, 8), ipady=3)
        e.bind("<Return>", lambda ev: self._mp_join_by_code())
        self.join_code_btn = tk.Button(row, text=i18n.t("btn_join_code"), bg=BTN,
                                       fg=TEXT, font=FONT_S, bd=0, padx=12, pady=5,
                                       cursor="hand2", command=self._mp_join_by_code)
        self.join_code_btn.pack(side="left")

    # ---- 日志 ----

    def _lobby_build_log(self, parent):
        box = tk.Frame(parent, bg=PANEL, bd=1, relief="solid")
        box.pack(fill="both", expand=True, pady=(10, 0))
        tk.Label(box, text=i18n.t("lobby_log"), bg=PANEL, fg=TEXT,
                 font=FONT_B).pack(anchor="w", padx=14, pady=(10, 2))
        self.lobby_logbox = tk.Text(box, height=6, bg=BG_ALT, fg=TEXT,
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
                bg=DANGER if self.mp_matching else SUCCESS)
        if self.room_btn is not None and self.room_btn.winfo_exists():
            self.room_btn.configure(
                text=i18n.t("btn_leave_room") if self.mp_room_code
                else i18n.t("btn_create_room"),
                bg=DANGER if self.mp_room_code else PRIMARY)
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

        port_i = int(port) if port.isdigit() else 6000
        addr = kards_host.local_addr(port_i)
        # 跨局域网：后台让路由器开公网端口（不阻塞 UI），结果用主线程轮询取。
        # 先申请映射再决定"自己连哪儿" —— 本机服务器一旦起来，就该对外可用。
        self._lobby_public_start(port_i, addr)
        # 局域网的其他人要连过来，得知道这个地址；顺带提醒防火墙
        self._lobby_log(i18n.t("host_firewall_hint"))

        # ⚠ 「开服」不等于「把自己从当前大厅拽走」。
        # 玩家可能已经在别人的服务器上登录了（正在等人开局），这时点建立服务器
        # 只是想让**朋友们连这台机器**。旧代码无条件 `_lobby_connect()`，
        # 会先 `_close_server_link()` 清掉 mp_user，再连到本机的空账号库 →
        # resume 必然失败 → 弹登录框 = 用户报的「开服就退登」。
        # 已登录的人保持原连接，想切到本机服再点「连接」（那是明确的意图）。
        link = self.mp_link
        if (link is not None and getattr(link, "alive", False)
                and self._srv_ready and self.mp_user):
            if net.same_server(self._srv_addr, addr):
                self._lobby_log(i18n.t("host_keep_session",
                                       name=self.mp_user or ""))
                self._lobby_set_addr_text(addr)
            else:
                self._lobby_log(i18n.t("host_keep_current"))
            self._lobby_sync()
            return
        # 没登录 / 没连上 → 切到本机服务器（这是开服的本意）
        self._lobby_set_addr_text(addr)
        # ⚠ 不能固定等 700ms 就connect：打包版第一次启动服务器要解压/import
        # 模块，实测 2~5 秒。提前连必然失败，而失败会 `_close_server_link()`
        # 把已登录的玩家清成游客 —— 用户看到的就是「一开服就退登」。
        # 改成轮询等端口真正 listen 再连（最多 15 秒）。
        self._lobby_connect_when_ready(port_i)

    def _lobby_connect_when_ready(self, port, tries=0):
        """等本机服务器真正 listen 之后再连（开服专用）。"""
        if not self._lobby_active:
            return
        if kards_host.port_in_use(port=port):
            self._lobby_connect()
            return
        if tries >= 30:                     # 15 秒还没起来：放弃但不退登
            self._lobby_log(i18n.t("host_not_ready", port=port))
            self._lobby_sync()
            return
        self._schedule("_t_host", 500,
                       lambda: self._lobby_connect_when_ready(port, tries + 1))

    # ---- 跨局域网：公网地址 ----

    def _lobby_pub_btn_refresh(self):
        """刷新「一键改为公网」按钮的文案与可用性。

        状态只有四种，别再拆细（用户只看懂「能不能点、点了会怎样」）：
          · 正在申请端口       → 「正在打通公网…」+ 禁用
          · 已打通 + 地址是公网 → 「改回局域网」
          · 已打通 + 地址是内网 → 「一键改为公网」
          · 没打通             → 「一键改为公网」（点了会开服并重试）
        """
        box = getattr(self, "srv_pub_btns", None)
        btn = getattr(self, "srv_pub_toggle", None)
        copy_btn = getattr(self, "srv_copy_btn", None)
        if box is None or btn is None:
            return
        try:
            if not (box.winfo_exists() and btn.winfo_exists()):
                return
        except tk.TclError:
            return
        if kards_host.public_status().get("state") == "working":
            text, state, color = i18n.t("btn_pub_working"), "disabled", BORDER
        elif getattr(self, "_pub_ok_addr", ""):
            if getattr(self, "_pub_switched", False):
                text, state, color = i18n.t("btn_pub_back_lan"), "normal", WARN
            else:
                text, state, color = i18n.t("btn_pub_onekey"), "normal", SUCCESS
        else:
            text, state, color = i18n.t("btn_pub_onekey"), "normal", PRIMARY
        try:
            btn.configure(text=text, state=state, bg=color)
            # 「复制地址」只在真有地址可复制时露出来，别放一个点了没反应的按钮
            if copy_btn is not None and copy_btn.winfo_exists():
                if getattr(self, "_pub_addr", ""):
                    if not copy_btn.winfo_ismapped():
                        copy_btn.pack(side="left", padx=(0, 6))
                        # 复制按钮排到 toggle 左边
                        copy_btn.pack_configure(before=btn)
                else:
                    copy_btn.pack_forget()
        except tk.TclError:
            pass

    def _lobby_pub_toggle(self):
        """一键把大厅地址改成公网地址（再点一次改回局域网）。

        这是用户要求的「一键改动」：不要求玩家先点「建立服务器」、也不需要
        理解 UPnP —— 没打通就先把服务器拉起来并申请端口，打通后自动把地址
        框换成公网地址并复制到剪贴板。
        """
        # 已经打通 → 纯地址切换，不重连、不动登录态
        if getattr(self, "_pub_ok_addr", ""):
            lan = getattr(self, "_pub_lan", "") or kards_host.local_addr()
            if getattr(self, "_pub_switched", False):
                self._lobby_set_addr_text(lan)
                self._pub_switched = False
                self._lobby_log(i18n.t("pub_switch_lan", addr=lan))
            else:
                self._lobby_set_addr_text(self._pub_ok_addr)
                self._pub_switched = True
                self._lobby_log(i18n.t("pub_switch_ok", addr=self._pub_ok_addr))
                self._lobby_copy_text(self._pub_ok_addr)
            self._lobby_pub_btn_refresh()
            return

        # 还没打通 → 一键开服 + 申请端口，映射结果回来后再切地址
        self._pub_auto_switch = True
        self._lobby_log(i18n.t("pub_onekey_start"))
        self._lobby_pub_btn_refresh()
        self._lobby_host_server()

    def _lobby_set_addr_text(self, addr):
        """只改地址输入框（不影响当前连接与登录态）。"""
        var = getattr(self, "srv_addr_var", None)
        if var is not None and addr:
            var.set(addr)

    def _lobby_copy_text(self, addr):
        """把地址写进剪贴板（失败静默 —— 复制不了不该打断流程）。"""
        try:
            self.clipboard_clear()
            self.clipboard_append(addr)
            return True
        except tk.TclError:
            return False

    def _lobby_public_start(self, port, lan_addr):
        """开服后开始申请公网端口（后台线程），并起一个主线程轮询。"""
        self._pub_addr = ""
        self._pub_lan = lan_addr
        self._pub_ok_addr = ""
        try:
            if not self.srv_public_lbl.winfo_exists():
                return
            self.srv_public_var.set(i18n.t("pub_working"))
            self.srv_public_lbl.configure(fg=DIM)
        except (AttributeError, tk.TclError):
            return
        self._lobby_pub_btn_refresh()
        kards_host.map_public_async(port)
        self._schedule("_t_pub", 200, self._pub_poll)

    def _pub_poll(self):
        """主线程轮询映射结果（绝不能在后台线程里碰 tk 控件）。"""
        st = kards_host.public_status()
        if st.get("state") == "working":
            self._schedule("_t_pub", 250, self._pub_poll)
            return
        self._lobby_public_render(st)

    def _lobby_public_render(self, st):
        try:
            if not self.srv_public_lbl.winfo_exists():
                return
        except (AttributeError, tk.TclError):
            return
        lan = getattr(self, "_pub_lan", "") or kards_host.local_addr()
        port = st.get("port") or 6000
        local_ip = st.get("local_ip") or lan.split(":")[0]
        lines = [i18n.t("pub_lan", addr=lan)]
        fg = GREEN

        if st.get("ok"):
            # 地址要按**传进来的这份状态**拼，别回头读 kards_host 的全局量
            # —— 两者一旦不同步（刚完成映射、下一轮还没刷新），就会显示空地址。
            pub = f"{st.get('external_ip')}:{port}"
            key = "pub_direct" if st.get("direct") else "pub_ok"
            lines.insert(0, i18n.t(key, addr=pub))
            self._pub_addr = pub
            self._pub_ok_addr = pub
            # 一键模式下自动把地址框换成公网地址（用户不用再点第二次）
            if getattr(self, "_pub_auto_switch", False):
                self._pub_auto_switch = False
                self._lobby_set_addr_text(pub)
                self._pub_switched = True
                self._lobby_copy_text(pub)
                self._lobby_log(i18n.t("pub_switch_ok", addr=pub))
        elif st.get("cg_nat"):
            lines.append(i18n.t("pub_cgnat", ip=st.get("external_ip") or "?",
                                port=port))
            fg = GOLD
            self._pub_addr = lan
            self._pub_ok_addr = ""
        elif st.get("double_nat"):
            lines.append(i18n.t("pub_double_nat", ip=st.get("external_ip") or "?",
                                port=port, local=local_ip))
            fg = GOLD
            self._pub_addr = lan
            self._pub_ok_addr = ""
        else:
            err = st.get("error") or ""
            if err == "no_gateway":
                lines.append(i18n.t("pub_fail_nogw", port=port, ip=local_ip))
            else:
                lines.append(i18n.t("pub_fail", err=err or "?", port=port,
                                    ip=local_ip))
            fg = GOLD
            self._pub_addr = lan
            self._pub_ok_addr = ""

        if not self._pub_ok_addr and getattr(self, "_pub_auto_switch", False):
            # 一键模式失败：明确收尾，别让玩家以为还在等
            self._pub_auto_switch = False
            self._lobby_log(i18n.t("pub_onekey_fail"))

        try:
            self.srv_public_var.set("\n".join(lines))
            self.srv_public_lbl.configure(fg=fg)
        except tk.TclError:
            pass
        self._lobby_pub_btn_refresh()

    def _lobby_public_clear(self):
        """连的是别人的服务器 → 自己这台没有公网入口，把那一行清掉。"""
        self._pub_addr = ""
        self._pub_ok_addr = ""
        self._pub_switched = False
        self._pub_auto_switch = False
        try:
            if self.srv_public_lbl.winfo_exists():
                self.srv_public_var.set("")
        except (AttributeError, tk.TclError):
            pass
        self._lobby_pub_btn_refresh()

    def _lobby_copy_addr(self):
        addr = getattr(self, "_pub_addr", "") or (
            self.srv_addr_var.get() if getattr(self, "srv_addr_var", None) else "")
        if not addr:
            return
        if not self._lobby_copy_text(addr):
            return
        self._lobby_log(i18n.t("addr_copied", addr=addr))

    def _lobby_connect(self, retry=False):
        # 已经离开大厅（回主菜单 / 进对局）→ 不许再把大厅轮询挂回来。
        # 掉线自动重连用的是 after(1200)，如果玩家在这 1.2 秒内点了返回，
        # 回调照样会执行并 `_schedule("_t_lobby")`，于是定时器永远停不掉
        # （实测：回主菜单后 _t_lobby 非 None，控制台刷 invalid command name）。
        if not getattr(self, "_lobby_active", False):
            return
        if not retry:
            self._connect_retry = 0     # 玩家手动发起 → 重试额度重置
        parsed = net.parse_addr(self.srv_addr_var.get()
                                if getattr(self, "srv_addr_var", None) else self.mp_server_addr)
        if parsed is None:
            messagebox.showwarning(i18n.t("srv_warn_addr_title"), i18n.t("srv_warn_addr"))
            return
        host, port = parsed
        addr = f"{host}:{port}"
        # ⚠ 同一台服务器已经连着 → **绝不重连**。
        # 重连会 `_close_server_link()` 把 mp_user / 远程账号代理清掉，
        # 再靠 resume 找回；而 resume 只要超时一次（尤其跨公网），玩家就
        # 被弹回登录框 —— 这就是用户报的「开服 / 进服就退登」。
        # 地址写法可能不同（127.0.0.1 ↔ 局域网 ↔ 公网），same_server 会认。
        link = self.mp_link
        if (link is not None and getattr(link, "alive", False)
                and self._srv_ready and net.same_server(self._srv_addr, addr)):
            self.mp_server_addr = addr
            self._srv_error = ""
            self._lobby_log(i18n.t("srv_already_same", name=self.mp_user or ""))
            # 补订阅一次大厅快照：界面刚重建时服务器那边不会主动重推
            self._srv_send({"m": "lobby"})
            self._lobby_sync()
            if self._t_lobby is None:
                self._schedule("_t_lobby", 120, self._lobby_poll)
            return
        # 连的若是别人的服务器，本机就没有「公网入口」这回事，别留上次开服的字样
        if not net.is_self_host(host):
            self._lobby_public_clear()
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

    def _try_auto_reconnect(self, force=False):
        """意外掉线后自动重连一次。

        为什么要有：掉线后只弹「连接已断开」是把问题丢给玩家 —— 明明本地
        还存着 30 天免密令牌，直接再连一次就能无缝恢复。只在**没有**活跃
        链路、且仍在大厅时触发；每次掉线最多自动重连一次，避免服务器真挂了
        时无限重试刷屏。
        """
        if not force and getattr(self, "_reconnecting", 0) >= 1:
            return False
        if self.mp_link is not None or not self._lobby_active:
            return False
        self._reconnecting = getattr(self, "_reconnecting", 0) + 1
        self._lobby_log(i18n.t("srv_reconnecting"))
        # 用具名定时器（而不是裸 after）：玩家可能在 1.2 秒内回主菜单，
        # `_lobby_back()` 要能把它取消掉。
        self._schedule("_t_reconnect", 1200, self._lobby_connect)
        return True

    def _close_server_link(self):
        """断开并复位所有联机状态（回主菜单 / 重连前调用）

        ⚠ 必须在 close() **之前**给链路打上 intentional 标记：这是我们自己
        主动断的，不能算「连接已断开」去吓玩家（用户报过「天天说我连接
        已断开」—— 其中一部分就是重连前主动断开被当成意外掉线）。
        """
        link = self.mp_link
        self.mp_link = None
        if link is not None:
            try:
                link.intentional = True
                link.close()
            except Exception:
                pass
        account.set_remote(None)
        self.mp_user = None
        self.mp_matching = False
        self.mp_room_code = None
        self.mp_lobby_players = []
        self._srv_ready = False
        self._resume_retry = 0       # 新链路重新给一次免密重试机会

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
                # 连不上先自动重试两次再报错：服务器刚起来（打包版要解压）、
                # 或者玩家正在等 Wi-Fi/防火墙放行，都可能让第一次连接失败。
                # 旧代码一次失败就弹模态框，玩家已经登录的界面同时也被清成
                # 游客 —— 这就是「点连接就退登」的另一半原因。
                if getattr(self, "_connect_retry", 0) < 2:
                    self._connect_retry = getattr(self, "_connect_retry", 0) + 1
                    self._lobby_log(i18n.t("srv_retry_connect",
                                           n=self._connect_retry))
                    self._schedule("_t_retry", 900,
                                   lambda: self._lobby_connect(retry=True))
                    return
                self._lobby_sync()
                messagebox.showerror(i18n.t("srv_fail_hint").split("\n")[0],
                                     i18n.t("srv_fail_hint", err=res[1]))
            elif res:
                self.mp_link = res[0]
                self.mp_link.on_event = None
                self._srv_ready = True
                self._reconnecting = 0        # 连上了 → 下次掉线还能自动重连一次
                self._connect_retry = 0
                link = self.mp_link
                # 账号代理到服务器：能免密 resume 就直接进大厅
                account.set_remote(link, self._srv_addr)
                ok, who = account.connect()
                if ok:
                    self.mp_user = who
                    self._resume_retry = 0
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
                    # 链路还活着但免密登录没成功，有两种情况：
                    #   ① 服务器明确拒绝（session 已被清）→ 必须重新登录；
                    #   ② 这次只是超时/抖动（令牌还在）→ 直接弹登录框就是
                    #      「退登」。原地重试一次，通常就好了。
                    if self._resume_retry < 1 and account.has_session_token():
                        self._resume_retry += 1
                        self._lobby_log(i18n.t("srv_resume_retry"))
                        ok2, who2 = account.connect()
                        if ok2:
                            self.mp_user = who2
                            self._resume_retry = 0
                            self._apply_account(who2)
                            self._lobby_log(i18n.t("srv_connected",
                                                   addr=self._srv_addr, name=who2))
                            self._srv_send({"m": "lobby"})
                            self._schedule("_t_lobby", 120, self._lobby_poll)
                            return
                    # ③ 连的是**本机服务器**（自己开的服）→ 免密接管。
                    # 账号本来就存在这台机器上，没有任何理由因为「换了个
                    # 服务器实例」就要求玩家重新输密码（用户报的「开服退登」）。
                    # 服务器端只放行本机来源，局域网其他玩家仍要正常登录。
                    parsed = net.parse_addr(self._srv_addr or "")
                    if parsed and net.is_self_host(parsed[0]):
                        cand = self.account or account.session_name()
                        if cand and account.adopt_local(cand):
                            self.mp_user = cand
                            self._resume_retry = 0
                            self._apply_account(cand)
                            self._lobby_log(i18n.t("srv_adopt_ok", name=cand))
                            self._srv_send({"m": "lobby"})
                            self._schedule("_t_lobby", 120, self._lobby_poll)
                            return
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
        # 连接断了：复位大厅状态。
        # ⚠ 主动 disconnect（intentional）不算掉线 —— 那是我方在重连/回菜单，
        # 提示"连接已断开"只会误导玩家。
        if (not getattr(link, "alive", False)
                and not getattr(link, "intentional", False)
                and self._srv_ready):
            self._srv_ready = False
            self.mp_link = None
            self.mp_matching = False
            self.mp_room_code = None
            self.mp_lobby_players = []
            self._lobby_log(i18n.t("log_srv_down"))
            if self.game is not None:
                self._mp_teardown_game()
            self._lobby_sync()
            # 别只报错：有免密令牌就原地重连一次，玩家不会被平白踢回菜单
            self._try_auto_reconnect()

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
            if self.mp_role is not None:
                # 准备阶段：对手已经走了，别再傻等（否则永远卡在「等待对手准备」）
                self._mp_route_in_game(msg)
                return
            self._lobby_log(i18n.t("log_peer_left"))
        elif m == "kick":
            # 被服务器踢掉（同一账号在别处登录）。**不能**自动重连：
            # 重连会拿同一账号把对面又踢下线，两边互相踢 = 无限刷
            # 「连接已断开」。这里必须明确停下来让玩家自己处理。
            self._kicked = True
            self.mp_user = None
            self._lobby_log(i18n.t("log_kicked"))
            if self.mp_role is not None:
                self._mp_cleanup_to_menu()      # 准备阶段被踢：直接退出准备界面
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
            rk = p.get("rank") or {}
            if rk.get("tier"):
                tk.Label(row, text=i18n.t("player_rank", tier=rk["tier"]),
                         bg=PANEL, fg=ACCENT, font=FONT_S
                         ).pack(side="left", padx=(8, 0))
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
        self._cancel_timer("_t_pub")         # 公网映射轮询也停（控件马上销毁）
        self._cancel_timer("_t_reconnect")   # 在途的自动重连不许再进大厅
        self._cancel_timer("_t_retry")       # 在途的连接重试同上
        self._cancel_timer("_t_host")        # 等端口的轮询同上
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
                 font=(FONT_FAMILY, 20, "bold")).pack(anchor="w")
        tk.Label(left_t, text=f"总部卡：{hq.name}（{hq.hp} HP）｜{hq.perk_desc}｜"
                              f"可用：{nation} + 盟国（意大利/法国/芬兰/波兰/澳新军团）",
                 bg=BG, fg=DIM, font=FONT_S).pack(anchor="w")
        right_t = tk.Frame(top, bg=BG)
        right_t.pack(side="right")
        self.deck_count_lbl = tk.Label(right_t, text="", bg=BG, fg=GOLD,
                                       font=(FONT_FAMILY, 16, "bold"))
        self.deck_count_lbl.pack(side="left", padx=10)
        self.ally_count_lbl = tk.Label(right_t, text="", bg=BG, fg=DIM, font=FONT_S)
        self.ally_count_lbl.pack(side="left", padx=10)
        tk.Button(right_t, text=i18n.t("btn_import"), bg=INFO, fg=TEXT, font=FONT_S,
                  bd=0, padx=12, pady=6, cursor="hand2",
                  command=self.on_import_deck).pack(side="left", padx=4)
        tk.Button(right_t, text=i18n.t("btn_save"), bg=WARN, fg=TEXT, font=FONT_S,
                  bd=0, padx=12, pady=6, cursor="hand2",
                  command=self.on_save_deck).pack(side="left", padx=4)
        tk.Button(right_t, text=i18n.t("btn_load"), bg=BTN, fg=TEXT, font=FONT_S,
                  bd=0, padx=12, pady=6, cursor="hand2",
                  command=self.on_load_deck).pack(side="left", padx=4)
        tk.Button(right_t, text=i18n.t("btn_recommend"), bg=PRIMARY, fg=TEXT, font=FONT_S,
                  bd=0, padx=12, pady=6, cursor="hand2",
                  command=self._auto_fill).pack(side="left", padx=4)
        tk.Button(right_t, text=i18n.t("btn_clear"), bg=BTN, fg=TEXT, font=FONT_S,
                  bd=0, padx=12, pady=6, cursor="hand2",
                  command=lambda: self._auto_fill(clear=True)).pack(side="left", padx=4)
        self.start_btn = tk.Button(
            right_t, text=i18n.t("btn_start_mp") if mp else i18n.t("btn_start_sp"),
            state="disabled",
            bg=SUCCESS, fg=TEXT, font=FONT_B, bd=0,
            padx=20, pady=8, cursor="hand2",
            activebackground=SUCCESS_HOVER,
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
            full = n >= core.max_copies(c)      # 带满了（传说卡带 1 张就满）
            row = tk.Label(self.avail_inner, bg=CARD_BG if n else BG,
                           fg=DIM if full else (GOLD if n else TEXT),
                           font=FONT_S, anchor="w", padx=10, pady=4,
                           text=self._card_row_text(c) + i18n.t("copies", n=n, max=core.max_copies(c)))
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
        if n >= core.max_copies(card):
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
        """按推荐思路补满：低费加权，约 33 张单位 + 6 张指令/反制

        ⚠ clear=True 必须**清空后就返回**。历史 bug：先 `deck_counts = {}`
        紧接着又跑下面的 while 填满 → 「清空」点下去等于「推荐卡组」，
        玩家永远清不掉卡组（用户实测报障）。
        """
        if clear:
            self.deck_counts = {}
            self._builder_refresh()
            return
        pool = core.allowed_cards(self.deck_nation, self.db)
        weights = [core.COST_WEIGHT.get(c.cost, 1) for c in pool]
        guard = 0
        while self._deck_total() < core.DECK_SIZE and guard < 100000:
            guard += 1
            c = random.choices(pool, weights=weights, k=1)[0]
            if self.deck_counts.get(c.name, 0) >= core.max_copies(c):
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
            # parse_deck_text 已经按稀有度截过；这里再走一遍 clamp_counts 是保险，
            # 免得以后解析逻辑改动时漏掉上限。
            self.deck_counts = core.clamp_counts(counts, self.db)[0]
            win.destroy()
            self._builder_refresh()
            msg = i18n.t("import_result", n=sum(counts.values()), m=self._deck_total())
            if unmatched:
                msg += i18n.t("import_unmatched", k=len(unmatched),
                              samples="；".join(unmatched[:3]))
            messagebox.showinfo(i18n.t("import_result_title"), msg)

        tk.Button(win, text=i18n.t("btn_import_go"), bg=SUCCESS, fg=TEXT, font=FONT_B, bd=0,
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
            tk.Button(win, text=i18n.t("btn_close"), bg=BTN, fg=TEXT, font=FONT_S, bd=0,
                      padx=14, pady=6, cursor="hand2",
                      command=win.destroy).pack(pady=10)
            return

        def do_load(nm):
            counts, _ = core.load_deck_counts(nm, self.db)
            win.destroy()
            if counts is None:
                messagebox.showwarning(i18n.t("btn_load"), i18n.t("load_missing"))
                return
            counts, trimmed = core.clamp_counts(counts, self.db)
            self.deck_counts = dict(counts)
            self._builder_refresh()
            msg = i18n.t("load_ok", name=nm, n=self._deck_total(), size=core.DECK_SIZE)
            if trimmed:
                # 旧存档是按"单卡一律 3 张"存的，稀有度上限上线后传说/史诗 会超标。
                # 不提示的话玩家只看到张数变少、开始按钮变灰，不知道为什么。
                items = i18n.t("load_trimmed_sep").join(
                    f"{n} ×{old}→×{new}" for n, old, new in trimmed[:5])
                if len(trimmed) > 5:
                    items += i18n.t("load_trimmed_more", k=len(trimmed) - 5)
                msg += "\n\n" + i18n.t("load_trimmed", items=items)
            messagebox.showinfo(i18n.t("btn_load"), msg)

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
        # ⚠ 绝不能在这里把 mp_opp 清成 None：对手可能**先于我方**点了准备，
        # 他的 ready 已经被 _mp_prep_watch / _lobby_drain_events 收进 mp_opp。
        # 清掉之后对手不会重发 ready，主机就永远等不到"对手已就绪"，
        # 双方一起卡在「等待对手准备」——典型症状就是"两边都准备了却开不了"。
        self._mp_me_ready = True
        self.mp_link.send({"m": "ready", "nation": self.deck_nation,
                           "deck": self.mp_my_deck})
        self._lobby_log(i18n.t("mp_log_ready_sent"))
        if self.mp_opp:                      # 对手早就准备好了：主机立刻可以发种子
            self._lobby_log(i18n.t("mp_log_opp_ready",
                                   nation=self.mp_opp.get("nation", "?"),
                                   n=len(self.mp_opp.get("deck") or [])))
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
                    # ⚠ 不在这里直接开局：对手的 ready 可能还没到（尤其是我方
                    # "后点准备"时），此时 opp 为空会被误判成"对手卡组数量异常"。
                    # 先暂存种子，等 ready 落地后再开局。
                    self._mp_pending_seed = m.get("seed", 0)
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
        if (self.mp_role == "client" and self._mp_pending_seed is not None
                and self.mp_opp is not None):
            seed, self._mp_pending_seed = self._mp_pending_seed, None
            self._mp_launch(seed)
            return
        if self.mp_role == "host" and self.mp_opp is not None and self._mp_me_ready:
            seed = random.SystemRandom().randrange(10 ** 9)
            self.mp_link.send({"m": "seed", "seed": seed})
            self._lobby_log(i18n.t("mp_log_seed_host"))
            self._mp_launch(seed)
            return
        self._schedule("_t_hello", 200, self._mp_poll_hello)

    def _mp_launch(self, seed):
        """双方用同一种子同步开局：先手随机、发牌一致"""
        self._mp_pending_seed = None
        if self.mp_role == "client":
            self._lobby_log(i18n.t("mp_log_seed_client"))
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
            messagebox.showerror(i18n.t("mp_title"),
                                 i18n.t("mp_bad_deck", n=len(opp_deck),
                                        need=core.DECK_SIZE))
            self._mp_cleanup_to_menu()
            return
        # ⚠ 必须等上面所有提前 return 走完再激活：否则视图方法已被实例
        # 覆盖，却没走到 _run_pyboard() 的还原逻辑 → 一直留在 pygame 视图。
        # 对战界面只有 pygame 一种；激活失败（缺 pygame）直接不开局。
        if self._activate_pyboard() is None:
            messagebox.showerror(i18n.t("msg_error"), i18n.t("err_need_pygame"))
            self._mp_cleanup_to_menu()
            return
        random.seed(seed)
        foe_name = self.mp_opp_name or f"对手·{opp.get('nation', '?')}"
        me = core.Player("你", self.deck_nation, my_deck)
        foe = core.Player(foe_name, opp.get("nation", "德国"), opp_deck)
        self.game = GUIGame(me, foe, self.add_log, self.on_game_event)
        self._game_online = True        # 联机对局 → 结算段位
        self._music_play("battle")
        for attr in ("start_frame", "builder_frame"):
            fr = getattr(self, attr, None)
            if fr is not None and fr.winfo_exists():
                fr.destroy()
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
        self._run_pyboard()       # 阻塞至对局结束（期间泵 Tk 事件跑网络轮询）
        return

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
            if getattr(link, "intentional", False):
                return                    # 我方主动断的（重连/回菜单），不是掉线
            self._mp_disconnected()
            return
        self._schedule("_t_net", 80, self._mp_poll_net)

    def _mp_route_in_game(self, msg):
        """中转消息路由：对局中交给 _mp_handle；准备阶段在此落地 ready/seed

        ⚠ 准备阶段（game is None）**必须**处理 ready/seed：`_lobby_drain_events()`
        会把 inbox 里的消息全部喂给本方法，若这里只认对局状态，双方点完准备
        后对手的 ready 会被静默吞掉（主机永远等不到对手准备、永远不发种子）
        → 两边一起卡在「等待对手准备」。用户实测踩过。
        """
        if self.game is not None:
            self._mp_handle(msg)
            return
        m = msg.get("m")
        if m == "ready":
            first = self.mp_opp is None
            self.mp_opp = msg
            if first:
                self._lobby_log(i18n.t("mp_log_opp_ready",
                                       nation=msg.get("nation", "?"),
                                       n=len(msg.get("deck") or [])))
        elif m == "seed" and self.mp_role == "client":
            # 同上：种子到了但对手 ready 可能还在路上，先存着
            self._mp_pending_seed = msg.get("seed", 0)
        elif m in ("peer_left", "kick"):
            messagebox.showerror(i18n.t("mp_title"), i18n.t("mp_peer_left_prep"))
            self._mp_cleanup_to_menu()
        elif m == "concede":
            self._mp_cleanup_to_menu()
        if (self.mp_role == "client" and self._mp_pending_seed is not None
                and self.mp_opp is not None):
            seed, self._mp_pending_seed = self._mp_pending_seed, None
            self._mp_launch(seed)

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
            # 记录投降方 = 对手，结算文案走「敌方举旗投降」
            g.conceded = g.players[1]
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
        """服务器连接意外断开：对局中判负回菜单，否则只在大厅里提示一次。

        ⚠ 同一局链路只能提示一次（_dead_notified），否则每个轮询 tick 都会
        弹一个窗，玩家会看到满屏「连接已断开」（用户报过）。
        """
        if getattr(self, "_dead_notified", False):
            return
        self._dead_notified = True
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
            # 对局中掉线：直接写进日志并结算，不再叠一个模态弹窗
            # （结算画面已经说明了结果，弹窗只会多拦一次点击）
            self.add_log("  ⚠ 与服务器的连接已断开！")
            self._mp_game_over = True
            self.finish(winner=self.game.players[0])
        else:
            self.add_log("  ⚠ 与服务器的连接已断开！")
            self._try_auto_reconnect()

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
        self._mp_me_ready = False
        self._mp_pending_seed = None
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
        # 对战界面只有 pygame 一种（经典 tkinter 界面已删除）。必须先激活：
        # 开局日志要进棋盘日志面板。激活失败说明 pygame 缺失/装坏 —— 直接
        # 不开局并明确报错，好过开局后面对一个没有视图的控制器。
        if self._activate_pyboard() is None:
            messagebox.showerror(i18n.t("msg_error"), i18n.t("err_need_pygame"))
            return
        p1 = core.Player("你", nation, deck if deck is not None else core.build_deck(nation, self.db))
        p2 = core.Player("AI", ai_nation, core.build_deck(ai_nation, self.db))
        self.game = GUIGame(p1, p2, self.add_log, self.on_game_event)
        self._game_online = False       # 人机练习 → 不计段位
        self._music_play("battle")
        if hasattr(self, "start_frame") and self.start_frame.winfo_exists():
            self.start_frame.destroy()
        if hasattr(self, "builder_frame") and self.builder_frame.winfo_exists():
            self.builder_frame.destroy()

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
        self._run_pyboard()       # 阻塞至对局结束（期间泵 Tk 事件）

    # ---------------- 主界面布局 ----------------
    def toggle_speed(self):
        self.fast_ai = not self.fast_ai
        self.ai_step_ms = 300 if self.fast_ai else 850
        # ⚠ pygame 对战界面下没有 speed_btn 控件（_build_main 不执行），
        # 直接 configure 会 AttributeError → 点「加速」按钮当场闪退。
        # pygame 侧每帧从 app.fast_ai 读状态自己画，无需通知。
        btn = getattr(self, "speed_btn", None)
        if btn is not None and btn.winfo_exists():
            btn.configure(text=i18n.t("btn_fast") if self.fast_ai
                          else i18n.t("btn_slow"))

    # ---------------- 渲染 ----------------
    # ---------------- 拖拽操作 ----------------
    # ---- 拖拽：幽灵卡直接挂主窗口 ----
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
                self.add_log(i18n.t("log_need_frontline"))
            else:
                self.add_log(i18n.t("log_guard_blocked"))
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

    # ---------------- pygame 对战视图（混合架构） ----------------
    # tkinter 管主菜单/大厅/组卡/账号；对战界面可切换为 pygame 渲染
    # （kards_board.py）。动画/拖拽走补间主循环，卡面支持图片资产，
    # 为牌桌特效与音效铺路。经典 tkinter 界面保留为回退。

    _PY_VIEW_ATTRS = ("refresh", "add_log", "show_banner", "float_text",
                      "flash_widget", "_shake_widget", "_wcenter", "_anim_entry",
                      "_anim_move", "_anim_attack", "shake", "show_end_animation")

    # ---------------- 视图兜底 ----------------
    # 经典 tkinter 对战界面已删除：下列方法正常由 _activate_pyboard() 用
    # pygame 棋盘的实现做**实例覆盖**，对局期间不会走到这里。保留类级兜底
    # 是为了主菜单/大厅阶段的偶发调用（比如断线提示路径上的 refresh /
    # show_banner）不再 AttributeError —— 没有对战视图时，唯一正确的动作
    # 就是安静地什么都不画。

    def refresh(self):
        b = self._pyboard
        if b is not None:
            b.refresh()

    def show_banner(self, text, color=None, ms=900):
        b = self._pyboard
        if b is not None:
            b.show_banner(text, color, ms)

    def float_text(self, anchor, text, color, ms=900):
        b = self._pyboard
        if b is not None:
            b.float_text(anchor, text, color, ms)

    def flash_widget(self, ref, color=None, times=3, interval=110):
        # 默认值不能写成 color=RED —— 默认参数在 def 时就绑死了，换主题后
        # 仍然闪旧色。这里在调用时取当前的 RED。
        color = color or RED
        b = self._pyboard
        if b is not None:
            b.flash_widget(ref, color, times, interval)

    def shake(self):
        b = self._pyboard
        if b is not None:
            b.shake_screen()

    def _shake_widget(self, ref):
        b = self._pyboard
        if b is not None:
            b._shake_widget(ref)

    def _wcenter(self, ref):
        b = self._pyboard
        return b.wcenter(ref) if b is not None else None

    def _anim_entry(self, u):
        b = self._pyboard
        if b is not None:
            b.anim_entry(u)

    def _anim_move(self, u, on_done=None):
        b = self._pyboard
        if b is not None:
            b.anim_move(u, on_done=on_done)
        elif on_done is not None:
            on_done()          # 无视图也要解锁输入，否则对局卡死

    def _anim_attack(self, att, tgt_ref, on_done=None):
        b = self._pyboard
        if b is not None:
            b.anim_attack(att, tgt_ref, on_done=on_done)
        elif on_done is not None:
            on_done()

    def show_end_animation(self, won, on_done=None, nation=None, rank_line=""):
        b = self._pyboard
        if b is not None:
            b.show_end_animation(won, on_done=on_done, nation=nation,
                                 rank_line=rank_line)
        elif on_done is not None:
            on_done()          # 没有结算动画可放，直接收尾回菜单

    def _activate_pyboard(self):
        """把视图方法切到 pygame 棋盘（实例属性覆盖类方法，back 时删除即还原）。

        控制器（AI 步进/联机回放/on_game_event）拿到的 unit_widgets /
        hq_widget 是棋盘的 Ref 替身 —— 有 winfo_exists()，语义与控件一致，
        所以这些代码零改动。

        返回棋盘对象；**失败返回 None**（pygame 缺失/装坏时，调用方不开局）。
        """
        try:
            import kards_board
        except Exception as exc:                      # noqa: BLE001
            self.add_log(f"[界面] pygame 对战界面不可用：{exc}")
            return None
        b = kards_board.PygameBoard(self)
        self._pyboard = b
        self.refresh = b.refresh
        # ⚠ add_log 必须也接过去：pygame 模式下 _build_main() 不执行，
        # self.logbox 不存在，原 add_log 会静默丢弃 → 棋盘日志面板永远空。
        self.add_log = b.add_log
        self.show_banner = b.show_banner
        self.float_text = b.float_text
        self.flash_widget = b.flash_widget
        self._shake_widget = b._shake_widget
        self._wcenter = b.wcenter
        self._anim_entry = b.anim_entry
        self._anim_move = b.anim_move
        self._anim_attack = b.anim_attack
        self.shake = b.shake_screen
        self.show_end_animation = b.show_end_animation
        self.unit_widgets = b.unit_refs
        self.enemy_widgets = b.enemy_refs
        self.hq_widget = b.hq_ref
        self.my_hq_widget = b.my_hq_ref        # 结算爆炸要用（我方总部也要炸）
        self.pending_flash = b.pending_flash
        return b

    def _deactivate_pyboard(self):
        b = self._pyboard
        self._pyboard = None
        if b is not None:
            for a in self._PY_VIEW_ATTRS:
                self.__dict__.pop(a, None)      # 撤掉实例覆盖 → 类方法还原
            self.unit_widgets = {}
            self.enemy_widgets = []
            self.hq_widget = None
            self.my_hq_widget = None
            self.pending_flash = []
        return b

    def _run_pyboard(self):
        """阻塞跑 pygame 主循环；每帧泵 Tk 事件让 after 定时器（AI 步进/
        联机轮询）照常触发。结束后按玩家选择决定是否退出程序。"""
        b = self._pyboard
        try:
            b.start_intro()           # 开场动画：两军对冲（点击可跳过）
            b.run(pump=self.update)
        finally:
            self._deactivate_pyboard()
        if b.result == "quit":
            self.destroy()

    def pyboard_intent(self, act):
        """pygame 棋盘 → 控制器意图路由。

        联机语义与 tkinter 拖拽完全一致（同一批 _act_* / _attack_* 方法，
        _mp_send_act 由它们内部触发）。
        """
        g = self.game
        if g is None or self.busy:
            return
        me = g.players[0]
        k = act.get("k")
        if k == "play":
            self._act_play(act.get("idx", -1))
        elif k == "move":
            u = next((u for u in me.board if u.slot == act.get("slot")), None)
            if u is not None:
                self._act_move(u, act.get("pos", "前线"))
        elif k == "attack":
            u = next((u for u in me.board if u.slot == act.get("slot")), None)
            tgt = next((u for u in g.players[1].board
                        if u.slot == act.get("tslot")), None)
            if u is not None and tgt is not None:
                self._attack_unit(u, tgt)
        elif k == "hq":
            u = next((u for u in me.board if u.slot == act.get("slot")), None)
            if u is not None:
                self._attack_hq(u)
        elif k == "end":
            self.on_end_turn()
        elif k == "concede":
            self.add_log(i18n.t("log_surrender"))
            if self.mp_link is not None:
                self.mp_link.send({"m": "concede"})
            # 记录投降方：结算动画靠它把文案区分为「举旗投降」而非「总部沦陷」
            g.conceded = g.players[0]
            self.finish(winner=g.players[1])
        elif k == "leave":
            self.back_to_menu()
        elif k == "speed":
            self.toggle_speed()

    def _act_play(self, idx):
        """打出第 idx 张手牌（pygame 意图 / tkinter 拖拽共用；含联机转发）"""
        g = self.game
        if g is None or self.busy:
            return
        me = g.players[0]
        if idx < 0 or idx >= len(me.hand):
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

    def _act_move(self, unit, dest):
        """机动单位到 前线/后方（pygame 意图 / tkinter 拖拽共用；含联机转发）"""
        g = self.game
        if g is None or self.busy or unit not in g.players[0].board:
            return
        moved = g.move_unit(unit, dest)
        if moved and self.mp_link is not None:
            self._mp_send_act({"k": "move", "s": unit.slot, "p": dest})
        self.cleanup_dead()
        if moved and self.anim_enabled:
            self.busy = True
            self._anim_move(unit, on_done=self._refresh_unlock)
        elif self.game:
            self.refresh()

    # ---------------- 动画 ----------------
    def _guard(self):
        return self.busy or self.game is None

    # ---------------- 战术动画：部署入场 / 行军 / 进攻冲刺 ----------------
    UNIT_ICON = {"步兵": "🚶", "坦克": "🚜", "战斗机": "✈", "轰炸机": "🛩", "炮兵": "💣"}

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
                self.float_text(w, "✖", TEXT)
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
    def open_theme_dialog(self):
        """独立的外观窗（对局中也能开：棋盘会实时换色，不必退出对局）。"""
        win = tk.Toplevel(self)
        win.role = "theme"
        win.title(i18n.t("theme_section"))
        win.configure(bg=BG)
        win.geometry("800x580")
        win.transient(self)
        head = tk.Frame(win, bg=BG)
        head.pack(fill="x", padx=22, pady=(18, 6))
        tk.Label(head, text=i18n.t("theme_section"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(side="left")
        x_btn = tk.Button(head, text="\u2715", bg=BTN, fg=TEXT, font=FONT_S,
                          bd=0, padx=10, pady=3, cursor="hand2",
                          activebackground=BTN_HOVER, activeforeground=TEXT,
                          command=win.destroy)
        x_btn.pack(side="right")
        bind_hover(x_btn)
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", padx=22, pady=(6, 12))
        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=22)

        def reload():
            try:
                win.destroy()
                self.open_theme_dialog()
            except tk.TclError:
                pass

        self._theme_controls(body, on_change=reload)

    def open_settings(self):
        win = tk.Toplevel(self)
        win.role = "ingame_settings"
        win.title(i18n.t("settings_title"))
        win.configure(bg=BG)
        win.geometry("360x720")
        win.transient(self)
        tk.Label(win, text=i18n.t("settings_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(16, 6))
        # 对局中切语言：偏好立即保存，界面文本随下次界面重建生效
        self._lang_buttons(win, on_change=win.destroy)
        self._music_row(win)

        def surrender():
            if messagebox.askyesno(i18n.t("surrender_title"), i18n.t("surrender_confirm")):
                win.destroy()
                self.add_log(i18n.t("log_surrender"))
                if self.mp_link is not None:
                    self.mp_link.send({"m": "concede"})
                # 记录投降方（结算文案要区分「举旗投降」与「总部沦陷」）
                if self.game is not None:
                    self.game.conceded = self.game.players[0]
                    self.finish(winner=self.game.players[1])
                else:
                    self.finish()

        def to_menu():
            if messagebox.askyesno(i18n.t("to_menu_title"), i18n.t("to_menu_confirm")):
                win.destroy()
                self.back_to_menu()

        def keywords():
            self.open_keyword_guide()

        def theme_dialog():
            # 先关掉设置窗：换主题后它是旧配色，留着会和新棋盘"撞色"
            win.destroy()
            self.open_theme_dialog()

        def quit_app():
            if messagebox.askyesno(i18n.t("quit_title"), i18n.t("quit_safe_confirm")):
                win.destroy()
                self.destroy()

        for text, cmd, color in ((i18n.t("btn_theme"), theme_dialog, INFO),
                                 (i18n.t("btn_keywords"), keywords, INFO),
                                 (i18n.t("btn_surrender"), surrender, DANGER),
                                 (i18n.t("btn_to_menu"), to_menu, PRIMARY),
                                 (i18n.t("btn_quit"), quit_app, BTN)):
            b = tk.Button(win, text=text, bg=color, fg=TEXT, font=FONT_B, bd=0,
                          padx=18, pady=8, cursor="hand2",
                          activebackground=theme.hover_of(color),
                          activeforeground=TEXT, command=cmd)
            b.pack(pady=5)
            bind_hover(b)

    def on_esc(self, event=None):
        """Esc：对局中安全退出到主菜单；主菜单则退出游戏

        ⚠ pygame 对战界面下必须直接放行、交给棋盘自己处理 —— 棋盘用 Esc
        开关暂停菜单，这里再弹一次 tkinter 确认框就是「一次按键两个反应」
        （用户报的「按键绑错」），而且确认后会从 pygame 主循环内部把棋盘拆掉，
        紧接着 _run_pyboard 又去还原视图 → 闪退。
        """
        if self._pyboard is not None:
            return
        if self.game is not None:
            if messagebox.askyesno(i18n.t("leave_title"), i18n.t("leave_confirm")):
                self.back_to_menu()
        else:
            if messagebox.askyesno(i18n.t("quit_title"), i18n.t("quit_confirm")):
                self.destroy()

    def on_f1(self, event=None):
        """F1：随时打开关键词说明（对局中也能查）

        pygame 窗口盖在 Tk 之上，弹出来的 Toplevel 必须主动抬到最前，
        否则玩家按了 F1 看起来"没反应"。
        """
        try:
            win = self.open_keyword_guide()
            if win is not None and self._pyboard is not None:
                win.lift()
                win.focus_force()
        except Exception:
            pass

    def back_to_menu(self):
        """安全回到主菜单（放弃当前对局）。

        ⚠ 注意：这里是**回主菜单**，不是断服务器 —— 服务器连接要保留，
        否则用户每打一局都得重连 + 重新登录。
        """
        self._finishing = False
        if self._pyboard is not None:
            self._pyboard.quit()   # 让 pygame 主循环退出；视图方法由 _run_pyboard 还原
        if self.mp_link is not None:
            if self.game is not None and not self._mp_game_over:
                self.mp_link.send({"m": "concede"})   # 中途退出 = 投降
                self.mp_link.send({"m": "leave_room"})
        self._mp_game_over = False
        self.mp_role = None
        self.mp_opp = None
        self.mp_opp_name = None
        self.mp_my_deck = None
        self._mp_me_ready = False
        self._mp_pending_seed = None
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
        self._music_play("menu")

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
        self._music_play("result", fade_ms=900)
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
        # 账号战绩 + 货币奖励。游客也发币（存 guest 键）：输了也有 30 金币
        # 保底，胜利才给钻石，让"再来一局"始终有个看得见的进账。
        result = "draw" if won is None else ("win" if won else "lose")
        rank_line = ""
        if self.account:
            account.stats_add(self.account, result)
            # 段位只在联机对局中结算：人机可以无限刷，算进段位就等于送分。
            # 平局按规则不存在；真出了也不动段位（不让异常结算打花数据）。
            if (getattr(self, "_game_online", False)
                    and result in ("win", "lose")):
                rank_line = self._rank_settle(result)
            self._refresh_account_btn()
        rw = account.currency_reward(result, name=self.account)
        self.add_log(i18n.t("currency_reward", gold=rw["gold"],
                            diamonds=rw["diamonds"]))
        self.refresh()

        def after_click():
            self._finishing = False
            self.back_to_menu()

        self.show_end_animation(won, after_click, nation=me.nation,
                                rank_line=rank_line)

    def _rank_settle(self, result):
        """联机对局结算段位；返回一行展示文案（网络失败返回空）。

        ⚠ 失败时**不能**退回本地再算一遍：服务器可能已经记了，只是应答
        丢了（超时/断线），本地补算会变成一局两记。
        """
        res = account.rank_add(self.account, result)
        if not res:
            self.add_log(i18n.t("rank_settle_failed"))
            return ""
        self.rank_state = res["rank"]
        self._rank_last = res.get("change") or {}
        ch = self._rank_last
        if ch.get("season_rolled"):
            self.add_log(i18n.t("rank_new_season", year=res["rank"]["season"]))
        line = rank.describe(ch, i18n.t)
        if line:
            self.add_log(i18n.t("rank_log", text=line))
        return line

    # ---------------- 胜利 / 失败结算动画 ----------------
    HQ_EXPLODE_MS = 1400        # 总部爆炸阶段时长

    # ---------------- 冒烟测试 ----------------
def _debug_addr(addr=None):
    """解析 --debug-on-net / --debug-auto 的服务器地址参数"""
    if addr:
        return addr
    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            continue
        if net.parse_addr(arg) is not None:
            return arg
    return net.DEFAULT_SERVER


def run_debug_net(addr=None):
    """--debug-on-net：本机双开自战（**两个独立进程**，各自一个窗口）

    为什么必须是两个进程：
      对战界面只有 pygame，而 `pygame.display.set_mode()` 在同一进程里
      第二次调用会让前一个 Surface 失效（实测报 Surface is not
      initialized）——单进程双窗口再也跑不起来。分开进程还顺带消灭了
      session.json 共享导致「后连的把先连的顶下线」的老坑。
      这样做和玩家真实场景（两个人各开一个客户端）完全一致。

    前提：先启动 `python kards_server.py`（默认 6000 端口）。
    用法：python KARDS.py --debug-on-net 127.0.0.1:6000
    """
    import tempfile

    addr = _debug_addr(addr)
    print(f"[调试自战] 启动两个独立进程，服务器 {addr} …")
    base = os.environ.get("KARDS_DATA_DIR") or tempfile.mkdtemp(prefix="kards_dbgnet_")
    script = ([sys.executable] if getattr(sys, "frozen", False)
              else [sys.executable, os.path.abspath(__file__)])
    procs = []
    for tag in ("A", "B"):
        env = dict(os.environ)
        env["KARDS_DATA_DIR"] = os.path.join(base, tag)
        os.makedirs(env["KARDS_DATA_DIR"], exist_ok=True)
        procs.append(subprocess.Popen(
            script + ["--debug-auto", addr, tag, "--no-fullscreen"],
            env=env, cwd=os.path.dirname(os.path.abspath(__file__))))
    print("[调试自战] 两个窗口已拉起：A=DebugA(德国) / B=DebugB(苏联)，"
          "自动登录→匹配→组卡→开局。")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()


def run_debug_auto(addr=None, tag="A"):
    """--debug-auto：调试自战的子进程（一个窗口跑完 连服→登录→匹配→组卡→开局）"""
    addr = _debug_addr(addr)
    me = "DebugA" if tag == "A" else "DebugB"
    nation = "德国" if tag == "A" else "苏联"
    try:
        # 子进程 stdout 被父进程接管时默认是缓冲的，被 taskkill 会丢日志
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError, OSError):
        pass
    app = App()
    app.title(f"KARDS 联机调试 · 窗口{tag}")
    app.geometry("+60+60" if tag == "A" else "+780+60")
    app.on_battle()                 # 先进联机大厅：地址框/日志框在这里才建出来
    st = {"n": 0, "deck": False, "said": False}

    def tick():
        st["n"] += 1
        n = st["n"]
        try:
            if app.game is not None:
                if not st["said"]:
                    st["said"] = True
                    print(f"[窗口{tag}] 就绪！联机对局已开始。")
                app.after(500, tick)
                return
            if n == 2:
                app.srv_addr_var.set(addr)
                app._lobby_connect()
            elif n == 6:
                if app.mp_link is None:
                    print(f"[窗口{tag}] 连不上服务器 {addr}，请先运行 kards_server.py")
                    return
                account.set_remote(app.mp_link, addr)
                ok, err = account.login(me, "debug1234")
                if not ok:
                    ok, err = account.register(me, "debug1234")
                if not ok:
                    print(f"[窗口{tag}] 账号失败：{err}")
                    return
                app.mp_user = account.current()
                app._apply_account(app.mp_user)
                app._srv_send({"m": "lobby"})
                # 关掉自动弹出的账号窗，别挡视线
                for w in app.winfo_children():
                    if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == "account":
                        w.destroy()
            elif n == 9:
                app._mp_quick_match()
            elif (app.mp_role is not None and not st["deck"]
                  and getattr(app, "start_frame", None) is not None
                  and app.start_frame.winfo_exists()):
                st["deck"] = True
                app._build_deck_builder(nation, mp=True)
                deck = core.build_deck(nation, app.db)
                app.deck_counts = {}
                for c in deck:
                    app.deck_counts[c.name] = app.deck_counts.get(c.name, 0) + 1
                app._start_mp()
        except Exception as exc:                       # noqa: BLE001
            print(f"[窗口{tag}] 异常：{exc!r}")
        app.after(300, tick)

    app.after(300, tick)
    app.mainloop()


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
    if "--board-smoke" in sys.argv:
        # pygame 棋盘自检：dummy 驱动跑若干帧 + 模拟操作（无需 Tk/真窗口）
        import kards_board
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        sys.exit(0 if kards_board.smoke() else 1)
    if "--debug-on-net" in sys.argv:
        run_debug_net()
        return
    if "--debug-auto" in sys.argv:
        # 调试自战的子进程入口：单实例互斥体不能拦（同一台机器要开两个窗口）
        i = sys.argv.index("--debug-auto")
        rest = sys.argv[i + 1:]
        run_debug_auto(rest[0] if rest else None,
                       rest[1] if len(rest) > 1 else "A")
        return
    if "--smoke" not in sys.argv and _another_instance_running():
        return
    if "--smoke" in sys.argv:
        # 无界面整局冒烟：原 smoke_test 依赖经典 tkinter 对战视图，已随视图
        # 一起删除。现在改跑纯引擎 AI vs AI 整局（不创建 App，无 Tk/pygame），
        # 校验卡池完整、推荐卡组合法、整局能正常打到结束。
        db = core.card_database()
        nat1 = random.choice(core.MAIN_NATIONS)
        nat2 = random.choice(core.MAIN_NATIONS)
        g = core.Game(core.Player("甲", nat1, core.build_deck(nat1, db)),
                      core.Player("乙", nat2, core.build_deck(nat2, db)),
                      interactive=False)
        winner = g.run()
        finished = g.over or g.conceded is not None
        played = getattr(g, "turn_num", 0)
        print(f"[smoke] {nat1} vs {nat2} → "
              f"胜者={winner.name if winner else '平局'} 回合={played}")
        sys.exit(0 if finished else 1)
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
