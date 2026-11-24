# -*- coding: utf-8 -*-
"""删除账号确认框截图（人眼验收）

    python debug/shot_account_delete.py

产出 promo/shots/11_delete_local.png / 12_delete_server.png。
真实删除不可逆，这里全部打桩：只截「界面」。
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

_DATA = tempfile.mkdtemp(prefix="kards_del_shot_")
os.environ["KARDS_DATA_DIR"] = _DATA
sys.path.insert(0, ROOT)
os.chdir(ROOT)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                      # noqa: E402
from PIL import ImageGrab                 # noqa: E402

import kards_i18n as i18n                 # noqa: E402

_TMP = os.path.join(tempfile.gettempdir(), "kards_del_shot_settings.json")
with open(_TMP, "w", encoding="utf-8") as fh:
    json.dump({"language": "zh"}, fh)
i18n._SETTINGS_PATH = _TMP

import kards_rank as rank                 # noqa: E402
import KARDS as gui                       # noqa: E402


def dpi_scale(win):
    try:
        import ctypes
        hwnd = win.winfo_id()
        root = ctypes.windll.user32.GetAncestor(hwnd, 2) or hwnd
        return (ctypes.windll.user32.GetDpiForWindow(root) or 96) / 96.0
    except Exception:                                      # noqa: BLE001
        return 1.0


def pump(win, times=10):
    win.lift()
    win.focus_force()
    for _ in range(times):
        win.update_idletasks()
        win.update()
        time.sleep(0.05)


def grab(win, name):
    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass
    pump(win)
    time.sleep(0.35)
    pump(win, 4)
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
    stack = [win]
    while stack:
        w = stack.pop()
        stack.extend(w.winfo_children())
        if isinstance(w, tk.Button):
            try:
                if w.cget("text") == text:
                    w.invoke()
                    return True
            except tk.TclError:
                pass
    return False


def main():
    gui.App.open_update_dialog = lambda self, auto=False: None
    gui.account.get_stats = lambda name=None: {"win": 37, "lose": 21, "draw": 0}
    gui.account.get_rank = lambda name=None: rank.normalize({
        "tier": 9, "stars": 3, "best": 9, "season": rank.season_id()})
    app = gui.App()
    app.geometry("1180x820+20+20")
    try:
        app.attributes("-fullscreen", False)
    except tk.TclError:
        pass
    app.update()

    # 1) 离线/本地账号：复选框禁用，只删本机
    app.account = "Guderian"
    app.rank_state = None
    app._account_dialog()
    app.update()
    win = find_win(app, "account")
    pump(win, 6)
    click(win, i18n.t("account_delete"))
    app.update()
    dlg = find_win(app, "acct_del")
    grab(dlg, "11_delete_local.png")
    dlg.destroy()
    win.destroy()

    # 2) 在线（服务器账号）：复选框可用且默认勾选
    gui.account.online = lambda: True
    gui.account.backend = lambda: "server"
    app.account = "Guderian"
    app._account_dialog()
    app.update()
    win = find_win(app, "account")
    pump(win, 6)
    click(win, i18n.t("account_delete"))
    app.update()
    dlg = find_win(app, "acct_del")
    grab(dlg, "12_delete_server.png")

    try:
        dlg.destroy()
        win.destroy()
        app.destroy()
    except tk.TclError:
        pass


if __name__ == "__main__":
    main()
