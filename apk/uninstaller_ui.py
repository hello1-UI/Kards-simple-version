# -*- coding: utf-8 -*-
"""KARDS 卸载程序的图形界面。

⚠ 只在 uninstall.main() 里延迟 import —— 顶层依赖 tkinter，而控制台模式
  （--cli / --gc / 回归测试）必须在没有 tkinter 的环境下照常工作。
"""
import ctypes
import os
import queue
import sys
import threading
import tkinter as tk

import setup_ui as ui
import uninstall as core

C = ui.C
PAD = 26


def _dir_stats(path):
    """(文件数, 字节数)；读不到就返回 0。"""
    n = size = 0
    if not path or not os.path.isdir(path):
        return 0, 0
    for root, dirs, files in os.walk(path, onerror=lambda _e: None):
        for f in files:
            n += 1
            try:
                size += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n, size


def _human(n):
    if n >= 1048576:
        return f"{n / 1048576:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


class _StreamToQueue:
    """卸载流程的 print → 界面日志。"""

    def __init__(self, put):
        self._put = put
        self._buf = ""

    def write(self, s):
        if not s:
            return 0
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._put("log", line.rstrip())
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False


class UninstallerWindow(ui.BaseWindow):
    def __init__(self, target=None, warn=""):
        super().__init__("KARDS 简化版 卸载程序", 700, 560)
        self._target = target
        self._warn = warn
        self._q = queue.Queue(maxsize=4000)
        self._worker = None
        self._busy = False
        self._finished = False
        self._build()
        self._load_stats()
        self.after(60, self._pump)

    # -------------------------------------------------- 布局
    def _build(self):
        ui.Header(self, "KARDS 简化版", "WWII CARD GAME  ·  卸载程序").pack(fill="x")

        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=PAD, pady=(18, 0))

        tk.Label(body, text="程序目录", bg=C["bg"], fg=C["dim"],
                 font=ui.F(9)).pack(anchor="w")

        box = tk.Frame(body, bg=C["panel"], highlightbackground=C["border"],
                       highlightthickness=1)
        box.pack(fill="x", pady=(6, 0))
        self.lbl_path = tk.Label(
            box, text=self._target or core.self_dir(), bg=C["panel"],
            fg=C["text"] if self._target else C["mute"], font=ui.F(9),
            anchor="w", justify="left", wraplength=600, padx=10, pady=8)
        self.lbl_path.pack(fill="x")

        self.lbl_size = tk.Label(
            body, text="正在统计…", bg=C["bg"],
            fg=C["mute"], font=ui.F(8), anchor="w")
        self.lbl_size.pack(anchor="w", pady=(6, 0))

        if self._warn:
            self.lbl_warn = tk.Label(
                body, text="⚠  " + self._warn, bg=C["bg"], fg=C["gold"],
                font=ui.F(9), anchor="w", justify="left", wraplength=620)
            self.lbl_warn.pack(anchor="w", pady=(8, 0))

        # --- 选项
        tk.Frame(body, bg=C["bg"], height=20).pack()
        self.chk_data = ui.Check(
            body, "同时删除用户数据", value=False,
            sub="包括设置、日志、自组卡组；保留的话下次重装还能沿用")
        self.chk_data.pack(fill="x")

        # --- 进度
        tk.Frame(body, bg=C["bg"], height=20).pack()
        self.bar = ui.Progress(body, height=8)
        self.bar.pack(fill="x")
        srow = tk.Frame(body, bg=C["bg"])
        srow.pack(fill="x", pady=(8, 0))
        self.lbl_status = tk.Label(srow, text="准备就绪", bg=C["bg"],
                                   fg=C["dim"], font=ui.F(9), anchor="w")
        self.lbl_status.pack(side="left", fill="x", expand=True)

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

        self.btn_main = ui.Button(foot, "卸载", command=self._start,
                                  kind="danger", width=104, height=36)
        self.btn_alt = ui.Button(foot, "取消", command=self.on_close,
                                 kind="ghost", width=92, height=36)
        self.btn_main.pack(side="right", padx=(0, 10), pady=13)
        self.btn_alt.pack(side="right", pady=13)

        if not self._target:
            self.btn_main.set_state("disabled")
            self.btn_main.set_text("无法卸载")
            self.lbl_foot.configure(text="请从安装目录运行卸载器")

    def _load_stats(self):
        if not self._target:
            self.lbl_size.configure(text="目录不存在，无需卸载")
            return

        def work():
            n, size = _dir_stats(self._target)
            self._q.put(("stats", (n, size)))

        threading.Thread(target=work, daemon=True).start()

    # -------------------------------------------------- 交互
    def on_close(self):
        if self._busy:
            try:
                import tkinter.messagebox as mb
                if not mb.askyesno(
                        "退出卸载",
                        "卸载正在进行中。\n\n现在退出可能只删掉一部分文件。\n"
                        "确定要退出吗？", parent=self):
                    return
            except Exception:
                pass
        self.destroy()

    def _start(self):
        if self._busy or not self._target:
            return
        purge = self.chk_data.get()
        self._busy = True
        self._finished = False
        self.chk_data.set_enabled(False)
        self.btn_main.set_text("卸载中…")
        self.btn_main.set_state("disabled")
        self.btn_alt.set_state("disabled")
        self.log.clear()
        self.bar.set(0.0)
        core.set_ui_hooks(progress=self._push_progress)
        self._worker = threading.Thread(target=self._run, args=(purge,),
                                        daemon=True)
        self._worker.start()
        self.after(60, self._pump)

    def _run(self, purge):
        old = sys.stdout
        sys.stdout = _StreamToQueue(self._push)
        try:
            res = core.uninstall_core(keep_data=not purge, target=self._target)
            self._push("done", res)
        except Exception as e:
            import traceback
            self._push("trace", traceback.format_exc())
            self._push("error", f"{type(e).__name__}: {e}")
        finally:
            try:
                sys.stdout = old
            except Exception:
                pass
            core.set_ui_hooks(None)
            self._push("finish", None)

    def _push(self, kind, payload):
        try:
            self._q.put_nowait((kind, payload))
        except queue.Full:
            pass

    def _push_progress(self, frac, text):
        self._push("progress", (frac, text))

    def _pump(self):
        try:
            while True:
                kind, payload = self._q.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        if not self._finished:
            self.after(60, self._pump)

    def _handle(self, kind, payload):
        if kind == "stats":
            n, size = payload
            if n:
                self.lbl_size.configure(
                    text=f"{n} 个文件  ·  占用 {_human(size)}",
                    fg=C["mute"])
            else:
                self.lbl_size.configure(text="目录是空的", fg=C["mute"])
        elif kind == "log":
            if payload:
                self.log.push(payload)
        elif kind == "progress":
            frac, text = payload
            if frac is not None:
                self.bar.set(frac)
            if text:
                self.lbl_status.configure(text=text, fg=C["dim"])
        elif kind == "trace":
            for line in (payload or "").splitlines():
                self.log.push(line)
        elif kind == "done":
            self._on_done(payload)
        elif kind == "error":
            self._on_error(payload)
        elif kind == "finish":
            self._finished = True
            self._busy = False

    # -------------------------------------------------- 终态
    def _on_done(self, res):
        self.bar.set(1.0, tone=C["green"])
        self.lbl_status.configure(text="卸载完成", fg=C["green"])
        self.btn_main.set_text("完成")
        self.btn_main.set_kind("primary")
        self.btn_main.set_command(self.on_close)
        self.btn_main.set_state("normal")
        self.btn_alt.pack_forget()
        kit = (res or {}).get("data_removed")
        self.lbl_foot.configure(
            text="用户数据已一并删除" if kit else "用户数据已保留")
        self.log.push("")
        self.log.push("点「完成」关闭窗口，安装目录会在后台自动清理干净。")

    def _on_error(self, msg):
        self.bar.set(self.bar._frac, tone=C["red"])
        self.lbl_status.configure(
            text=(msg or "未知错误").splitlines()[0], fg=C["red"])
        for line in (msg or "").splitlines():
            self.log.push("✗ " + line)
        self.btn_main.set_text("重试")
        self.btn_main.set_state("normal")
        self.btn_alt.set_state("normal")
        self.chk_data.set_enabled(True)
        self.lbl_foot.configure(text="可能需要在管理员权限下重新运行卸载器")


def run():
    target, warn = core.detect_target()
    # 装在 Program Files 且非管理员：先提权，避免删到一半 permission denied
    if target and not core.is_admin() and "program files" in target.lower():
        try:
            core.relaunch_as_admin()
        except SystemExit:
            # 提权重启成功：本进程要立刻安静退场，别让 SystemExit 被吞掉后
            # 又建一个没有管理员权限的窗口
            os._exit(0)
        except Exception:
            pass
    if os.name == "nt" and getattr(sys, "frozen", False):
        try:
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
    app = UninstallerWindow(target, warn)
    app.show()
    app.mainloop()
