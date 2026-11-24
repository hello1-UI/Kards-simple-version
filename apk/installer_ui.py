# -*- coding: utf-8 -*-
"""KARDS 安装程序的图形界面。

⚠ 本模块只在 install.main_gui() 里延迟 import —— 它顶层会 import tkinter，
  而 install.py 的控制台模式（--cli / 回归测试）必须在没有 tkinter 的
  受管 Python 下也能跑。
"""
import ctypes
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog

import install
import setup_ui as ui

C = ui.C
PAD = 26


class _StreamToQueue:
    """把安装流程里的 print 输出转成界面日志。

    进度行是用 `\\r` 覆写的（`    [####----] 42%`）：`\\r` = 回到行首，
    所以它**之后**到下一个换行之间的内容才是当前状态行；它之前的残段
    （上一次进度行的尾巴）直接丢弃。普通行才进日志。
    """

    def __init__(self, put):
        self._put = put
        self._buf = ""
        self._after_cr = False
        self._blank = False

    def write(self, s):
        if not s:
            return 0
        self._buf += s
        while True:
            i_n = self._buf.find("\n")
            i_r = self._buf.find("\r")
            if i_r >= 0 and (i_n < 0 or i_r < i_n):
                # \r 覆写：把前面残留的旧状态段丢掉
                self._buf = self._buf[i_r + 1:]
                self._after_cr = True
                continue
            if i_n < 0:
                break
            seg = self._buf[:i_n]
            self._buf = self._buf[i_n + 1:]
            self._emit_line(seg)
            self._after_cr = False
        return len(s)

    def _emit_line(self, seg):
        if self._after_cr:
            # 进度行：只当状态；进度条结束后 print() 出的空行不推
            if seg.strip():
                self._blank = False
                self._put("status", seg.strip())
            return
        if seg.strip():
            self._blank = False
            self._put("log", seg.rstrip())
        elif not self._blank:
            self._blank = True
            self._put("log", "")

    def flush(self):
        pass

    def isatty(self):
        return False


class InstallerWindow(ui.BaseWindow):
    def __init__(self, install_dir, keep_models=None, auto=False):
        super().__init__("KARDS 简化版 安装程序", 782, 612)
        self._dir0 = install_dir or install.DEFAULT_DIR
        self._keep0 = True if keep_models is None else bool(keep_models)
        self._auto = auto
        self._q = queue.Queue(maxsize=4000)
        self._cancel = None
        self._worker = None
        self._finished = False
        self._pumping = False
        self._done_info = None
        self._busy = False
        self._build()
        self._on_progress(0.0, "准备就绪")
        self._ensure_pump()

    def _ensure_pump(self):
        """启动消息泵（幂等）：工作线程 / 统计线程的消息都从这里进界面。"""
        if not self._pumping:
            self._pumping = True
            self.after(60, self._pump)

    # -------------------------------------------------- 布局
    def _build(self):
        ui.Header(self, "KARDS 简化版",
                  "WWII CARD GAME  ·  安装程序",
                  right=f"v{install.app_version()}").pack(fill="x")

        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=PAD, pady=(18, 0))

        # --- 安装位置
        tk.Label(body, text="安装位置", bg=C["bg"], fg=C["dim"],
                 font=ui.F(9)).pack(anchor="w")
        row = tk.Frame(body, bg=C["bg"])
        row.pack(fill="x", pady=(6, 0))
        self.e_dir = tk.Entry(
            row, bg=C["panel"], fg=C["text"], insertbackground=C["text"],
            relief="flat", font=ui.F(10), bd=0,
            highlightthickness=1, highlightbackground=C["border"],
            highlightcolor=C["accent"])
        self.e_dir.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        self.e_dir.insert(0, self._dir0)
        self.e_dir.bind("<Return>", lambda _e: self._start())
        self.e_dir.bind("<FocusIn>",
                        lambda _e: self.e_dir.configure(
                            highlightbackground=C["border_hi"]))
        self.e_dir.bind("<FocusOut>",
                        lambda _e: self.e_dir.configure(
                            highlightbackground=C["border"]))
        ui.Button(row, "浏览…", command=self._browse, kind="ghost",
                  width=86).pack(side="left")

        self.lbl_hint = tk.Label(
            body, text="安装到 Program Files 需要管理员权限，会自动弹出授权窗口",
            bg=C["bg"], fg=C["mute"], font=ui.F(8), anchor="w", justify="left")
        self.lbl_hint.pack(anchor="w", pady=(6, 0))

        # --- 可选组件
        tk.Frame(body, bg=C["bg"], height=16).pack()
        n = install.bundled_models_count()
        sub = ("装完在「设置 → 外观」里一键换肤；不想要也可以随时删掉，不影响游戏本体"
               if n <= 0 else
               f"{n} 套配色，装完在「设置 → 外观」里一键换肤；"
               "不想要也可以随时删掉")
        self.chk_models = ui.Check(
            body, "安装内置 UI 模板", value=self._keep0, sub=sub)
        self.chk_models.pack(fill="x")

        # --- 进度
        tk.Frame(body, bg=C["bg"], height=18).pack()
        self.bar = ui.Progress(body, height=8)
        self.bar.pack(fill="x")

        srow = tk.Frame(body, bg=C["bg"])
        srow.pack(fill="x", pady=(8, 0))
        self.lbl_status = tk.Label(srow, text="", bg=C["bg"], fg=C["dim"],
                                   font=ui.F(9), anchor="w")
        self.lbl_status.pack(side="left", fill="x", expand=True)
        self.lbl_pct = tk.Label(srow, text="", bg=C["bg"], fg=C["mute"],
                                font=ui.F(9), anchor="e")
        self.lbl_pct.pack(side="right")

        # --- 日志
        tk.Frame(body, bg=C["bg"], height=14).pack()
        self.log = ui.LogBox(body, height=6)
        self.log.pack(fill="both", expand=True)

        # --- 底栏
        ui.Divider(self).pack(fill="x", side="bottom")
        foot = tk.Frame(self, bg=C["bg"], height=62)
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)

        self.lbl_foot = tk.Label(foot, text="", bg=C["bg"], fg=C["mute"],
                                 font=ui.F(8), anchor="w")
        self.lbl_foot.pack(side="left", padx=(PAD, 0))

        self.btn_close = ui.Button(foot, "关闭", command=self.on_close,
                                   kind="flat", width=72)
        self.btn_main = ui.Button(foot, "开始安装", command=self._start,
                                  kind="primary", width=112, height=36)
        self.btn_alt = ui.Button(foot, "取消", command=self._cancel_or_close,
                                 kind="ghost", width=96, height=36)
        # pack(side="right") 先放的在最右：主按钮 → 次按钮 → 关闭
        self.btn_main.pack(side="right", padx=(0, 10), pady=13)
        self.btn_alt.pack(side="right", pady=13)

    # -------------------------------------------------- 交互
    def _browse(self):
        cur = self.e_dir.get().strip() or install.DEFAULT_DIR
        start = cur if os.path.isdir(cur) else os.path.dirname(cur)
        try:
            picked = filedialog.askdirectory(
                parent=self, title="选择安装位置", initialdir=start,
                mustexist=False)
        except Exception:
            picked = ""
        if picked:
            picked = os.path.normpath(picked)
            base = os.path.basename(picked).lower()
            if base in ("kards-simple-version", "kards"):
                self.e_dir.delete(0, "end")
                self.e_dir.insert(0, picked)
            else:
                self.e_dir.delete(0, "end")
                self.e_dir.insert(0, os.path.join(picked, "KARDS"))

    def _cancel_or_close(self):
        if self._busy:
            self._cancel_install()
        else:
            self.on_close()

    def on_close(self):
        if self._busy:
            if not self._ask_quit():
                return
            if self._cancel is not None:
                self._cancel.set()
        self.destroy()

    def _ask_quit(self):
        try:
            import tkinter.messagebox as mb
            return mb.askyesno(
                "退出安装",
                "安装正在进行中。\n\n现在退出会中断安装，已解压的文件可能残留。\n"
                "确定要退出吗？", parent=self)
        except Exception:
            return True

    # -------------------------------------------------- 校验 + 启动
    def _target(self):
        raw = self.e_dir.get().strip().strip('"').strip("'").strip()
        if not raw:
            self._fail_hint("请输入安装位置")
            return None
        if any(s in raw for s in ("\\n", "\\t", "\\r")):
            self._fail_hint(r"路径里不能出现 \n \t 这类转义写法")
            return None
        try:
            path = os.path.abspath(os.path.expanduser(raw))
        except (OSError, ValueError) as e:
            self._fail_hint(f"路径无法解析：{e}")
            return None
        if os.path.dirname(path) == path:
            self._fail_hint("不能直接装到磁盘根目录，请换个子文件夹")
            return None
        bad = [c for c in '<>:"|?*' if c in path.lstrip(os.sep)[2:]]
        if bad:
            self._fail_hint("路径含 Windows 不允许的字符：" + " ".join(bad))
            return None
        return path

    def _fail_hint(self, msg):
        self.lbl_status.configure(text=msg, fg=C["red"])
        self.log.push("✗ " + msg)

    def _start(self):
        if self._busy:
            return
        target = self._target()
        if not target:
            return
        keep = self.chk_models.get()

        # 需要管理员权限：带着参数以管理员身份重开，并自动开始安装
        if not install.can_write(target) and not install.is_admin():
            if self._elevate(target, keep):
                self.destroy()
                return
            self.log.push("未获得管理员权限，改用当前用户权限继续（可能失败）")

        self._busy = True
        self._finished = False
        self._done_info = None
        self._cancel = threading.Event()
        self.e_dir.configure(state="disabled")
        self.chk_models.set_enabled(False)
        self.btn_main.set_text("安装中…")
        self.btn_main.set_state("disabled")
        self.btn_alt.set_text("停止")
        self.btn_alt.set_kind("danger")
        self.lbl_foot.configure(text="")
        self.log.clear()
        self.bar.reset()
        self._set_pct("")

        install.set_ui_hooks(progress=self._push_progress, cancel=self._cancel)
        self._worker = threading.Thread(target=self._run, args=(target, keep),
                                        daemon=True)
        self._worker.start()
        self._ensure_pump()

    def _elevate(self, target, keep):
        try:
            args = [target, "--models" if keep else "--no-models", "--auto"]
            exe, params = install._launch_spec(args)
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, params, None, 1)
            return rc > 32
        except Exception:
            return False

    def _run(self, target, keep):
        old = sys.stdout
        sys.stdout = _StreamToQueue(self._push)
        try:
            res = install.install_core(target, keep, open_dir=False)
            self._push("done", res)
        except install.Cancelled:
            self._push("cancelled", None)
        except install.InstallError as e:
            self._push("error", str(e))
        except Exception as e:
            import traceback
            self._push("trace", traceback.format_exc())
            self._push("error", f"{type(e).__name__}: {e}")
        finally:
            try:
                sys.stdout = old
            except Exception:
                pass
            install.set_ui_hooks(None, None)
            self._push("finish", None)

    # -------------------------------------------------- 线程 → 界面
    def _push(self, kind, payload):
        try:
            self._q.put_nowait((kind, payload))
        except queue.Full:
            pass

    def _push_progress(self, frac, text):
        self._push("progress", (frac, text))

    def _pump(self):
        try:
            if not self.winfo_exists():
                self._pumping = False
                return
        except tk.TclError:
            self._pumping = False
            return
        try:
            while True:
                kind, payload = self._q.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        if not self._finished:
            self.after(60, self._pump)
        else:
            self._pumping = False

    def _handle(self, kind, payload):
        if kind == "log":
            if payload:
                self.log.push(payload)
        elif kind == "status":
            self.lbl_status.configure(text=self._ellipsis(payload),
                                      fg=C["dim"])
        elif kind == "progress":
            frac, text = payload
            self._on_progress(frac, text)
        elif kind == "trace":
            for line in (payload or "").splitlines():
                self.log.push(line)
        elif kind == "done":
            self._on_done(payload)
        elif kind == "cancelled":
            self._on_cancelled()
        elif kind == "error":
            self._on_error(payload)
        elif kind == "finish":
            self._finished = True
            self._busy = False

    # -------------------------------------------------- 进度显示
    def _on_progress(self, frac, text=""):
        if frac is None:
            self.bar.set(None)
            self._set_pct("")
        else:
            self.bar.set(frac)
            self._set_pct(f"{int(frac * 100)}%")
        if text:
            self.lbl_status.configure(text=self._ellipsis(text), fg=C["dim"])

    def _set_pct(self, text):
        self.lbl_pct.configure(text=text)

    @staticmethod
    def _ellipsis(text, limit=52):
        text = text.strip()
        return text if len(text) <= limit else text[:limit - 1] + "…"

    # -------------------------------------------------- 终态
    def _settle_buttons(self):
        self.btn_main.set_state("normal")
        self.e_dir.configure(state="normal")
        self.chk_models.set_enabled(True)

    def _on_done(self, res):
        self._done_info = res or {}
        self.bar.set(1.0, tone=C["green"])
        self._set_pct("100%")
        self.lbl_status.configure(text="安装完成  ·  桌面已创建快捷方式",
                                  fg=C["green"])
        self.btn_main.set_text("启动游戏")
        self.btn_main.set_kind("gold")
        self.btn_main.set_command(self._launch_game)
        self.btn_alt.set_text("打开文件夹")
        self.btn_alt.set_kind("ghost")
        self.btn_alt.set_command(self._open_dir)
        self.btn_close.pack(side="right", padx=(0, 8), pady=13)
        self.lbl_foot.configure(text="")
        self._settle_buttons()

    def _on_error(self, msg):
        self.bar.set(self.bar._frac, tone=C["red"])
        self.lbl_status.configure(
            text=self._ellipsis((msg or "未知错误").splitlines()[0]),
            fg=C["red"])
        self._set_pct("")
        for line in (msg or "").splitlines():
            self.log.push("✗ " + line)
        self.btn_main.set_text("重试")
        self.btn_main.set_kind("primary")
        self.btn_main.set_command(self._start)
        self.btn_alt.set_text("关闭")
        self.btn_alt.set_kind("ghost")
        self.btn_alt.set_command(self.on_close)
        self.lbl_foot.configure(text="可更换网络后点「重试」，或改用绿色版")
        self._settle_buttons()

    def _on_cancelled(self):
        self.bar.set(self.bar._frac, tone=C["mute"])
        self.lbl_status.configure(text="已取消安装", fg=C["mute"])
        self._set_pct("")
        self.log.push("已取消。若已开始解压，安装目录里可能残留部分文件。")
        self.btn_main.set_text("重新开始")
        self.btn_main.set_kind("primary")
        self.btn_main.set_command(self._start)
        self.btn_alt.set_text("关闭")
        self.btn_alt.set_kind("ghost")
        self.btn_alt.set_command(self.on_close)
        self._settle_buttons()

    def _cancel_install(self):
        if self._cancel is not None:
            self._cancel.set()
            self.btn_alt.set_state("disabled")
            self.lbl_status.configure(text="正在停止…", fg=C["mute"])

    # -------------------------------------------------- 完成后动作
    def _launch_game(self):
        exe = (self._done_info or {}).get("exe")
        if exe and os.path.isfile(exe):
            try:
                os.startfile(exe)             # noqa: S606
            except OSError:
                pass
        self.destroy()

    def _open_dir(self):
        d = (self._done_info or {}).get("install_dir") or self.e_dir.get().strip()
        if d and os.path.isdir(d):
            try:
                os.startfile(d)               # noqa: S606
            except OSError:
                pass


def run(install_dir=None, keep_models=None, auto=False):
    # 控制台窗口立刻藏起来：exe 是 console=True 打的（保证 --cli 能输出），
    # 图形模式不藏的话双击时会带着一个黑框。
    # ⚠ 只在 frozen 下做 —— 源码运行时 FreeConsole 会把用户 cmd 里的
    #   输出断开，开发者反而什么都看不到。
    if os.name == "nt" and getattr(sys, "frozen", False):
        try:
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
    app = InstallerWindow(install_dir, keep_models, auto)
    app.show()
    if auto:
        app.after(450, app._start)
    app.mainloop()
