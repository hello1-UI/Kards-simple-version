# -*- coding: utf-8 -*-
"""KARDS 安装程序 / 卸载程序共用的 tkinter 控件库。

设计约束（改之前先读）：
  · 本模块**只在 main_gui() 里延迟 import**。install.py / uninstall.py 的顶层
    绝不能 import tkinter —— 受管 Python 环境里没有 tkinter，而控制台模式
    （--cli 与全部回归测试）必须仍能跑起来。
  · 只依赖标准库，不 import 游戏本体（安装器是独立打包的 exe）。
  · 视觉与游戏内保持一致：钢蓝灰底 + 金色点缀（kards_theme 的 frontline 预设）。
"""
import ctypes
import tkinter as tk
import tkinter.font as tkfont

# ------------------------------------------------------------------ 配色
C = {
    "bg": "#14171c",
    "bg_alt": "#0f1216",
    "panel": "#1c2028",
    "panel_alt": "#252b35",
    "border": "#2e3543",
    "border_hi": "#495364",
    "text": "#e6e8ec",
    "dim": "#98a0ac",
    "mute": "#68707d",
    "accent": "#4c7fb8",
    "accent_hi": "#5c94d0",
    "gold": "#e0b45c",
    "green": "#6fbf73",
    "red": "#e05c5c",
    "log_bg": "#0f1216",
}

# 中文字体候选（按优先级）。tkinter 显式指定字族时不会跨族回退，
# 精简版 Windows 上没有雅黑就会整屏方块，所以必须探测真实存在的字族。
_CJK = (
    "Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑",
    "DengXian", "等线", "SimHei", "黑体", "SimSun", "宋体",
    "Noto Sans SC", "Noto Sans CJK SC", "Source Han Sans SC",
    "PingFang SC", "Hiragino Sans GB", "Yu Gothic UI", "Malgun Gothic",
)
_FAMILY = "Microsoft YaHei UI"
_FONT_CACHE = {}


def set_family(name):
    global _FAMILY
    _FAMILY = name
    _FONT_CACHE.clear()


def get_family():
    return _FAMILY


def pick_font(root):
    """挑一个系统上真实存在的中文字族，返回选中的名字。"""
    try:
        fams = {}
        for f in tkfont.families(root):
            fams[f.lower()] = f
    except Exception:
        return _FAMILY
    for want in _CJK:
        got = fams.get(want.lower())
        if got:
            set_family(got)
            return got
    return _FAMILY


def F(size=10, weight="normal"):
    """取一个缓存的字体对象（Canvas/Label 都能直接用）。"""
    key = (size, weight)
    f = _FONT_CACHE.get(key)
    if f is None:
        try:
            f = tkfont.Font(family=_FAMILY, size=size, weight=weight)
        except Exception:
            return (_FAMILY, size, weight)
        _FONT_CACHE[key] = f
    return f


def init_dpi():
    """声明 DPI 感知，否则 150%/200% 缩放的屏幕上整个界面是放大的糊图。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # PROCESS_PER_MONITOR
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def dpi_scale(widget):
    """返回相对 96dpi 的缩放系数（1.0 / 1.25 / 1.5 …）。

    DPI 感知进程里 tk 的像素坐标就是物理像素，而字体按 point 自动放大 ——
    所以所有用像素写死的尺寸（窗口、按钮宽）都要乘这个系数。
    """
    try:
        f = widget.winfo_fpixels("1i") / 96.0
    except Exception:
        return 1.0
    return max(1.0, min(f, 2.5))


def _bg_of(widget):
    try:
        return widget.cget("bg") or C["bg"]
    except Exception:
        return C["bg"]


def round_rect(cv, x1, y1, x2, y2, r, **kw):
    """在 Canvas 上画圆角矩形（平滑多边形近似，r 建议 6~10）。"""
    r = max(0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return cv.create_polygon(pts, smooth=True, splinesteps=36, **kw)


# ------------------------------------------------------------------ 按钮
class Button(tk.Canvas):
    """自绘按钮：tk 原生按钮在深色底上无法做出圆角与悬停态。"""

    _KIND = {
        "primary": dict(fill=C["accent"], fg="#ffffff",
                        hfill=C["accent_hi"], hfg="#ffffff", border=""),
        "gold": dict(fill=C["gold"], fg="#191c22",
                     hfill="#eec46c", hfg="#191c22", border=""),
        "ghost": dict(fill="", fg=C["dim"],
                      hfill=C["panel_alt"], hfg=C["text"], border=C["border_hi"]),
        "danger": dict(fill="", fg=C["red"],
                       hfill="#3a2327", hfg="#ff8b8b", border="#7c4141"),
        "flat": dict(fill="", fg=C["mute"], hfill=C["panel"],
                     hfg=C["text"], border=""),
    }

    def __init__(self, master, text, command=None, kind="ghost", height=34,
                 width=None, pad_x=20, size=10, weight="normal", radius=8):
        self._parent_bg = _bg_of(master)
        self._kind = kind
        self._text = text
        self._size = size
        self._weight = weight
        self._radius = radius
        self._command = command
        self._state = "normal"
        self._hover = False
        f = dpi_scale(master)
        if width:
            width = int(width * f)
        w = width or (F(size, weight).measure(text) + int(pad_x * 2 * f))
        tk.Canvas.__init__(self, master, width=w, height=height,
                           bg=self._parent_bg, highlightthickness=0, bd=0,
                           takefocus=0)
        self._cw, self._ch = w, height
        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    # -- 对外
    def set_text(self, text, width=None):
        self._text = text
        f = dpi_scale(self)
        w = width or (F(self._size, self._weight).measure(text) + int(40 * f))
        if w != self._cw:
            self._cw = w
            self.configure(width=w)
        self._draw()

    def set_state(self, state):
        self._state = state
        self.configure(cursor="hand2" if state == "normal" else "arrow")
        self._hover = False
        self._draw()

    def set_kind(self, kind):
        self._kind = kind
        self._draw()

    def set_command(self, command):
        self._command = command

    # -- 内部
    def _colors(self):
        k = self._KIND[self._kind]
        if self._state != "normal":
            return (k["fill"] or C["panel"]), C["mute"], C["border"]
        if self._hover:
            return (k["hfill"] or k["fill"]), k["hfg"], k.get("border") or ""
        return k["fill"], k["fg"], k.get("border") or ""

    def _draw(self):
        self.delete("all")
        fill, fg, border = self._colors()
        w, h, r = self._cw, self._ch, self._radius
        if fill:
            round_rect(self, 0.5, 0.5, w - 0.5, h - 0.5, r, fill=fill, outline="")
        if border:
            round_rect(self, 0.5, 0.5, w - 0.5, h - 0.5, r, fill="",
                       outline=border, width=1)
        self.create_text(w / 2.0, h / 2.0 - 0.5, text=self._text, fill=fg,
                         font=F(self._size, self._weight))

    def _on_enter(self, _e=None):
        if self._state == "normal":
            self._hover = True
            self._draw()

    def _on_leave(self, _e=None):
        if self._hover:
            self._hover = False
            self._draw()

    def _on_press(self, _e=None):
        if self._state == "normal":
            self.move_all = 0
            self._draw()

    def _on_release(self, e=None):
        if self._state != "normal" or self._command is None:
            return
        if e is not None:
            if not (0 <= e.x <= self._cw and 0 <= e.y <= self._ch):
                return
        try:
            self._command()
        except Exception:
            import traceback
            traceback.print_exc()


# ------------------------------------------------------------------ 勾选框
class Check(tk.Frame):
    """自绘 ☑ 勾选框，支持一行说明文字（副标题）。整行可点。"""

    def __init__(self, master, text, value=True, command=None, sub="",
                 size=10):
        bg = _bg_of(master)
        tk.Frame.__init__(self, master, bg=bg)
        self._value = bool(value)
        self._command = command
        self._hover = False
        self._box_size = 18

        self.box = tk.Canvas(self, width=18, height=18, bg=bg,
                             highlightthickness=0, bd=0)
        self.box.pack(side="left", anchor="n", pady=(2 if sub else 0, 0))

        holder = tk.Frame(self, bg=bg)
        holder.pack(side="left", fill="x", expand=True, padx=(9, 0))
        self.lbl = tk.Label(holder, text=text, bg=bg, fg=C["text"],
                            font=F(size), anchor="w", justify="left")
        self.lbl.pack(anchor="w")
        self.sub = None
        if sub:
            self.sub = tk.Label(holder, text=sub, bg=bg, fg=C["mute"],
                                font=F(9), anchor="w", justify="left")
            self.sub.pack(anchor="w", pady=(1, 0))

        for w in (self, self.box, holder, self.lbl) + ((self.sub,) if sub else ()):
            w.bind("<Button-1>", self._toggle)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)
            try:
                w.configure(cursor="hand2")
            except tk.TclError:
                pass
        self._paint()

    def get(self):
        return self._value

    def set(self, value, notify=False):
        self._value = bool(value)
        self._paint()
        if notify and self._command:
            self._command(self._value)

    def set_enabled(self, ok):
        self.configure(cursor="hand2" if ok else "arrow")

    def _paint(self):
        self.box.delete("all")
        s = self._box_size
        if self._value:
            round_rect(self.box, 0.5, 0.5, s - 0.5, s - 0.5, 4,
                       fill=C["accent"], outline="")
            self.box.create_line(4.5, 9.0, 7.6, 12.4, 13.6, 5.2,
                                 fill="#ffffff", width=2,
                                 capstyle="round", joinstyle="round")
        else:
            edge = C["border_hi"] if self._hover else "#3d4553"
            round_rect(self.box, 0.5, 0.5, s - 0.5, s - 0.5, 4,
                       fill="", outline=edge, width=1)

    def _toggle(self, _e=None):
        self.set(not self._value, notify=True)

    def _enter(self, _e=None):
        self._hover = True
        self._paint()

    def _leave(self, _e=None):
        # 指针在子控件之间移动也会触发 Leave，用坐标判断是否还在整行内
        try:
            x, y = self.winfo_pointerxy()
            rx, ry = self.winfo_rootx(), self.winfo_rooty()
            if rx <= x <= rx + self.winfo_width() and \
                    ry <= y <= ry + self.winfo_height():
                return
        except tk.TclError:
            pass
        self._hover = False
        self._paint()


# ------------------------------------------------------------------ 进度条
class Progress(tk.Canvas):
    """细进度条。set(None) 进入「不确定」模式（测速/等待时来回滑动）。"""

    def __init__(self, master, height=8):
        bg = _bg_of(master)
        tk.Canvas.__init__(self, master, height=height, bg=bg,
                           highlightthickness=0, bd=0)
        self._ch = height
        self._frac = 0.0
        self._indet = False
        self._phase = 0.0
        self._tone = C["accent"]
        self._anim = None
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, frac, tone=None):
        if tone:
            self._tone = tone
        if frac is None:
            if not self._indet:
                self._indet = True
                self._start_anim()
        else:
            self._indet = False
            self._stop_anim()
            self._frac = max(0.0, min(1.0, float(frac)))
        self._draw()

    def reset(self):
        self._tone = C["accent"]
        self.set(0.0)

    def _start_anim(self):
        if self._anim is None:
            self._tick()

    def _stop_anim(self):
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except Exception:
                pass
            self._anim = None

    def _tick(self):
        self._anim = None
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self._phase = (self._phase + 0.022) % 1.0
        self._draw()
        try:
            self._anim = self.after(33, self._tick)
        except tk.TclError:
            self._anim = None

    def destroy(self):
        self._stop_anim()
        tk.Canvas.destroy(self)

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self._ch
        if w <= 1:
            return
        round_rect(self, 0, 0, w, h, h / 2.0, fill=C["panel"], outline="")
        if self._indet:
            seg = w * 0.28
            x = (w + seg) * self._phase - seg
            x1, x2 = max(0, x), min(w, x + seg)
            if x2 - x1 > 2:
                round_rect(self, x1, 0, x2, h, h / 2.0,
                           fill=C["border_hi"], outline="")
            return
        if self._frac <= 0:
            return
        fill_w = max(h, w * self._frac)
        round_rect(self, 0, 0, fill_w, h, h / 2.0, fill=self._tone, outline="")


# ------------------------------------------------------------------ 日志框
class LogBox(tk.Frame):
    """只读滚动日志。自动跟到底部；用户手动上翻时不抢滚动。"""

    def __init__(self, master, height=7):
        bg = _bg_of(master)
        tk.Frame.__init__(self, master, bg=C["log_bg"],
                          highlightbackground=C["border"], highlightthickness=1)
        self.t = tk.Text(self, bg=C["log_bg"], fg=C["dim"], bd=0,
                         relief="flat", highlightthickness=0, wrap="word",
                         font=F(9), padx=10, pady=8, height=height,
                         insertbackground=C["dim"], spacing1=1, spacing3=1,
                         selectbackground=C["panel_alt"], cursor="arrow")
        self.t.pack(fill="both", expand=True)
        self.t.configure(state="disabled")
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.t.bind(seq, self._wheel)
        self.t.bind("<Key>", lambda e: "break" if e.keysym not in
                    ("Up", "Down", "Prior", "Next", "Home", "End") else None)
        self._blank = False

    def push(self, line):
        if line == "":
            if self._blank:          # 不堆连续空行
                return
            self._blank = True
        else:
            self._blank = False
        try:
            at_bottom = self.t.yview()[1] >= 0.995
        except tk.TclError:
            return
        self.t.configure(state="normal")
        self.t.insert("end", line + "\n")
        # 行数上限，防止几千行日志拖慢重绘
        try:
            total = int(self.t.index("end-1c").split(".")[0])
            if total > 600:
                self.t.delete("1.0", f"{total - 500}.0")
        except (tk.TclError, ValueError):
            pass
        self.t.configure(state="disabled")
        if at_bottom:
            self.t.see("end")

    def clear(self):
        self.t.configure(state="normal")
        self.t.delete("1.0", "end")
        self.t.configure(state="disabled")
        self._blank = False

    def _wheel(self, e):
        delta = 1 if getattr(e, "num", None) == 5 else -1
        if getattr(e, "num", None) is None:
            delta = -1 if e.delta > 0 else 1
        try:
            self.t.yview_scroll(delta, "units")
        except tk.TclError:
            pass
        return "break"


# ------------------------------------------------------------------ 标题区
class Header(tk.Frame):
    def __init__(self, master, title, subtitle, right=""):
        bg = _bg_of(master)
        tk.Frame.__init__(self, master, bg=bg)
        inner = tk.Frame(self, bg=bg)
        inner.pack(fill="x", padx=24, pady=(20, 18))

        logo = tk.Canvas(inner, width=44, height=44, bg=bg,
                         highlightthickness=0, bd=0)
        logo.pack(side="left")
        round_rect(logo, 1, 1, 43, 43, 9, fill=C["accent"], outline="")
        logo.create_text(22, 22, text="K", fill="#ffffff", font=F(21, "bold"))

        text = tk.Frame(inner, bg=bg)
        text.pack(side="left", padx=(13, 0))
        tk.Label(text, text=title, bg=bg, fg=C["text"],
                 font=F(17, "bold")).pack(anchor="w")
        tk.Label(text, text=subtitle, bg=bg, fg=C["mute"],
                 font=F(9)).pack(anchor="w", pady=(2, 0))

        if right:
            tk.Label(inner, text=right, bg=bg, fg=C["mute"],
                     font=F(8)).pack(side="right", anchor="n")

        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")


class Divider(tk.Frame):
    def __init__(self, master):
        tk.Frame.__init__(self, master, bg=C["border"], height=1)


# ------------------------------------------------------------------ 窗口基类
class BaseWindow(tk.Tk):
    """深色窗口：居中、暗色标题栏、DPI 感知、Esc = 关闭。"""

    def __init__(self, title, width=780, height=600, resizable=False):
        init_dpi()
        tk.Tk.__init__(self)
        self.withdraw()
        pick_font(self)
        self.configure(bg=C["bg"])
        self.title(title)
        self._want_w, self._want_h = width, height
        self.resizable(resizable, resizable)
        self.bind("<Escape>", lambda _e: self.on_close())
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._titlebar_done = False

    def show(self):
        self.update_idletasks()
        self._center()
        self.deiconify()
        try:
            self.attributes("-topmost", True)
            self.after(260, lambda: self._safe_topmost(False))
        except tk.TclError:
            pass
        self.after(30, self._dark_titlebar)
        try:
            self.focus_force()
        except tk.TclError:
            pass

    def _safe_topmost(self, on):
        try:
            self.attributes("-topmost", on)
        except tk.TclError:
            pass

    def _center(self):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        f = dpi_scale(self)
        w = min(int(self._want_w * f), int(sw * 0.94))
        h = min(int(self._want_h * f), int(sh * 0.92))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2 - int(sh * 0.02))
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(min(w, int(560 * f)), min(h, int(420 * f)))

    def _dark_titlebar(self):
        """让系统标题栏跟随深色（Win10 1809+ 属性 20，早期版本 19）。"""
        if self._titlebar_done:
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            if not hwnd:
                hwnd = self.winfo_id()
            val = ctypes.c_int(1)
            for attr in (20, 19):
                rc = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
                if rc == 0:
                    self._titlebar_done = True
                    break
        except Exception:
            pass

    def on_close(self):
        self.destroy()
