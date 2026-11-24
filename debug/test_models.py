# -*- coding: utf-8 -*-
"""内置 UI 模板（models/*.json）回归测试

背景
    设置 → 外观里除了 7 套内置预设、玩家自建模板之外，还会显示随安装包分发的
    「编好的模板」（models/*.json，带「内置」标记）。这些文件：
      * 只读 —— 编辑器里点「复制」才会另存成用户模板；
      * 由 apk/install.py 在安装时**可选删除**（`--no-models`）；
      * 语言跟随 UI（name / name_en / name_ja）。

本测试锁定：
    1. 磁盘上的模板文件齐全、字段完整、颜色合法、名字唯一，且与生成脚本一致；
    2. 加载/应用/持久化：选过的内置模板重启后仍生效；模板被删则回落默认；
    3. 只读语义：is_editable=False、复制生成 custom:、模型文件一个字节都不变；
    4. 容错：坏 JSON 跳过、同名 slug 由优先目录覆盖、绝不抛异常；
    5. 安装器：models/ 与 _internal/models/ 都数得到、删得掉，且不碰用户 themes/；
       `--no-models` / `--models` 解析、无 stdin 时默认保留；
    6. GUI：外观页列出全部模板（含「内置」标记）、点胶囊即应用、
       点「复制」打开编辑器并预填、保存后变成用户模板。

跑法（GUI 段需要带 tkinter 的系统 Python）：
    python debug/test_models.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODELS_DIR = os.path.join(ROOT, "models")
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="kards_models_")
os.environ["KARDS_DATA_DIR"] = TMP

import kards_theme as theme                                    # noqa: E402
import kards_i18n as i18n                                      # noqa: E402

PASS, FAIL = [], []


def check(label, cond, extra=""):
    if cond:
        PASS.append(label)
        print("  [OK] %s" % label)
    else:
        FAIL.append(label)
        print("  [FAIL] %s  %s" % (label, extra))


def _model_files():
    try:
        return sorted(f for f in os.listdir(MODELS_DIR) if f.endswith(".json"))
    except OSError:
        return []


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


def headless():
    print("1. 磁盘上的内置模板文件")
    files = _model_files()
    check("models/ 目录存在且有模板", len(files) >= 10, len(files))
    bad = []
    keys = set()
    names = set()
    for fn in files:
        try:
            with open(os.path.join(MODELS_DIR, fn), encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError) as exc:
            bad.append("%s: %s" % (fn, exc))
            continue
        if not isinstance(raw, dict):
            bad.append(fn + ": 不是对象")
            continue
        colors = raw.get("colors") or {}
        missing = [k for k in theme.BASE_KEYS if k not in colors]
        if missing:
            bad.append("%s 缺键 %s" % (fn, missing))
        for k in theme.BASE_KEYS:
            if k in colors and theme._norm_hex(colors[k]) != colors[k]:
                bad.append("%s.%s=%r 非法" % (fn, k, colors[k]))
        for field in ("name", "name_en", "name_ja", "base"):
            if not str(raw.get(field) or "").strip():
                bad.append("%s 缺 %s" % (fn, field))
        if raw.get("base") not in theme.PRESETS:
            bad.append("%s base=%r 不是内置预设" % (fn, raw.get("base")))
        if not isinstance(raw.get("light"), bool):
            bad.append("%s light 不是 bool" % fn)
        key = os.path.splitext(fn)[0]
        if key in keys:
            bad.append("slug 重复: " + key)
        keys.add(key)
        nm = str(raw.get("name") or "")
        if nm.lower() in names:
            bad.append("显示名重复: " + nm)
        names.add(nm.lower())
    check("全部模板格式合法（21 键 / 颜色 / 名称 / base）", not bad, bad[:6])

    r = subprocess.run([sys.executable, os.path.join(HERE, "gen_models.py"),
                        "--check"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    check("生成脚本自检通过（对比度等）", r.returncode == 0,
          (r.stdout or r.stderr or "").strip()[-200:])

    print("\n2. 加载：键命名空间 / 与预设共存")
    theme.set_custom_dir(os.path.join(TMP, "themes"))
    theme.set_model_dir(None)                 # 走自动探测（项目根 models/）
    models = theme.model_presets()
    check("加载到全部内置模板", len(models) == len(files),
          (len(models), len(files)))
    check("键统一带 model: 前缀",
          all(k.startswith(theme.MODEL_PREFIX) for k in models))
    check("与内置预设不互相覆盖",
          all(k in theme.all_presets() for k in theme.PRESETS)
          and all(k in theme.all_presets() for k in models))
    check("is_model / is_editable 区分只读",
          all(theme.is_model(k) and not theme.is_editable(k) for k in models))

    print("\n3. 每套配色都能直接上屏（对比度兜底）")
    weak = []
    for key in models:
        pal = theme.palette(key)
        if theme.contrast(pal["text"], pal["bg"]) < 4.5:
            weak.append("%s text/bg %.2f" % (key, theme.contrast(
                pal["text"], pal["bg"])))
        if theme.contrast(pal["dim"], pal["bg"]) < 3.0:
            weak.append("%s dim/bg" % key)
        if theme.contrast(pal["primary_fg"], pal["accent"]) < 3.0:
            weak.append("%s accent/fg" % key)
        light = bool(theme.base_of(key).get("light"))
        if light != (theme.luminance(pal["bg"]) > 0.5):
            weak.append("%s 亮暗标记与底色不符" % key)
    check("全部模板正文/次要文字/按钮字可读", not weak, weak[:6])

    print("\n4. 名称跟随界面语言")
    i18n.set_lang("zh")
    check("中文名", theme.preset_label("model:nordic-night") == "北境夜航",
          theme.preset_label("model:nordic-night"))
    i18n.set_lang("en")
    check("英文名", theme.preset_label("model:nordic-night") == "Nordic Night",
          theme.preset_label("model:nordic-night"))
    i18n.set_lang("ja")
    check("日文名", theme.preset_label("model:nordic-night") == "北極夜航",
          theme.preset_label("model:nordic-night"))
    i18n.set_lang("zh")
    check("缺翻译时回落中文",
          theme.preset_label("model:desert-fox") == "沙漠之狐")

    print("\n5. 应用 + 持久化 + 模板缺失时回落")
    settings = os.path.join(TMP, "settings.json")
    i18n._SETTINGS_PATH = settings
    _write(settings, {"language": "zh"})
    i18n.set_lang("zh")

    pal = theme.apply("model:blood-iron", None)
    check("apply 生效", theme.preset_name() == "model:blood-iron",
          theme.preset_name())
    check("token 用模板自己的颜色", pal["bg"] == "#14100f", pal["bg"])
    theme.save("model:blood-iron", "")
    check("load 能恢复内置模板", theme.load() == "model:blood-iron",
          theme.preset_name())

    theme.set_model_dir(os.path.join(TMP, "no_such_dir"))
    check("模板目录不见 → 回落默认（安装器删掉 models/ 的情形）",
          theme.load() == theme.DEFAULT_PRESET, theme.preset_name())
    theme.set_model_dir(None)
    theme.load()

    print("\n6. 只读语义：复制 / 导出 / 改名")
    theme.set_custom_dir(os.path.join(TMP, "themes2"))
    before = {f: os.path.getsize(os.path.join(MODELS_DIR, f)) for f in files}
    src = theme.base_of("model:nordic-night")
    k = theme.save_custom("北境夜航（我的）", src)
    check("复制成用户模板", theme.is_custom(k), k)
    check("模型文件未被改动",
          {f: os.path.getsize(os.path.join(MODELS_DIR, f)) for f in files}
          == before)
    dup = theme.save_custom("北境夜航", src)
    check("与内置模板重名会自动加序号",
          theme.preset_label(dup) == "北境夜航 2", theme.preset_label(dup))

    ex = os.path.join(TMP, "export.json")
    theme.export_custom("model:nordic-night", ex)
    with open(ex, encoding="utf-8") as fh:
        payload = json.load(fh)
    check("导出的 JSON 含 21 色",
          set(payload.get("colors") or {}) == set(theme.BASE_KEYS))
    check("导出的 JSON 带三语言名字",
          payload.get("name") == "北境夜航"
          and payload.get("name_en") == "Nordic Night")
    imported = theme.import_custom(ex)
    check("导回来变成用户模板", theme.is_custom(imported), imported)
    try:
        theme.export_custom("model:not-exist", ex)
        check("导出不存在的模板会报错", False)
    except ValueError:
        check("导出不存在的模板会报错", True)

    print("\n7. 容错：坏文件跳过 / 优先目录覆盖")
    bad_dir = os.path.join(TMP, "bad_models")
    _write(os.path.join(bad_dir, "broken.json"), "{ 这不是 JSON")
    _write(os.path.join(bad_dir, "half.json"), {"name": "半成品",
                                                "colors": {"bg": "#112233"}})
    theme.set_model_dir(bad_dir)
    got = theme.model_presets()
    check("坏文件被跳过、半成品仍可用",
          "model:half" in got and "model:broken" not in got, list(got))
    check("半成品缺色回落预设",
          got["model:half"]["data"]["panel"]
          == theme.PRESETS[theme.DEFAULT_PRESET]["panel"])

    over = os.path.join(TMP, "override_models")
    _write(os.path.join(over, "nordic-night.json"),
           {"name": "覆盖后的名字", "colors": {"bg": "#101820"}})
    theme.set_model_dir(None)
    os.environ["KARDS_MODELS_DIR"] = over
    theme.set_model_dir(None)                 # 清缓存
    check("KARDS_MODELS_DIR 优先于随包目录",
          theme.preset_label("model:nordic-night") == "覆盖后的名字",
          theme.preset_label("model:nordic-night"))
    os.environ.pop("KARDS_MODELS_DIR", None)
    theme.set_model_dir(None)
    check("去掉环境变量后回到随包模板",
          theme.preset_label("model:nordic-night") == "北境夜航",
          theme.preset_label("model:nordic-night"))


def installer_tests():
    print("\n8. 安装器：可选删除内置模板")
    sys.path.insert(0, os.path.join(ROOT, "apk"))
    import install                                             # noqa: E402

    d = os.path.join(TMP, "install_dir")
    _write(os.path.join(d, "models", "a.json"), {"name": "A"})
    _write(os.path.join(d, "models", "b.json"), {"name": "B"})
    _write(os.path.join(d, "_internal", "models", "c.json"), {"name": "C"})
    _write(os.path.join(d, "_internal", "models", "readme.txt"), "not a template")
    _write(os.path.join(d, "themes", "mine.json"), {"name": "我的"})

    n, size = install.models_info(d)
    check("两层布局都数得到（外层 + _internal）", n == 3, n)
    check("只统计 json、字节数合理", size > 0, size)

    check("ask_keep_models(keep=True) 不问直接保留",
          install.ask_keep_models(d, keep=True) is True)
    check("ask_keep_models(keep=False) 不问直接删",
          install.ask_keep_models(d, keep=False) is False)

    removed = install.remove_models(d)
    check("删除返回套数", removed == 3, removed)
    check("models/ 已删", not os.path.isdir(os.path.join(d, "models")))
    check("_internal/models/ 已删",
          not os.path.isdir(os.path.join(d, "_internal", "models")))
    check("用户 themes/ 不受影响",
          os.path.isfile(os.path.join(d, "themes", "mine.json")))
    check("重复删除是安全的（幂等）", install.remove_models(d) == 0)

    empty = os.path.join(TMP, "empty_install")
    os.makedirs(empty, exist_ok=True)
    check("没有模板时 ask_keep_models 直接放行",
          install.ask_keep_models(empty) is True)

    keep, rest = install.parse_flags(["install.py", "--no-models"])
    check("--no-models 解析", keep is False and rest == ["install.py"], (keep, rest))
    keep, rest = install.parse_flags(["install.py", r"D:\Games\KARDS", "--models"])
    check("--models 解析且路径保留",
          keep is True and rest == ["install.py", r"D:\Games\KARDS"], (keep, rest))
    keep, rest = install.parse_flags(["install.py", "--whatever", "D:/g"])
    check("未知开关被忽略、不当成路径",
          keep is None and rest == ["install.py", "D:/g"], (keep, rest))

    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "import install\n"
        "print('KEEP=%%s' %% install.ask_keep_models(%r))\n"
        % (os.path.join(ROOT, "apk"), d)
    )
    r = subprocess.run([sys.executable, "-c", code], stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    check("无 stdin（双击 exe）时默认保留", "KEEP=True" in (r.stdout or ""),
          (r.stdout or "") + (r.stderr or "")[-200:])


def gui_tests():
    import tkinter as tk
    from tkinter import messagebox

    print("\n9. GUI：外观页列出内置模板 → 点选 → 复制")
    settings = os.path.join(TMP, "settings.json")
    _write(settings, {"language": "zh"})
    i18n._SETTINGS_PATH = settings
    i18n.set_lang("zh")

    import KARDS as gui                                        # noqa: E402
    gui.App._account_dialog = lambda self, for_server=False: None
    gui.App.open_update_dialog = lambda self, auto=False: None
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showwarning = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    messagebox.askyesno = lambda *a, **k: True

    theme.set_custom_dir(os.path.join(TMP, "gui_themes"))
    theme.set_model_dir(None)
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

        def chips(root):
            """模板胶囊：212x46 的 Frame。

            ⚠ 必须同时比高度：上面那排内置预设色卡也是 width=212（height=94），
            只看宽度会把 7 张预设卡一起算进来。
            """
            out = []
            for w in widgets(root):
                if not isinstance(w, tk.Frame):
                    continue
                try:
                    if (str(w.cget("width")) == "212"
                            and str(w.cget("height")) == "46"):
                        out.append(w)
                except tk.TclError:
                    continue
            return out

        def by_role(role):
            return [w for w in app.winfo_children()
                    if isinstance(w, tk.Toplevel)
                    and getattr(w, "role", "") == role]

        app.open_start_settings(tab="appearance")
        app.update()
        wins = by_role("start_settings")
        check("设置窗能打开", bool(wins))
        win = wins[0]
        body = " ".join(texts(win))
        model_names = [theme.preset_label(k) for k in theme.model_presets()]
        check("外观页显示全部内置模板",
              all(n in body for n in model_names),
              [n for n in model_names if n not in body])
        check("有「内置」标记", i18n.t("tpl_builtin") in body)
        check("有内置模板说明", i18n.t("tpl_model_hint") in body)
        check("胶囊数量 = 内置 + 用户模板",
              len(chips(win)) == len(theme.model_presets())
              + len(theme.custom_presets()), len(chips(win)))

        # ---- 点胶囊即应用（内置模板只读，但不影响「用了它」）----
        target = "model:nordic-night"
        label = theme.preset_label(target)
        chip = None
        for c in chips(win):
            if label in " ".join(texts(c)):
                chip = c
                break
        check("找得到「%s」的胶囊" % label, chip is not None)
        chip.event_generate("<Button-1>", x=6, y=6)
        app.update()
        check("点胶囊就应用该模板", theme.preset_name() == target,
              theme.preset_name())
        check("应用后落盘（重启不丢）",
              json.load(open(settings, encoding="utf-8")).get("theme_preset")
              == target)

        # ---- 点「复制」→ 编辑器预填 → 保存成用户模板 ----
        win = by_role("start_settings")[0]
        chip = None
        for c in chips(win):
            if label in " ".join(texts(c)):
                chip = c
                break
        copy_lbl = None
        for w in widgets(chip):
            try:
                if str(w.cget("text")) == i18n.t("tpl_copy"):
                    copy_lbl = w
                    break
            except (tk.TclError, AttributeError):
                continue
        check("胶囊上有「复制」", copy_lbl is not None)
        copy_lbl.event_generate("<Button-1>", x=2, y=2)
        app.update()
        editors = by_role("theme_editor")
        check("复制会打开编辑器", bool(editors))
        ed = editors[0]
        entry = [w for w in widgets(ed) if isinstance(w, tk.Entry)][0]
        want = i18n.t("tpl_copy_suffix", name=label)
        check("名称预填「%s」" % want, entry.get() == want, entry.get())
        check("内置模板不给删除按钮", i18n.t("tpl_delete") not in " ".join(texts(ed)))

        n_before = len(theme.model_presets())
        save_btn = [w for w in widgets(ed)
                    if isinstance(w, tk.Button)
                    and str(w.cget("text")) == i18n.t("tpl_save")
                    and str(w.cget("state")) != "disabled"][0]
        save_btn.invoke()
        app.update()
        check("保存后变成用户模板",
              theme.is_custom(theme.preset_name()), theme.preset_name())
        check("保存后主题就是这份副本",
              theme.preset_label(theme.preset_name()).startswith(label),
              theme.preset_label(theme.preset_name()))
        check("内置模板数量没变（只读）",
              len(theme.model_presets()) == n_before)
        check("models/ 里没有多出文件",
              len(_model_files()) == len(theme.model_presets()),
              len(_model_files()))

        # ---- 英文界面显示英文名 ----
        for w in by_role("start_settings"):
            w.destroy()
        i18n.set_lang("en")
        app.open_start_settings(tab="appearance")
        app.update()
        en_wins = by_role("start_settings")
        body_en = " ".join(texts(en_wins[0])) if en_wins else ""
        check("英文界面显示英文模板名", "Nordic Night" in body_en)
        for w in en_wins:
            w.destroy()
        i18n.set_lang("zh")
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
        installer_tests()
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
