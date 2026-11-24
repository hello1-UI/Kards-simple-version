# -*- coding: utf-8 -*-
"""宣传片素材截图（人眼验收 + 出片用）

    python debug/shot_promo.py

产出到项目根 promo/shots/：
    01_menu.png        主菜单（带头像 / 每日任务 / 商店入口）
    02_shop.png        商店（六个货位 + 购买/装备状态 + 刷新按钮）
    03_quests.png      每日任务（进度条 + 领取）
    04_rank.png        段位与排行榜
    05_battle.png      对战棋盘（桌饰 + 总部皮肤已装备）
    06_intro.png       开场两军对冲
    07_victory.png     胜利结算大字

为什么单独做一份：宣传片要的是「同一套外观、同一个账号」的连拍，
临时手点截图每次都不一致；这里把账号、金币、库存、对局种子全固定住，
重复运行得到同一批图。
"""
import copy
import json
import os
import random
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "promo", "shots")
os.makedirs(OUT, exist_ok=True)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
_DATA = tempfile.mkdtemp(prefix="kards_promo_")
os.environ["KARDS_DATA_DIR"] = _DATA
sys.path.insert(0, ROOT)
os.chdir(ROOT)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                      # noqa: E402
from PIL import ImageGrab                 # noqa: E402

import kards_i18n as i18n                 # noqa: E402

_TMP = os.path.join(tempfile.gettempdir(), "kards_promo_settings.json")
with open(_TMP, "w", encoding="utf-8") as fh:
    json.dump({"language": "zh"}, fh)
i18n._SETTINGS_PATH = _TMP

import kards_account as account           # noqa: E402
import kards_rank as rank                 # noqa: E402
import kards_shop as shop                 # noqa: E402
import kards_quests as quests             # noqa: E402
import KARDS as gui                       # noqa: E402

NAME = "Scharnhorst"


def seed_account():
    """造一个"已经玩了一阵子"的账号：有钱、有外观、有任务进度。"""
    ok, err = account.register(NAME, "pass1234")
    if not ok and err:
        print("注册跳过：", err)
    account.login(NAME, "pass1234")
    account.currency_add(gold=4800, diamonds=42, name=NAME)
    key = account.wallet_key(NAME)
    today = shop._today()
    st = shop.normalize(None)
    st["owned"] = {"avatar": ["av_crown", "av_star"],
                   "table": ["tb_night", "tb_forest"],
                   "hq": ["hq_steel", "hq_gold"]}
    st["equipped"] = {"avatar": "av_crown", "table": "tb_night", "hq": "hq_gold"}
    st["stock"] = {"date": today, "seed": 0,
                   "ids": ["av_crown", "av_bolt", "tb_night", "tb_snow",
                           "hq_gold", "hq_ember"], "rerolls": 0}
    path = shop._FILE
    try:
        with open(path, encoding="utf-8") as fh:
            db = json.load(fh)
    except (OSError, ValueError):
        db = {}
    db[key] = st
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(db, fh, ensure_ascii=False, indent=1)

    for _ in range(2):
        quests.record_game("win", online=False, nation="德国", my_hq=18,
                           name=NAME)
    quests.record_game("lose", online=False, nation="苏联", my_hq=0, name=NAME)
    return st


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
    # Windows 的开窗淡入动画约 200ms，不等它播完 ImageGrab 会截到半透明帧
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


def find_win(app, role):
    for w in app.winfo_children():
        if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == role:
            return w
    return None


TOP_ROWS = [
    {"name": NAME, "tier": 1, "stars": 4, "pts": 87, "win": 31, "lose": 2, "pos": 1},
    {"name": "北极星", "tier": 1, "stars": 3, "pts": 64, "win": 24, "lose": 4, "pos": 2},
    {"name": "钢蓝", "tier": 1, "stars": 2, "pts": 41, "win": 17, "lose": 5, "pos": 3},
    {"name": "老兵不死", "tier": 1, "stars": 1, "pts": 22, "win": 10, "lose": 3, "pos": 4},
    {"name": "雪原猎手", "tier": 1, "stars": 0, "pts": 9, "win": 5, "lose": 2, "pos": 5},
]


def tk_shots():
    gui.App._account_dialog = lambda self, for_server=False: None
    gui.App.open_update_dialog = lambda self, auto=False: None
    app = gui.App()
    app.geometry("1180x820+20+20")
    try:
        app.attributes("-fullscreen", False)
    except tk.TclError:
        pass
    app.update()

    app.account = NAME
    app.rank_state = {"tier": 1, "stars": 4, "best": 1, "streak": 3,
                      "zero_losses": 0, "season": rank.season_id(),
                      "lb_pts": 87, "lb_win": 31, "lb_lose": 2,
                      "lb_active": True, "ai_wins": 1}
    gui.account.get_rank = lambda name=None: dict(app.rank_state)
    gui.account.leaderboard = lambda limit=20: {
        "rows": TOP_ROWS, "total": 126, "me": TOP_ROWS[0], "online": True,
        "season": rank.season_id()}
    app._refresh_account_btn()
    app.update()
    grab(app, "01_menu.png")

    app.open_shop_dialog()
    app.update()
    win = find_win(app, "shop")
    if win is not None:
        grab(win, "02_shop.png")
        win.destroy()
        app.update()

    app.open_quests_dialog()
    app.update()
    win = find_win(app, "quests")
    if win is not None:
        grab(win, "03_quests.png")
        win.destroy()
        app.update()

    app.open_rank_dialog()
    app.update()
    win = find_win(app, "rank")
    if win is not None:
        grab(win, "04_rank.png")
        win.destroy()
        app.update()

    try:
        app.destroy()
    except Exception:                                      # noqa: BLE001
        pass


def board_shots():
    import pygame
    import kards_board as B
    import kards_engine as core
    sys.path.insert(0, HERE)
    import shot_board as SB

    pygame.init()
    g = SB.make()
    me, foe = g.players[0], g.players[1]
    me.name = NAME
    me.kredits = 4
    SB.unit(g, foe, "步兵", "前线")
    SB.unit(g, foe, "坦克", "后方")
    SB.unit(g, me, "步兵", "前线")
    app = SB.App(g)
    app.account = NAME                 # ← 棋盘按这个账号读商店外观
    b = B.PygameBoard(app, game=g, on_intent=app.pyboard_intent)
    b.anim_enabled = True
    b.sync()
    surf = pygame.Surface((b.W, b.H))

    b.draw(surf)
    pygame.image.save(surf, os.path.join(OUT, "05_battle.png"))
    print("saved 05_battle.png")

    b2 = B.PygameBoard(app, game=g, on_intent=app.pyboard_intent)
    b2.anim_enabled = True
    b2.sync()
    b2.start_intro()
    b2.step(350)
    b2.draw(surf)
    pygame.image.save(surf, os.path.join(OUT, "06_intro.png"))
    print("saved 06_intro.png")

    b3 = B.PygameBoard(app, game=g, on_intent=app.pyboard_intent)
    b3.anim_enabled = True
    b3.sync()
    b3.show_end_animation(True, None, nation="德国")
    b3.step(b3.EXPLODE_MS)
    b3.draw(surf)
    pygame.image.save(surf, os.path.join(OUT, "07_victory.png"))
    print("saved 07_victory.png")


def main():
    st = seed_account()
    tk_shots()
    board_shots()
    print("\n输出目录:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
