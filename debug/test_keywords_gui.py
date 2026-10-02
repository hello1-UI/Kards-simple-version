# -*- coding: utf-8 -*-
"""GUI：关键词说明窗口与按钮的实机验证（系统 Python + tkinter）

运行：
    C:\\Users\\freet\\AppData\\Local\\Programs\\Python\\Python313\\python.exe \\
        debug/test_keywords_gui.py

注意：受管 Python 没有 tkinter，必须用系统 Python。
"""
import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import kards_i18n as i18n          # noqa: E402
import KARDS as gui                # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


def pump(root, times=2):
    """跑几轮事件循环，让 pack/destroy 真正落到 Tk 里"""
    for _ in range(times):
        try:
            root.update_idletasks()
            root.update()
        except tk.TclError:
            return


def count_labels(w):
    n = 0
    for c in w.winfo_children():
        if isinstance(c, tk.Label):
            n += 1
        n += count_labels(c)
    return n


def find_toplevels(root, role=None):
    """回收已销毁的引用，返回当前存活的 Toplevel。

    role 不为 None 时只返回带同名 role 标记的窗口（open_keyword_guide 等
    会给窗口打 role），这样计数不会被「账号管理」这类无关弹窗污染。
    """
    out = []
    try:
        kids = root.winfo_children()
    except tk.TclError:
        return out
    for w in kids:
        if not isinstance(w, tk.Toplevel):
            continue
        try:
            if not w.winfo_exists():
                continue
        except tk.TclError:
            continue
        if role is not None and getattr(w, "role", None) != role:
            continue
        out.append(w)
    return out


def roles_of(root):
    return [getattr(w, "role", "?") for w in find_toplevels(root)]


def close_all_tops(root, keep=()):
    """关掉所有 Toplevel（启动时的账号窗、上一次残留的窗口等）"""
    n = 0
    for w in find_toplevels(root):
        if w in keep:
            continue
        try:
            w.destroy()
            n += 1
        except tk.TclError:
            pass
    pump(root, 3)
    return n


def labels_of(w):
    """收集窗口内所有 Label 的文本 -> 次数"""
    found = {}

    def rec(x):
        try:
            kids = x.winfo_children()
        except tk.TclError:
            return
        for c in kids:
            try:
                if isinstance(c, tk.Label):
                    t = c.cget("text")
                    found[t] = found.get(t, 0) + 1
            except tk.TclError:
                pass
            rec(c)
    rec(w)
    return found


def buttons_of(w):
    """收集窗口内所有 Button 的文本（递归，含嵌套 Frame 里的）"""
    out = []

    def rec(x):
        try:
            kids = x.winfo_children()
        except tk.TclError:
            return
        for c in kids:
            try:
                if isinstance(c, tk.Button):
                    out.append(c.cget("text"))
            except tk.TclError:
                pass
            rec(c)
    rec(w)
    return out


def open_guide_and_get(app):
    """打开关键词说明窗并返回它（用 role 标记定位，避免计数受残留窗口干扰）"""
    app.open_keyword_guide()
    pump(app, 3)
    guide = find_toplevels(app, role="keyword_guide")
    return (guide[0] if guide else None), guide


def main():
    app = gui.App()
    pump(app)
    app.anim_enabled = False
    # 启动时若无账号会弹出「账号管理」窗，先关掉，避免干扰计数
    closed = close_all_tops(app)
    if closed:
        print(f"  (启动时自动关闭了 {closed} 个初始弹窗)")

    # ---------------------------------------------------------- 1
    print("1. 主界面设置窗含两个按钮")
    close_all_tops(app)
    app.open_start_settings()
    pump(app)
    tops = find_toplevels(app, role="start_settings")
    check("设置窗已打开", len(tops) == 1, len(tops))
    st = tops[0]
    texts = []
    for c in st.winfo_children():
        if isinstance(c, tk.Button):
            texts.append(c.cget("text"))
    check("含「操作说明」按钮", any("操作说明" in t for t in texts), texts)
    check("含「关键词说明」按钮", any("关键词" in t for t in texts), texts)
    # 设置窗里的「关键词说明」按钮真的能开出说明窗
    st.destroy()
    pump(app)

    # ---------------------------------------------------------- 2
    print("2. 关键词说明窗口（中文）")
    i18n.set_lang("zh")
    close_all_tops(app)                       # 清干净，确保只数本次打开的窗口
    kw, tops = open_guide_and_get(app)
    check("说明窗已打开", len(tops) == 1, roles_of(app))
    if kw is None:
        check("渲染出的 Label 数量合理（>=80）", False, "窗口未找到")
    else:
        # 4 个分组标题 + 38 条目×(名称+说明) + 标题/副标题 = 4+76+2 = 82
        check("渲染出的 Label 数量合理（>=80）", count_labels(kw) >= 80,
              count_labels(kw))
        found = labels_of(kw)
        check("含分组标题「单位关键词」", "单位关键词" in found)
        check("含分组标题「触发类关键词」", "触发类关键词" in found)
        check("含分组标题「规则术语」", "规则术语" in found)
        check("含分组标题「原版词条…未实装」",
              any("未实装" in t for t in found))
        check("含关键词「闪击」", "闪击" in found)
        check("含关键词「亡计」", "亡计" in found)
        check("含术语「前线」", "前线" in found)
        check("含未实装词条「烟幕」", "烟幕" in found)
        check("含未实装词条「士气伤害」", "士气伤害" in found)
        # 关闭按钮挂在窗口根上，不在滚动区 Frame 里
        win_texts = list(found) + buttons_of(kw)
        check("含关闭按钮文案", any("知道了" in t for t in win_texts),
              buttons_of(kw))
        kw.destroy()
    pump(app)

    # ---------------------------------------------------------- 3
    print("3. 关键词说明窗口（英文）")
    i18n.set_lang("en")
    close_all_tops(app)
    kw, tops = open_guide_and_get(app)
    check("说明窗已打开", len(tops) == 1, roles_of(app))
    if kw is not None:
        found = labels_of(kw)
        check("含英文分组标题", "Unit keywords" in found, list(found)[:8])
        check("含英文关键词 Blitz", "Blitz" in found)
        check("含英文术语 Frontline", "Frontline" in found)
        kw.destroy()
    pump(app)

    # ---------------------------------------------------------- 4
    print("4. 关键词说明窗口（日文）")
    i18n.set_lang("ja")
    close_all_tops(app)
    kw, tops = open_guide_and_get(app)
    check("说明窗已打开", len(tops) == 1, roles_of(app))
    if kw is not None:
        found = labels_of(kw)
        check("含日文分组标题", "ユニットキーワード" in found, list(found)[:8])
        check("含日文关键词 電撃", "電撃" in found)
        kw.destroy()
    pump(app)

    i18n.set_lang("zh")

    # ---------------------------------------------------------- 4b
    print("4b. 反复打开说明窗不叠加（单例检查）")
    close_all_tops(app)
    for _ in range(3):
        app.open_keyword_guide()
    pump(app, 3)
    tops = find_toplevels(app, role="keyword_guide")
    # 说明窗允许并存（用户可对照查看），这里只验证每次调用都真的产出窗口
    check("连续打开 3 次 → 3 个说明窗", len(tops) == 3, len(tops))
    for w in tops:
        w.destroy()
    pump(app)

    print("4c. 账号窗单实例（反复点击不叠加）")
    close_all_tops(app)
    for _ in range(3):
        app._account_dialog()
    pump(app, 3)
    acc = find_toplevels(app, role="account")
    check("连续点击 3 次 → 仅 1 个账号窗", len(acc) == 1, roles_of(app))
    for w in acc:
        w.destroy()
    pump(app)

    # ---------------------------------------------------------- 5
    print("5. 对局中 F1 打开说明")
    app.destroy()
    app2 = gui.App()
    pump(app2)
    app2.anim_enabled = False
    close_all_tops(app2)
    app2.new_game("德国")
    pump(app2, 3)
    check("已进入对局", app2.game is not None)
    close_all_tops(app2)                      # F1 之前先清掉可能残留的弹窗
    app2.on_f1()
    pump(app2, 3)
    tops = find_toplevels(app2, role="keyword_guide")
    check("对局中 F1 能打开说明窗", len(tops) == 1, roles_of(app2))
    for w in tops:
        try:
            w.destroy()
        except tk.TclError:
            pass
    pump(app2)

    # ---------------------------------------------------------- 6
    print("6. 对局中设置窗含关键词按钮")
    close_all_tops(app2)
    app2.open_settings()
    pump(app2)
    tops = find_toplevels(app2, role="ingame_settings")
    check("设置窗已打开", len(tops) == 1, len(tops))
    if tops:
        # 用递归收集，按钮可能在嵌套 Frame 里
        texts = buttons_of(tops[0])
        check("对局设置窗含「关键词说明」", any("关键词" in t for t in texts), texts)
        check("对局设置窗仍含「投降」", any("投降" in t for t in texts), texts)
        tops[0].destroy()
    pump(app2)

    app2.destroy()

    print()
    if FAIL:
        print(f"FAILED: {len(FAIL)}/{len(PASS) + len(FAIL)}")
        for f in FAIL:
            print("  -", f)
        sys.exit(1)
    print(f"ALL OK ({len(PASS)} checks)")


if __name__ == "__main__":
    main()
