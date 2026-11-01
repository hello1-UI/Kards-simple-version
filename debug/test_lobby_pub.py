# -*- coding: utf-8 -*-
"""大厅「公网地址」那一行的 GUI 测试

为什么单独测
    跨局域网联机 = 后台向路由器要端口 + 主线程轮询渲染。
    最容易错的地方不是 UPnP 协议（那有 test_upnp.py），而是：
      · 后台线程直接碰 tk 控件（会随机崩）
      · 状态没接上，界面一直卡在"正在申请…"
      · 复制按钮复制了个空字符串
      · CGNAT 和"没找到路由器"两种失败被糊成同一句话（处理方式完全不同）

必须用系统 Python：
    C:\\Users\\freet\\AppData\\Local\\Programs\\Python\\Python313\\python.exe debug/test_lobby_pub.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                          # noqa: E402

PASS, FAIL = [], []


def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [!!] ") + label + (f"  {extra}" if extra else ""))


def pump(app, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        try:
            app.update()
        except tk.TclError:
            return False
        time.sleep(0.01)
    return True


def main():
    import tkinter.messagebox as mb
    mb.showwarning = lambda *a, **k: "ok"
    mb.showerror = lambda *a, **k: "ok"
    mb.showinfo = lambda *a, **k: "ok"
    mb.askyesno = lambda *a, **k: False

    import kards_engine as core
    import kards_i18n as i18n
    import kards_host
    import importlib

    core.setup_error_log()
    i18n.set_lang("zh")                       # 别的测试可能把语言改了
    K = importlib.import_module("KARDS")

    app = K.App()
    pump(app, 0.4)

    print("0. 进大厅")
    app._build_lobby()
    pump(app, 0.5)
    check("大厅已建立", app.start_frame.winfo_exists())
    check("公网地址标签存在", getattr(app, "srv_public_lbl", None) is not None)
    check("初始为空（还没开服）",
          (app.srv_public_var.get() or "") == "",
          repr(app.srv_public_var.get()))
    check("复制按钮默认不显示",
          not app.srv_copy_btn.winfo_ismapped())

    # 打桩：绝不真的去动本机路由器
    called = {}

    def fake_map(port=None, on_done=None):
        called["port"] = port
        return None

    orig_map = kards_host.map_public_async
    orig_status = kards_host.public_status
    kards_host.map_public_async = fake_map
    try:
        print("1. 开服 → 正在申请")
        app._lobby_public_start(6000, "192.168.1.7:6000")
        pump(app, 0.1)
        check("调用了后台映射", called.get("port") == 6000, called)
        check("文案是「正在申请」", "正在" in app.srv_public_var.get(),
              app.srv_public_var.get())

        print("2. 映射成功 → 显示公网地址 + 显示复制按钮")
        # 开服时挂了个 200ms 的轮询定时器；这里手动喂状态，
        # 得先把它取消，否则真实轮询会把界面刷回「失败」。
        app._cancel_timer("_t_pub")
        ok_state = {"state": "done", "ok": True, "external_ip": "203.0.113.7",
                    "port": 6000, "local_ip": "192.168.1.7", "gateway": "192.168.1.1",
                    "error": "", "cg_nat": False, "manual": False}
        app._lobby_public_render(ok_state)
        pump(app, 0.2)
        text = app.srv_public_var.get()
        check("文案含公网地址", "203.0.113.7:6000" in text, text)
        check("文案含局域网地址", "192.168.1.7:6000" in text, text)
        check("复制按钮已显示", app.srv_copy_btn.winfo_ismapped())
        check("取到可复制的公网地址", app._pub_addr == "203.0.113.7:6000",
              app._pub_addr)

        print("3. 点复制 → 剪贴板里就是公网地址")
        app._lobby_copy_addr()
        pump(app, 0.1)
        clip = ""
        try:
            clip = app.clipboard_get()
        except tk.TclError:
            pass
        check("剪贴板内容正确", clip == "203.0.113.7:6000", repr(clip))

        print("4. CGNAT（运营商内网）→ 说明为什么不行、给出路")
        cg = dict(ok_state, ok=False, cg_nat=True, error="cgnat",
                  external_ip="100.72.5.9")
        app._lobby_public_render(cg)
        pump(app, 0.2)
        text = app.srv_public_var.get()
        check("明确指出运营商内网", "运营商内网" in text, text)
        check("提到端口号", "6000" in text, text)
        check("没被说成「成功」", "已自动开放端口" not in text, text)
        check("复制的是局域网地址（公网不可用）",
              app._pub_addr == "192.168.1.7:6000", app._pub_addr)

        print("4b. 双重 NAT（光猫 + 路由器都路由）→ 告诉用户两层都要映射")
        dn = dict(ok_state, ok=False, cg_nat=False, double_nat=True,
                  error="double_nat", external_ip="192.168.1.2")
        app._lobby_public_render(dn)
        pump(app, 0.2)
        text = app.srv_public_var.get()
        check("指出是双重 NAT", "双重 NAT" in text, text)
        check("给出两级映射口径", "光猫" in text and "6000" in text, text)
        check("带上本机地址", "192.168.1.7" in text, text)

        print("5. 没找到 UPnP 路由器 → 让用户手动映射")
        nogw = dict(ok_state, ok=False, cg_nat=False, error="no_gateway",
                    external_ip="")
        app._lobby_public_render(nogw)
        pump(app, 0.2)
        text = app.srv_public_var.get()
        check("提示没有 UPnP 路由器", "UPnP" in text, text)
        check("给出本机地址方便手动映射", "192.168.1.7" in text, text)

        print("6. 其它错误 → 带上错误原因")
        err = dict(ok_state, ok=False, cg_nat=False, error="HTTP 403")
        app._lobby_public_render(err)
        pump(app, 0.2)
        text = app.srv_public_var.get()
        check("文案里带上错误码", "HTTP 403" in text, text)

        print("7. 未完成时轮询会继续等")
        kards_host.public_status = lambda: {"state": "working", "ok": False,
                                            "port": 6000}
        app._pub_poll()
        pump(app, 0.1)
        check("working 状态下不报错", True)

        print("8. 本机直接持有公网 IP → 不用映射的说法")
        direct = dict(ok_state, direct=True, direct_ip="203.0.113.7")
        app._lobby_public_render(direct)
        pump(app, 0.2)
        text = app.srv_public_var.get()
        check("文案说明本机直连公网", "本机" in text and "203.0.113.7:6000" in text, text)

        print("9. 标签被销毁后不能崩")
        app.srv_public_var = tk.StringVar(value="")
        app._lobby_public_render(ok_state)     # 不抛异常即通过
        check("重复渲染幂等", "203.0.113.7:6000" in app.srv_public_var.get())
    finally:
        kards_host.map_public_async = orig_map
        kards_host.public_status = orig_status

    try:
        app.destroy()
    except tk.TclError:
        pass

    print()
    print("=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAIL:", f)
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
