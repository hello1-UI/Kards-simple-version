# -*- coding: utf-8 -*-
"""可选音乐包窗口截图（人眼验收）

    python debug/shot_musicpack.py

产出 promo/shots/08_musicpack_ready.png / 09_musicpack_downloading.png
/ 10_musicpack_done.png

为什么要打桩：真实下载要 4 GB、真实 Release 也未必存在。这里只截「界面」，
所以把远端清单和安装任务换成固定假数据，保证每次出图一致。
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "promo", "shots")
os.makedirs(OUT, exist_ok=True)

_DATA = tempfile.mkdtemp(prefix="kards_mp_shot_")
os.environ["KARDS_DATA_DIR"] = _DATA
sys.path.insert(0, ROOT)
os.chdir(ROOT)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                      # noqa: E402
from PIL import ImageGrab                 # noqa: E402

import kards_i18n as i18n                 # noqa: E402

_TMP = os.path.join(tempfile.gettempdir(), "kards_mp_shot_settings.json")
with open(_TMP, "w", encoding="utf-8") as fh:
    json.dump({"language": "zh"}, fh)
i18n._SETTINGS_PATH = _TMP

import kards_musicdl as musicdl           # noqa: E402
import KARDS as gui                       # noqa: E402

PARTS = [
    {"name": "music.zip", "url": "", "size": 1610612736, "sha256": ""},
    {"name": "music-2.zip", "url": "", "size": 1468006400, "sha256": ""},
    {"name": "music-3.zip", "url": "", "size": 1468006400, "sha256": ""},
]

musicdl.release = lambda timeout=12: {
    "ok": True, "err": "", "parts": PARTS,
    "page": musicdl.PAGE, "sums": []}


class FakeTask:
    """假安装任务：只提供界面读的字段。"""

    def __init__(self, local_only=False, state="downloading"):
        self.state = state
        self.progress = 0.0
        self.done_mb = 0.0
        self.total_mb = 4300.0
        self.message = "music.zip"
        self.audio = 251
        self.verified = True
        self.local_only = local_only

    def start(self):
        pass

    def cancel(self):
        pass


def dpi_scale(win):
    try:
        import ctypes
        hwnd = win.winfo_id()
        root = ctypes.windll.user32.GetAncestor(hwnd, 2) or hwnd
        return (ctypes.windll.user32.GetDpiForWindow(root) or 96) / 96.0
    except Exception:                                      # noqa: BLE001
        return 1.0


def grab(win, name):
    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass
    win.lift()
    win.focus_force()
    for _ in range(8):
        win.update_idletasks()
        win.update()
    time.sleep(0.45)
    for _ in range(4):
        win.update_idletasks()
        win.update()
    s = dpi_scale(win)
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    img = ImageGrab.grab(bbox=(round(x * s), round(y * s),
                               round((x + w) * s), round((y + h) * s)))
    path = os.path.join(OUT, name)
    img.save(path)
    print("saved", path, img.size)
    return path


def find_win(app, role):
    for w in app.winfo_children():
        if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == role:
            return w
    return None


def click(win, text):
    """按文案点按钮（找不到就返回 False）。"""
    stack = [win]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        if isinstance(w, tk.Button):
            try:
                if text in w.cget("text"):
                    w.invoke()
                    return True
            except tk.TclError:
                pass
    return False


def pump(win, times=8):
    for _ in range(times):
        win.update_idletasks()
        win.update()
        time.sleep(0.06)


def main():
    gui.App._account_dialog = lambda self, for_server=False: None
    gui.App.open_update_dialog = lambda self, auto=False: None
    app = gui.App()
    app.geometry("1180x820+20+20")
    try:
        app.attributes("-fullscreen", False)
    except tk.TclError:
        pass
    app.update()

    # 1) 就绪态：显示体积与分卷数
    app.open_musicpack_dialog()
    app.update()
    win = find_win(app, "musicpack")
    pump(win, 10)
    grab(win, "08_musicpack_ready.png")

    # 2) 下载中：点「下载并安装」，任务被替换成固定的 62%
    musicdl.InstallTask = lambda local_only=False: FakeTask(
        local_only, state="downloading")
    fake = musicdl.InstallTask()
    fake.progress = 0.62
    fake.done_mb = 2670.0
    fake.message = "music-2.zip"
    musicdl.InstallTask = lambda local_only=False: fake
    click(win, i18n.t("mpk_btn_download"))
    pump(win, 8)
    grab(win, "09_musicpack_downloading.png")

    # 3) 完成态
    fake.state = "done"
    fake.progress = 1.0
    pump(win, 8)
    grab(win, "10_musicpack_done.png")

    try:
        app.destroy()
    except Exception:                                      # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
