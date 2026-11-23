"""主题/主菜单截图工具（人眼验收用）。

单元测试能证明 token 齐全、对比度达标，但证明不了「卡片有没有溢出、
亮色主题下按钮文字看不看得见」。这里把主菜单和外观设置真渲染出来，
几套配色各抓一张到 debug/shots/。

用法：
    python debug/shot_theme.py            # 全部
    python debug/shot_theme.py menu       # 只抓主菜单三套
    python debug/shot_theme.py settings   # 只抓外观设置窗
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

import kards_i18n as i18n

# 截图工具绝不能写玩家的 settings.json
_TMP = os.path.join(tempfile.gettempdir(), "kards_shot_theme_settings.json")
with open(_TMP, "w", encoding="utf-8") as fh:
    json.dump({"language": "zh"}, fh)
i18n._SETTINGS_PATH = _TMP

import KARDS as gui          # noqa: E402
import kards_theme as theme  # noqa: E402

OUT = os.path.join(ROOT, "debug", "shots")


def _dpi_scale(win):
    """tkinter 报告**逻辑像素**，ImageGrab 抓的是**物理像素**。

    125% 缩放的机器上不换算的话，抓图只能拿到窗口左上角的一块
    （右边的按钮整排消失 —— 实测踩过）。用 GetDpiForWindow 拿真实缩放。
    """
    try:
        import ctypes
        # 进程不是 DPI-aware 时 GetDpiForWindow 会返回虚拟化的 96（实测），
        # 而 GetScaleFactorForDevice 读的是显示器属性，不受进程感知度影响。
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
    # ⚠ ImageGrab 抓的是**屏幕区域**，不是窗口内容 —— 窗口必须真的在最前面，
    # 否则抓到的会是盖在上面的其它程序（实测抓到过 IDE 界面）。
    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass
    win.lift()
    win.focus_force()
    for _ in range(6):
        win.update_idletasks()
        win.update()
    s = _dpi_scale(win)
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    img = ImageGrab.grab(bbox=(round(x * s), round(y * s),
                               round((x + w) * s), round((y + h) * s)))
    path = os.path.join(OUT, f"theme_{name}.png")
    img.save(path)
    print("saved", path, img.size)
    return path


def find_win(app, role):
    for w in app.winfo_children():
        if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == role:
            return w
    return None


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    os.makedirs(OUT, exist_ok=True)

    # 截图时不要弹账号窗 / 更新窗（启动后它们会被 after 排队）
    gui.App._account_dialog = lambda self, for_server=False: None
    gui.App.open_update_dialog = lambda self, auto=False: None

    app = gui.App()
    app.geometry("1180x820+30+30")
    try:
        app.attributes("-fullscreen", False)
    except tk.TclError:
        pass
    app.update()

    shots = []
    if only in (None, "menu"):
        for preset in ("frontline", "desert", "paper", "arctic"):
            app._pick_theme(preset, None)
            app.update()
            shots.append(grab(app, "menu_" + preset))

    if only in (None, "settings"):
        for preset in ("frontline", "paper"):
            app._pick_theme(preset, None)
            app.update()
            app.open_start_settings(tab="appearance")
            app.update()
            win = find_win(app, "start_settings")
            if win is None:
                print("settings window not found")
                continue
            win.update_idletasks()
            win.update()
            shots.append(grab(win, "settings_" + preset))
            win.destroy()
            app.update()

    app.destroy()
    print("done:", len(shots))


if __name__ == "__main__":
    main()
