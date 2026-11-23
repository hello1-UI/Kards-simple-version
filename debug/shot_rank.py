# -*- coding: utf-8 -*-
"""段位界面截图工具（人眼验收）。

    python debug/shot_rank.py

产出到 debug/shots/：
    rank_menu.png          主菜单（顶部多了「段位」按钮）
    rank_window_locked.png 12 段 · 3 星 · 未上榜
    rank_window_top.png    1 段 · 已上榜 · 排行榜
    rank_window_guest.png  游客态
    rank_account.png       账号窗里的段位行
    rank_end.png           pygame 结算页的段位变化行
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ["KARDS_DATA_DIR"] = tempfile.mkdtemp(prefix="kards_shot_rank_")

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                      # noqa: E402
from PIL import ImageGrab                 # noqa: E402

import kards_i18n as i18n                 # noqa: E402

_TMP = os.path.join(tempfile.gettempdir(), "kards_shot_rank_settings.json")
with open(_TMP, "w", encoding="utf-8") as fh:
    json.dump({"language": "zh"}, fh)
i18n._SETTINGS_PATH = _TMP

import KARDS as gui                       # noqa: E402
import kards_rank as rank                 # noqa: E402

OUT = os.path.join(HERE, "shots")


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
    for _ in range(6):
        win.update_idletasks()
        win.update()
    s = dpi_scale(win)
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    img = ImageGrab.grab(bbox=(round(x * s), round(y * s),
                               round((x + w) * s), round((y + h) * s)))
    path = os.path.join(OUT, f"rank_{name}.png")
    img.save(path)
    print("saved", path, img.size)
    return path


def find_win(app, role):
    for w in app.winfo_children():
        if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == role:
            return w
    return None


TOP_ROWS = [
    {"name": "沙漠之狐", "tier": 1, "stars": 4, "pts": 87, "win": 31, "lose": 2, "pos": 1},
    {"name": "北极星", "tier": 1, "stars": 3, "pts": 64, "win": 24, "lose": 4, "pos": 2},
    {"name": "Scharnhorst", "tier": 1, "stars": 2, "pts": 41, "win": 17, "lose": 5, "pos": 3},
    {"name": "钢蓝", "tier": 1, "stars": 1, "pts": 22, "win": 10, "lose": 3, "pos": 4},
    {"name": "老兵不死", "tier": 1, "stars": 0, "pts": 9, "win": 5, "lose": 2, "pos": 5},
    {"name": "雪原猎手", "tier": 1, "stars": 0, "pts": -3, "win": 3, "lose": 4, "pos": 6},
]


def tk_shots():
    _orig_account = gui.App._account_dialog
    gui.App._account_dialog = lambda self, for_server=False: None
    gui.App.open_update_dialog = lambda self, auto=False: None
    app = gui.App()
    app.geometry("1180x820+30+30")
    try:
        app.attributes("-fullscreen", False)
    except tk.TclError:
        pass
    app.update()

    st = {"tier": 12, "stars": 3, "best": 15, "streak": 2, "zero_losses": 1,
          "season": rank.season_id(), "lb_pts": 0, "lb_win": 0, "lb_lose": 0,
          "lb_active": False}
    app.account = "Scharnhorst"
    app.rank_state = dict(st)
    gui.account.get_rank = lambda name=None: dict(app.rank_state)
    gui.account.leaderboard = lambda limit=20: {
        "rows": TOP_ROWS, "total": 37, "me": None, "online": True,
        "season": rank.season_id()}
    app._refresh_account_btn()
    app.update()
    grab(app, "menu")

    app.open_rank_dialog()
    app.update()
    win = find_win(app, "rank")
    if win is not None:
        grab(win, "window_locked")
        win.destroy()
        app.update()

    app.rank_state = {"tier": 1, "stars": 2, "best": 1, "streak": 5,
                      "zero_losses": 0, "season": rank.season_id(),
                      "lb_pts": 41, "lb_win": 17, "lb_lose": 5,
                      "lb_active": True}
    gui.account.leaderboard = lambda limit=20: {
        "rows": TOP_ROWS, "total": 37,
        "me": TOP_ROWS[2], "online": True, "season": rank.season_id()}
    app.open_rank_dialog()
    app.update()
    win = find_win(app, "rank")
    if win is not None:
        grab(win, "window_top")
        win.destroy()
        app.update()

    app.account = None
    app.rank_state = None
    app._refresh_account_btn()
    app.open_rank_dialog()
    app.update()
    win = find_win(app, "rank")
    if win is not None:
        grab(win, "window_guest")
        win.destroy()
        app.update()

    app.account = "Scharnhorst"
    app.rank_state = dict(st)
    gui.App._account_dialog = _orig_account      # 恢复真账号窗
    # 主菜单之前被 grab() 置了 topmost：两个 topmost 窗口叠在一起时，
    # 谁后 lift 谁在上 —— 不把主菜单摘下来，账号窗会被压在下面
    # （截到的就是主菜单而不是弹窗，实测踩过）。
    try:
        app.attributes("-topmost", False)
    except tk.TclError:
        pass
    app._account_dialog()
    app.update()
    win = find_win(app, "account")
    if win is not None:
        grab(win, "account")
        win.destroy()
        app.update()
    gui.App._account_dialog = lambda self, for_server=False: None
    app.destroy()


def pygame_shot():
    import pygame
    import kards_engine as core
    import kards_board as B

    class FakeApp:
        game = None
        busy = False
        anim_enabled = True
        fast_ai = False

        def pyboard_intent(self, act):
            pass

        def add_log(self, msg):
            pass

    pygame.init()
    db = core.card_database()
    p1 = core.Player("你", "德国", core.build_deck("德国", db))
    p2 = core.Player("AI", "苏联", core.build_deck("苏联", db))
    g = core.Game(p1, p2, interactive=False)
    g.log = lambda *a, **k: None
    g.draw_cards(p1, core.START_HP)
    g.draw_cards(p2, core.START_HP)
    g.current = p1
    g.start_turn()
    app = FakeApp()
    b = B.PygameBoard(app, game=g, on_intent=app.pyboard_intent)
    b.anim_enabled = True
    b.sync()
    b.show_end_animation(True, None, nation="德国",
                         rank_line="晋级！第 11 段 0 星")
    b.step(b.EXPLODE_MS + 600)
    surf = pygame.Surface((b.W, b.H))
    b.draw(surf)
    path = os.path.join(OUT, "rank_end.png")
    pygame.image.save(surf, path)
    print("saved", path)


def main():
    os.makedirs(OUT, exist_ok=True)
    tk_shots()
    pygame_shot()
    print("done")


if __name__ == "__main__":
    main()
