# -*- coding: utf-8 -*-
"""主菜单快捷键角标截图（人眼验收用）

    python debug/shot_hotkeys.py

产出 debug/shots/25_hotkeys.png 与 26_hotkeys_zoom.png（工具条放大）。
"""

import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "shots")
os.makedirs(OUT, exist_ok=True)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
_DATA = tempfile.mkdtemp(prefix="kards_keys_shot_")
os.environ["KARDS_DATA_DIR"] = _DATA
sys.path.insert(0, ROOT)
os.chdir(ROOT)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                       # noqa: E402
from PIL import ImageGrab                  # noqa: E402

import kards_i18n as i18n                  # noqa: E402

_TMP = os.path.join(tempfile.gettempdir(), "kards_keys_settings.json")
with open(_TMP, "w", encoding="utf-8") as fh:
    json.dump({"language": "zh"}, fh)
i18n._SETTINGS_PATH = _TMP

import KARDS as gui                        # noqa: E402


def dpi_scale(win):
    try:
        import ctypes
        try:
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
    print("  写出", name, img.size)
    return img


def main():
    sys.argv = [sys.argv[0], "--no-fullscreen", "--no-update-check"]
    gui.App._account_dialog = lambda self, for_server=False: None
    gui.App.open_update_dialog = lambda self, auto=False: None
    app = gui.App()
    app.geometry("1180x820+40+40")
    try:
        app.attributes("-fullscreen", False)
    except tk.TclError:
        pass
    for _ in range(10):
        app.update_idletasks()
        app.update()
    img = grab(app, "25_hotkeys.png")
    # 工具条放大（截上半部分 1/6，方便看清按钮下的字母）
    s = dpi_scale(app)
    w, h = img.size
    top = img.crop((0, 0, w, int(h * 0.13)))
    top = top.resize((top.width * 2, top.height * 2))
    p2 = os.path.join(OUT, "26_hotkeys_zoom.png")
    top.save(p2)
    print("  写出 26_hotkeys_zoom.png", top.size)
    app.destroy()


if __name__ == "__main__":
    main()
