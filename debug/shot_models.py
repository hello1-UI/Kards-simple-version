"""内置 UI 模板（models/）的界面截图 —— 人眼验收用。

测得出「有 12 个胶囊、点了能应用」，测不出「12 个胶囊排三行会不会显得挤、
「内置」小标有没有把名字挤掉、亮色模板在深色主界面里看着冷不冷」。抓图看。

    19_models_list.png        设置 → 外观，滚到底部（12 套内置 + 1 套自己的）
    20_model_copy_editor.png  从内置模板点「复制」打开的编辑器（预填副本名）

用法：python debug/shot_models.py
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

DATA = tempfile.mkdtemp(prefix="kards_shot_models_")
os.environ["KARDS_DATA_DIR"] = DATA

import kards_i18n as i18n

_TMP = os.path.join(tempfile.gettempdir(), "kards_shot_models_settings.json")
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
    # 桌面上可能有别的置顶窗口（比如正在运行的安装器控制台），
    # 只靠 tk 的 lift 压不过去 —— 用 Win32 把自己钉到最顶再抓。
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        HWND_TOPMOST = -1
        SWP_NOMOVE_NOSIZE = 0x0001 | 0x0002
        ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                          SWP_NOMOVE_NOSIZE)
    except Exception:                                      # noqa: BLE001
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
    stack = list(win.winfo_children())
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
    theme.set_model_dir(None)                 # 用项目根的 models/

    # 一套自己的模板，用来确认「内置」与「我的」在同一个列表里能区分开
    theme.save_custom("我的夜战", {"colors": {
        "bg": "#0e1620", "bg_alt": "#0a1119", "panel": "#17222e",
        "panel_alt": "#1e2b39", "card": "#223141", "card_dim": "#1a2634",
        "text": "#e6f0f8", "dim": "#9bb0c2", "mute": "#6c8092",
        "border": "#2b3d4f", "border_hi": "#43607a", "accent": "#54c8e8",
        "btn": "#2c3d4d"}})
    theme.apply("model:nordic-night", None)

    gui.App._account_dialog = lambda self, for_server=False: None
    gui.App.open_update_dialog = lambda self, auto=False: None

    app = gui.App()
    app.geometry("1180x820+360+180")
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
    scroll_to(win, 1.0)
    grab(win, "19_models_list")
    win.destroy()
    app.update()

    app.open_theme_editor(edit_key="model:nordic-night")
    app.update()
    ed = find_win(app, "theme_editor")
    if ed is not None:
        grab(ed, "20_model_copy_editor")
        ed.destroy()
        app.update()

    app.destroy()
    theme.set_model_dir(None)
    print("done")


if __name__ == "__main__":
    main()
