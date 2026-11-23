# -*- coding: utf-8 -*-
"""复现「开服/进服会退登」—— 打点每步的登录态，定位到底在哪一步丢的。

跑法：
    C:\\Users\\freet\\AppData\\Local\\Programs\\Python\\Python313\\python.exe debug/repro_logout.py
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
import tkinter.messagebox as mb                          # noqa: E402

mb.showwarning = lambda *a, **k: "ok"
mb.showerror = lambda *a, **k: "ok"
mb.showinfo = lambda *a, **k: "ok"
mb.askyesno = lambda *a, **k: False

import kards_account as account                          # noqa: E402
import kards_engine as core                              # noqa: E402
import kards_host                                        # noqa: E402
import kards_i18n as i18n                                # noqa: E402
import kards_net as net                                  # noqa: E402


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
            return
        time.sleep(0.01)


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


def state(tag, app):
    print(f"    [{tag}] mp_user={app.mp_user!r} account={getattr(app,'account',None)!r} "
          f"backend={account.backend()} current={account.current()!r} "
          f"ready={app._srv_ready} srv_addr={app._srv_addr!r} "
          f"link={'alive' if (app.mp_link and getattr(app.mp_link,'alive',False)) else app.mp_link}")


def start_server(db, port, log):
    return subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "kards_server.py"),
         "--host", "127.0.0.1", "--port", str(port), "--db", db],
        stdout=open(log, "wb"), stderr=subprocess.STDOUT, cwd=ROOT)


def main():
    tmp = tempfile.mkdtemp(prefix="kards_repro_")
    core.DATA_DIR = tmp
    account._ACCOUNTS = os.path.join(tmp, "accounts.json")
    account._SESSION = os.path.join(tmp, "session.json")
    core.setup_error_log()
    i18n.set_lang("zh")

    p1, p2 = free_port(), free_port()
    s1 = start_server(os.path.join(tmp, "s1.db"), p1, os.path.join(tmp, "s1.log"))
    wait_port(p1)
    app = None
    try:
        import KARDS as K
        app = K.App()
        pump(app, 0.5)
        app._build_lobby()
        pump(app, 0.4)
        print("1. 连服务器 A（临时库）")
        app.srv_addr_var.set(f"127.0.0.1:{p1}")
        app._lobby_connect()
        until(app, lambda: app._srv_ready and app.mp_link is not None, 10, "连上 A")
        state("connected", app)
        ok, err = account.register("Alice", "pass1234")
        print(f"    注册 Alice -> {ok} {err!r}")
        if ok:
            app.mp_user = "Alice"
            app._apply_account("Alice")
            app._srv_send({"m": "lobby"})
            pump(app, 0.3)
        state("logged-in A", app)

        print("2. 点「连接」（同地址）——旧版这里会退登")
        app._lobby_connect()
        pump(app, 0.6)
        state("reconnect same", app)

        print("3. 开服：本机起服务器 B（空库），地址切到 B")
        s2 = start_server(os.path.join(tmp, "s2.db"), p2, os.path.join(tmp, "s2.log"))
        wait_port(p2)
        orig = {k: getattr(kards_host, k) for k in
                ("running", "port_in_use", "local_addr", "map_public_async")}
        kards_host.running = lambda: True
        kards_host.port_in_use = lambda **kw: True
        kards_host.local_addr = lambda port=None: f"127.0.0.1:{p2}"
        kards_host.map_public_async = lambda p=None, on_done=None: None
        try:
            app._lobby_host_server()
            pump(app, 1.2)
            state("after host B", app)
            print("    (期望：不该退登；若 mp_user=None 就是用户报的 bug)")
        finally:
            for k, v in orig.items():
                setattr(kards_host, k, v)
            s2.terminate()

        print("4. 回主菜单再进大厅")
        app._lobby_back()
        pump(app, 0.4)
        app._build_lobby()
        pump(app, 1.0)
        state("re-enter lobby", app)
    finally:
        try:
            if app is not None:
                app.destroy()
        except Exception:                                # noqa: BLE001
            pass
        s1.terminate()
    print("tmp:", tmp)


if __name__ == "__main__":
    main()
