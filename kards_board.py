#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kards_board —— pygame 对战界面（混合架构：tkinter 管菜单/大厅，pygame 画战场）

设计要点（2026-10-04，替换 tkinter 对战界面的动因：动画/拖拽卡顿、
想要图片卡面、为牌桌特效/音效铺路）：

- **依赖面收敛**：本模块只依赖 core(kards_engine) / i18n / 一个 `on_intent`
  回调，完全不 import tkinter —— 可以脱离 Tk 单测（SDL dummy 驱动）。
- **与 tkinter 界面鸭子兼容**：KARDS.App 在 pygame 模式下把
  refresh/show_banner/_anim_* 等视图方法指向本类的同名方法，控制器
  （AI 步进 / 联机消息回放）代码零改动。Ref 用 `winfo_exists()` 伪装。
- **意图路由**：玩家操作产出 {"k": "play"/"move"/"attack"/"hq"/"end"/...}
  意图，由 App.pyboard_intent 路由到与 tkinter 拖拽完全相同的
  _act_play/_act_move/_attack_* —— 联机 _mp_send_act 语义天然一致。
- **虚拟时钟**：所有动画基于 self.t_now（step(dt) 推进），真实运行与
  单测（手动 step）共用同一套补间逻辑，结果可复现。
- **图片卡面**：优先加载 assets/cards/<卡名>.png（HQ 用 assets/hq/<国家>.png），
  缺失时过程式绘制兜底 —— 以后逐卡补图零代码改动。

⚠ 中文字体：必须用 SysFont("microsoftyahei,...")，默认字体渲染中文是方块。
"""

import os
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")   # 别在日志里刷 pygame 横幅

import math
import random
import sys
import warnings

# pygame 会通过 pkg_resources 触发一条已弃用警告（setuptools 到期提醒），
# 对玩家毫无意义，还在日志里刷屏 —— 必须在 import pygame 之前压掉。
warnings.filterwarnings(
    "ignore", message=r".*pkg_resources is deprecated.*", category=UserWarning)

import pygame

import kards_engine as core
import kards_i18n as i18n

# ---------------------------------------------------------------- 主题配色
# 与 KARDS.py 保持一致（拷贝一份避免循环 import；改动需两边同步）

BG = "#1a1d23"
PANEL = "#242831"
CARD_BG = "#2e3440"
TEXT = "#e6e6e6"
DIM = "#9aa0a8"
RED = "#e05c5c"
GREEN = "#6fbf73"
GOLD = "#e0b45c"
ROW_BG = "#1f232b"
ROW_EDGE = "#2a2f3a"
MID_BG = "#20242c"
LOG_BG = "#161a20"
HAND_AREA = "#242831"

NATION_COLOR = {
    "德国": "#6b7a8f", "苏联": "#a05a4c", "美国": "#4c7a6b",
    "英国": "#7a6b8f", "日本": "#8f6b4c",
    "意大利": "#6f8f6b", "法国": "#6b7a9f", "芬兰": "#8fb0c8",
    "波兰": "#c8a06b", "澳新军团": "#8f9f6b", "中立": "#7a7a7a",
}

# 稀有度 → 宝石色（1 传说 / 2 史诗 / 3 普通 / 4 稀有，与主程序映射一致）
RARITY_COLOR = {1: "#e0b45c", 2: "#b07ae0", 3: "#9aa0a8", 4: "#5c9ee0"}

_BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(_BASE, "assets")


def asset_roots():
    """卡面/音效资产的搜索目录，按优先级从高到低。

    - 安装版：exe 同级目录下的 assets（玩家可以自己丢图进去，不用重打包）
    - 源码版：项目根目录下的 assets
    - 兜底：打包内部（_internal/assets）
    """
    roots = []
    if getattr(sys, "frozen", False):
        try:
            roots.append(os.path.join(
                os.path.dirname(os.path.abspath(sys.executable)), "assets"))
        except Exception:
            pass
    if ASSETS not in roots:
        roots.append(ASSETS)
    return roots


def find_asset(*parts):
    """在资产目录里找一个文件（相对路径），找不到返回 None"""
    for root in asset_roots():
        p = os.path.join(root, *parts)
        if os.path.exists(p):
            return p
    return None


def C(hexstr):
    """'#rrggbb'（或已是 (r,g,b)）→ (r, g, b)"""
    if isinstance(hexstr, (tuple, list)):
        return tuple(hexstr[:3])
    hexstr = hexstr.lstrip("#")
    if len(hexstr) == 3:                      # #rgb → #rrggbb
        hexstr = "".join(ch * 2 for ch in hexstr)
    return (int(hexstr[0:2], 16), int(hexstr[2:4], 16), int(hexstr[4:6], 16))


def kw_text(keywords):
    return " ".join(f"[{k}]" for k in keywords)


# pygame 的 SysFont **不会**跨字体回退：文案里的装饰 emoji/符号
# （⚔ 🏠 🏳 🏆 💀 ☰ 🐇 🐢 ♥ …）在雅黑里没有字形，会画成空心方块，
# 界面上到处是"□"。这里统一在渲染前剥掉 —— tkinter 版有系统级回退
# 没这个问题，pygame 版必须在源头处理。
_BAD_GLYPHS = "♥⚔☰🏳🏠🚪🏆💀▼▲🐇🐢⏩⚙⚡✖◼◆►◄"
_GLYPH_MAP = {ord(ch): None for ch in _BAD_GLYPHS}


def plain(text):
    """去掉 pygame 字体渲染不出来的装饰符号"""
    return str(text).translate(_GLYPH_MAP).replace("   ", " ").strip()


def t(key, **kw):
    """i18n.t + 符号清洗（棋盘内统一走这里）"""
    return plain(i18n.t(key, **kw))


# ---------------------------------------------------------------- 字体

_font_cache = {}


def font(size, bold=False):
    """带中文回退的字体（雅黑 → 黑宝 → 默认）。缓存。"""
    key = (size, bold)
    if key not in _font_cache:
        try:
            f = pygame.font.SysFont(
                "microsoftyahei,msyh,simhei,dengxian,notosanscjk,arial",
                size, bold=bold)
        except Exception:
            f = pygame.font.Font(None, size)
        _font_cache[key] = f
    return _font_cache[key]


def wrap_text(text, fnt, maxw):
    """按像素宽度折行（中文逐字、英文按词）"""
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if fnt.size(cur + ch)[0] > maxw and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines or [""]


def truncate(text, fnt, maxw):
    if fnt.size(text)[0] <= maxw:
        return text
    while text and fnt.size(text + "…")[0] > maxw:
        text = text[:-1]
    return text + "…"


def rr(surf, rect, color, radius=6, width=0, border_color=None):
    """圆角矩形（width=0 实心；width>0 描边）"""
    r = pygame.Rect(rect)
    if width == 0:
        pygame.draw.rect(surf, color, r, border_radius=radius)
    if border_color is not None:
        pygame.draw.rect(surf, border_color, r, width=width or 1,
                         border_radius=radius)


# ---------------------------------------------------------------- 资产加载

_img_cache = {}


def card_image(name, w, h):
    """卡面图片：assets/cards/<卡名>.png（缺失返回 None，调用方走过程式绘制）"""
    key = (name, w, h)
    if key in _img_cache:
        return _img_cache[key]
    img = None
    for ext in (".png", ".jpg"):
        p = find_asset("cards", name + ext)
        if p:
            try:
                img = pygame.image.load(p).convert_alpha()
                img = pygame.transform.smoothscale(img, (w, h))
            except Exception:
                img = None
            break
    _img_cache[key] = img
    return img


def hq_image(nation, w, h):
    key = ("hq:" + nation, w, h)
    if key in _img_cache:
        return _img_cache[key]
    img = None
    for ext in (".png", ".jpg"):
        p = find_asset("hq", nation + ext)
        if p:
            try:
                img = pygame.image.load(p).convert_alpha()
                img = pygame.transform.smoothscale(img, (w, h))
            except Exception:
                img = None
            break
    _img_cache[key] = img
    return img


_sfx_ready = None


def sfx(name):
    """音效钩子：assets/sfx/<名>.wav|ogg。没有资产就静默（为后续特效铺路）"""
    global _sfx_ready
    if _sfx_ready is None:
        try:
            pygame.mixer.init()
            _sfx_ready = True
        except Exception:
            _sfx_ready = False
    if not _sfx_ready:
        return
    for ext in (".wav", ".ogg"):
        p = find_asset("sfx", name + ext)
        if p:
            try:
                pygame.mixer.Sound(p).play()
            except Exception:
                pass
            return


# ---------------------------------------------------------------- Ref（控件替身）

class Ref:
    """界面元素替身 —— 与 tkinter 控件鸭子兼容（winfo_exists / 中心点）。

    KARDS.App 的控制器代码（AI 步进动画、事件特效）通过
    unit_widgets.get(id(unit)) 拿到本对象后直接使用，无需感知 pygame。
    """

    __slots__ = ("rect", "kind", "unit", "card", "idx", "alive",
                 "flash_tint", "fly", "ready", "guard", "nat_color", "blast_t0")

    def __init__(self, rect, kind, unit=None, card=None, idx=None,
                 nat_color="#666"):
        self.rect = pygame.Rect(rect)
        self.kind = kind          # "unit" / "hq" / "hand"
        self.unit = unit
        self.card = card
        self.idx = idx
        self.alive = True
        self.flash_tint = None    # (color, until_time)
        self.fly = None           # 入场动画 (src, t0, dur) 或 None
        self.ready = False
        self.guard = False
        self.nat_color = nat_color
        self.blast_t0 = None      # 结算爆炸起始时刻（None=未爆炸）

    def winfo_exists(self):
        return self.alive

    def center(self):
        return self.rect.center

    def kill(self):
        self.alive = False


# ---------------------------------------------------------------- 主类

class PygameBoard:
    """pygame 对战棋盘。

    用法（App 内）：
        b = PygameBoard(self)
        b.run(pump=self.update)      # 阻塞至对局结束，期间泵 Tk 事件
        # b.result: None=正常结束回菜单 / "quit"=玩家要求退出程序
    """

    HAND_CW, HAND_CH = 148, 204     # 手牌尺寸
    UNIT_W, UNIT_H = 132, 88        # 战场单位尺寸
    HQ_W, HQ_H = 108, 118           # 总部尺寸

    def __init__(self, app=None, game=None, on_intent=None, me_index=0):
        self.app = app
        self.game = game
        self.on_intent = on_intent or (app.pyboard_intent if app is not None
                                       else (lambda act: None))
        self.me_index = me_index
        # 880：五段式战场(544) + 我方信息条(56) + 手牌(212) + 底边距。
        # 800 时 info_my 会掉进手牌区正下方被整个盖住 → 玩家看不到自己的
        # 费用/牌库（实测截图确认），所以默认高度必须留够。
        self.W, self.H = 1280, 880
        self.running = True
        self.result = None

        # 虚拟时钟（ms）
        self.t_now = 0
        self.tweens = []          # dict(t0, dur, fn, on_done, tag)
        self.timers = []          # (due, fn)

        # 视图状态
        self.log_lines = []
        self.log_scroll = 0       # 距底部 0 = 贴底
        self.floats = []          # dict(text,color,x,y,t0,dur)
        self.rings = []           # dict(x,y,t0,dur,color)
        self.banner = None        # dict(text,color,until)
        self.shake_off = (0, 0)
        self.particles = []       # 结算粒子

        # 控制器鸭接面（App 会把这些引用挂到自己身上）
        self.unit_refs = {}       # id(unit) -> Ref
        self.enemy_refs = []      # [(unit, Ref)]
        self.hq_ref = None        # 敌方总部
        self.my_hq_ref = None     # 我方总部（结算时也要炸——玩家得看到自己的总部）
        self.pending_flash = []   # (unit, color) —— on_game_event "deploy" 塞进来

        # 交互状态
        self.drag = None
        self.hover_ref = None
        self.mouse = (0, 0)
        self.pause = False
        self.pause_confirm = None
        self.end_state = None     # dict(won, on_done, nation, ready_at, phase, phase_at)
        self._end_clicked = False
        self._hq_fall_tip = None  # dict(text, until) —— 结算爆炸阶段的提示条

        # 绘制
        self.screen = None
        self.clock = None
        try:
            pygame.font.init()
        except Exception:
            pass

    # ================= 视图接口（与 KARDS.App 鸭子兼容） =================

    def refresh(self):
        self.sync()

    def add_log(self, msg):
        for ln in str(msg).split("\n"):
            self.log_lines.append(ln)
        if len(self.log_lines) > 400:
            self.log_lines = self.log_lines[-400:]
        self.log_scroll = 0

    def show_banner(self, text, color, ms=900):
        if not self._anim_on():
            return
        self.banner = {"text": text, "color": color, "until": self.t_now + ms}

    def float_text(self, anchor, text, color, ms=900):
        """anchor: Ref（tkinter 模式是控件；这里统一是 Ref）"""
        if not self._anim_on() or anchor is None:
            return
        x, y = anchor.rect.centerx, anchor.rect.top - 6
        self.floats.append({"text": text, "color": color,
                            "x": x, "y": y, "t0": self.t_now, "dur": ms})

    def flash_widget(self, ref, color=RED, times=3, interval=110):
        if not self._anim_on() or ref is None:
            return
        total = times * 2 * interval
        ref.flash_tint = (color, self.t_now + total)

    def _shake_widget(self, ref):
        self.flash_widget(ref, RED, times=1, interval=160)

    def shake(self, times=6, amp=7, interval=40):
        """整屏震动（HQ 受伤）"""
        if not self._anim_on():
            return
        for i in range(times):
            self.after(i * interval,
                       lambda a=amp if i % 2 == 0 else -amp:
                       setattr(self, "shake_off", (a, int(a * 0.6))))
        self.after(times * interval, lambda: setattr(self, "shake_off", (0, 0)))

    # 兼容别名：App._activate_pyboard 把 self.shake 指到这里也不会撞名
    shake_screen = shake

    def wcenter(self, ref):
        if ref is None or not ref.winfo_exists():
            return None
        return ref.rect.center

    def anim_entry(self, u):
        """部署入场：卡从牌库区飞到落点（真身同步时已建好，飞行中只画令牌）

        ⚠ 必须和 tkinter 版一样在动画关闭时直接 return —— 否则会挂上飞行
        令牌，令牌期间真身不画，界面看起来"卡没部署上去"且永不落地。
        """
        if not self._anim_on():
            return
        ref = self.unit_refs.get(id(u))
        if ref is None:
            return
        src = (self.W - 70, self.H - 90)
        ref.fly = (src, self.t_now, 480)   # 绘制时按 t_now 插值，飞到点自动清除
        sfx("deploy")

    def anim_move(self, u, on_done=None):
        """行军：令牌从左侧滑入落点（真身同步时已就位，飞行中只画令牌）"""
        ref = self.unit_refs.get(id(u))
        if ref is None or not self._anim_on():
            if on_done:
                on_done()
            return
        ref.fly = ((ref.rect.x - 260, ref.rect.y), self.t_now, 360)
        sfx("move")
        self._tween(360, lambda p: None,
                    on_done=lambda: (setattr(ref, "fly", None),
                                     on_done() if on_done else None),
                    tag="move")

    def anim_attack(self, att, tgt_ref, on_done=None):
        """进攻：攻击者向目标突进 45% 再弹回，命中瞬间冲击环 + 目标闪红。

        偏移存在外部字典（Ref 用 __slots__ 挂不了属性）；动画期间 sync()
        可能已把单位挪到结算后的位置，突进偏移叠加在最新位置上，视觉一致。
        """
        aref = self.unit_refs.get(id(att))
        if aref is None or tgt_ref is None or not self._anim_on():
            if on_done:
                on_done()
            return
        tx, ty = tgt_ref.rect.center
        ax, ay = aref.rect.center
        dx, dy = tx - ax, ty - ay
        sfx("attack")
        if not hasattr(self, "_lunge_state"):
            self._lunge_state = {}
        state = {"dx": 0, "dy": 0}
        self._lunge_state[id(att)] = state

        def fn(p):
            k = math.sin(p * math.pi)
            state["dx"] = int(dx * 0.45 * k)
            state["dy"] = int(dy * 0.45 * k)

        def fin():
            self._lunge_state.pop(id(att), None)
            if tgt_ref.winfo_exists():
                self.flash_widget(tgt_ref, RED, times=2, interval=90)
                self.rings.append({"x": tgt_ref.rect.centerx,
                                   "y": tgt_ref.rect.centery,
                                   "t0": self.t_now, "dur": 320, "color": GOLD})
            if on_done:
                on_done()
        self._tween(340, fn, on_done=fin, tag="attack")

    def show_end_animation(self, won, on_done=None, nation=None):
        """全屏结算：**先炸总部，再出胜负大字**。点击任意处 → on_done

        ⚠ 时序（用户要求）：不能一点「结算」就把胜利/战败大字盖上来 ——
        先让总部地点爆开（敌方总部被我方打爆 / 我方总部沦陷），
        爆炸播完才弹出胜负标，玩家能看清"是哪边总部先炸的"。

        阶段划分（全部基于虚拟时钟 self.t_now，单测可直接 step 推进）：
          phase 0  hq   : 爆炸特效 + 「XX总部被摧毁」提示（EXPLODE_MS）
          phase 1  full : 胜负大字 + 粒子庆祝 / 暗场震动
        """
        self.end_state = {"won": won, "on_done": on_done, "nation": nation,
                          "ready_at": self.t_now + 700}
        self._end_clicked = False
        self._start_hq_explode(won)
        if won:
            sfx("win" if won else "lose")

    EXPLODE_MS = 1500               # 总部爆炸阶段时长（期间不出胜负大字）

    def _start_hq_explode(self, won):
        """结算前奏：在总部位置炸开。

        哪个总部爆由 won 决定：
          won=True  → 敌方总部（玩家打赢了）
          won=False → 我方总部（玩家输了）
          won=None  → 两边一起炸（平局）
        """
        if not self._anim_on():
            self.end_state["phase"] = "full"
            self.end_state["phase_at"] = self.t_now
            return
        targets = []
        if won is True:
            targets = [("foe", self.hq_ref)]
        elif won is False:
            targets = [("me", self.my_hq_ref)]
        else:
            targets = [("foe", self.hq_ref), ("me", self.my_hq_ref)]
        targets = [(side, r) for side, r in targets if r is not None]
        for side, ref in targets:
            cx, cy = ref.rect.centerx, ref.rect.centery
            ref.blast_t0 = self.t_now              # 绘制时按 t0 展开冲击波
            ref.flash_tint = (GOLD, self.t_now + 600)
            # 火星/碎片粒子
            rng = random.Random(hash((id(ref), self.t_now)) & 0xFFFF)
            for _ in range(26):
                ang = rng.uniform(0, math.tau)
                spd = rng.uniform(90, 320)
                self.particles.append({
                    "x": cx, "y": cy,
                    "vx": math.cos(ang) * spd, "vy": math.sin(ang) * spd,
                    "t0": self.t_now, "dur": rng.randint(500, 1100),
                    "color": rng.choice(["#ffb347", "#ff7a3c", "#ffe08a",
                                         "#c0c6d0", GOLD]),
                    "size": rng.randint(2, 6)})
            self.rings.append({"x": cx, "y": cy, "t0": self.t_now,
                               "dur": 620, "color": "#ff9c54"})
        sfx("boom")
        self.shake(times=10, amp=12, interval=38)
        # 提示条：说明是哪边总部被摧毁
        if won is True:
            tip = i18n.t("hq_fall_foe")
        elif won is False:
            tip = i18n.t("hq_fall_me")
        else:
            tip = i18n.t("hq_fall_both")
        self._hq_fall_tip = {"text": tip, "until": self.t_now + self.EXPLODE_MS}
        self.end_state["phase"] = "hq"
        self.end_state["phase_at"] = self.t_now

    def _end_phase(self):
        """当前结算阶段：hq（爆炸中）/ full（出大字）"""
        st = self.end_state
        if st is None:
            return "full"
        if st.get("phase") == "hq":
            if self.t_now - st.get("phase_at", self.t_now) < self.EXPLODE_MS:
                return "hq"
            st["phase"] = "full"
            st["phase_at"] = self.t_now
            # 胜负大字出现的瞬间补粒子庆祝（胜利）
            if st.get("won"):
                rng = random.Random(20261004)
                for _ in range(60):
                    self.particles.append({
                        "x": rng.uniform(0, self.W), "y": rng.uniform(0, self.H * 0.9),
                        "vx": rng.uniform(-40, 40), "vy": rng.uniform(-120, -30),
                        "t0": self.t_now, "dur": rng.randint(1200, 2600),
                        "color": rng.choice([GOLD, "#fff1b8", "#e0e6f0", "#d4af37"]),
                        "size": rng.randint(2, 5)})
        return "full"

    def quit(self):
        self.running = False

    def _anim_on(self):
        if self.app is None:
            return True
        return getattr(self.app, "anim_enabled", True)

    # ================= 调度 / 补间 =================

    def after(self, ms, fn):
        self.timers.append((self.t_now + ms, fn))

    def _tween(self, dur, fn, on_done=None, tag=None):
        self.tweens.append({"t0": self.t_now, "dur": max(1, dur),
                            "fn": fn, "on_done": on_done, "tag": tag})

    def step(self, dt_ms):
        """推进虚拟时钟：到期定时器、补间、浮动文字。单测可直接调。"""
        self.t_now += dt_ms
        due = [t for t in self.timers if t[0] <= self.t_now]
        if due:
            self.timers = [t for t in self.timers if t[0] > self.t_now]
            for _, fn in due:
                fn()
        done = []
        for tw in self.tweens:
            p = (self.t_now - tw["t0"]) / tw["dur"]
            if p >= 1.0:
                tw["fn"](1.0)
                done.append(tw)
            else:
                tw["fn"](p)
        for tw in done:
            if tw in self.tweens:
                self.tweens.remove(tw)
                if tw["on_done"]:
                    tw["on_done"]()
        self.floats = [f for f in self.floats
                       if self.t_now - f["t0"] < f["dur"]]
        self.rings = [r for r in self.rings
                      if self.t_now - r["t0"] < r["dur"]]
        if self.banner is not None and self.t_now > self.banner["until"]:
            self.banner = None
        # 结算阶段推进（爆炸 → 大字）：放在 step 里，绘制与单测都能驱动，
        # 不依赖 _draw_end 被调用（否则 headless 测试推不动阶段）。
        if self.end_state is not None:
            self._end_phase()

    # ================= 布局与同步 =================

    def layout(self):
        """根据当前窗口尺寸计算各区域（可变窗口，每帧可算）"""
        W, H = self.W, self.H
        logw = 330
        lx = W - logw - 10
        capw = 108
        bx, bw = 12, lx - capw - 22
        y_info_foe = 10
        rows_h = 104
        y_foe_rear = 44
        y_foe_front = y_foe_rear + rows_h + 12
        y_mid = y_foe_front + rows_h + 12
        mid_h = 36
        y_my_front = y_mid + mid_h + 12
        y_my_rear = y_my_front + rows_h + 12
        hand_y = H - self.HAND_CH - 46
        # 我方信息条必须**紧贴手牌上方**且不压到战场行：
        # 旧版固定 y_my_rear+rows_h+10，窗口一矮就被手牌区整个盖住，
        # 玩家看不到自己的费用/牌库/研发被动（实测截图确认的 bug）。
        y_info_my = max(y_my_rear + rows_h + 8, hand_y - 62)
        return {
            "log": pygame.Rect(lx, 10, logw, hand_y - 24),
            "row_foe_rear": pygame.Rect(bx + capw, y_foe_rear, bw, rows_h),
            "row_foe_front": pygame.Rect(bx + capw, y_foe_front, bw, rows_h),
            "mid": pygame.Rect(bx, y_mid, lx - bx - 12, mid_h),
            "row_my_front": pygame.Rect(bx + capw, y_my_front, bw, rows_h),
            "row_my_rear": pygame.Rect(bx + capw, y_my_rear, bw, rows_h),
            "cap_foe_rear": pygame.Rect(bx, y_foe_rear, capw, rows_h),
            "cap_foe_front": pygame.Rect(bx, y_foe_front, capw, rows_h),
            "cap_my_front": pygame.Rect(bx, y_my_front, capw, rows_h),
            "cap_my_rear": pygame.Rect(bx, y_my_rear, capw, rows_h),
            "info_foe": pygame.Rect(bx, y_info_foe, lx - bx - 12, 28),
            "info_my": pygame.Rect(bx, y_info_my, lx - bx - 12, 56),
            "hand": pygame.Rect(bx, hand_y, lx - bx - 12, self.HAND_CH + 8),
            "end_btn": pygame.Rect(lx, H - 44, logw, 36),
            "speed_btn": pygame.Rect(lx, H - 88, 150, 36),
            "menu_btn": pygame.Rect(lx + 160, H - 88, logw - 160, 36),
        }

    def _game_state(self):
        """优先读 app.game（联机重连会换局）"""
        if self.app is not None:
            g = getattr(self.app, "game", None)
            if g is not None:
                self.game = g
        return self.game

    def _fingerprint(self, g):
        """引擎状态指纹：变了就该 sync（防控制器漏调 refresh 的兜底）"""
        fp = [g.current is g.players[0], g.players[0].hq, g.players[1].hq,
              g.players[0].kredits, g.players[1].kredits,
              len(g.players[0].hand), len(g.players[1].hand),
              len(g.players[0].counters), g.frontline_owner()]
        for p in g.players:
            for u in p.board:
                fp.append((id(u), u.attack, u.defense, u.position, u.slot))
        return tuple(fp)

    def _ensure_sync(self):
        g = self._game_state()
        if g is None:
            return
        fp = self._fingerprint(g)
        if fp != getattr(self, "_fp", None):
            self.sync()

    def sync(self):
        """从引擎状态重建所有 Ref（= tkinter 的 refresh，但无销毁重建成本）"""
        g = self._game_state()
        if g is None:
            return
        self._fp = self._fingerprint(g)
        me, foe = g.players[0], g.players[1]
        human_turn = g.current is me
        L = self.layout()
        nat_me = NATION_COLOR.get(me.nation, "#666")
        nat_foe = NATION_COLOR.get(foe.nation, "#666")

        old = self.unit_refs
        self.unit_refs = {}
        self.enemy_refs = []
        hq = Ref(pygame.Rect(L["row_foe_rear"].x + 8, L["row_foe_rear"].y + 4,
                             self.HQ_W, self.HQ_H), "hq", nat_color=nat_foe)
        self.hq_ref = hq
        my_hq = Ref(pygame.Rect(L["row_my_rear"].x + 8, L["row_my_rear"].y + 4,
                                self.HQ_W, self.HQ_H), "hq", nat_color=nat_me)
        self.my_hq_ref = my_hq

        def place_units(units, row_rect, is_enemy):
            x = row_rect.x + 8
            for u in units:
                r = pygame.Rect(x, row_rect.y + (row_rect.h - self.UNIT_H) // 2,
                                self.UNIT_W, self.UNIT_H)
                ref = old.get(id(u))
                if ref is not None and ref.kind == "unit":
                    ref.rect = r            # 保留动画态，只更新落点（fly 不动）
                else:
                    ref = Ref(r, "unit", unit=u,
                              nat_color=nat_foe if is_enemy else nat_me)
                ref.guard = u.has("警卫")
                ref.ready = (not is_enemy and human_turn
                             and g.unit_ready(u))
                self.unit_refs[id(u)] = ref
                if is_enemy:
                    self.enemy_refs.append((u, ref))
                x += self.UNIT_W + 10

        foe_front = [u for u in foe.board if u.position == "前线"]
        foe_rear = [u for u in foe.board if u.position != "前线"]
        my_front = [u for u in me.board if u.position == "前线"]
        my_rear = [u for u in me.board if u.position != "前线"]
        place_units(foe_rear, L["row_foe_rear"], True)
        # 敌方后排与 HQ 同排：HQ 已占头部，单位从 HQ 右侧开始排
        x = hq.rect.right + 14
        for u in foe_rear:
            ref = self.unit_refs[id(u)]
            ref.rect.topleft = (x, L["row_foe_rear"].y +
                                (L["row_foe_rear"].h - self.UNIT_H) // 2)
            x += self.UNIT_W + 10
        place_units(foe_front, L["row_foe_front"], True)
        place_units(my_front, L["row_my_front"], False)
        place_units(my_rear, L["row_my_rear"], False)
        # 我方后排也与 HQ 同排：HQ 占头部，单位从 HQ 右侧开始排
        # （否则单位会压在总部上；截图肉眼确认的错位）
        x = my_hq.rect.right + 14
        for u in my_rear:
            ref = self.unit_refs[id(u)]
            ref.rect.topleft = (x, L["row_my_rear"].y +
                                (L["row_my_rear"].h - self.UNIT_H) // 2)
            x += self.UNIT_W + 10

        # 手牌 Ref
        self.hand_refs = []
        if human_turn:
            x = L["hand"].x + 6
            for i, c in enumerate(me.hand):
                eff = g.get_cost(c, me)
                playable = eff <= me.kredits
                if c.kind == "unit":
                    can = playable and g.can_deploy(me)
                elif c.kind == "counter":
                    can = playable and len(me.counters) < core.COUNTER_SLOTS
                else:
                    can = playable
                r = pygame.Rect(x, L["hand"].y + 4, self.HAND_CW, self.HAND_CH)
                self.hand_refs.append(Ref(r, "hand", card=c, idx=i,
                                          nat_color=NATION_COLOR.get(c.nation, "#666")))
                self.hand_refs[-1].ready = can
                x += self.HAND_CW + 10

        # 部署入场动画（on_game_event "deploy" 塞进 pending_flash）
        for u, _color in self.pending_flash:
            self.anim_entry(u)
        self.pending_flash = []

    # ================= 落点与合法性 =================

    def drop_zones(self):
        """[(rect, kind, ref_or_unit)] —— kind: deploy/front/enemy_card/hq"""
        L = self.layout()
        zones = [(L["row_my_rear"], "deploy", None),
                 (L["row_my_front"], "front", None)]
        for u, ref in self.enemy_refs:
            zones.append((ref.rect, "enemy_card", u))
        if self.hq_ref is not None:
            zones.append((self.hq_ref.rect, "hq", None))
        return zones

    def zone_at(self, pos):
        for rect, kind, extra in self.drop_zones():
            if rect.collidepoint(pos):
                return kind, extra
        return None, None

    def valid_drop(self, kind, extra, drag=None):
        """镜像 KARDS.App._valid_drop 的语义（决定绿/红高亮）

        ⚠ drag 参数：_handle_release 必须在判定**之后**才能清 self.drag，
        所以把当时的拖拽快照显式传进来。早期版本先清 self.drag 再判定，
        导致任何落点都判非法 → 拖拽完全出不了牌（只能靠按钮）。
        """
        g = self._game_state()
        d = self.drag if drag is None else drag
        if g is None or d is None:
            return False
        me = g.players[0]
        if d["kind"] == "hand":
            idx = d["idx"]
            if idx >= len(me.hand):
                return False
            card = me.hand[idx]
            if card.kind == "unit":
                return kind == "deploy"
            return kind in ("deploy", "front")
        u = d["unit"]
        if u not in me.board:
            return False
        if kind == "enemy_card":
            return (extra is not None and g.unit_ready(u)
                    and extra in g.attack_targets(u))
        if kind == "hq":
            return g.unit_ready(u)
        if kind in ("front", "deploy"):
            return True
        return False

    # ================= 输入 =================

    def handle_event(self, ev):
        """真实事件（pygame.event）与测试用伪事件共用本入口"""
        if ev.type == pygame.VIDEORESIZE:
            self.W, self.H = ev.w, ev.h
            return
        if ev.type == pygame.QUIT:
            # 关掉窗口 = 退出程序（以前没接这个事件，点 X 完全没反应）
            self.result = "quit"
            self.running = False
            return
        if self.end_state is not None:
            if ev.type == pygame.MOUSEBUTTONDOWN and not self._end_clicked:
                # 必须等总部爆炸播完（full 阶段）才允许点击回大厅，
                # 否则玩家一点就把"是哪边总部炸的"跳过去了。
                if (self._end_phase() != "hq"
                        and self.t_now >= self.end_state["ready_at"]):
                    self._end_clicked = True
                    self.end_state["on_done"]()
            return
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.pause = not self.pause
                self.pause_confirm = None
            return
        if self.pause:
            self._handle_pause(ev)
            return
        if ev.type == pygame.MOUSEMOTION:
            self.mouse = ev.pos
            self._handle_motion(ev)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self.mouse = ev.pos
            self._handle_press(ev)
        elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            self.mouse = ev.pos
            self._handle_release(ev)
        elif ev.type == pygame.MOUSEWHEEL:
            self.log_scroll = max(0, self.log_scroll - ev.y * 24)

    def _busy(self):
        return bool(self.app is not None and getattr(self.app, "busy", False))

    def _my_turn(self):
        g = self._game_state()
        if g is None:
            return False
        return g.current is g.players[0]

    def _handle_press(self, ev):
        g = self._game_state()
        if g is None or self._busy():
            return
        L = self.layout()
        # 按钮
        if L["end_btn"].collidepoint(ev.pos):
            if self._my_turn():
                self.on_intent({"k": "end"})
            return
        if L["speed_btn"].collidepoint(ev.pos):
            self.on_intent({"k": "speed"})
            return
        if L["menu_btn"].collidepoint(ev.pos):
            self.pause = True
            return
        # 手牌拖拽起点
        if self._my_turn():
            for ref in self.hand_refs:
                if ref.rect.collidepoint(ev.pos) and ref.ready:
                    self.drag = {"kind": "hand", "idx": ref.idx,
                                 "card": ref.card, "pos": ev.pos,
                                 "sx": ev.pos[0], "sy": ev.pos[1], "moved": False}
                    return
            # 己方单位拖拽起点（机动 / 攻击）
            me = g.players[0]
            for u in me.board:
                ref = self.unit_refs.get(id(u))
                if ref is not None and ref.rect.collidepoint(ev.pos):
                    self.drag = {"kind": "unit", "unit": u,
                                 "pos": ev.pos, "moved": False,
                                 "sx": ev.pos[0], "sy": ev.pos[1],
                                 "src_rect": pygame.Rect(ref.rect)}
                    return

    def _handle_motion(self, ev):
        if self.drag is None:
            # 悬停目标（提示面板）
            self.hover_ref = None
            for ref in getattr(self, "hand_refs", []):
                if ref.rect.collidepoint(ev.pos):
                    self.hover_ref = ref
            if self.hover_ref is None:
                for ref in self.unit_refs.values():
                    if ref.rect.collidepoint(ev.pos):
                        self.hover_ref = ref
            return
        d = self.drag
        d["pos"] = ev.pos
        if (abs(ev.pos[0] - d["sx"]) > 4
                or abs(ev.pos[1] - d["sy"]) > 4):   # 4px 阈值，兼顾轻点与拖拽
            d["moved"] = True

    def _handle_release(self, ev):
        d = self.drag
        if d is None:
            return
        try:
            self._release_apply(d, ev.pos)
        finally:
            # 判定要用 drag 快照，所以统一在这里清（所有分支都不漏）
            self.drag = None

    def _release_apply(self, d, pos):
        # 兜底判定位移：SDL 在快速拖动时可能合并/省略 MOUSEMOTION，
        # 只看递过来的坐标就够判断"指针离开过起点"了（4px 内算原地点击）。
        if (abs(pos[0] - d.get("sx", pos[0])) > 4
                or abs(pos[1] - d.get("sy", pos[1])) > 4):
            d["moved"] = True
        if not d["moved"]:
            return                     # 原地点击 = 无操作
        kind, extra = self.zone_at(pos)
        if kind is None:
            self.add_log(t("log_drop_cancel"))
            return
        if not self.valid_drop(kind, extra, drag=d):
            if d["kind"] == "hand":
                card = d.get("card")
                idx = d.get("idx")
                g = self._game_state()
                me = g.players[0] if g else None
                if card is None and me is not None and 0 <= idx < len(me.hand):
                    card = me.hand[idx]
                if card is not None and getattr(card, "kind", None) == "unit":
                    self.add_log(t("log_unit_only_rear"))
                else:
                    self.add_log(t("log_bad_drop"))
            else:
                u = d["unit"]
                if u.position == "后方":
                    self.add_log(t("log_need_frontline"))
                else:
                    self.add_log(t("log_guard_blocked"))
            return
        if d["kind"] == "hand":
            self.on_intent({"k": "play", "idx": d["idx"]})
            return
        u = d["unit"]
        if kind == "enemy_card":
            self.on_intent({"k": "attack", "slot": u.slot, "tslot": extra.slot})
        elif kind == "hq":
            self.on_intent({"k": "hq", "slot": u.slot})
        elif kind in ("front", "deploy"):
            self.on_intent({"k": "move", "slot": u.slot,
                            "pos": "前线" if kind == "front" else "后方"})

    # ---- 暂停菜单 ----

    def _pause_items(self):
        return [("resume", t("btn_resume")),
                ("concede", t("btn_surrender")),
                ("leave", t("btn_to_menu")),
                ("quit", t("btn_quit"))]

    def _handle_pause(self, ev):
        if ev.type != pygame.MOUSEBUTTONDOWN:
            return
        items = self._pause_items()
        w, h = 320, 60 * len(items) + 90
        x0, y0 = (self.W - w) // 2, (self.H - h) // 2
        for i, (key, _label) in enumerate(items):
            r = pygame.Rect(x0 + 20, y0 + 70 + i * 60, w - 40, 46)
            if r.collidepoint(ev.pos):
                if key == "resume":
                    self.pause = False
                    self.pause_confirm = None
                elif key == "concede":
                    if self.pause_confirm == "concede":
                        self.pause = False
                        self.on_intent({"k": "concede"})
                    else:
                        self.pause_confirm = "concede"
                elif key == "leave":
                    if self.pause_confirm == "leave":
                        self.pause = False
                        self.on_intent({"k": "leave"})
                    else:
                        self.pause_confirm = "leave"
                elif key == "quit":
                    self.result = "quit"
                    self.running = False
                return

    # ================= 主循环 =================

    def run(self, pump=None, fps=60, max_frames=None):
        """阻塞主循环。pump：每帧回调（App 传 self.update 泵 Tk 事件）。

        max_frames：测试/冒烟用帧数上限（None=不限）。
        """
        pygame.init()
        flags = pygame.RESIZABLE
        self.screen = pygame.display.set_mode((self.W, self.H), flags)
        pygame.display.set_caption("KARDS 简化版 — 战场")
        self.clock = pygame.time.Clock()
        self._lunge_state = getattr(self, "_lunge_state", {})
        frames = 0
        try:
            while self.running:
                dt = self.clock.tick(fps)
                self.step(dt)
                self._ensure_sync()
                for ev in pygame.event.get():
                    self.handle_event(ev)
                    if not self.running:
                        break
                if pump is not None:
                    try:
                        pump()
                    except Exception:
                        # 泵 Tk 事件时可能遇到窗口销毁等良性异常；
                        # 但真 bug 也不能吞 —— 打到 stderr 保底可见
                        import traceback
                        traceback.print_exc()
                self.draw(self.screen)
                pygame.display.flip()
                frames += 1
                if max_frames is not None and frames >= max_frames:
                    break
                if self.end_state is not None and self.game is None:
                    break
        finally:
            self.screen = None
            self.clock = None
            pygame.display.quit()

    # ================= 绘制 =================

    def draw(self, surf):
        g = self._game_state()
        surf.fill(C(BG))
        if g is None:
            return
        self._ensure_sync()
        me, foe = g.players[0], g.players[1]
        human_turn = g.current is me
        L = self.layout()

        # 整屏震动偏移
        sx, sy = self.shake_off if self._anim_on() else (0, 0)
        content = surf.copy() if (sx or sy) else None
        target = content if content is not None else surf

        self._draw_info(target, L, g, me, foe, human_turn)
        self._draw_rows(target, L, g, me, foe)
        self._draw_log(target, L)
        self._draw_hand(target, L, g, me, human_turn)
        self._draw_buttons(target, L, g, human_turn)
        self._draw_drag(target, L)
        self._draw_fx(target)

        if content is not None:
            surf.blit(content, (sx, sy))

        if self.hover_ref is not None and self.drag is None:
            self._draw_tooltip(surf, self.hover_ref)
        if self.pause:
            self._draw_pause(surf)
        if self.end_state is not None:
            self._draw_end(surf)
        if self.banner is not None:
            self._draw_banner(surf)

    def _draw_info(self, surf, L, g, me, foe, human_turn):
        turn_tag = "" if human_turn else t("turn_tag")
        txt = t("foe_info", name=foe.name, nation=foe.nation, hq=foe.hq,
                hand=len(foe.hand), kr=foe.kredits,
                cnt=len(foe.counters), tag=turn_tag)
        surf.blit(font(16, True).render(txt, True, C(RED)), (L["info_foe"].x, L["info_foe"].y))
        counter_txt = (t("counter_zone") + " | ".join(c.name for c in me.counters)) if me.counters else ""
        txt2 = t("my_info", name=me.name, nation=me.nation, hq=me.hq,
                 kr=me.kredits, deck=len(me.deck),
                 perk=me.hq_card.perk_desc, counters=counter_txt)
        y = L["info_my"].y
        for ln in wrap_text(txt2, font(14), L["info_my"].w)[:3]:
            surf.blit(font(14).render(ln, True, C(TEXT)), (L["info_my"].x, y))
            y += 18

    def _draw_rows(self, surf, L, g, me, foe):
        # 行框 + 标题
        caps = (("cap_foe_rear", "row_foe_rear", t("row_foe_rear")),
                ("cap_foe_front", "row_foe_front", t("row_foe_front")),
                ("cap_my_front", "row_my_front", t("row_my_front")),
                ("cap_my_rear", "row_my_rear", t("row_my_rear")))
        for capk, rowk, label in caps:
            rr(surf, L[rowk], C(ROW_BG), radius=8, border_color=C(ROW_EDGE))
            y0 = L[capk].y + 8
            for ln in wrap_text(label, font(13), L[capk].w):
                surf.blit(font(13).render(ln, True, C(DIM)), (L[capk].x, y0))
                y0 += 17

        # 前线占领条
        rr(surf, L["mid"], C(MID_BG), radius=6)
        owner = g.frontline_owner()
        own_front = sum(1 for u in me.board if u.position == "前线")
        if owner is None:
            ftxt, ffg = t("front_none"), DIM
        elif owner is me:
            ftxt, ffg = t("front_mine", n=own_front, total=core.FRONTLINE_SLOTS), GOLD
        else:
            ftxt, ffg = t("front_foe"), RED
        f = font(16, True)
        surf.blit(f.render(ftxt, True, C(ffg)),
                  (L["mid"].centerx - f.size(ftxt)[0] // 2,
                   L["mid"].centery - 11))

        # 敌方总部
        self._draw_hq(surf, g, foe)

        # 我方总部（与敌方同款样式，蓝色调区分；结算时也会在这里爆炸）
        self._draw_hq(surf, g, me, ref=self.my_hq_ref)

        # 单位
        lunge = getattr(self, "_lunge_state", {})
        for ref in self.unit_refs.values():
            off = lunge.get(id(ref.unit))
            ox, oy = (off["dx"], off["dy"]) if off else (0, 0)
            if ref.fly is not None:
                self._draw_fly_token(surf, ref)
                continue
            self._draw_unit(surf, ref, g, ox, oy)

        # 拖拽高亮
        if self.drag is not None:
            kind, extra = self.zone_at(self.drag["pos"])
            if kind is not None:
                ok = self.valid_drop(kind, extra)
                col = C(GREEN) if ok else C(RED)
                zr = None
                if kind in ("deploy", "front"):
                    zr = L["row_my_rear" if kind == "deploy" else "row_my_front"]
                elif kind == "hq":
                    zr = self.hq_ref.rect
                else:
                    for u, ref in self.enemy_refs:
                        if u is extra:
                            zr = ref.rect
                if zr is not None:
                    rr(surf, zr.inflate(6, 6), col, radius=8, width=3)

    def _draw_hq(self, surf, g, foe, ref=None):
        """总部卡（含血量心形）。ref 可显式指定（我方总部），默认敌方总部。

        结算爆炸：ref.blast_t0 有值时，按虚拟时钟展开冲击波 + 白光，
        让玩家明确看到「是哪边总部先炸的」。
        """
        ref = ref if ref is not None else self.hq_ref
        if ref is None:
            return
        r = ref.rect
        mine = ref is self.my_hq_ref
        if mine:
            rr(surf, r, C("#24303a"), radius=8, border_color=C("#3a6a8a"))
        else:
            rr(surf, r, C("#3a2430"), radius=8, border_color=C("#8a3a3a"))
        img = hq_image(foe.nation, r.w - 12, r.h - 44)
        if img is not None:
            surf.blit(img, (r.x + 6, r.y + 6))
        else:
            f = font(15, True)
            hq_txt = t("my_hq") if mine else t("foe_hq")
            surf.blit(f.render(hq_txt, True, C(TEXT)),
                      (r.centerx - f.size(hq_txt)[0] // 2, r.y + 14))
            tint = "#88aacc" if mine else "#cc8888"
            surf.blit(font(26).render(foe.nation, True, C(tint)),
                      (r.centerx - font(26).size(foe.nation)[0] // 2, r.y + 40))
        hp = font(22, True)
        htxt = str(foe.hq)
        hw = hp.size(htxt)[0]
        # 心形自绘（♥ 在 pygame 里渲染成方块，见模块头 plain() 说明）
        hx, hy = r.centerx - hw // 2 - 18, r.bottom - 22
        pygame.draw.polygon(surf, C(RED),
                            [(hx, hy + 6), (hx - 7, hy - 2), (hx - 4, hy - 7),
                             (hx, hy - 3), (hx + 4, hy - 7), (hx + 7, hy - 2)])
        surf.blit(hp.render(htxt, True, C(RED)),
                  (r.centerx - hw // 2 + 6, r.bottom - 30))
        # ---- 结算爆炸特效 ----
        if ref.blast_t0 is not None:
            self._draw_blast(surf, r, ref.blast_t0)

    def _draw_blast(self, surf, r, t0):
        """总部爆炸：扩散冲击波 + 中心白光 + 闪红（按虚拟时钟推进）"""
        dt = self.t_now - t0
        if dt < 0:
            return
        cx, cy = r.centerx, r.centery
        maxr = max(r.w, r.h) * 2.2
        # 冲击波圆环
        p = min(1.0, dt / 620.0)
        rad = int(maxr * p)
        alpha = int(200 * (1 - p))
        if rad > 0 and alpha > 0:
            ring = pygame.Surface((rad * 2 + 8, rad * 2 + 8), pygame.SRCALPHA)
            pygame.draw.circle(ring, (*C("#ff9c54"), alpha),
                               (rad + 4, rad + 4), rad, max(2, int(6 * (1 - p))))
            surf.blit(ring, (cx - rad - 4, cy - rad - 4))
        # 中心白光（前 260ms）
        if dt < 260:
            fa = int(235 * (1 - dt / 260.0))
            flash = pygame.Surface(r.size, pygame.SRCALPHA)
            flash.fill((255, 240, 200, fa))
            surf.blit(flash, r.topleft, special_flags=pygame.BLEND_RGBA_ADD)
        # 火球（前 700ms 逐渐膨胀）
        if dt < 700:
            fr = int(max(r.w, r.h) * (0.35 + 0.75 * (dt / 700.0)))
            fa = int(180 * (1 - dt / 700.0))
            ball = pygame.Surface((fr * 2, fr * 2), pygame.SRCALPHA)
            pygame.draw.circle(ball, (*C("#ff7a3c"), fa), (fr, fr), fr)
            pygame.draw.circle(ball, (*C("#ffe08a"), max(0, fa - 40)),
                               (fr, fr), int(fr * 0.55))
            surf.blit(ball, (cx - fr, cy - fr))

    def _draw_unit(self, surf, ref, g, ox=0, oy=0):
        r = ref.rect.move(ox, oy)
        u = ref.unit
        base = C(CARD_BG)
        border = C(GOLD) if (ref.ready and not self._busy()) else (
            C(ref.nat_color))
        rr(surf, r, base, radius=6, border_color=border)
        if ref.flash_tint and self.t_now < ref.flash_tint[1]:
            # 闪烁：按 220ms 周期开关
            if ((self.t_now // 110) % 2) == 0:
                tint = pygame.Surface(r.size, pygame.SRCALPHA)
                tint.fill((*C(ref.flash_tint[0]), 70))
                surf.blit(tint, r.topleft, special_flags=pygame.BLEND_RGBA_ADD)
        nf = font(14, True)
        name = truncate(u.name, nf, r.w - 16)
        surf.blit(nf.render(name, True, C(TEXT)), (r.x + 8, r.y + 6))
        sf = font(11)
        sub = f"#{u.slot} {u.unit_type}"
        surf.blit(sf.render(sub, True, C(DIM)), (r.x + 8, r.y + 26))
        # 关键字（取每词首字，做成小徽章）
        x = r.x + 8
        for kw in u.keywords:
            ch = kw[:1]
            wch = font(11).size(ch)[0] + 8
            rr(surf, (x, r.y + 44, wch, 16), C("#3a4150"), radius=3)
            surf.blit(font(11).render(ch, True, C(GOLD)), (x + 4, r.y + 46))
            x += wch + 4
        af = font(17, True)
        surf.blit(af.render(str(u.attack), True, C(RED)), (r.x + 10, r.bottom - 26))
        df = font(17, True)
        surf.blit(df.render(str(u.defense), True, C(GREEN)), (r.right - 26, r.bottom - 26))
        if ref.guard:
            # 小盾牌
            cx, cy = r.right - 16, r.y + 16
            pygame.draw.polygon(surf, C(GOLD),
                                [(cx - 7, cy - 8), (cx + 7, cy - 8),
                                 (cx + 7, cy + 2), (cx, cy + 9),
                                 (cx - 7, cy + 2)])

    def _draw_fly_token(self, surf, ref):
        """入场/行军飞行令牌（落地前只画令牌不画真身）"""
        src, t0, dur = ref.fly
        p = min(1.0, (self.t_now - t0) / max(1, dur))
        sx, sy = src
        ex, ey = ref.rect.centerx, ref.rect.centery
        # 弧线：中途抬升 60px
        lift = math.sin(p * math.pi) * 60
        x = sx + (ex - sx) * p
        y = sy + (ey - sy) * p - lift
        pygame.draw.circle(surf, C(GOLD), (int(x), int(y)), 9)
        pygame.draw.circle(surf, C("#15171c"), (int(x), int(y)), 5)
        if p >= 1.0:
            ref.fly = None

    def _draw_hand(self, surf, L, g, me, human_turn):
        rr(surf, L["hand"], C(HAND_AREA), radius=8)
        if not human_turn:
            txt = t("hand_hidden")
            f = font(15)
            surf.blit(f.render(txt, True, C(DIM)),
                      (L["hand"].x + 14, L["hand"].y + 20))
            return
        if not getattr(self, "hand_refs", []):
            txt = t("hand_empty")
            f = font(15)
            surf.blit(f.render(txt, True, C(DIM)),
                      (L["hand"].x + 14, L["hand"].y + 20))
            return
        drag_src = self.drag["idx"] if (self.drag and self.drag["kind"] == "hand") else None
        for ref in self.hand_refs:
            if ref.idx == drag_src:
                continue                    # 拖拽中的卡画成幽灵
            r = pygame.Rect(ref.rect)
            if self.hover_ref is ref:
                r.y -= 14
            self._draw_card(surf, ref.card, r, g, me, ref.ready)

    def _draw_card(self, surf, card, r, g, me, playable, eff_cost=None):
        nat = NATION_COLOR.get(card.nation, "#666")
        border = C(nat) if playable else C("#555555")
        rr(surf, r, C(CARD_BG), radius=8, border_color=border)
        if eff_cost is None:
            eff_cost = g.get_cost(card, me)
        # 费用圆
        pygame.draw.circle(surf, C("#10131a"), (r.x + 20, r.y + 20), 14)
        pygame.draw.circle(surf, C(GOLD), (r.x + 20, r.y + 20), 14, 2)
        cf = font(15, True)
        cs = str(eff_cost)
        surf.blit(cf.render(cs, True, C(GOLD)),
                  (r.x + 20 - cf.size(cs)[0] // 2, r.y + 20 - 10))
        # 研发被动折价时，把**原价**标在旁边 —— 否则玩家看到 2 费的坦克
        # 会以为费用记错了（tkinter 版有「（原 3）」提示，pygame 版之前没有）。
        # ⚠ 必须够亮够大：第一版用 11px + DIM 灰，截图放大才发现几乎看不见，
        #   玩家自然还是觉得"费用记错"（用户报障）。
        if eff_cost != getattr(card, "cost", eff_cost):
            of = font(13, True)
            os_ = f"原{card.cost}"
            surf.blit(of.render(os_, True, C("#c8a44a")),
                      (r.x + 38, r.y + 11))
        # 稀有度宝石
        gem = RARITY_COLOR.get(getattr(card, "rarity", None) or 3, C(DIM))
        gx, gy = r.right - 14, r.y + 14
        pygame.draw.polygon(surf, C(gem),
                            [(gx, gy - 6), (gx + 6, gy), (gx, gy + 6), (gx - 6, gy)])
        # 标题（最多两行）
        tf = font(14, True)
        lines = wrap_text(card.name, tf, r.w - 40)[:2]
        y = r.y + 38
        for ln in lines:
            surf.blit(tf.render(ln, True, C(TEXT)), (r.x + 10, y))
            y += 17
        # 图片区 / 兵种色带
        art = pygame.Rect(r.x + 10, y + 2, r.w - 20, 64)
        img = card_image(card.name, art.w, art.h)
        if img is not None:
            surf.blit(img, art.topleft)
        else:
            rr(surf, art, C(nat), radius=4)
            ch = (card.unit_type[:1] if card.kind == "unit"
                  else ("反" if card.kind == "counter" else "令"))
            bf = font(30, True)
            surf.blit(bf.render(ch, True, C("#15171c")),
                      (art.centerx - bf.size(ch)[0] // 2,
                       art.centery - bf.size(ch)[1] // 2))
        # 底部：单位攻/防；指令/反制描述
        if card.kind == "unit":
            kws = kw_text(card.keywords)
            kf = font(11)
            for ln in wrap_text(kws, kf, r.w - 20)[:1]:
                surf.blit(kf.render(ln, True, C(GOLD)), (r.x + 10, art.bottom + 4))
            af = font(19, True)
            surf.blit(af.render(str(card.attack), True, C(RED)),
                      (r.x + 14, r.bottom - 30))
            df = font(19, True)
            surf.blit(df.render(str(card.defense), True, C(GREEN)),
                      (r.right - 34, r.bottom - 30))
        else:
            df = font(11)
            tag = "【反制】" if card.kind == "counter" else "【指令】"
            desc = truncate(card.desc, df, r.w - 24)
            surf.blit(df.render(tag + desc, True, C(DIM)),
                      (r.x + 10, art.bottom + 4))
        if not playable:
            dim = pygame.Surface(r.size, pygame.SRCALPHA)
            dim.fill((10, 12, 16, 120))
            surf.blit(dim, r.topleft)

    def _draw_log(self, surf, L):
        rr(surf, L["log"], C(LOG_BG), radius=8, border_color=C(ROW_EDGE))
        surf.blit(font(13).render(t("log_title"), True, C(DIM)),
                  (L["log"].x + 8, L["log"].y + 6))
        f = font(12)
        lineh = 17
        maxlines = (L["log"].h - 30) // lineh
        lines = []
        for raw in self.log_lines:
            lines.extend(wrap_text(raw, f, L["log"].w - 20) or [""])
        total = len(lines)
        skip = max(0, total - maxlines - self.log_scroll)
        y = L["log"].y + 26
        for ln in lines[skip:skip + maxlines]:
            surf.blit(f.render(ln, True, C(TEXT)), (L["log"].x + 10, y))
            y += lineh

    def _draw_buttons(self, surf, L, g, human_turn):
        # 结束回合
        col = "#3a5a80" if human_turn else "#333a44"
        rr(surf, L["end_btn"], C(col), radius=8)
        f = font(16, True)
        label = t("btn_end_turn")
        surf.blit(f.render(label, True, C(TEXT if human_turn else DIM)),
                  (L["end_btn"].centerx - f.size(label)[0] // 2,
                   L["end_btn"].centery - 11))
        # 速度
        rr(surf, L["speed_btn"], C("#4a4f5a"), radius=8)
        fast = getattr(self.app, "fast_ai", False) if self.app else False
        label = t("btn_fast") if fast else t("btn_slow")
        f2 = font(13)
        surf.blit(f2.render(label, True, C(TEXT)),
                  (L["speed_btn"].centerx - f2.size(label)[0] // 2,
                   L["speed_btn"].centery - 9))
        # 菜单
        rr(surf, L["menu_btn"], C("#4a4f5a"), radius=8)
        label = t("btn_board_menu")
        f3 = font(13)
        surf.blit(f3.render(label, True, C(TEXT)),
                  (L["menu_btn"].centerx - f3.size(label)[0] // 2,
                   L["menu_btn"].centery - 9))

    def _draw_drag(self, surf, L):
        d = self.drag
        if d is None:
            return
        g = self._game_state()
        me = g.players[0]
        px, py = d["pos"]
        if d["kind"] == "hand":
            card = d["card"]
            r = pygame.Rect(px - self.HAND_CW // 2, py - self.HAND_CH // 2,
                            self.HAND_CW, self.HAND_CH)
            kind, _extra = self.zone_at(d["pos"])
            ok = self.valid_drop(kind, _extra) if kind else False
            border = C(GOLD) if ok else C("#7a4a4a")
            self._draw_card(surf, card, r, g, me, True)
            rr(surf, r, border, radius=8, width=3)
        else:
            u = d["unit"]
            r = pygame.Rect(px - self.UNIT_W // 2, py - self.UNIT_H // 2,
                            self.UNIT_W, self.UNIT_H)
            kind, _extra = self.zone_at(d["pos"])
            ok = self.valid_drop(kind, _extra) if kind else False
            rr(surf, r, C(CARD_BG), radius=6,
               border_color=C(GOLD) if ok else C("#7a4a4a"))
            nf = font(14, True)
            name = truncate(u.name, nf, r.w - 16)
            surf.blit(nf.render(name, True, C(TEXT)), (r.x + 8, r.y + 6))
            af = font(16, True)
            surf.blit(af.render(f"{u.attack}/{u.defense}", True, C(TEXT)),
                      (r.centerx - af.size(f"{u.attack}/{u.defense}")[0] // 2,
                       r.centery))

    def _draw_fx(self, surf):
        # 冲击环
        for ring in self.rings:
            p = (self.t_now - ring["t0"]) / ring["dur"]
            rad = int(10 + 46 * p)
            alpha = int(200 * (1 - p))
            pts = []
            for i in range(20):
                a = i * math.pi / 10
                pts.append((ring["x"] + rad * math.cos(a),
                            ring["y"] + rad * math.sin(a)))
            if len(pts) > 2:
                pygame.draw.lines(surf, C(ring["color"]), False, pts, 3)
        # 浮动文字
        for fl in self.floats:
            p = (self.t_now - fl["t0"]) / fl["dur"]
            y = fl["y"] - 34 * p
            f = font(17, True)
            surf.blit(f.render(fl["text"], True, C(fl["color"])),
                      (fl["x"] - f.size(fl["text"])[0] // 2, y))
        # 结算粒子
        for pt in self.particles:
            age = self.t_now - pt["t0"]
            if age < 0 or age > pt["dur"]:
                continue
            p = age / pt["dur"]
            x = pt["x"] + pt["vx"] * age / 1000
            y = pt["y"] + pt["vy"] * age / 1000 + 300 * p * p
            pygame.draw.circle(surf, C(pt["color"]), (int(x), int(y)), pt["size"])

    def _draw_banner(self, surf):
        b = self.banner
        f = font(30, True)
        w, h = f.size(b["text"])
        pad = 18
        rect = pygame.Rect(self.W // 2 - w // 2 - pad, self.H // 3 - h,
                           w + pad * 2, h + pad)
        rr(surf, rect, C("#10131a"), radius=10, border_color=C(b["color"]))
        surf.blit(f.render(b["text"], True, C(b["color"])),
                  (rect.centerx - w // 2, rect.centery - h // 2))

    def _draw_tooltip(self, surf, ref):
        """悬停详情面板（卡牌/单位）"""
        g = self._game_state()
        if g is None:
            return
        me = g.players[0]
        lines = []
        c = ref.card if ref.kind == "hand" else getattr(ref.unit, "card", None)
        u = ref.unit
        if ref.kind == "hand":
            card = ref.card
            eff = g.get_cost(card, me)
            lines.append((card.name, TEXT, True))
            if card.kind == "unit":
                lines.append((f"{card.nation} · {card.unit_type} · {card.attack}/{card.defense}", DIM, False))
            else:
                tag = "反制" if card.kind == "counter" else "指令"
                lines.append((f"{card.nation} · [{tag}]", DIM, False))
            lines.append((f"费用 {eff}" + (f"（原 {card.cost}）" if eff != card.cost else ""), GOLD, False))
            if card.kind == "unit":
                if card.keywords:
                    lines.append((kw_text(card.keywords), GOLD, False))
            else:
                for ln in wrap_text(card.desc, font(13), 300):
                    lines.append((ln, TEXT, False))
        elif u is not None:
            card = u.card
            lines.append((u.name, TEXT, True))
            lines.append((f"{card.nation} · {u.unit_type} · 当前 {u.attack}/{u.defense}", DIM, False))
            if u.keywords:
                lines.append((kw_text(u.keywords), GOLD, False))
        if not lines:
            return
        w = 330
        h = 26 + sum(20 for _ in lines)
        x = min(self.mouse[0] + 18, self.W - w - 8)
        y = min(self.mouse[1] + 18, self.H - h - 8)
        panel = pygame.Rect(x, y, w, h)
        rr(surf, panel, C("#10131a"), radius=8, border_color=C(GOLD))
        yy = y + 10
        for text, color, bold in lines:
            f = font(13, bold)
            surf.blit(f.render(text, True, C(color)), (x + 12, yy))
            yy += 20

    def _draw_pause(self, surf):
        dim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        dim.fill((8, 10, 14, 170))
        surf.blit(dim, (0, 0))
        items = self._pause_items()
        w, h = 320, 60 * len(items) + 90
        x0, y0 = (self.W - w) // 2, (self.H - h) // 2
        rr(surf, (x0, y0, w, h), C(PANEL), radius=10, border_color=C(GOLD))
        f = font(20, True)
        title = t("pause_title")
        surf.blit(f.render(title, True, C(GOLD)),
                  (self.W // 2 - f.size(title)[0] // 2, y0 + 18))
        for i, (key, label) in enumerate(items):
            r = pygame.Rect(x0 + 20, y0 + 70 + i * 60, w - 40, 46)
            confirm = self.pause_confirm == key
            col = "#8a3a3a" if key in ("concede",) else "#3a5a80"
            if key == "quit":
                col = "#4a4f5a"
            rr(surf, r, C(col), radius=8)
            txt = (t("confirm_again") if confirm else label)
            bf = font(15, True)
            surf.blit(bf.render(txt, True, C(TEXT)),
                      (r.centerx - bf.size(txt)[0] // 2, r.centery - 10))

    def _draw_end(self, surf):
        """结算画面。

        ⚠ 必须分阶段（用户要求）：phase="hq" 时**不画胜负大字** —— 只有总部
        位置的爆炸 + 「XX总部被摧毁」提示，让玩家先看清是哪边炸的；
        爆炸播完（phase="full"）才弹出胜利/战败大字与徽章。
        """
        phase = self._end_phase()
        if phase == "hq":
            # 爆炸阶段：只压一层薄暗罩 + 顶部提示，不遮挡战场（总部要看得到）
            dim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            dim.fill((13, 16, 23, 110))
            surf.blit(dim, (0, 0))
            tip = getattr(self, "_hq_fall_tip", None)
            if tip is not None and self.t_now < tip["until"]:
                f = font(40, True)
                tw = f.size(tip["text"])[0]
                box = pygame.Rect(0, int(self.H * 0.10), tw + 64, 62)
                box.centerx = self.W // 2
                rr(surf, box, C("#2a1a12"), radius=10,
                   border_color=C("#ff9c54"))
                surf.blit(f.render(tip["text"], True, C("#ffb347")),
                          (box.centerx - tw // 2, box.centery - 24))
            # 爆炸闪屏：整屏橙色泛光（前 300ms）
            st = self.end_state
            dt = self.t_now - st.get("phase_at", self.t_now)
            if dt < 300:
                fa = int(90 * (1 - dt / 300.0))
                fw = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
                fw.fill((255, 170, 90, fa))
                surf.blit(fw, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
            return

        won = self.end_state["won"]
        dim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        dim.fill((13, 16, 23, 235))
        surf.blit(dim, (0, 0))
        txt, color = ((t("draw_big"), DIM) if won is None
                      else (t("win_big"), GOLD) if won else (t("lose_big"), RED))
        # 大字弹出：phase 切换后 260ms 内从小到大（更有冲击力）
        st = self.end_state
        gp = min(1.0, (self.t_now - st.get("phase_at", self.t_now)) / 260.0)
        f = font(64, True)
        if gp < 1.0:
            # 放大登场：用 smoothscale 缩放渲染结果，围绕中心插值
            base = f.render(txt, True, C(color))
            scale = 0.55 + 0.45 * gp
            w = max(1, int(base.get_width() * scale))
            h = max(1, int(base.get_height() * scale))
            big = pygame.transform.smoothscale(base, (w, h))
            surf.blit(big, (self.W // 2 - w // 2,
                            int(self.H * 0.36) - h // 2))
        else:
            surf.blit(f.render(txt, True, C(color)),
                      (self.W // 2 - f.size(txt)[0] // 2, int(self.H * 0.34)))
        sub = (t("win_sub") if won is True
               else (t("lose_sub") if won is False else t("draw_sub")))
        f2 = font(18)
        surf.blit(f2.render(sub, True, C(DIM)),
                  (self.W // 2 - f2.size(sub)[0] // 2, int(self.H * 0.52)))
        # 国家徽章（简化版：圆盘 + 首字）
        nation = self.end_state.get("nation") or ""
        main = C(GOLD) if won else C("#6a7076")
        cx, cy = self.W // 2, int(self.H * 0.24)
        pygame.draw.circle(surf, main, (cx, cy), 56, 4)
        nf = font(40, True)
        ch = nation[:1] if nation else "★"
        surf.blit(nf.render(ch, True, C(TEXT)),
                  (cx - nf.size(ch)[0] // 2, cy - 28))
        if self.t_now >= self.end_state["ready_at"]:
            hint = t("click_hint")
            f3 = font(15)
            surf.blit(f3.render(hint, True, C(DIM)),
                      (self.W // 2 - f3.size(hint)[0] // 2, int(self.H * 0.68)))


# ---------------------------------------------------------------- 冒烟自检

class _FakeApp:
    """smoke 用最小 App 替身（无 Tk）"""

    def __init__(self, game):
        self.game = game
        self.busy = False
        self.anim_enabled = True
        self.fast_ai = False
        self.intents = []
        self.logs = []

    def pyboard_intent(self, act):
        self.intents.append(act)

    def add_log(self, msg):
        self.logs.append(msg)


def smoke(frames=600):
    """--board-smoke：dummy 驱动下跑若干帧 + 模拟操作，不崩即过"""
    import random as _r
    _r.seed(20261004)
    db = core.card_database()
    p1 = core.Player("你", "德国", core.build_deck("德国", db))
    p2 = core.Player("AI", "苏联", core.build_deck("苏联", db))
    g = core.Game(p1, p2, interactive=False)
    g.log = lambda *a, **k: None
    g.draw_cards(p1, core.START_HP)
    g.draw_cards(p2, core.START_HP)
    g.start_turn()
    app = _FakeApp(g)
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    b = PygameBoard(app, game=g, on_intent=app.pyboard_intent)
    b.run(max_frames=60)
    # 模拟部署：打出第一张可部署的单位（费用足够 + 支援线有空位）
    me = g.players[0]
    b.sync()
    idx = next((r.idx for r in b.hand_refs
                if r.card.kind == "unit" and r.ready), None)
    if idx is not None:
        b.on_intent({"k": "play", "idx": idx})
        b.step(500)
    # 模拟拖一张手牌到敌区（非法落点）→ 应只记日志不发意图
    if me.hand:
        b.drag = {"kind": "hand", "idx": 0, "card": me.hand[0],
                  "pos": (100, 100), "moved": True}
        b._handle_release(type("E", (), {"pos": (100, 100)})())
        b.drag = None
    # 结束回合 + AI 阶段跑一段
    app.intents.clear()
    b.on_intent({"k": "end"})
    b.step(2000)
    b.run(max_frames=frames - 120)
    assert app.intents and app.intents[0]["k"] in ("play", "end")
    return True


if __name__ == "__main__":
    print("smoke:", "OK" if smoke() else "FAIL")
