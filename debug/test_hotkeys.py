# -*- coding: utf-8 -*-
"""主菜单字母快捷键回归测试（Q W E R T Y A S F G H）。

覆盖三层：
    1. 键位表：12 个键齐全、指向真实存在的方法、字母大小写都能触发；
    2. 守门条件：对局中 / 不在主菜单 / 有对话框 / 焦点在输入框 —— 一律不响应；
    3. 界面提示：三张入口卡有 F/G/H 角标、工具条六个按钮有 Q/W/E/R/T/Y 字母。

跑法（GUI 段需要带 tkinter 的系统 Python）：
    python debug/test_hotkeys.py
"""

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="kards_keys_")
os.environ["KARDS_DATA_DIR"] = TMP

import kards_i18n as i18n                                      # noqa: E402

PASS = []
FAIL = []


def check(label, cond, extra=""):
    if cond:
        PASS.append(label)
        print("  [OK] %s" % label)
    else:
        FAIL.append(label)
        print("  [FAIL] %s  %s" % (label, extra))


EXPECT = {
    "q": "open_start_settings",
    "w": "_home_theme_switch",
    "e": "open_rank_dialog",
    "r": "open_shop_dialog",
    "t": "open_quests_dialog",
    "y": "_toggle_music",
    "a": "_account_dialog",
    "s": "open_keyword_guide",
    "f": "on_battle",
    "g": "_practice_entry",
    "h": "_build_casual_select",
    "l": "on_hall",
}


class Ev:
    """假的 tkinter 事件：只需要 keysym。"""

    def __init__(self, keysym):
        self.keysym = keysym


def _one_screen(app):
    """主窗口直属的、还活着的 Frame —— 正常永远 ≤1 个（叠屏是历史 bug）。"""
    n = 0
    for w in app.winfo_children():
        try:
            if w.winfo_exists() and w.winfo_class() == "Frame":
                n += 1
        except Exception:                              # noqa: BLE001
            pass
    return n <= 1


def headless():
    print("1. 键位表（主菜单快捷键 12 个）")
    import KARDS as gui
    table = gui.App.HOTKEYS
    check("12 个键齐全", len(table) == 12, len(table))
    missing = {k: v for k, v in EXPECT.items() if table.get(k) != v}
    check("每个键指向的处理函数与需求一致", not missing, missing)
    bad = {k: v for k, v in table.items() if not callable(getattr(gui.App, v, None))}
    check("处理函数都真实存在", not bad, bad)
    check("没有多余键", set(table) == set(EXPECT), set(table) ^ set(EXPECT))
    # 字母键不能落到 Tk 的默认行为上（例如 <space> 会激活焦点按钮）
    check("不含特殊键名", all(len(k) == 1 and k.islower() for k in table), list(table))

    print("\n2. 首页提示文案提到快捷键")
    for lang in ("zh", "en", "ja"):
        t = i18n.LANGS[lang].get("home_hint", "")
        check("%s 的 home_hint 含 F/G/H" % lang, "F" in t and "G" in t and "H" in t, t)


def gui_tests():
    import tkinter as tk

    print("\n3. GUI：界面角标 + 按键分发 + 守门条件")
    settings = os.path.join(TMP, "settings.json")
    with open(settings, "w", encoding="utf-8") as fh:
        json.dump({"language": "zh"}, fh)
    i18n._SETTINGS_PATH = settings
    i18n.set_lang("zh")

    import KARDS as gui
    gui.App._account_dialog = lambda self, for_server=False: None
    gui.App.open_update_dialog = lambda self, auto=False: None

    import tkinter.messagebox as mb
    mb.showinfo = lambda *a, **k: None
    mb.showwarning = lambda *a, **k: None
    mb.showerror = lambda *a, **k: None

    app = gui.App()
    try:
        app.geometry("1180x820+20+20")
        try:
            app.attributes("-fullscreen", False)
        except tk.TclError:
            pass
        app.update()

        def kids(w):
            try:
                return list(w.winfo_children())
            except tk.TclError:
                return []

        def walk(w, out):
            for c in kids(w):
                out.append(c)
                walk(c, out)
            return out

        all_w = walk(app, [])
        labels = [c.cget("text") for c in all_w
                  if isinstance(c, tk.Label)]

        # ---- 角标：三张入口卡各挂一个字母 ----
        cards = getattr(app, "_menu_cards", ())
        check("主菜单记下了四张入口卡", len(cards) == 4, cards)
        got = []
        for c in cards:
            txt = [w.cget("text") for w in kids(c) if isinstance(w, tk.Label)]
            hit = [t for t in txt if t in ("F", "G", "H", "L")]
            got.extend(hit)
        check("入口卡带 F/G/H/L 角标", sorted(got) == ["F", "G", "H", "L"], got)
        check("工具条带 Q/W/E/R/T/Y 字母",
              {"Q", "W", "E", "R", "T", "Y"} <= set(labels),
              [x for x in labels if len(x) == 1])

        # ---- 分发 ----
        def dispatch(keysym):
            calls.clear()
            app._hotkey_at = 0.0          # 绕开 0.25s 连发保护
            app.on_hotkey(Ev(keysym))
            return list(calls)

        calls = []
        saved = {}
        for key, name in EXPECT.items():
            saved[name] = getattr(app, name)
            setattr(app, name, (lambda k: (lambda *a, **kw: calls.append(k)))(key))

        check("主菜单判据为真", app._on_main_menu() is True)
        for key in EXPECT:
            check("按 %s 触发 %s" % (key.upper(), EXPECT[key]),
                  dispatch(key) == [key], dispatch(key))

        check("大写 keysym（Shift+字母）同样生效",
              dispatch("Q") == ["q"], dispatch("Q"))
        check("未映射的键不触发任何动作", dispatch("z") == [], dispatch("z"))
        check("方向键不触发（keysym 带名字）", dispatch("Up") == [], dispatch("Up"))

        # ---- 守门：对局中 ----
        app.game = object()
        check("对局中（tkinter 棋盘）不响应", dispatch("q") == [], dispatch("q"))
        app.game = None
        app._pyboard = object()
        check("对局中（pygame 棋盘）不响应", dispatch("q") == [], dispatch("q"))
        app._pyboard = None

        # ---- 守门：对话框开着 ----
        dlg = tk.Toplevel(app)
        dlg.role = "start_settings"
        app.update()
        check("有对话框开着时不响应", dispatch("r") == [], dispatch("r"))
        dlg.destroy()
        app.update()
        check("对话框关掉后恢复响应", dispatch("r") == ["r"], dispatch("r"))

        # ---- 守门：焦点在输入框（账号 / 密码） ----
        entry = tk.Entry(app)
        real_focus = app.focus_get
        app.focus_get = lambda: entry
        check("焦点在输入框时不响应（不然打不出字）",
              dispatch("a") == [], dispatch("a"))
        text = tk.Text(app)
        app.focus_get = lambda: text
        check("焦点在多行文本框时也不响应", dispatch("a") == [], dispatch("a"))
        app.focus_get = real_focus
        check("焦点离开输入框后恢复响应", dispatch("a") == ["a"], dispatch("a"))

        # ---- 守门：不在主菜单 ----
        app._build_nation_select()
        app.update()
        check("选国家页判据为假", app._on_main_menu() is False)
        check("选国家页不响应入口快捷键", dispatch("f") == [], dispatch("f"))
        check("选国家页不响应工具快捷键", dispatch("r") == [], dispatch("r"))

        app._build_casual_select()
        app.update()
        check("休闲选择页也不响应", dispatch("h") == [], dispatch("h"))

        app._build_start()
        app.update()
        check("回主菜单后判据恢复", app._on_main_menu() is True)
        check("回主菜单后按键恢复", dispatch("q") == ["q"], dispatch("q"))

        # ---- 异常不许把界面搞崩 ----
        def boom(*a, **kw):
            raise RuntimeError("handler boom")
        app.open_shop_dialog = boom
        try:
            dispatch("r")
            crashed = False
        except Exception:                              # noqa: BLE001
            crashed = True
        check("处理函数抛异常不会冒出来", not crashed)
        check("异常后主菜单还在", app._on_main_menu() is True)

        # ---- 连发保护：按住不放不会连开 ----
        app.open_shop_dialog = saved["open_shop_dialog"]
        calls.clear()
        app._hotkey_at = __import__("time").monotonic()
        app.on_hotkey(Ev("r"))
        check("0.25s 内的重复按键被吞掉（防按住连开）", calls == [], calls)

        # ---- 音乐按钮改文案后，Y 角标还在 ----
        app._refresh_music_btn()
        app.update()
        chips = [w.cget("text") for w in kids(app.music_box)
                 if isinstance(w, tk.Label)]
        check("音乐按钮换文案后 Y 角标不丢", chips == ["Y"], chips)
        check("工具条按钮已重新包装（music_btn 仍在）",
              isinstance(app.music_btn, tk.Button))

        # ---- P：子界面返回（与 Q~H 相反：只在子界面生效）----
        print("  -- P 返回 --")
        for name, fn in saved.items():
            setattr(app, name, fn)

        app._build_start()
        app.update()
        dispatch("p")
        check("主菜单按 P 无动作", app._on_main_menu() is True,
              app._on_main_menu())
        check("主菜单没有登记返回动作", app._back_action is None)
        check("按 P 不触发任何快捷键", dispatch("p") == [], dispatch("p"))

        app._build_casual_select()
        app.update()
        check("休闲选择页登记了返回动作",
              callable(app._back_action), app._back_action)
        check("休闲选择页有 P 提示的返回按钮",
              any(str(w.cget("text")).endswith("P")
                  for w in walk(app, []) if isinstance(w, tk.Button)))
        dispatch("p")
        app.update()
        check("休闲选择页按 P 回主菜单", app._on_main_menu() is True)
        check("主菜单只有一套界面", _one_screen(app))

        app._build_nation_select()
        app.update()
        dispatch("p")
        app.update()
        check("练习·选国家按 P 回主菜单", app._on_main_menu() is True)
        check("选国家返回后不叠屏", _one_screen(app))

        # 组卡页 → 选国家（上一级不是主菜单）
        app._build_nation_select()
        app.update()
        app._build_deck_builder("德国")
        app.update()
        check("组卡页登记了返回动作", callable(app._back_action))
        dispatch("p")
        app.update()
        check("组卡页按 P 回选国家（不是直接回主菜单）",
              app._on_main_menu() is False and
              any(str(w.cget("text")).startswith(i18n.t("btn_back"))
                  for w in walk(app, []) if isinstance(w, tk.Button)))
        check("组卡返回后不叠屏", _one_screen(app))

        # 大厅 → 主菜单（必须顺手脱队）
        app._build_lobby()
        app.update()
        app.mp_matching = True
        dispatch("p")
        app.update()
        check("大厅按 P 回主菜单", app._on_main_menu() is True)
        check("大厅按 P 顺带取消排队标志", app.mp_matching is False)
        check("大厅返回后不叠屏", _one_screen(app))

        # ---- P 的守门条件 ----
        app._build_casual_select()
        app.update()
        app.game = object()
        dispatch("p")
        app.update()
        check("对局中按 P 不返回（要 Esc 走判负确认）",
              app._on_main_menu() is False)
        app.game = None
        app._pyboard = object()
        dispatch("p")
        app.update()
        check("pygame 棋盘里按 P 不返回", app._on_main_menu() is False)
        app._pyboard = None

        dlg2 = tk.Toplevel(app)
        dlg2.role = "shop"
        app.update()
        dispatch("p")
        app.update()
        check("对话框开着按 P 不关对话框也不跳屏", app._on_main_menu() is False)
        dlg2.destroy()
        app.update()

        entry2 = tk.Entry(app)
        app.focus_get = lambda: entry2
        dispatch("p")
        app.update()
        check("焦点在输入框时 P 只是字母 p", app._on_main_menu() is False)
        app.focus_get = real_focus

        # 连发保护：这里必须直接调 on_hotkey（dispatch 会重置时间戳，
        # 那等于把要测的保护关掉了）
        app._hotkey_at = __import__("time").monotonic()
        app.on_hotkey(Ev("p"))
        app.update()
        check("0.25s 内的重复 P 被吞掉", app._on_main_menu() is False)

        dispatch("p")
        app.update()
        check("守门解除后 P 恢复正常", app._on_main_menu() is True)

        for name, fn in saved.items():
            setattr(app, name, fn)
    finally:
        try:
            app.destroy()
        except Exception:                              # noqa: BLE001
            pass


def main():
    headless()
    try:
        gui_tests()
    except Exception:                                  # noqa: BLE001
        import traceback
        traceback.print_exc()
        FAIL.append("GUI 段异常")

    print("\n" + "=" * 52)
    print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    sys.argv = [sys.argv[0], "--no-fullscreen", "--no-update-check"]
    main()
