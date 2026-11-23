"""大厅「公网地址」一行的截图工具（人眼验收用）。

tkinter 的 UI 光靠单元测试是看不出错位的 —— 这里把大厅真渲染出来，
注入几种公网映射状态，各抓一张图到 debug/shots/。

用法：
    python debug/shot_lobby.py            # 四种状态各一张
    python debug/shot_lobby.py ok         # 只抓「映射成功」那张
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk

from PIL import ImageGrab

import KARDS as gui

OUT = os.path.join(ROOT, "debug", "shots")
LAN = "192.168.1.7:6000"

STATES = {
    "ok": {"state": "done", "ok": True, "external_ip": "203.0.113.7", "port": 6000,
           "local_ip": "192.168.1.7", "gateway": "192.168.1.1", "error": "",
           "cg_nat": False, "double_nat": False, "manual": False, "direct": False},
    "double": {"state": "done", "ok": False, "external_ip": "192.168.1.2", "port": 6000,
               "local_ip": "192.168.1.7", "gateway": "192.168.1.1", "error": "double_nat",
               "cg_nat": False, "double_nat": True, "manual": True, "direct": False},
    "nogw": {"state": "done", "ok": False, "external_ip": "", "port": 6000,
             "local_ip": "192.168.1.7", "gateway": "", "error": "no_gateway",
             "cg_nat": False, "double_nat": False, "manual": True, "direct": False},
    "working": {"state": "working", "ok": False, "external_ip": "", "port": 6000,
                "local_ip": "", "gateway": "", "error": "", "cg_nat": False,
                "double_nat": False, "manual": False, "direct": False},
}


def shot(app, name):
    app.update_idletasks()
    app.update()
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    path = os.path.join(OUT, f"lobby_pub_{name}.png")
    img.save(path)
    print("saved", path, img.size)
    return path


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    os.makedirs(OUT, exist_ok=True)

    import kards_host
    gui.i18n.set_lang("zh")
    app = gui.App()
    app.geometry("1000x760+40+40")
    try:
        app.attributes("-fullscreen", False)
    except tk.TclError:
        pass
    app._lobby_connect = lambda: None      # 不真去连服务器，免得状态行干扰截图
    app._build_lobby()
    app._pub_lan = LAN
    app.update()

    orig_status = kards_host.public_status
    try:
        for name in STATES:
            if only and name != only:
                continue
            st = STATES[name]
            if name == "working":
                # 轮询中：按钮应显示「正在打通公网…」且禁用
                kards_host.public_status = lambda: {"state": "working",
                                                    "ok": False, "port": 6000}
                app.srv_public_var.set(gui.i18n.t("pub_working"))
                app.srv_public_lbl.configure(fg=gui.DIM)
                app._pub_ok_addr = ""
                app._lobby_pub_btn_refresh()
            else:
                kards_host.public_status = lambda st=st: st
                app._lobby_public_render(st)
            shot(app, name)

        # 额外一张：一键切换**之后**的界面（地址框已是公网地址、按钮变「改回局域网」）
        if not only or only == "switched":
            ok = STATES["ok"]
            kards_host.public_status = lambda: ok
            app._lobby_public_render(ok)
            app._lobby_set_addr_text("203.0.113.7:6000")
            app._pub_switched = True
            app._lobby_pub_btn_refresh()
            shot(app, "switched")
    finally:
        kards_host.public_status = orig_status

    app.destroy()


if __name__ == "__main__":
    main()
