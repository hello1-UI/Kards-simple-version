# -*- coding: utf-8 -*-
"""自定义 UI 模板（kards_theme 的 custom:* 模板）回归测试。

覆盖三层：
    1. 骨架校验：少字段/坏颜色/大小写/亮暗标记 —— 任何野值都不能让游戏起不来；
    2. 增删改查 + 落盘：文件名清洗（防路径穿越）、重名、改名、导入导出；
    3. GUI：设置页入口、编辑器 21 个色块、保存后真的应用、删除后回落默认、
       内容高度不超出窗口（防止再加一段就把按钮裁掉）。

跑法（GUI 段需要带 tkinter 的系统 Python）：
    python debug/test_ui_custom.py
"""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="kards_tpl_")
os.environ["KARDS_DATA_DIR"] = TMP

import kards_theme as theme                                    # noqa: E402
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


def _files():
    d = theme.custom_dir()
    try:
        return sorted(f for f in os.listdir(d) if f.endswith(".json"))
    except OSError:
        return []


def headless():
    print("1. 骨架校验：野值一律回落，绝不抛异常")
    n = theme.normalize_preset({"colors": {"bg": "#abc"}})
    check("3 位色补成 6 位", n["bg"] == "#aabbcc", n["bg"])
    check("缺字段用默认预设补齐",
          n["panel"] == theme.PRESETS[theme.DEFAULT_PRESET]["panel"], n["panel"])
    check("自定义模板标记 raw（原色渲染）", n.get("raw") is True)
    bad = theme.normalize_preset({"bg": "red", "panel": "#12345",
                                  "card": None, "text": 12345})
    base = theme.PRESETS[theme.DEFAULT_PRESET]
    check("非法颜色回落预设", bad["bg"] == base["bg"] and
          bad["panel"] == base["panel"] and bad["card"] == base["card"],
          (bad["bg"], bad["panel"], bad["card"]))
    check("非字符串颜色也不炸", bad["text"] == base["text"], bad["text"])
    check("大小写统一小写", theme.normalize_preset({"BG": "#ABCDEF"})["bg"]
          == "#abcdef")
    check("light 被强制成 bool",
          theme.normalize_preset({"light": 1})["light"] is True
          and theme.normalize_preset({"light": ""})["light"] is False)
    check("非 dict 输入也不炸",
          theme.normalize_preset(None)["bg"] == base["bg"])

    print("\n2. 新建 / 改名 / 重名 / 落盘")
    theme.set_custom_dir(os.path.join(TMP, "themes"))
    k1 = theme.save_custom("夜战", {"colors": {"bg": "#101418",
                                               "panel": "#1b2028",
                                               "text": "#e8e8e8",
                                               "accent": "#00d0a0"}})
    check("返回带命名空间的键", k1 == "custom:夜战", k1)
    check("模板文件已落盘", _files() == ["夜战.json"], _files())
    check("列表里能查到", k1 in theme.custom_presets())
    check("显示名就是用户起的名字", theme.preset_label(k1) == "夜战")
    p = theme.palette(k1)
    check("自定义颜色按原值渲染（不被主色染色）", p["bg"] == "#101418",
          p["bg"])

    k1b = theme.save_custom("夜战·改", {"colors": {"bg": "#101418"}}, key=k1)
    check("改名不改键（引用不失效）", k1b == k1, k1b)
    check("改名后只有一个文件", _files() == ["夜战.json"], _files())
    check("改名后显示名更新", theme.preset_label(k1) == "夜战·改",
          theme.preset_label(k1))

    k2 = theme.save_custom("夜战·改", {"colors": {"bg": "#222222"}})
    check("重名自动加序号", theme.preset_label(k2) == "夜战·改 2",
          theme.preset_label(k2))
    check("重名不覆盖原文件", len(_files()) == 2, _files())

    k3 = theme.save_custom("../../evil", {"colors": {"bg": "#333333"}})
    d = os.path.abspath(theme.custom_dir())
    inside = [f for f in _files() if "evil" in f]
    check("路径穿越被清洗（文件留在模板目录）",
          bool(inside) and os.path.dirname(
              os.path.join(d, inside[0])) == d, (inside, os.listdir(d)))
    check("上级目录没有多出文件",
          not os.path.exists(os.path.join(TMP, "evil.json")))

    k4 = theme.save_custom("ABC", {"colors": {"bg": "#444444"}})
    k5 = theme.save_custom("abc", {"colors": {"bg": "#555555"}})
    check("大小写重名也各自成文件", k4 != k5 and len(_files()) == 5, _files())

    print("\n3. 应用 / 派生 token / 可读性兜底")
    theme.apply(k1, None)
    check("apply 认得自定义键", theme.preset_name() == k1, theme.preset_name())
    check("模块级常量同步到自定义色", theme.BG == "#101418", theme.BG)
    ns = {}
    theme.sync(ns)
    check("sync 把自定义 token 灌回调用方", ns["BG"] == "#101418", ns.get("BG"))
    check("主色派生（按钮/悬停）",
          theme.current()["primary"] == "#00d0a0"
          and theme.current()["primary_hover"] != "#00d0a0")

    k_low = theme.save_custom("瞎配", {"colors": {"bg": "#ffffff",
                                                  "panel": "#ffffff",
                                                  "card": "#ffffff",
                                                  "text": "#ffffff",
                                                  "dim": "#ffffff",
                                                  "mute": "#ffffff"}})
    lp = theme.palette(k_low)
    check("白底白字被兜底成可读", theme.contrast(lp["text"], lp["bg"]) >= 4.5,
          round(theme.contrast(lp["text"], lp["bg"]), 2))
    check("次要文字也有最低对比度",
          theme.contrast(lp["dim"], lp["bg"]) >= 3.0,
          round(theme.contrast(lp["dim"], lp["bg"]), 2))

    bp = theme.palette("frontline")
    check("内置预设仍保留主色染色（行为不变）",
          bp["bg"] != theme.PRESETS["frontline"]["bg"], bp["bg"])

    print("\n4. 持久化：重启后恢复 / 模板被删则回落")
    theme.save(k1, "")
    theme.apply(theme.DEFAULT_PRESET, None)
    got = theme.load()
    check("重启恢复上次的自定义模板", got == k1 and theme.preset_name() == k1,
          got)
    theme.delete_custom(k1)
    got2 = theme.load()
    check("模板被删后 load 回落默认", got2 == theme.DEFAULT_PRESET, got2)
    check("删除后当前主题也回落", theme.preset_name() == theme.DEFAULT_PRESET)

    print("\n5. 坏文件容错：一个坏文件不许拖垮整份配置")
    d = theme.custom_dir()
    with open(os.path.join(d, "坏文件.json"), "w", encoding="utf-8") as fh:
        fh.write("{ 这不是 JSON ")
    with open(os.path.join(d, "列表.json"), "w", encoding="utf-8") as fh:
        json.dump([1, 2, 3], fh)
    with open(os.path.join(d, "半成品.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": "半成品", "colors": {"bg": "#000000"}}, fh)
    theme._custom_cache["sig"] = None
    items = theme.custom_presets()
    labels = [v["name"] for v in items.values()]
    check("坏 JSON 被跳过", "坏文件" not in labels, labels)
    check("非对象 JSON 被跳过", "列表" not in labels, labels)
    check("缺字段的半成品仍可用", "半成品" in labels, labels)
    half = [k for k, v in items.items() if v["name"] == "半成品"][0]
    hp = theme.palette(half)
    check("半成品缺失字段回落预设",
          hp["panel"] == theme.PRESETS[theme.DEFAULT_PRESET]["panel"])

    print("\n6. 导出 / 导入（可分享）")
    kexp = theme.save_custom("分享用", {"colors": {"bg": "#0a0b0c",
                                                   "accent": "#ff8800",
                                                   "text": "#f0f0f0"}})
    path = os.path.join(TMP, "share.json")
    theme.export_custom(kexp, path)
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    check("导出的 JSON 带名字与颜色",
          payload.get("name") == "分享用" and
          payload["colors"]["accent"] == "#ff8800", payload.get("name"))
    check("导出不含本机路径", "path" not in payload and "slug" not in payload)
    kimp = theme.import_custom(path)
    check("导入得到新模板", kimp != kexp and theme.preset_label(kimp) == "分享用 2",
          theme.preset_label(kimp))
    check("导入后颜色一致",
          theme.base_of(kimp)["accent"] == "#ff8800",
          theme.base_of(kimp)["accent"])

    bad_path = os.path.join(TMP, "bad.json")
    with open(bad_path, "w", encoding="utf-8") as fh:
        fh.write("[]")
    try:
        theme.import_custom(bad_path)
        ok_bad = False
    except ValueError:
        ok_bad = True
    check("导入非对象文件报 ValueError", ok_bad)

    empty_path = os.path.join(TMP, "empty.json")
    with open(empty_path, "w", encoding="utf-8") as fh:
        json.dump({"name": "空的"}, fh)
    try:
        theme.import_custom(empty_path)
        ok_empty = False
    except ValueError:
        ok_empty = True
    check("导入没有颜色的文件报 ValueError", ok_empty)

    try:
        theme.import_custom(os.path.join(TMP, "不存在.json"))
        ok_missing = False
    except ValueError:
        ok_missing = True
    check("导入不存在的文件报 ValueError", ok_missing)

    print("\n7. 未知键不污染当前主题")
    theme.apply(kexp, None)
    theme.apply("完全不存在的模板", None)
    check("非法 preset 回落默认", theme.preset_name() == theme.DEFAULT_PRESET,
          theme.preset_name())
    check("base_of 未知键给默认骨架",
          theme.base_of("nope")["bg"] == theme.PRESETS[theme.DEFAULT_PRESET]["bg"])


def gui_tests():
    import tkinter as tk
    from tkinter import messagebox

    print("\n8. GUI：设置页入口 → 编辑器 → 保存应用 → 删除")
    settings = os.path.join(TMP, "settings.json")
    with open(settings, "w", encoding="utf-8") as fh:
        json.dump({"language": "zh"}, fh)
    i18n._SETTINGS_PATH = settings
    i18n.set_lang("zh")

    import KARDS as gui
    gui.App._account_dialog = lambda self, for_server=False: None
    gui.App.open_update_dialog = lambda self, auto=False: None
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showwarning = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None

    # GUI 段换一个干净的模板目录：headless 段存了一堆模板，
    # 否则「空列表提示」永远不成立（用例之间互相污染）。
    theme.set_custom_dir(os.path.join(TMP, "gui_themes"))
    theme.apply(theme.DEFAULT_PRESET, None)
    theme.save(theme.DEFAULT_PRESET, "")
    gui.theme.sync(vars(gui))

    app = gui.App()
    try:
        app.geometry("1180x820+20+20")
        try:
            app.attributes("-fullscreen", False)
        except tk.TclError:
            pass
        app.update()

        def widgets(w):
            try:
                yield w
            except tk.TclError:
                return
            try:
                kids = w.winfo_children()
            except tk.TclError:
                return
            for ch in kids:
                yield from widgets(ch)

        def texts(root):
            out = []
            for w in widgets(root):
                try:
                    t = w.cget("text")
                except (tk.TclError, AttributeError):
                    continue
                if t:
                    out.append(str(t))
            return out

        def scroll_reaches_bottom(win):
            """滚动容器的滚动区能覆盖全部内容（最后一个控件滚得到）。"""
            canvases = [w for w in widgets(win) if isinstance(w, tk.Canvas)
                        and isinstance(getattr(w, "master", None), gui.ScrollBox)]
            if not canvases:
                return False, "没有 ScrollBox"
            c = canvases[0]
            win.update_idletasks()
            bbox = c.bbox("all")
            if not bbox:
                return False, "scrollregion 为空"
            content_h = bbox[3] - bbox[1]
            c.yview_moveto(1.0)
            win.update_idletasks()
            visible_bottom = c.canvasy(c.winfo_height())
            return visible_bottom >= content_h - 2, (content_h, visible_bottom)

        def by_role(role):
            return [w for w in app.winfo_children()
                    if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == role]

        app.open_start_settings(tab="appearance")
        app.update()
        wins = by_role("start_settings")
        check("设置窗能打开", bool(wins))
        win = wins[0]
        body_text = " ".join(texts(win))
        check("外观页有「自定义模板」区", i18n.t("tpl_section") in body_text)
        check("有「新建模板」按钮", i18n.t("tpl_new") in body_text)
        check("有「导入」「导出」入口",
              i18n.t("tpl_import") in body_text and i18n.t("tpl_export") in body_text)
        check("空列表有提示", i18n.t("tpl_empty") in body_text)
        ok_scroll, info_scroll = scroll_reaches_bottom(win)
        check("设置页可滚动且内容能滚到底（不裁按钮）", ok_scroll, info_scroll)

        # ---- 新建：点按钮 → 编辑器 ----
        new_btn = [w for w in widgets(win)
                   if isinstance(w, tk.Button)
                   and str(w.cget("text")) == i18n.t("tpl_new")][0]
        new_btn.invoke()
        app.update()
        editors = by_role("theme_editor")
        check("新建会打开编辑器", bool(editors))
        ed = editors[0]
        check("编辑器内容不超出窗口", ed.winfo_reqheight() <= 700,
              ed.winfo_reqheight())
        ed_texts = " ".join(texts(ed))
        check("编辑器列出全部色块",
              all(i18n.t("tpl_f_" + f) in ed_texts for f in theme.BASE_KEYS),
              [i18n.t("tpl_f_" + f) for f in theme.BASE_KEYS
               if i18n.t("tpl_f_" + f) not in ed_texts])
        check("编辑器有亮色开关", i18n.t("tpl_light") in ed_texts)

        # 色块按钮（空 text 的 Button）共 21 个，第一个 = accent
        swatches = [w for w in widgets(ed)
                    if isinstance(w, tk.Button) and not str(w.cget("text"))]
        check("色块数量 = BASE_KEYS", len(swatches) == len(theme.BASE_KEYS),
              len(swatches))

        gui.colorchooser.askcolor = lambda **kw: ((0, 255, 170), "#00ffaa")
        swatches[0].invoke()          # accent
        app.update()

        # 改名 + 保存
        entries = [w for w in widgets(ed) if isinstance(w, tk.Entry)]
        check("编辑器有名称输入框", bool(entries))
        entries[0].delete(0, "end")
        entries[0].insert(0, "银翼")
        save_btns = [w for w in widgets(ed)
                     if isinstance(w, tk.Button)
                     and str(w.cget("text")) == i18n.t("tpl_save")
                     and str(w.cget("state")) != "disabled"]
        check("保存按钮可点", bool(save_btns))
        save_btns[0].invoke()
        app.update()

        check("保存后编辑器关闭", not by_role("theme_editor"))
        check("保存后主题就是新模板",
              theme.preset_name().startswith(theme.CUSTOM_PREFIX),
              theme.preset_name())
        check("保存后主色是选的色", theme.accent_color() == "#00ffaa",
              theme.accent_color())
        check("模板出现在列表里",
              any(v["name"] == "银翼" for v in theme.custom_presets().values()),
              [v["name"] for v in theme.custom_presets().values()])
        check("保存后设置窗重建且显示模板",
              any("银翼" in " ".join(texts(w)) for w in by_role("start_settings")))

        # ---- 编辑并删除 ----
        key = theme.preset_name()
        app.open_theme_editor(edit_key=key)
        app.update()
        eds = by_role("theme_editor")
        check("能再次打开已有模板", bool(eds))
        ed2 = eds[0]
        check("编辑已有模板时有删除按钮",
              i18n.t("tpl_delete") in " ".join(texts(ed2)))
        messagebox.askyesno = lambda *a, **k: True
        del_btn = [w for w in widgets(ed2)
                   if isinstance(w, tk.Button)
                   and str(w.cget("text")) == i18n.t("tpl_delete")][0]
        del_btn.invoke()
        app.update()
        check("删除后回到默认主题",
              theme.preset_name() == theme.DEFAULT_PRESET, theme.preset_name())
        check("删除后文件真的没了",
              "银翼" not in [v["name"] for v in theme.custom_presets().values()],
              [v["name"] for v in theme.custom_presets().values()])
        check("删除后主窗口仍可用", app.start_frame.winfo_exists() == 1)

        # ---- 对局内外观窗也要有入口且不裁内容 ----
        app.open_theme_dialog()
        app.update()
        dialogs = by_role("theme")
        check("对局内外观窗能打开", bool(dialogs))
        if dialogs:
            dt = " ".join(texts(dialogs[0]))
            check("外观窗也有自定义模板区", i18n.t("tpl_section") in dt)
            ok_d, info_d = scroll_reaches_bottom(dialogs[0])
            check("外观窗可滚动且内容能滚到底", ok_d, info_d)
            dialogs[0].destroy()
            app.update()
    finally:
        try:
            for w in list(app.winfo_children()):
                if isinstance(w, tk.Toplevel):
                    w.destroy()
        except tk.TclError:
            pass
        theme.reset()
        theme.save(theme.DEFAULT_PRESET, "")
        app.destroy()


def main():
    try:
        headless()
        try:
            import tkinter as tk
            r = tk.Tk()
            r.withdraw()
            r.destroy()
            has_tk = True
        except Exception as exc:                            # noqa: BLE001
            has_tk = False
            print("(跳过 GUI 段：无 tkinter ——", exc, ")")
        if has_tk:
            gui_tests()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

    print()
    print("=" * 50)
    print("通过 %d 项 / 失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  -", f)
        sys.exit(1)
    print("全部通过 ✓")


if __name__ == "__main__":
    main()
