# -*- coding: utf-8 -*-
"""更新窗 GUI 测试：能开、能渲染、失败/无更新/有更新三种状态都对

**不真下载**：把 `kards_update` 的网络函数打桩，控制状态机走向，
只验证界面反应正确（否则测试会拉起几十 MB 的下载）。

必须用**系统 Python**（受控 Python 无 tkinter）：
    C:\\Users\\freet\\AppData\\Local\\Programs\\Python\\Python313\\python.exe debug/test_update_gui.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                          # noqa: E402

import kards_engine as core                   # noqa: E402
import kards_i18n as i18n                     # noqa: E402
import kards_update as up                     # noqa: E402

PASS, FAIL = [], []


def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [!!] ") + label + (f"  {extra}" if extra else ""))


def pump(app, seconds=1.0):
    end = time.time() + seconds
    while time.time() < end:
        try:
            app.update()
        except tk.TclError:
            return False
        time.sleep(0.01)
    return True


def until(app, cond, timeout=8.0, label=""):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if cond():
                return True
        except tk.TclError:
            pass
        if not pump(app, 0.1):
            return False
    if label:
        print(f"      (超时等待: {label})")
    return False


def labels_of(win):
    out = []
    for w in win.winfo_children():
        try:
            out.append(w)
            out.extend(labels_of(w))
        except tk.TclError:
            pass
    return out


def texts_of(win):
    res = []
    for w in labels_of(win):
        try:
            if isinstance(w, tk.Label):
                res.append(w.cget("text"))
            elif isinstance(w, tk.Button):
                res.append(w.cget("text"))
        except tk.TclError:
            pass
    return res


def buttons_of(win):
    return [w for w in labels_of(win) if isinstance(w, tk.Button)]


def find_update_win(app):
    for w in app.winfo_children():
        if getattr(w, "role", "") == "update":
            return w
    return None


def main():
    import tkinter.messagebox as mb
    mb.showwarning = lambda *a, **k: "ok"
    mb.showerror = lambda *a, **k: "ok"
    mb.showinfo = lambda *a, **k: "ok"
    mb.askyesno = lambda *a, **k: False          # 重启确认一律选"否"，别真重启

    core.setup_error_log()
    # ⚠ 语言会持久化到 settings.json。其它测试可能把语言改成 ja/en，
    # 于是断言里的中文按钮文案就匹配不上了（实测踩过：界面是日文）。
    # 这里强制切中文，让断言稳定。
    i18n.set_lang("zh")
    import importlib
    K = importlib.import_module("KARDS")

    app = K.App()
    pump(app, 0.4)
    check("主菜单没有自动弹出更新窗（静默检查）", find_update_win(app) is None)

    print("1. 无更新：界面显示「已是最新」")
    orig_check = up.check_latest
    up.check_latest = lambda timeout=12: {"ok": True, "version": "1.2.0.3",
                                          "notes": "", "page": "p", "assets": []}
    try:
        app.open_update_dialog()
        pump(app, 0.3)
        win = find_update_win(app)
        check("更新窗已打开", win is not None)
        ok = until(app, lambda: any("最新" in str(t) or "latest" in str(t).lower()
                                    for t in texts_of(win)), timeout=6,
                   label="显示已是最新")
        check("显示「已是最新版本」", ok, [t for t in texts_of(win) if t][:3])
        check("有「关闭」按钮", any("关闭" in str(b.cget("text")) or "Close" in str(b.cget("text"))
                                for b in buttons_of(win)))
        app._close_update_dialog()
        pump(app, 0.2)
        check("关闭后窗口引用已清空", app._update_win is None)

        print("2. 有新版本：显示版本号 + 更新内容 + 三个按钮")
        notes = "- 修复了大厅断线不提示\n- 新增自动更新"
        up.check_latest = lambda timeout=12: {
            "ok": True, "version": "1.9.9.9", "notes": notes, "page": "http://x",
            "assets": [{"name": "KARDS.zip", "url": "http://127.0.0.1:1/x.zip",
                        "size": 100}]}
        app.open_update_dialog()
        pump(app, 0.3)
        win = find_update_win(app)
        ok = until(app, lambda: any("1.9.9.9" in str(t) for t in texts_of(win)),
                   timeout=6, label="显示新版本号")
        check("显示新版本号", ok, [t for t in texts_of(win) if "1.9.9.9" in str(t)][:2])
        ok = until(app, lambda: any("修复了大厅断线" in str(t)
                                    for w in labels_of(win)
                                    if isinstance(w, tk.Text)
                                    for t in [w.get("1.0", "end")]), timeout=4)
        check("把 Release 说明渲染进内容框", ok)
        btns = [str(b.cget("text")) for b in buttons_of(win)]
        check("有「立即更新」按钮", any("更新" in t and "立即" in t for t in btns), btns)
        check("有「打开发布页」按钮", any("发布页" in t for t in btns), btns)
        check("有「稍后」按钮", any("稍后" in t for t in btns), btns)
        app._close_update_dialog()
        pump(app, 0.2)

        print("3. 检查失败：显示失败原因，不崩")
        up.check_latest = lambda timeout=12: {"ok": False, "err": "SSL 握手失败"}
        app.open_update_dialog()
        pump(app, 0.3)
        win = find_update_win(app)
        ok = until(app, lambda: any("SSL 握手失败" in str(t) for t in texts_of(win)),
                   timeout=6, label="显示失败原因")
        check("显示失败原因", ok, [t for t in texts_of(win) if "SSL" in str(t)][:2])
        check("失败时仍可关闭", any("关闭" in str(b.cget("text")) for b in buttons_of(win)))
        app._close_update_dialog()
        pump(app, 0.2)

        print("4. 静默检查：无更新/失败都自动消失，有更新才留下")
        up.check_latest = lambda timeout=12: {"ok": True, "version": "1.2.0.3",
                                              "notes": "", "page": "", "assets": []}
        app.open_update_dialog(auto=True)
        ok = until(app, lambda: find_update_win(app) is None, timeout=8,
                   label="无更新时自动关窗")
        check("静默检查无更新 → 自动关窗", ok)

        up.check_latest = lambda timeout=12: {"ok": False, "err": "网络不通"}
        app.open_update_dialog(auto=True)
        ok = until(app, lambda: find_update_win(app) is None, timeout=8,
                   label="失败时自动关窗")
        check("静默检查失败 → 自动关窗（不打扰用户）", ok)

        up.check_latest = lambda timeout=12: {
            "ok": True, "version": "2.0.0.0", "notes": "x", "page": "",
            "assets": [{"name": "KARDS.zip", "url": "http://127.0.0.1:1/x.zip",
                        "size": 1}]}
        app.open_update_dialog(auto=True)
        pump(app, 1.2)
        check("静默检查有更新 → 窗口保留", find_update_win(app) is not None)
        app._close_update_dialog()
        pump(app, 0.2)

        print("5. 重复打开不会叠出多个窗")
        up.check_latest = lambda timeout=12: {"ok": True, "version": "1.2.0.3",
                                              "notes": "", "page": "", "assets": []}
        app.open_update_dialog()
        pump(app, 0.2)
        app.open_update_dialog()
        pump(app, 0.2)
        wins = [w for w in app.winfo_children() if getattr(w, "role", "") == "update"]
        check("只有 1 个更新窗", len(wins) == 1, len(wins))
        app._close_update_dialog()
        pump(app, 0.2)

        print("6. 关闭游戏时更新窗一并清理，不留 after 回调")
        up.check_latest = lambda timeout=12: {"ok": True, "version": "1.2.0.3",
                                              "notes": "", "page": "", "assets": []}
        app.open_update_dialog()
        pump(app, 0.3)
        app.destroy()
        pump(app, 0.3)
        check("destroy 后不抛异常", True)
    finally:
        up.check_latest = orig_check
        try:
            app.destroy()
        except Exception:                        # noqa: BLE001
            pass

    print()
    print("=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
