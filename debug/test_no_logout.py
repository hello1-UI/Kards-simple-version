# -*- coding: utf-8 -*-
"""「开服 / 进服不退登」回归测试

覆盖三条会让玩家"莫名变成游客"的路径：
  1. 本机服务器免密接管（adopt）：自己开的服，账号在本机，不该重输密码
  2. 服务器还没 listen 就发起连接（打包版启动要几秒）→ 等端口就绪再连
  3. 一次连接失败不再立刻弹框/清登录态 → 自动重试两次

必须用系统 Python：
    C:\\Users\\freet\\AppData\\Local\\Programs\\Python\\Python313\\python.exe debug/test_no_logout.py
"""
import os
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if "--no-update-check" not in sys.argv:
    sys.argv.append("--no-update-check")

import tkinter as tk                                     # noqa: E402

PASS, FAIL = [], []


def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [!!] ") + label + (f"  {extra}" if extra else ""))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_port(port, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), 0.3).close()
            return True
        except OSError:
            time.sleep(0.1)
    return False


def pump(app, sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        try:
            app.update()
        except tk.TclError:
            return False
        time.sleep(0.01)
    return True


def until(app, cond, timeout=8, label=""):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if cond():
                return True
        except tk.TclError:
            pass
        pump(app, 0.1)
    print(f"    (超时: {label})")
    return False


class Modal:
    """拦掉 messagebox（模态框会让自动化测试永久卡死），并记账。"""

    def __init__(self):
        import tkinter.messagebox as mb
        self.mb = mb
        self.calls = []
        self._orig = {}

    def __enter__(self):
        for n in ("showwarning", "showerror", "showinfo", "askyesno"):
            self._orig[n] = getattr(self.mb, n)
            setattr(self.mb, n, (lambda name: lambda *a, **k: self.calls.append(name) or (
                True if name.startswith("ask") else "ok"))(n))
        return self

    def __exit__(self, *exc):
        for n, f in self._orig.items():
            setattr(self.mb, n, f)
        return False


def main():
    tmp = tempfile.mkdtemp(prefix="kards_nologout_")
    db = os.path.join(tmp, "s.db")
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "kards_server.py"),
         "--host", "127.0.0.1", "--port", str(port), "--db", db],
        stdout=open(os.path.join(tmp, "s.log"), "wb"),
        stderr=subprocess.STDOUT, cwd=ROOT)

    import kards_account as account
    import kards_engine as core
    import kards_i18n as i18n
    import kards_net as net
    import kards_server as srv

    core.DATA_DIR = tmp
    account._ACCOUNTS = os.path.join(tmp, "accounts.json")
    account._SESSION = os.path.join(tmp, "session.json")
    core.setup_error_log()
    i18n.set_lang("zh")

    app = None
    try:
        if not wait_port(port):
            print("服务器未能启动")
            return 1

        print("1. 本机来源判定（免密接管的边界）")
        check("回环算本机", srv.is_local_peer("127.0.0.1"))
        check("外网地址不算本机", not srv.is_local_peer("203.0.113.9"))
        check("局域网别人的地址不算本机（避免越权接管）",
              not srv.is_local_peer("10.99.99.99"))
        check("网卡列表非空", bool(srv.local_ips()), srv.local_ips())

        print("2. 服务器端 adopt：已存在账号免密发会话；不存在则拒绝")
        link = {}
        net.connect_server_async(f"127.0.0.1:{port}", link, timeout=5)
        until_dummy = time.time() + 6
        while time.time() < until_dummy and "result" not in link:
            time.sleep(0.05)
        lk = link["result"][0]
        account.set_remote(lk, f"127.0.0.1:{port}")
        ok, err = account.register("Alice", "pass1234")
        check("服务器上注册 Alice", ok, err)
        account._drop_session()
        lk.close()
        account.set_remote(None)
        lk = None
        # ⚠ adopt 是**握手阶段**消息（和 login/register/resume 并列），
        # 必须在新连接上作为前几条消息发 —— 重连一次再接管。
        link2 = {}
        net.connect_server_async(f"127.0.0.1:{port}", link2, timeout=5)
        end = time.time() + 6
        while time.time() < end and "result" not in link2:
            time.sleep(0.05)
        lk = link2["result"][0]
        account.set_remote(lk, f"127.0.0.1:{port}")
        account._is_guest = True
        check("清掉 token 后是游客", account.is_guest())
        check("免密接管成功", account.adopt_local("Alice"))
        check("接管后账号是 Alice", account.current() == "Alice", account.current())
        check("接管后不再是游客", not account.is_guest())
        check("接管不存在的账号会被拒", not account.adopt_local("NobodyXYZ"))
        account.logout()
        account.set_remote(None)
        lk.close()
        lk = None

        print("2b. 本地账号第一次连本机服务器：带哈希免密建号（不传明文密码）")
        account.set_remote(None)
        account._is_guest = False
        ok, err = account.register("LocalBob", "bobpass")
        check("先在本地库注册 LocalBob", ok, err)
        account._drop_session()
        link3 = {}
        net.connect_server_async(f"127.0.0.1:{port}", link3, timeout=5)
        end = time.time() + 6
        while time.time() < end and "result" not in link3:
            time.sleep(0.05)
        lk3 = link3["result"][0]
        account.set_remote(lk3, f"127.0.0.1:{port}")
        check("本机服务器上没有也能免密建号", account.adopt_local("LocalBob"))
        check("建号后账号正确", account.current() == "LocalBob", account.current())
        account.logout()
        ok, err = account.login("LocalBob", "bobpass")
        check("之后用原密码仍能正常登录（哈希格式兼容）", ok, err)
        account.logout()
        account.set_remote(None)
        lk3.close()

        print("3. 大厅：连本机服务器时自动免密接管（不弹登录框）")
        with Modal() as modal:
            import importlib
            K = importlib.import_module("KARDS")
            app = K.App()
            pump(app, 0.4)
            app._build_lobby()
            pump(app, 0.4)
            # 模拟「本地记得这个账号，但会话令牌没了」——开服/重装后的常态
            account._drop_session()
            account._is_guest = True
            app.account = "Alice"
            app.srv_addr_var.set(f"127.0.0.1:{port}")
            modal.calls.clear()
            app._lobby_connect()
            got = until(app, lambda: app.mp_user == "Alice", 12, "自动接管")
            check("大厅恢复成 Alice（没有退登）", got, app.mp_user)
            check("没有弹登录框", "showerror" not in modal.calls
                  and "showwarning" not in modal.calls, modal.calls)
            check("账号按钮的名字也回来了", app.account == "Alice", app.account)
            check("日志说明了免密进入",
                  any("免密" in x for x in app.mp_lobby_log[-8:]),
                  app.mp_lobby_log[-8:])

        print("4. 开服：服务器还没 listen 时不急着连（避免一次失败就清登录态）")
        with Modal():
            app._cancel_timers()
            hp = free_port()                 # 故意没人监听
            called = []
            orig_connect = app._lobby_connect
            app._lobby_connect = lambda *a, **k: called.append(1)
            app._lobby_active = True
            try:
                app._lobby_connect_when_ready(hp, 0)
                pump(app, 0.2)
                check("端口未就绪时不发起连接", not called, called)
                check("挂了等待定时器", app._t_host is not None)
            finally:
                app._lobby_connect = orig_connect
                app._cancel_timer("_t_host")

        print("5. 连接失败自动重试两次后才报错（不立刻把玩家打成游客）")
        with Modal() as modal:

            class FakePoller:
                ready = True

                def __init__(self):
                    self.n = 0

                def take(self):
                    self.n += 1
                    return ("err", "测试用：连接被拒绝")

            app._cancel_timers()
            app._lobby_active = True
            app._connect_retry = 0
            modal.calls.clear()
            app._srv_poll = FakePoller()
            app._lobby_poll()
            check("第一次失败不弹框", not modal.calls, modal.calls)
            check("安排了重试", app._t_retry is not None)
            check("重试计数为 1", app._connect_retry == 1, app._connect_retry)
            app._cancel_timers()

            app._connect_retry = 2           # 额度用尽
            modal.calls.clear()
            app._srv_poll = FakePoller()
            app._lobby_poll()
            check("重试用尽才弹错误", bool(modal.calls), modal.calls)
            app._cancel_timers()
    finally:
        if app is not None:
            try:
                app.destroy()
            except Exception:                            # noqa: BLE001
                pass
        proc.terminate()

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
