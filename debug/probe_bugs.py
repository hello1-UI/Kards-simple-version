# -*- coding: utf-8 -*-
"""界面流转 / 状态泄漏 探 bug 脚本

不是回归测试，而是「主动找茬」：把玩家真实操作路径跑一遍，专挑下面这些
容易出错的地方：

  1. 界面叠加    —— `_build_start()` 不会销毁旧 start_frame，漏一处就两屏同挂
  2. 死路        —— 选国家 / 组卡页进去以后有没有返回出口
  3. 结算串台    —— 结算页整屏点击 + 连点，会不会把人踹进下一屏
  4. 匹配泄漏    —— 离开大厅只清本地标志，服务器仍排队 → 迟到的 matched 抢屏
  5. 状态残留    —— casual / mp_role / busy / 定时器 在回菜单后没清干净

用法（必须系统 Python，受管 Python 无 tkinter）：
    py debug/probe_bugs.py            # 全部探针
    py debug/probe_bugs.py -v         # 打印每一步的界面名

退出码：0 = 没有 FAIL（WARN 不影响），1 = 有 FAIL。
"""
import os
import sys
import tempfile
import json
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ["KARDS_DATA_DIR"] = tempfile.mkdtemp(prefix="kards_probe_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.argv.append("--no-fullscreen")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                        # noqa: E402

import kards_engine as K                    # noqa: E402
import kards_i18n as i18n                   # noqa: E402
import KARDS as gui                         # noqa: E402

VERBOSE = "-v" in sys.argv
PASS, FAIL, WARN = [], [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name
          + (f"   {extra}" if (extra and not cond) else ""))


def warn(name, cond, extra=""):
    if not cond:
        (WARN if not cond else PASS).append(name)
        print(f"  [~~] {name}" + (f"   {extra}" if extra else ""))
    else:
        PASS.append(name)
        print(f"  [OK] {name}")


# ---------------------------------------------------------------- 环境

def make_app():
    tmp = os.path.join(tempfile.gettempdir(), "kards_probe_settings.json")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"language": "zh"}, fh)
    i18n._SETTINGS_PATH = tmp
    i18n.set_lang("zh")
    gui.App._account_dialog = lambda self, for_server=False: None
    gui.App.open_update_dialog = lambda self, auto=False: None
    app = gui.App()
    app.geometry("1180x800+20+20")
    try:
        app.attributes("-fullscreen", False)
    except tk.TclError:
        pass
    app.update()
    return app


def screen_texts(app):
    out = []

    def walk(w):
        try:
            t = w.cget("text")
            if t:
                out.append(str(t))
        except (tk.TclError, AttributeError):
            pass
        for ch in w.winfo_children():
            walk(ch)
    for w in app.winfo_children():
        try:
            if w.winfo_exists():
                walk(w)
        except tk.TclError:
            pass
    return out


def screen_kind(app):
    """认屏。

    ⚠ 别拿「休闲模式」这种文案当唯一标识：它同时是休闲入口页和休闲选国家
    页的标题。选国家页的硬特征是一次出现全部主国名；组卡页有「可选用卡」；
    主菜单的入口卡副标题里也会提到「联机对战」，所以主菜单要先于大厅判断。
    """
    blob = " ".join(screen_texts(app))
    if i18n.t("label_pool") in blob:
        return "组卡"
    if all(n in blob for n in K.MAIN_NATIONS):
        if i18n.t("mode_casual") in blob:
            return "休闲·选国家"
        if i18n.t("mode_mp") in blob:
            return "联机·选国家"
        return "练习·选国家"
    if i18n.t("casual_select_title") in blob:
        return "休闲·选对手"
    if i18n.t("app_title") in blob:
        return "主菜单"
    if i18n.t("lobby_title") in blob:
        return "大厅"
    return "未知"


def walk_widgets(w):
    try:
        yield w
    except Exception:                           # noqa: BLE001
        return
    try:
        kids = w.winfo_children()
    except tk.TclError:
        return
    for ch in kids:
        yield from walk_widgets(ch)


def top_frames(app):
    """主窗口直属的、还活着的 Frame —— 正常永远只有 1 个（当前界面）。"""
    out = []
    for w in app.winfo_children():
        try:
            if w.winfo_exists() and w.winfo_class() == "Frame":
                out.append(w)
        except tk.TclError:
            pass
    return out


def only_one_screen(app, name):
    n = len(top_frames(app))
    check(f"{name}：主窗口只挂 1 个界面", n <= 1, f"实际 {n} 个")
    return n


def has_back(app):
    # 返回按钮的文案带快捷键后缀（"← 返回  P"），用 startswith 判，
    # 免得每次改提示都要跟着改探针。
    back = i18n.t("btn_back")
    return any(str(t).strip().startswith(back) for t in screen_texts(app))


# ---------------------------------------------------------------- 桩

class Rec:
    def __init__(self):
        self.stats, self.rank, self.ai, self.money = [], [], [], []
        self.quest, self.logs = [], []

    def install(self, app):
        gui.account.stats_add = lambda n, r: self.stats.append((n, r))
        gui.account.rank_add = lambda n, r: (
            self.rank.append((n, r)) or {"rank": {"tier": 1, "stars": 1, "season": 1},
                                         "change": {}})
        gui.account.rank_add_ai = lambda n, r: (
            self.ai.append((n, r)) or {"rank": {"tier": 1, "stars": 1, "season": 1},
                                       "change": {}})
        gui.account.currency_reward = lambda r, name=None: (
            self.money.append((name, r)) or {"gold": 10, "diamonds": 0})
        gui.quests.record_game = lambda r, **kw: self.quest.append(r)
        app.add_log = lambda m: self.logs.append(m)
        app._refresh_account_btn = lambda: None
        app._refresh_quest_btn = lambda: None
        app._music_play = lambda *a, **k: None
        app._lobby_log = lambda m: self.logs.append(m)


class FakeBoard:
    """最小棋盘替身：run() 里模拟「一局打完 → 结算页 → 玩家点一下」。"""

    def __init__(self, app):
        self.app = app
        self.on_done = None
        self.result = None
        self.quit_called = False
        self.win = True

    # 视图方法
    def show_end_animation(self, won, on_done=None, nation=None, rank_line=""):
        self.won = won
        self.on_done = on_done

    def start_intro(self):
        pass

    def run(self, pump=None, max_frames=None):
        g = self.app.game
        if g is None:
            return
        g.players[1].hq = 0 if self.win else 1
        if not self.win:
            g.players[0].hq = 0
        self.app.finish()
        if self.on_done is not None:
            self.on_done()          # 模拟「结算页点一下」

    def quit(self):
        self.quit_called = True
        self.result = "leave"

    def refresh(self):
        pass

    def add_log(self, m):
        pass

    def show_banner(self, *a, **k):
        pass


def install_board_stub(app):
    board = FakeBoard(app)

    def activate():
        app._pyboard = board
        app.refresh = board.refresh
        app.add_log = board.add_log
        app.show_banner = board.show_banner
        app.show_end_animation = board.show_end_animation
        app.unit_widgets = {}
        app.enemy_widgets = []
        app.hq_widget = None
        app.my_hq_widget = None
        app.pending_flash = []
        return board

    app._activate_pyboard = activate
    return board


def feed(app, msg):
    """往大厅事件泵里塞一条服务器消息；返回异常（没有异常返回 None）。

    真实环境里 Tk 回调抛异常只会打到 stderr，界面看起来「什么都没发生」，
    所以探针必须把异常抓出来单独判失败。
    """
    try:
        app._lobby_handle_event(msg)
        return None
    except Exception as exc:                    # noqa: BLE001
        return exc


def build_deck_into(app):
    deck = K.build_deck("德国", app.db)
    app.deck_counts = {}
    for c in deck:
        app.deck_counts[c.name] = app.deck_counts.get(c.name, 0) + 1
    return deck


# ---------------------------------------------------------------- 探针

def probe_navigation(app):
    print("\n1. 界面流转：每一屏都要能进能出，且不同屏叠加")
    app.back_to_menu()
    app.update()
    check("回主菜单", screen_kind(app) == "主菜单", screen_kind(app))
    only_one_screen(app, "主菜单")

    app._build_nation_select()
    app.update()
    check("练习 → 选国家", screen_kind(app) == "练习·选国家", screen_kind(app))
    only_one_screen(app, "选国家")
    check("选国家页有「返回」", has_back(app), screen_texts(app)[:6])

    app._build_deck_builder("德国")
    app.update()
    check("选国家 → 组卡", screen_kind(app) == "组卡", screen_kind(app))
    only_one_screen(app, "组卡")
    check("组卡页有「返回」", has_back(app), screen_texts(app)[:6])

    app._deck_back()
    app.update()
    check("组卡 → 返回选国家", screen_kind(app) == "练习·选国家", screen_kind(app))
    only_one_screen(app, "组卡返回后")

    app._nation_back()
    app.update()
    check("选国家 → 返回主菜单", screen_kind(app) == "主菜单", screen_kind(app))
    only_one_screen(app, "选国家返回后")

    print("\n2. 休闲链路")
    app._build_casual_select()
    app.update()
    check("主菜单 → 休闲选对手", screen_kind(app) == "休闲·选对手", screen_kind(app))
    only_one_screen(app, "休闲选对手")
    app._build_nation_select(casual=True)
    app.update()
    check("休闲 → 选国家（casual 标记）", app.casual is True, app.casual)
    app._nation_back()
    app.update()
    check("休闲选国家 → 回休闲选对手",
          screen_kind(app) == "休闲·选对手", screen_kind(app))
    app._casual_back()
    app.update()
    check("休闲选对手 → 回主菜单", screen_kind(app) == "主菜单", screen_kind(app))
    check("回主菜单后 casual 复位", app.casual is False, app.casual)
    only_one_screen(app, "休闲返回后")


def probe_settle(app, rec):
    print("\n3. 结算回菜单：不能被「连点 + 刚出现的卡片」带跑")
    app._build_nation_select()
    app.update()
    app._build_deck_builder("德国")
    app.update()
    build_deck_into(app)
    board = install_board_stub(app)
    app._start_custom()
    app.update()
    check("开局打到结算页（假棋盘接管）", board.on_done is not None)
    check("结算并回菜单后停在同一屏",
          screen_kind(app) in ("主菜单",), f"{screen_kind(app)}")
    only_one_screen(app, "结算后")
    check("结算后 _finishing 复位", app._finishing is False, app._finishing)
    check("结算后 _menu_after_board 复位", app._menu_after_board is False)
    check("结算后 game 已清空", app.game is None)
    check("结算页 quit 被调用", board.quit_called is True)
    check("连胜记录进了战绩", ("Tester", "win") in rec.stats, rec.stats[-3:])

    print("\n4. 换屏点击冷却（防结算页第二下穿透）")
    hits = []
    card = gui.CardWidget(app.start_frame, "T", "S", None, gui.PRIMARY)
    go = card._guard_click(lambda: hits.append(1))
    app._mark_screen()
    go()
    check("刚换屏：点击被吞", hits == [], hits)
    app._screen_built_at = time.monotonic() - (app._click_guard_s + 0.05)
    go()
    check("冷却过后：点击生效", hits == [1], hits)
    card.destroy()

    # 端到端：结算后紧接的那一下点击，不能把主菜单的入口卡点开
    app._build_start()
    app.update()
    cards = [w for w in walk_widgets(app.start_frame)
             if isinstance(w, gui.CardWidget)]
    check("主菜单认得出 3 张入口卡", len(cards) >= 3, len(cards))
    app._mark_screen()                       # 模拟「屏幕刚建好」
    for c in cards:
        c.event_generate("<Button-1>", x=6, y=6)
    app.update()
    check("冷却期内点入口卡无效", screen_kind(app) == "主菜单", screen_kind(app))
    # 对照组：把阈值归零，同一张卡、同样的点击必须立刻生效 ——
    # 否则上面那条"无效"可能只是事件没派发，成了空断言。
    keep = app._click_guard_s
    app._click_guard_s = 0.0
    app._mark_screen()
    cards[1].event_generate("<Button-1>", x=6, y=6)     # 中间那张 = 练习
    app.update()
    check("对照组（阈值归零）：点击立刻生效",
          screen_kind(app) == "练习·选国家", screen_kind(app))
    app._click_guard_s = keep
    app._nation_back()
    app.update()

    print("\n5. 连打两局仍稳定（不叠屏、不重复结算）")
    for i in range(2):
        app._build_nation_select()
        app.update()
        app._build_deck_builder("德国")
        app.update()
        build_deck_into(app)
        before = len(rec.stats)
        app._start_custom()
        app.update()
        only_one_screen(app, f"第 {i + 1} 局结算后")
        check(f"第 {i + 1} 局只记一次战绩", len(rec.stats) == before + 1,
              len(rec.stats) - before)
        check(f"第 {i + 1} 局后停在主菜单", screen_kind(app) == "主菜单",
              screen_kind(app))


def probe_match_leak(app, rec):
    print("\n6. 匹配泄漏：离开大厅必须让服务器放人，迟到 matched 不许抢屏")

    class FakeLink:
        def __init__(self):
            self.alive = True
            self.msgs = []

        def send(self, m):
            self.msgs.append(m)
            return True

    # 6.1 排队中返回大厅
    app.back_to_menu()
    app.update()
    link = FakeLink()
    app.mp_link = link
    app.mp_matching = True
    app.mp_room_code = None
    app._lobby_back()
    app.update()
    check("排队中返回 → 通知服务器取消匹配",
          {"m": "cancel_match"} in link.msgs, link.msgs)
    check("排队中返回 → 本地标志清空", app.mp_matching is False)
    check("排队中返回 → 落到主菜单", screen_kind(app) == "主菜单", screen_kind(app))

    # 6.2 开着房间返回
    link2 = FakeLink()
    app.mp_link = link2
    app.mp_matching = False
    app.mp_room_code = "ABC123"
    app._lobby_back()
    app.update()
    check("房间中返回 → 通知服务器退出房间",
          {"m": "leave_room"} in link2.msgs, link2.msgs)

    # 6.3 迟到的 matched（已回主菜单）：不许进准备页
    link3 = FakeLink()
    app.mp_link = link3
    app._lobby_active = False
    app.game = None
    app.mp_matching = True
    err = feed(app, {"m": "matched", "role": "host", "opp": "Foe",
                     "room": 7, "casual": 0})
    app.update()
    check("迟到的 matched 不进准备页",
          err is None and screen_kind(app) == "主菜单",
          f"异常 {err!r}" if err else screen_kind(app))
    check("迟到的 matched 会放掉房间",
          {"m": "leave_room"} in link3.msgs, link3.msgs)
    check("迟到的 matched 清掉排队标志", app.mp_matching is False)

    # 6.4 对局中收到 matched
    g = K.Game(K.Player("我", "德国", [app.db["近卫步兵"]] * K.DECK_SIZE),
               K.Player("敌", "苏联", [app.db["近卫步兵"]] * K.DECK_SIZE),
               interactive=False)
    app.game = g
    app._lobby_active = True
    err = feed(app, {"m": "matched", "role": "guest", "opp": "Foe",
                     "room": 8, "casual": 0})
    check("对局中的 matched 被丢弃",
          err is None and screen_kind(app) == "主菜单",
          f"异常 {err!r}" if err else screen_kind(app))

    # 6.5 回菜单会停掉大厅轮询
    app._lobby_active = True
    app._schedule("_t_lobby", 5000, lambda: None)
    app.game = None
    app.mp_link = FakeLink()
    app.back_to_menu()
    app.update()
    check("回菜单停掉大厅轮询", app._t_lobby is None, app._t_lobby)
    check("回菜单清掉大厅激活标志", app._lobby_active is False)

    # 6.6 非大厅路径回主菜单（语言/主题切换也是 _build_start）也必须脱队
    link4 = FakeLink()
    app.mp_link = link4
    app._lobby_active = True
    app.mp_matching = True
    app.mp_room_code = None
    app._destroy_alive("start_frame")
    app._build_start()          # 模拟「在大厅排队时切语言/主题」
    app.update()
    check("非大厅入口回主菜单也会取消匹配",
          {"m": "cancel_match"} in link4.msgs, link4.msgs)
    check("非大厅入口回主菜单清掉排队", app.mp_matching is False)
    n_before = len(link4.msgs)
    app._build_start()
    app.update()
    check("重复回主菜单不会重复发取消",
          len(link4.msgs) == n_before, link4.msgs[n_before:])

    print("\n7. 回菜单后的状态残留")
    check("game 清空", app.game is None)
    check("busy 解锁", app.busy is False)
    check("selected 清空", app.selected is None)
    check("mp_role 清空", app.mp_role is None)
    check("mp_matching 清空", app.mp_matching is False)
    check("mp_room_code 清空", app.mp_room_code is None)
    check("casual 复位", app.casual is False)
    check("_mp_game_over 复位", app._mp_game_over is False)
    only_one_screen(app, "多次回菜单后")


def probe_stuck_flags(app):
    print("\n8. 卡死标志：连续开关菜单不会把 _finishing 卡在 True")
    for _ in range(5):
        app._build_casual_select()
        app._casual_back()
        app.update()
    check("反复进出休闲 5 次后界面仍只有一个", len(top_frames(app)) <= 1,
          len(top_frames(app)))
    check("_finishing 未被卡住", app._finishing is False, app._finishing)
    check("仍在主菜单", screen_kind(app) == "主菜单", screen_kind(app))

    print("\n9. 结算页重复点击只回一次菜单")
    app._menu_after_board = False
    app.back_to_menu()
    app.update()
    st = app._screen_built_at
    app.back_to_menu()
    app.update()
    check("连按两次返回不会叠屏", len(top_frames(app)) <= 1, len(top_frames(app)))
    warn("第二次返回确实刷新了换屏时间戳（服务点击冷却）",
         app._screen_built_at >= st)


def main():
    app = make_app()
    rec = Rec()
    try:
        app.account = "Tester"
        rec.install(app)
        probe_navigation(app)
        probe_settle(app, rec)
        probe_match_leak(app, rec)
        probe_stuck_flags(app)
    finally:
        try:
            app.destroy()
        except Exception:                       # noqa: BLE001
            pass

    print()
    print("=" * 60)
    print(f"通过 {len(PASS)}　警告 {len(WARN)}　失败 {len(FAIL)}")
    if WARN:
        for w in WARN:
            print("  [~~]", w)
    if FAIL:
        for f in FAIL:
            print("  [!!]", f)
        return 1
    print("没有发现界面流转 / 状态泄漏问题")
    return 0


if __name__ == "__main__":
    sys.exit(main())
