# -*- coding: utf-8 -*-
"""休闲模式界面截图（人眼验收）

    python debug/shot_casual.py

产出到 promo/shots/：
    13_menu_casual.png   主菜单三入口（战斗 / 练习 / 休闲）
    14_casual_select.png 休闲：选 AI 还是真人
    15_casual_lobby.png  休闲大厅（匹配按钮写「休闲匹配」）
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

os.environ["KARDS_DATA_DIR"] = tempfile.mkdtemp(prefix="kards_casualshot_")
sys.path.insert(0, ROOT)
sys.argv.append("--no-fullscreen")
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                       # noqa: E402
from PIL import ImageGrab                  # noqa: E402

import kards_i18n as i18n                  # noqa: E402

_TMP = os.path.join(tempfile.gettempdir(), "kards_casualshot_settings.json")
with open(_TMP, "w", encoding="utf-8") as fh:
    json.dump({"language": "zh"}, fh)
i18n._SETTINGS_PATH = _TMP

import KARDS as gui                        # noqa: E402


def dpi_scale(win):
    try:
        import ctypes
        if sys.platform != "win32":
            return 1.0
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:                                  # noqa: BLE001
            pass
        try:
            if hasattr(ctypes.windll.shcore, "GetScaleFactorForDevice"):
                return ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
        except Exception:                                  # noqa: BLE001
            pass
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
    time.sleep(0.5)
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


class FakeLink:
    alive = True
    intentional = False

    def __init__(self):
        import queue
        self.inbox = queue.Queue()

    def send(self, obj):
        return True


PLAYERS = [
    {"name": "Scharnhorst", "rank": {"tier": 3}, "in_game": False,
     "stats": {"win": 12, "lose": 4, "draw": 0}},
    {"name": "北极星", "rank": {"tier": 5}, "in_game": False,
     "stats": {"win": 8, "lose": 3, "draw": 0}},
    {"name": "钢蓝", "rank": {"tier": 8}, "in_game": True,
     "stats": {"win": 5, "lose": 5, "draw": 1}},
]


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

    app.account = "Scharnhorst"
    app.rank_state = {"tier": 5, "stars": 3, "best": 3, "streak": 2,
                      "zero_losses": 0}
    gui.account.get_rank = lambda name=None: dict(app.rank_state)
    app._refresh_account_btn()
    app.update()
    grab(app, "13_menu_casual.png")

    app._build_casual_select()
    app.update()
    grab(app, "14_casual_select.png")

    # 伪造「已连上服务器 + 已登录」，让匹配按钮是亮着的
    app._lobby_connect = lambda: None
    app._schedule = lambda *a, **k: None
    app.mp_link = FakeLink()
    app.mp_user = "Scharnhorst"
    app._build_lobby(casual=True)
    app.update()
    app._lobby_set_players(PLAYERS)
    app._lobby_log("休闲匹配不会影响段位")
    app.update()
    grab(app, "15_casual_lobby.png")

    try:
        app.destroy()
    except Exception:                                      # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
