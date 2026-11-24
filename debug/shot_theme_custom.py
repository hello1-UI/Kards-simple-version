"""自定义 UI 模板的界面截图（人眼验收用）。

能测的是「有控件、能保存、不裁内容」，测不了「色块看着舒服吗、
预览是不是真的跟着变色」。这里真渲染出来抓图：
    16_theme_custom_top.png     设置 → 外观页（顶部，预设区）
    17_theme_custom_bottom.png  滚到底部（自定义模板区 + 按钮）
    18_theme_editor.png         模板编辑器（21 个色块 + 实时预览）

用法：python debug/shot_theme_custom.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk

from PIL import ImageGrab

DATA = tempfile.mkdtemp(prefix="kards_shot_tpl_")
os.environ["KARDS_DATA_DIR"] = DATA

import kards_i18n as i18n

_TMP = os.path.join(tempfile.gettempdir(), "kards_shot_tpl_settings.json")
with open(_TMP, "w", encoding="utf-8") as fh:
    json.dump({"language": "zh"}, fh)
i18n._SETTINGS_PATH = _TMP

import KARDS as gui          # noqa: E402
import kards_theme as theme  # noqa: E402

OUT = os.path.join(ROOT, "debug", "shots")


def _dpi_scale(win):
    try:
        import ctypes
        try:
            return ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
        except Exception:                                  # noqa: BLE001
            pass
        hwnd = win.winfo_id()
        GA_ROOT = 2
        root = ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT) or hwnd
        dpi = ctypes.windll.user32.GetDpiForWindow(root)
        return (dpi or 96) / 96.0
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
    s = _dpi_scale(win)
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    img = ImageGrab.grab(bbox=(round(x * s), round(y * s),
                               round((x + w) * s), round((y + h) * s)))
    path = os.path.join(OUT, name + ".png")
    img.save(path)
    print("saved", path, img.size)
    return path


def find_win(app, role):
    for w in app.winfo_children():
        if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == role:
            return w
    return None


def scroll_to(win, frac):
    for w in win.winfo_children():
        stack = [w]
        while stack:
            cur = stack.pop()
            if isinstance(cur, tk.Canvas):
                cur.yview_moveto(frac)
                win.update_idletasks()
                win.update()
                return cur
            stack.extend(cur.winfo_children())
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    theme.set_custom_dir(os.path.join(DATA, "themes"))
    k1 = theme.save_custom("北境夜航", {"colors": {
        "bg": "#0e1620", "bg_alt": "#0a1119", "panel": "#17222e",
        "panel_alt": "#1e2b39", "card": "#223141", "card_dim": "#1a2634",
        "text": "#e6f0f8", "dim": "#9bb0c2", "mute": "#6c8092",
        "border": "#2b3d4f", "border_hi": "#43607a", "accent": "#54c8e8",
        "btn": "#2c3d4d"}})
    theme.save_custom("血与铁", {"colors": {
        "bg": "#1a1010", "bg_alt": "#140c0c", "panel": "#261818",
        "panel_alt": "#321f1f", "card": "#3a2424", "card_dim": "#2b1b1b",
        "text": "#f5e6e0", "dim": "#c0a09a", "mute": "#8a6f6a",
        "border": "#402c2c", "border_hi": "#5c3f3f", "accent": "#d06848",
        "btn": "#4a2f2f"}})
    theme.apply(k1, None)

    gui.App._account_dialog = lambda self, for_server=False: None
    gui.App.open_update_dialog = lambda self, auto=False: None

    app = gui.App()
    app.geometry("1180x820+30+30")
    try:
        app.attributes("-fullscreen", False)
    except tk.TclError:
        pass
    app.update()

    app.open_start_settings(tab="appearance")
    app.update()
    win = find_win(app, "start_settings")
    if win is None:
        print("settings window not found")
        app.destroy()
        return
    grab(win, "16_theme_custom_top")
    scroll_to(win, 1.0)
    grab(win, "17_theme_custom_bottom")

    win.destroy()
    app.update()

    app.open_theme_editor(edit_key=k1)
    app.update()
    ed = find_win(app, "theme_editor")
    if ed is not None:
        grab(ed, "18_theme_editor")
        ed.destroy()
        app.update()

    app.destroy()
    print("done")


if __name__ == "__main__":
    main()
