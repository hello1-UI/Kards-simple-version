# -*- coding: utf-8 -*-
"""删除账号 GUI 测试：入口按钮 / 确认框复选框 / 删除后收尾

必须用系统 Python（受管 Python 无 tkinter）：
    py debug/test_account_delete_gui.py

⚠ 这里只验证界面接线，真正的删除逻辑由 test_account_delete.py 覆盖。
"""
import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ["KARDS_DATA_DIR"] = tempfile.mkdtemp(prefix="kards_del_gui_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.argv.append("--no-fullscreen")
sys.argv.append("--no-update-check")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json                                # noqa: E402

import tkinter as tk                       # noqa: E402

import kards_i18n as i18n                  # noqa: E402
import KARDS as gui                        # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name
          + (f"  {extra}" if (extra and not cond) else ""))


def find_toplevel(app, role):
    for w in app.winfo_children():
        if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == role:
            return w
    return None


def all_widgets(w, cls=None):
    out = []
    for ch in w.winfo_children():
        if cls is None or isinstance(ch, cls):
            out.append(ch)
        out.extend(all_widgets(ch, cls))
    return out


def button_by_text(w, text):
    for b in all_widgets(w, tk.Button):
        try:
            if str(b.cget("text")) == text:
                return b
        except tk.TclError:
            pass
    return None


def label_texts(w):
    out = []
    for lb in all_widgets(w, tk.Label):
        try:
            out.append(str(lb.cget("text")))
        except tk.TclError:
            pass
    return out


def make_app():
    tmp = os.path.join(tempfile.gettempdir(), "kards_del_gui_settings.json")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"language": "zh"}, fh)
    i18n._SETTINGS_PATH = tmp
    gui.App.open_update_dialog = lambda self, auto=False: None
    app = gui.App()
    app.geometry("1100x760+20+20")
    try:
        app.attributes("-fullscreen", False)
    except tk.TclError:
        pass
    app.update()
    return app


def open_account(app, name="Tester"):
    app.account = name
    app._account_dialog()
    app.update()
    return find_toplevel(app, "account")


def main():
    # 弹窗会阻塞自动化 → 直接打桩记录
    boxes = {"info": [], "error": []}
    gui.messagebox.showinfo = lambda *a, **k: boxes["info"].append(a)
    gui.messagebox.showerror = lambda *a, **k: boxes["error"].append(a)

    print("1. 账号窗：已登录时有删除入口")
    app = make_app()
    try:
        win = open_account(app)
        check("账号窗已打开", win is not None)
        btn = button_by_text(win, i18n.t("account_delete")) if win else None
        check("有「删除账号」按钮", btn is not None)
        check("登出按钮仍在",
              win is not None and button_by_text(
                  win, i18n.t("account_logout")) is not None)

        print("2. 确认框：离线时复选框禁用且默认不勾")
        if btn is not None:
            btn.invoke()
            app.update()
        dlg = find_toplevel(app, "acct_del")
        check("确认框已弹出", dlg is not None)
        check("确认框只有一个",
              len([w for w in app.winfo_children()
                   if isinstance(w, tk.Toplevel)
                   and getattr(w, "role", "") == "acct_del"]) == 1)

        cbs = all_widgets(dlg, tk.Checkbutton) if dlg else []
        check("有且仅有一个复选框", len(cbs) == 1, len(cbs))
        if cbs:
            cb = cbs[0]
            check("复选框文案",
                  str(cb.cget("text")) == i18n.t("acct_del_server"),
                  cb.cget("text"))
            check("离线时复选框禁用", str(cb.cget("state")) == "disabled",
                  cb.cget("state"))
            check("离线时默认不勾", not bool(cb.getvar(cb.cget("variable"))))
        texts = " | ".join(label_texts(dlg)) if dlg else ""
        check("显示不可恢复警示", i18n.t("acct_del_warn") in texts, texts[:220])
        check("显示本机清理范围", i18n.t("acct_del_local") in texts)
        check("离线提示可见", i18n.t("acct_del_offline") in texts)
        check("有取消按钮",
              dlg is not None and button_by_text(
                  dlg, i18n.t("acct_del_cancel")) is not None)
        check("有永久删除按钮",
              dlg is not None and button_by_text(
                  dlg, i18n.t("acct_del_confirm")) is not None)

        print("3. 离线删除：只传 server_data=False，删完回游客")
        calls = []

        def fake_delete(name, server_data=False):
            calls.append((name, server_data))
            return True, ""

        gui.account.delete_account = fake_delete
        app._rank_last = {"stars": 1}
        app.rank_state = {"tier": 3}
        if dlg:
            btn_del = button_by_text(dlg, i18n.t("acct_del_confirm"))
            btn_del.invoke()
            app.update()
        check("调用了删除且未勾服务器",
              calls == [("Tester", False)], calls)
        check("account 已置空", app.account is None, app.account)
        check("段位缓存已清", app.rank_state is None and app._rank_last == {},
              (app.rank_state, app._rank_last))
        check("确认框已关闭", find_toplevel(app, "acct_del") is None)
        check("账号窗已关闭", find_toplevel(app, "account") is None)
        check("有成功提示", len(boxes["info"]) == 1, boxes["info"])

        print("4. 在线时复选框可勾且默认勾选，删除走服务器")
        gui.account.online = lambda: True
        gui.account.backend = lambda: "server"
        win2 = open_account(app, "Online")
        btn2 = button_by_text(win2, i18n.t("account_delete")) if win2 else None
        if btn2 is not None:
            btn2.invoke()
            app.update()
        dlg2 = find_toplevel(app, "acct_del")
        cbs2 = all_widgets(dlg2, tk.Checkbutton) if dlg2 else []
        check("在线时复选框可用",
              bool(cbs2) and str(cbs2[0].cget("state")) == "normal",
              cbs2[0].cget("state") if cbs2 else None)
        check("在线时默认勾选",
              bool(cbs2) and bool(cbs2[0].getvar(cbs2[0].cget("variable"))))
        texts2 = " | ".join(label_texts(dlg2)) if dlg2 else ""
        check("在线时显示服务器清理说明",
              i18n.t("acct_del_server_note") in texts2, texts2[:240])

        calls.clear()
        if dlg2:
            button_by_text(dlg2, i18n.t("acct_del_confirm")).invoke()
            app.update()
        check("勾选后删除带 server_data=True",
              calls == [("Online", True)], calls)
        check("在线删除后也回游客", app.account is None)

        print("5. 删除失败：留在确认框并给出错误")
        gui.account.online = lambda: True
        gui.account.backend = lambda: "server"
        gui.account.delete_account = lambda n, server_data=False: (
            False, "server_failed")
        boxes["error"].clear()
        win3 = open_account(app, "Fail")
        button_by_text(win3, i18n.t("account_delete")).invoke()
        app.update()
        dlg3 = find_toplevel(app, "acct_del")
        if dlg3:
            button_by_text(dlg3, i18n.t("acct_del_confirm")).invoke()
            app.update()
        check("失败有错误弹窗", len(boxes["error"]) == 1, boxes["error"])
        err_txt = boxes["error"][0][1] if boxes["error"] else ""
        check("错误文案可读（不是裸 err key）",
              i18n.t("acct_del_err_server_failed") in err_txt, err_txt)
        check("失败后确认框还在（可重试）",
              find_toplevel(app, "acct_del") is not None)
        check("失败后账号没被清掉", app.account == "Fail", app.account)
    finally:
        try:
            app.destroy()
        except tk.TclError:
            pass

    print()
    print("=" * 52)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    for f in FAIL:
        print("  -", f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
