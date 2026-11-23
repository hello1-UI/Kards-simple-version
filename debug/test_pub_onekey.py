# -*- coding: utf-8 -*-
"""「一键改为公网」+「开服/进服不退登」回归测试

为什么单独测
    这两件事是同一个用户体验问题的两面：
      · 一键改公网 = 把地址框换成公网地址（打通端口后自动完成）
      · 换地址 / 开服 / 进服 不该把已登录的玩家打回登录框

    最容易错的地方：
      · 公网地址不被认作本机 → 被当成「换了服务器」→ 免密令牌作废（退登）
      · 从内网访问自己的公网 IP（hairpin NAT）→ 连接超时
      · 开服时无条件重连 → 清掉 mp_user（退登）
      · 一键按钮在没开服时点了没反应 / 一直卡在「正在打通」

必须用系统 Python（受管 Python 无 tkinter）：
    python debug/test_pub_onekey.py
"""
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                          # noqa: E402

PASS, FAIL = [], []


def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [!!] ") + label + (f"  {extra}" if extra else ""))


def pump(app, seconds=0.3):
    end = time.time() + seconds
    while time.time() < end:
        try:
            app.update()
        except tk.TclError:
            return False
        time.sleep(0.01)
    return True


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    import tkinter.messagebox as mb
    mb.showwarning = lambda *a, **k: "ok"
    mb.showerror = lambda *a, **k: "ok"
    mb.showinfo = lambda *a, **k: "ok"
    mb.askyesno = lambda *a, **k: False

    if "--no-update-check" not in sys.argv:
        sys.argv.append("--no-update-check")

    import kards_engine as core
    import kards_i18n as i18n
    import kards_net as net
    import kards_host
    import importlib

    core.setup_error_log()
    i18n.set_lang("zh")
    K = importlib.import_module("KARDS")

    # ---------------------------------------------------------------- A. 地址判定
    print("1. 公网 IP 要算「本机」（否则换地址 = 换服务器 = 退登）")
    pub_ip = "203.0.113.77"
    # 局域网地址用**本机真实网卡 IP**：same_server 的判定前提是两边都指本机，
    # 随手编一个 192.168.1.7 在这台机器上并不是本机地址。
    lan_ip = (net.get_local_ips() or ["127.0.0.1"])[0]
    lan_addr = f"{lan_ip}:6000"
    net.clear_public_ip()
    check("未登记时不是本机", not net.is_self_host(pub_ip))
    net.register_public_ip(pub_ip)
    check("登记后算本机", net.is_self_host(pub_ip))
    check("公网地址与局域网地址是同一台服务器",
          net.same_server(f"{pub_ip}:6000", lan_addr), lan_addr)
    check("不同端口仍不是同一台",
          not net.same_server(f"{pub_ip}:6000", f"{lan_ip}:7000"))
    net.register_public_ip("")                 # 空值不能登记
    check("空 IP 不登记", "" not in net._PUBLIC_IPS)

    print("2. 连本机公网地址要走回环（家用路由器普遍不支持 hairpin NAT）")
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.listen(1)
    got = {}

    def accept_once():
        try:
            c, _ = srv.accept()
            got["peer"] = c.getpeername()[:2]
            c.close()
        except OSError:
            pass

    th = threading.Thread(target=accept_once, daemon=True)
    th.start()
    holder = {}
    net.connect_server_async(f"{pub_ip}:{port}", holder, timeout=3.0)
    end = time.time() + 4
    while time.time() < end and "result" not in holder:
        time.sleep(0.02)
    res = holder.get("result")
    ok_conn = bool(res) and not (len(res) == 2 and res[0] == "err")
    check("公网地址能连上（走的是 127.0.0.1）", ok_conn, res)
    check("对端看到的是回环地址", got.get("peer", ("",))[0] == "127.0.0.1",
          got.get("peer"))
    try:
        link = holder["result"][0]
        link.close()
    except Exception:                          # noqa: BLE001
        pass
    srv.close()

    # ---------------------------------------------------------------- B. 大厅 UI
    print("3. 大厅里的「一键改为公网」按钮")
    app = K.App()
    pump(app, 0.4)
    app._build_lobby()
    pump(app, 0.4)

    btn = getattr(app, "srv_pub_toggle", None)
    check("按钮已创建", btn is not None and btn.winfo_exists())
    check("默认文案是「一键改为公网」",
          btn is not None and "一键改为公网" in btn.cget("text"),
          btn.cget("text") if btn else "")
    check("默认可用", btn is not None and str(btn.cget("state")) == "normal")

    # 打桩：绝不真去动路由器 / 真去起服务器
    host_calls = {}
    orig_map = kards_host.map_public_async
    orig_status = kards_host.public_status
    orig_running = kards_host.running
    orig_in_use = kards_host.port_in_use
    orig_local = kards_host.local_addr

    def fake_map(p=None, on_done=None):
        host_calls["mapped"] = p
        return None

    kards_host.map_public_async = fake_map
    kards_host.public_status = lambda: {"state": "working", "ok": False,
                                        "port": 6000}
    kards_host.running = lambda: True              # 假装已经开好服
    kards_host.port_in_use = lambda **kw: True
    kards_host.local_addr = lambda port=None: lan_addr

    after_calls = []
    orig_after = app.after

    def fake_after(ms, fn=None, *a):
        after_calls.append((ms, fn))
        return "fake"

    try:
        print("4. 没打通时点按钮 → 开服 + 申请端口（而不是点了没反应）")
        app.after = fake_after
        app._lobby_pub_toggle()
        pump(app, 0.1)
        check("进入了自动切换模式", app._pub_auto_switch is True)
        check("发起了端口映射", host_calls.get("mapped") == 6000, host_calls)
        check("按钮文案变成「正在打通公网…」",
              "正在打通公网" in btn.cget("text"), btn.cget("text"))
        check("按钮暂时禁用", str(btn.cget("state")) == "disabled")

        print("5. 映射成功 → 地址框自动换成公网地址 + 复制 + 按钮变「改回局域网」")
        kards_host.public_status = lambda: {"state": "done", "ok": True}
        app._cancel_timer("_t_pub")
        ok_st = {"state": "done", "ok": True, "external_ip": pub_ip,
                 "port": 6000, "local_ip": "192.168.1.7",
                 "gateway": "192.168.1.1", "error": "", "cg_nat": False,
                 "double_nat": False, "manual": False, "direct": False}
        app._lobby_public_render(ok_st)
        pump(app, 0.2)
        check("自动切换只做一次", app._pub_auto_switch is False)
        check("地址框已是公网地址",
              app.srv_addr_var.get() == f"{pub_ip}:6000", app.srv_addr_var.get())
        check("记住了公网地址", app._pub_ok_addr == f"{pub_ip}:6000",
              app._pub_ok_addr)
        check("标记为已切换", app._pub_switched is True)
        check("按钮文案变「改回局域网」",
              "改回局域网" in btn.cget("text"), btn.cget("text"))
        clip = ""
        try:
            clip = app.clipboard_get()
        except tk.TclError:
            pass
        check("已复制到剪贴板", clip == f"{pub_ip}:6000", repr(clip))

        print("6. 再点一次 → 改回局域网（不重连、不退登）")
        app._lobby_pub_toggle()
        pump(app, 0.1)
        check("地址框回到局域网", app.srv_addr_var.get() == lan_addr,
              app.srv_addr_var.get())
        check("标记复位", app._pub_switched is False)
        check("按钮文案回到「一键改为公网」",
              "一键改为公网" in btn.cget("text"), btn.cget("text"))

        print("7. 一键失败（如双重 NAT）→ 收尾并提示，不卡在等待")
        app._pub_ok_addr = ""
        app._pub_auto_switch = True
        kards_host.public_status = lambda: {"state": "done", "ok": False}
        bad_st = dict(ok_st, ok=False, double_nat=True, error="double_nat",
                      external_ip="192.168.1.2")
        before = len(app.mp_lobby_log)
        app._lobby_public_render(bad_st)
        pump(app, 0.2)
        check("自动切换模式已退出", app._pub_auto_switch is False)
        check("给出「没打通」的日志",
              any("没能自动打通" in x for x in app.mp_lobby_log[before:]),
              app.mp_lobby_log[before:])
        check("地址框仍是局域网", app.srv_addr_var.get() == lan_addr,
              app.srv_addr_var.get())
        check("按钮仍可点（可手动映射后重试）",
              str(btn.cget("state")) == "normal")
    finally:
        kards_host.map_public_async = orig_map
        kards_host.public_status = orig_status
        kards_host.running = orig_running
        kards_host.port_in_use = orig_in_use
        kards_host.local_addr = orig_local
        app.after = orig_after

    # ------------------------------------------------------------ C. 不退登
    print("8. 点「连接」指向同一台服务器（公网地址）→ 不重连、不丢登录态")

    class FakeLink:
        alive = True
        intentional = False
        inbox = __import__("queue").Queue()

        def send(self, obj):
            self.sent = getattr(self, "sent", [])
            self.sent.append(obj)
            return True

        def close(self):
            self.alive = False

    app.mp_link = FakeLink()
    app._srv_ready = True
    app._srv_addr = f"{pub_ip}:6000"
    app.mp_user = "Alice"
    app.srv_addr_var.set(f"{pub_ip}:6000")
    app._srv_poll = None
    closed = {}
    orig_close = app._close_server_link

    def fake_close():
        closed["hit"] = True

    app._close_server_link = fake_close
    try:
        app._lobby_connect()
        pump(app, 0.2)
        check("没有走断开重连", not closed)
        check("登录状态保留", app.mp_user == "Alice", app.mp_user)
        check("没新建连接轮询", app._srv_poll is None)
        check("补发了大厅订阅",
              any(m.get("m") == "lobby" for m in getattr(app.mp_link, "sent", [])))
    finally:
        app._close_server_link = orig_close

    print("9. 地址写法换成局域网 → 仍认作同一台，不重连")
    closed.clear()
    app._close_server_link = fake_close
    app.srv_addr_var.set(lan_addr)

    def fake_local(port=None):
        return lan_addr

    kards_host.local_addr = fake_local
    try:
        app._lobby_connect()
        pump(app, 0.2)
        check("没重连", not closed)
        check("登录状态保留", app.mp_user == "Alice", app.mp_user)
    finally:
        app._close_server_link = orig_close
        kards_host.local_addr = orig_local

    print("10. 已登录在大厅里点「建立服务器」→ 不把自己拽走")
    app._pub_ok_addr = ""
    app._pub_auto_switch = False
    app.mp_user = "Alice"
    app._srv_addr = "198.51.100.9:6000"          # 别人的服务器
    app.mp_link = FakeLink()
    app._srv_ready = True
    del after_calls[:]                     # 只看这一次调用排了哪些定时器
    kards_host.running = lambda: True
    kards_host.port_in_use = lambda **kw: True
    kards_host.local_addr = fake_local
    kards_host.map_public_async = fake_map
    try:
        app.after = fake_after
        app._lobby_host_server()
        pump(app, 0.1)
        check("没有排队重连", not any(ms == 700 for ms, _ in after_calls), after_calls)
        check("登录状态保留", app.mp_user == "Alice", app.mp_user)
        check("日志说明留在当前大厅",
              any("仍留在当前大厅" in x for x in app.mp_lobby_log[-6:]),
              app.mp_lobby_log[-6:])
        check("本机服务器仍在后台申请公网端口",
              host_calls.get("mapped") == 6000, host_calls)
    finally:
        app.after = orig_after
        kards_host.running = orig_running
        kards_host.port_in_use = orig_in_use
        kards_host.local_addr = orig_local
        kards_host.map_public_async = orig_map

    print("11. 未登录时开服 → 照常切到本机服务器")
    app.mp_user = None
    app._srv_ready = False
    app.mp_link = None
    del after_calls[:]
    kards_host.running = lambda: True
    kards_host.port_in_use = lambda **kw: True
    kards_host.local_addr = fake_local
    kards_host.map_public_async = fake_map
    try:
        app.after = fake_after
        app._lobby_host_server()
        pump(app, 0.1)
        check("排队了连接本机服", any(ms == 700 for ms, _ in after_calls), after_calls)
        check("地址框指向本机", app.srv_addr_var.get() == lan_addr,
              app.srv_addr_var.get())
    finally:
        app.after = orig_after
        kards_host.running = orig_running
        kards_host.port_in_use = orig_in_use
        kards_host.local_addr = orig_local
        kards_host.map_public_async = orig_map

    net.clear_public_ip()
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
