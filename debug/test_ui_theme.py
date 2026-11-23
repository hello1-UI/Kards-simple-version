# -*- coding: utf-8 -*-
"""主题系统测试：可切换配色 + 可调主色

背景
    以前配色是写死的模块常量（kards_theme 顶上那一排），玩家没有选择。
    现在有 7 套预设 + 8 个可调主色，运行中即时生效。这个测试锁住三件事：
    ① 每套配色都完整、合法、看得清（WCAG 对比度兜底）；
    ② 换主题真的能把新值灌回两个渲染器（不然换了个寂寞）；
    ③ 主界面在换主题后真的变色（GUI 冒烟）。

运行:
    python debug/test_ui_theme.py          # 全部（GUI 段需要系统 Python + tkinter）
"""
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_engine as core      # noqa: E402
import kards_theme as theme      # noqa: E402

PASS, FAIL = [], []
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [!!] ") + label + (f"  {extra}" if extra else ""))


def main():
    # 测试绝不写玩家的 settings.json
    tmp = os.path.join(tempfile.gettempdir(), "kards_test_theme_settings.json")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({}, fh)
    import kards_i18n as i18n
    i18n._SETTINGS_PATH = tmp

    print("1. 预设齐全：7 套 × 全部 token 都是合法 #rrggbb")
    check("预设数量 >= 7", len(theme.PRESETS) >= 7, list(theme.PRESETS))
    check("预设互不重名", len(set(theme.PRESETS)) == len(theme.PRESETS))
    for name, base in theme.PRESETS.items():
        p = theme.palette(name)
        missing = [t for t in theme.TOKENS if t.lower() not in p]
        check(f"{name}: token 齐全", not missing, missing or "")
        bad = [k for k, v in p.items()
               if isinstance(v, str) and v.startswith("#") and not HEX_RE.match(v)]
        check(f"{name}: 色值格式合法", not bad, bad or "")
        check(f"{name}: 亮暗标记一致",
              bool(p["light_theme"]) == (name == "paper"))

    print("2. 对比度兜底：换任何主题/主色都不允许看不清字")
    for name in theme.PRESETS:
        for acc in [None] + list(theme.ACCENTS.values()):
            p = theme.palette(name, acc)
            tag = f"{name}/{acc or '默认'}"
            check(f"{tag}: 正文/背景 >= 4.5",
                  theme.contrast(p["text"], p["bg"]) >= 4.5)
            check(f"{tag}: 正文/面板 >= 4.5",
                  theme.contrast(p["text"], p["panel"]) >= 4.5)
            check(f"{tag}: 正文/按钮 >= 3",
                  theme.contrast(p["text"], p["btn"]) >= 3)
            check(f"{tag}: 按钮字色/按钮底 >= 3",
                  theme.contrast(p["primary_fg"], p["primary"]) >= 3)
            check(f"{tag}: 次要文字/背景 >= 3",
                  theme.contrast(p["dim"], p["bg"]) >= 3)

    print("3. 主色真的会改样式（不然『可调』就是骗人）")
    base_p = theme.palette("frontline")
    for key, col in theme.ACCENTS.items():
        p = theme.palette("frontline", col)
        check(f"主色 {key}: primary 跟着变", p["primary"] == col)
    check("主色会染底色（bg 随主色轻微变化）",
          any(theme.palette("frontline", c)["bg"] != base_p["bg"]
              for c in theme.ACCENTS.values()))
    check("非法主色 → 回落预设默认",
          theme.palette("frontline", "not-a-color")["primary"]
          == theme.PRESETS["frontline"]["accent"])
    check("非法预设 → 回落默认",
          theme.palette("no_such_preset")["accent"]
          == theme.PRESETS[theme.DEFAULT_PRESET]["accent"])

    print("4. 亮色主题的方向性：paper 必须是深字浅底")
    p = theme.palette("paper")
    check("paper 亮色标记", p["light_theme"] is True)
    check("paper 文字比背景暗",
          theme.luminance(p["text"]) < theme.luminance(p["bg"]))
    check("paper 悬停是压暗而不是提亮",
          theme.contrast(p["btn_hover"], p["bg"])
          != theme.contrast(p["btn"], p["bg"]))
    for name in ("frontline", "midnight", "desert"):
        p = theme.palette(name)
        check(f"{name}: 暗色主题文字比背景亮",
              theme.luminance(p["text"]) > theme.luminance(p["bg"]))

    print("5. 悬停色方向正确")
    check("暗底悬停提亮",
          theme.luminance(theme.hover_of("#222222"))
          > theme.luminance("#222222"))
    check("亮底悬停压暗",
          theme.luminance(theme.hover_of("#dddddd"))
          < theme.luminance("#dddddd"))

    print("6. apply / sync：两个渲染器都能拿到新值")
    ns = {}
    theme.apply("desert", None)
    theme.sync(ns)
    check("sync 灌回全部 token", all(t in ns for t in theme.TOKENS))
    check("sync 后 BG 是 desert 的",
          ns["BG"] == theme.palette("desert")["bg"], ns["BG"])
    theme.apply("paper", None)
    theme.sync(ns)
    check("换主题后再 sync 值也跟着变",
          ns["BG"] == theme.palette("paper")["bg"], ns["BG"])
    check("theme 模块自身常量同步刷新",
          theme.BG == theme.palette("paper")["bg"])
    check("reset 回默认", theme.reset()["accent"]
          == theme.PRESETS[theme.DEFAULT_PRESET]["accent"])
    theme.apply("frontline", None)

    print("7. 持久化：save → load 往返，坏值被忽略")
    theme.apply("olive", theme.ACCENTS["teal"])
    theme.save(theme.preset_name(), theme.accent_color())
    data = json.load(open(tmp, encoding="utf-8"))
    check("写入了 theme_preset", data.get("theme_preset") == "olive",
          data.get("theme_preset"))
    check("写入了 theme_accent", data.get("theme_accent")
          == theme.ACCENTS["teal"], data.get("theme_accent"))
    theme.apply("midnight", None)
    theme.load()
    check("load 恢复 olive + teal",
          theme.preset_name() == "olive"
          and theme.accent_color() == theme.ACCENTS["teal"],
          (theme.preset_name(), theme.accent_color()))
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"theme_preset": "不存在的主题", "theme_accent": "zzz"}, fh)
    theme.apply("frontline", None)
    theme.load()
    check("坏值回落默认", theme.preset_name() == theme.DEFAULT_PRESET
          and theme.accent_color() == theme.PRESETS[theme.DEFAULT_PRESET]["accent"])
    check("load 后 token 与预设一致",
          theme.BG == theme.palette(theme.DEFAULT_PRESET)["bg"])

    print("8. 阵营色是语义色，不随主题变（对局中认敌我不能变色）")
    nc = theme.NATION_COLOR
    theme.apply("paper", None)
    check("换主题后阵营色不变", theme.NATION_COLOR is nc)
    theme.apply("frontline", None)

    print("9. 渲染器不许再抄配色（防止回潮）")
    src = open(os.path.join(ROOT, "KARDS.py"), encoding="utf-8").read()
    check("KARDS.py 不再内联旧按钮色 #4a4f5a", '"#4a4f5a"' not in src)
    check("KARDS.py 不再内联旧主色 #3a5a80", '"#3a5a80"' not in src)
    check("KARDS.py 不再内联旧成功色 #2e6b46", '"#2e6b46"' not in src)
    check("KARDS.py 不再内联旧危险色 #8a3a3a", '"#8a3a3a"' not in src)
    check("KARDS.py 启动时 load + sync",
          "theme.load()" in src and "theme.sync(globals())" in src)
    bsrc = open(os.path.join(ROOT, "kards_board.py"), encoding="utf-8").read()
    check("board 初始化同步主题", "theme.sync(globals())" in bsrc)
    check("board 有 apply_theme", "def apply_theme" in bsrc)
    check("board 不再内联旧按钮色", '"#4a4f5a"' not in bsrc)
    check("board 不再内联旧主色", '"#3a5a80"' not in bsrc)

    print("10. i18n：预设与主色都有三语名字")
    for key in theme.PRESETS:
        check(f"theme_p_{key} 三语齐备",
              all(("theme_p_" + key) in i18n.LANGS[l] for l in ("zh", "en", "ja")))
    for key in theme.ACCENTS:
        check(f"theme_a_{key} 三语齐备",
              all(("theme_a_" + key) in i18n.LANGS[l] for l in ("zh", "en", "ja")))

    # ---------------- GUI 冒烟（需要 tkinter） ----------------
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        has_tk = True
    except Exception as e:                                 # noqa: BLE001
        has_tk = False
        print("(跳过 GUI 段：无 tkinter ——", e, ")")

    if has_tk:
        root.destroy()
        print("11. GUI：换主题真的会重画界面")
        gui_tmp = os.path.join(tempfile.gettempdir(),
                               "kards_test_theme_gui.json")
        with open(gui_tmp, "w", encoding="utf-8") as fh:
            json.dump({"language": "zh"}, fh)
        i18n._SETTINGS_PATH = gui_tmp
        import KARDS as gui
        gui.App._account_dialog = lambda self, for_server=False: None
        gui.App.open_update_dialog = lambda self, auto=False: None

        app = gui.App()
        try:
            app.geometry("1100x760+20+20")
            try:
                app.attributes("-fullscreen", False)
            except tk.TclError:
                pass
            app.update()
            bg_before = app.winfo_children()[0].cget("bg")

            app._pick_theme("desert", None)
            app.update()
            bg_after = app.start_frame.cget("bg")
            check("主菜单底色随主题改变", bg_before != bg_after,
                  (bg_before, bg_after))
            check("窗口底色同步", app.cget("bg") == bg_after)
            check("预设落到 desert", theme.preset_name() == "desert")

            app._pick_theme("desert", theme.ACCENTS["red"])
            app.update()
            check("主色落到红", theme.accent_color() == theme.ACCENTS["red"])

            # 设置窗外观页能建出来（会经过 rebuild → 重建自身）
            app._pick_theme("frontline", None)
            app.update()
            app.open_start_settings(tab="appearance")
            app.update()
            wins = [w for w in app.winfo_children()
                    if isinstance(w, tk.Toplevel)
                    and getattr(w, "role", "") == "start_settings"]
            check("设置窗能打开", bool(wins))
            if wins:
                check("设置窗里有色卡网格", bool(wins[0].winfo_children()))
                wins[0].destroy()
                app.update()

            # 恢复默认按钮真的回到默认主题
            app._pick_theme("paper", None)
            app.update()
            app._pick_theme(theme.DEFAULT_PRESET, None)
            app.update()
            check("恢复默认生效", theme.preset_name() == theme.DEFAULT_PRESET)
        finally:
            theme.reset()
            theme.save(theme.DEFAULT_PRESET, "")
            app.destroy()

    print()
    print("=" * 50)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
