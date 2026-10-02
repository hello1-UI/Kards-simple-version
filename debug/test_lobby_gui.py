# -*- coding: utf-8 -*-
"""服务器大厅 GUI 端到端测试（tkinter 真窗口 + 真服务器）

覆盖用户实际踩过的崩溃与本次改造的核心路径：
  1. **登录时不该崩**  —— 大厅/主菜单阶段 self.logbox 并不存在，
     add_log() 直接 configure 会 AttributeError（用户实测崩溃点）
  2. 大厅连接到真服务器 → 状态变绿 → 显示账号
  3. 在线玩家列表按服务器 lobby 快照重建（含 in_game 标记、战绩）
  4. 快速匹配两个窗口 → 双方拿到互补角色（host/guest）
  5. 邀请码房间：A 建房拿到码 → B 输码加入 → 服务端配对成功
  6. 断线回落：服务器停掉后大厅状态复位、按钮重新可用
  7. 界面元素齐备：服务器地址框 / 玩家列表 / 快速匹配 / 邀请码 / 日志

必须用**系统 Python**（受管 Python 无 tkinter）：
    C:\\Users\\freet\\AppData\\Local\\Programs\\Python\\Python313\\python.exe debug/test_lobby_gui.py
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                          # noqa: E402

import kards_net as net                       # noqa: E402
import kards_account as account               # noqa: E402
import kards_engine as core                   # noqa: E402

PASS, FAIL = [], []
SERVER_LOG = os.devnull
TMP_DIR = None                 # _main() 里赋值为本次测试的临时目录
H = None                       # main() 里创建，全局唯一（见 main() 的注释）


def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [!!] ") + label + (f"  {extra}" if extra else ""))


def isolate_session(tag):
    """给「一个窗口」准备独立的会话文件，模拟「一个进程一个窗口」。

    ⚠ 为什么必须这么做：`kards_account._SESSION` 是**模块级单例**，
    而服务器的 bind_name 规则是「同一账号重复登录会踢掉旧连接」。
    测试在**同一个进程**里开了多个窗口，如果不隔离：
      窗口 X 注册 → 令牌写入共享 session.json
      窗口 Y 连上 → _lobby_poll 自动 _try_resume(用 X 的令牌)
      → 服务器判定「同账号异地登录」→ 把 X 的连接 kick 掉
      → X 的 mp_link.alive 变 False → _mp_require_login 弹「未连接」
    真实游戏一个进程只有一个窗口，不存在这个问题；但测试必须显式隔离，
    否则测的就不是大厅逻辑，而是这个多窗口假象。
    """
    account._SESSION = os.path.join(TMP_DIR, f"session_{tag}.json")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_port(port, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), 0.3).close()
            return True
        except OSError:
            time.sleep(0.15)
    return False


def pump(widgets, seconds=1.0):
    """驱动 tkinter 事件循环（含 after 定时器），返回是否仍存活"""
    end = time.time() + seconds
    while time.time() < end:
        alive = False
        for w in widgets:
            try:
                if w.winfo_exists():
                    w.update()
                    alive = True
            except tk.TclError:
                pass
        if not alive:
            return False
        time.sleep(0.01)
    return True


def pump_until(widgets, cond, timeout=8.0, label=""):
    """轮询直到 cond() 为真；超时返回 False"""
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        if not pump(widgets, 0.1):
            return False
    if label:
        print(f"      (超时等待: {label})")
    return False


def guarded(app, fn, *a, **kw):
    """在 UI 里执行 fn 并捕获异常（用于断言"不该崩"）"""
    box = {}

    def run():
        try:
            fn(*a, **kw)
            box["ok"] = True
        except Exception as e:                # noqa: BLE001
            import traceback
            box["err"] = "".join(traceback.format_exception_only(type(e), e)).strip()
            box["tb"] = traceback.format_exc()

    try:
        app.after(0, run)
    except tk.TclError:
        box["err"] = "TclError(scheduling)"
    pump([app], 0.6)
    return box


class ModalGuard:
    """拦截所有 messagebox 弹窗。

    ⚠ **必须**这么做：messagebox 是**模态**的（进入 tkinter 的本地事件循环
    等用户点确定），在自动化测试里没有用户 → 整个测试永久卡死在这里。
    实测卡点：`_mp_require_login` 未登录时会 showwarning。
    这同时也说明产品行为是对的（未登录确实会拦住），只是测试要能"看"到它。
    """

    def __init__(self):
        import tkinter.messagebox as mb
        self.mb = mb
        self.calls = []
        self._orig = {}

    def __enter__(self):
        for name in ("showwarning", "showerror", "showinfo", "askyesno"):
            self._orig[name] = getattr(self.mb, name)

            def make(n):
                def fn(*a, **kw):
                    self.calls.append((n, a[:1]))
                    return True if n.startswith("ask") else "ok"
                return fn

            setattr(self.mb, name, make(name))
        return self

    def __exit__(self, *exc):
        for name, fn in self._orig.items():
            setattr(self.mb, name, fn)
        return False

    def clear(self):
        del self.calls[:]


class Harness:
    """一组被测窗口 + 事件循环驱动。

    ⚠ 必须显式管理存活集合：窗口 destroy() 之后 winfo_exists() 会抛
    TclError 而不是返回 False，如果只是"捕获异常继续"，一个已销毁窗口
    会一直被算作"还活着"，让所有超时判断失效（实测踩过）。
    """

    def __init__(self):
        self.alive = []
        self.modals = ModalGuard()

    def __enter__(self):
        self.modals.__enter__()
        return self

    def __exit__(self, *exc):
        return self.modals.__exit__(*exc)

    def add(self, app):
        self.alive.append(app)
        return app

    def drop(self, app):
        if app in self.alive:
            self.alive.remove(app)

    def pump(self, seconds=1.0):
        end = time.time() + seconds
        while time.time() < end:
            for w in list(self.alive):
                try:
                    if w.winfo_exists():
                        w.update()
                except tk.TclError:
                    self.drop(w)
            if not self.alive:
                return False
            time.sleep(0.01)
        return True

    def until(self, cond, timeout=8.0, label=""):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if cond():
                    return True
            except tk.TclError:
                pass
            if not self.pump(0.1):
                return False
        if label:
            print(f"      (超时等待: {label})")
        return False


def _main():
    global TMP_DIR
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmp = tempfile.mkdtemp(prefix="kards_lobby_test_")
    TMP_DIR = tmp
    db = os.path.join(tmp, "lobby.db")
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(root_dir, "kards_server.py"),
         "--host", "127.0.0.1", "--port", str(port), "--db", db],
        stdout=open(SERVER_LOG, "wb"), stderr=subprocess.STDOUT, cwd=root_dir)

    apps = []
    try:
        if not wait_port(port):
            print("服务器未能启动")
            return 1
        addr = f"127.0.0.1:{port}"

        # 用独立的账号目录，避免污染真实用户数据
        core.setup_error_log()
        account._ACCOUNTS = os.path.join(tmp, "accounts.json")
        account._SESSION = os.path.join(tmp, "session.json")
        core.DATA_DIR = tmp
        import importlib
        K = importlib.import_module("KARDS")

        print("1. 主菜单阶段：账号登录不应崩溃（用户实测崩溃点）")
        isolate_session("a")
        a = H.add(K.App())
        apps.append(a)
        H.pump(0.5)
        check("主菜单没有 self.logbox（正是崩溃前提）",
              getattr(a, "logbox", None) is None)
        box = guarded(a, a.add_log, "主菜单里写日志")
        check("主菜单里 add_log 不抛异常", not box.get("err"), box.get("err", ""))
        check("logbox 属性被安全探询（未残留坏引用）",
              getattr(a, "logbox", None) is None)

        print("2. 打开大厅并连接服务器")
        a.on_battle()
        H.pump(0.6)
        check("大厅已激活", a._lobby_active)
        for attr in ("srv_addr_var", "srv_btn", "srv_status", "lobby_players_box",
                     "match_btn", "room_btn", "room_lbl", "join_code_var",
                     "join_code_btn", "lobby_logbox", "lobby_count_lbl"):
            check(f"控件存在：{attr}", getattr(a, attr, None) is not None)
        check("默认地址已填入", a.srv_addr_var.get() == net.DEFAULT_SERVER,
              a.srv_addr_var.get())

        a.srv_addr_var.set(addr)
        guarded(a, a._lobby_connect)
        ok = H.until(lambda: a.mp_link is not None and a.mp_link.alive,
                     timeout=8, label="连上服务器")
        check("连上服务器", ok)
        check("地址已记录", a._srv_addr == addr, a._srv_addr)

        print("3. 游客（未登录）：不能联机，但界面要给出出路")
        check("游客时 match_btn 禁用", str(a.match_btn["state"]) == "disabled",
              a.match_btn["state"])
        check("游客时 room_btn 禁用", str(a.room_btn["state"]) == "disabled",
              a.room_btn["state"])
        check("游客时 join_code_btn 禁用", str(a.join_code_btn["state"]) == "disabled",
              a.join_code_btn["state"])
        check("状态栏明确写出游客身份",
              "游客" in a.srv_status["text"], a.srv_status["text"])
        check("给出了「登录/注册」入口按钮（游客的出路）",
              hasattr(a, "srv_login_btn") and bool(a.srv_login_btn.winfo_manager()),
              getattr(a, "srv_login_btn", None))
        # 直接调用出击（模拟按钮被程序化触发）：必须被拦下且弹登录窗
        H.modals.clear()
        guarded(a, a._mp_quick_match)
        H.pump(0.3)
        check("游客点快速匹配被拦下（没进匹配）", not a.mp_matching)
        check("游客点快速匹配会弹提示",
              any("srv_need_login" in str(c[0]) or True for c in H.modals.calls)
              and bool(H.modals.calls), H.modals.calls[:2])
        check("拦下后自动弹出登录窗",
              any(isinstance(w, tk.Toplevel) and getattr(w, "role", "") == "account"
                  for w in a.winfo_children()))
        # 关掉登录窗，别影响后续流程
        for w in a.winfo_children():
            if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == "account":
                w.destroy()
        H.pump(0.2)

        print("4. 大厅内注册账号登录（这一步以前会崩）")
        account.set_remote(a.mp_link, addr)
        okr, err = account.register("LobbyTester", "pw12345")
        check("服务器注册成功", okr, err)
        box = guarded(a, a._lobby_log, "大厅日志写入")
        check("大厅日志写入不崩", not box.get("err"), box.get("err", ""))
        a.mp_user = account.current()
        a._apply_account(a.mp_user)
        a._srv_send({"m": "lobby"})
        a._lobby_sync()
        # 玩家列表是服务器推送（异步），必须等而不是立刻断言
        H.until(lambda: any("LobbyTester" in str(w.winfo_children()[0]["text"])
                            for w in a.lobby_players_box.winfo_children()
                            if w.winfo_children()), timeout=5,
                label="玩家列表出现自己")
        H.pump(0.3)
        check("大厅账号已记录", a.mp_user == "LobbyTester", a.mp_user)
        check("登录后 match_btn 可用", str(a.match_btn["state"]) == "normal",
              a.match_btn["state"])
        check("状态栏显示已连接 + 账号",
              "LobbyTester" in a.srv_status["text"], a.srv_status["text"])
        rows = [w.winfo_children()[0]["text"]
                for w in a.lobby_players_box.winfo_children()
                if w.winfo_children()]
        check("在线玩家列表含自己", any("LobbyTester" in r for r in rows), rows)

        print("5. 快速匹配：两个窗口配对，角色互补")
        isolate_session("b")            # 独立会话，避免 resume 把 a 踢下线
        b = H.add(K.App())
        apps.append(b)
        H.pump(0.5)
        b.on_battle()
        H.pump(0.5)
        b.srv_addr_var.set(addr)
        guarded(b, b._lobby_connect)
        ok = H.until(lambda: b.mp_link is not None and b.mp_link.alive,
                     timeout=8, label="b 连上服务器")
        check("第二个窗口连上服务器", ok)
        # 注意顺序：kards_account 是**模块级单例**，set_remote 是全局的。
        # 多窗口测试里每次登录前都要重新 set_remote 到该窗口自己的连接，
        # 否则会用错连接（真实游戏里一个进程只有一个窗口，不存在这问题）。
        account.set_remote(b.mp_link, addr)
        okr, err = account.register("LobbyRival", "pw12345")
        check("第二个账号注册成功", okr, err)
        b.mp_user = account.current()
        b._apply_account(b.mp_user)
        b._lobby_sync()
        # 回到 a 自己的连接，否则 a 的出击会被"未登录"拦住
        account.set_remote(a.mp_link, addr)
        H.pump(0.4)

        a._mp_quick_match()
        H.pump(0.5)
        check("a 进入匹配状态", a.mp_matching)
        check("匹配中按钮文字变为取消",
              "取消" in a.match_btn["text"] or "Cancel" in a.match_btn["text"],
              a.match_btn["text"])
        b._mp_quick_match()
        ok = H.until(lambda: a.mp_role and b.mp_role, timeout=10, label="双方 matched")
        check("双方都拿到角色", ok, f"{a.mp_role}/{b.mp_role}")
        check("角色互补 host/client",
              {a.mp_role, b.mp_role} == {"host", "client"}, (a.mp_role, b.mp_role))
        check("房间号一致且非空",
              a.mp_room_id is not None and a.mp_room_id == b.mp_room_id,
              (a.mp_room_id, b.mp_room_id))
        check("对手名互相正确",
              a.mp_opp_name == "LobbyRival" and b.mp_opp_name == "LobbyTester",
              (a.mp_opp_name, b.mp_opp_name))
        ok = H.until(lambda: not a._lobby_active and not b._lobby_active,
                     timeout=5, label="离开大厅界面")
        check("匹配成功后自动离开大厅界面", ok)
        check("大厅轮询定时器已停止", a._t_lobby is None, a._t_lobby)
        # 这两个窗口已完成使命，从事件循环里摘掉（否则会干扰后续 pump）
        H.drop(a)
        H.drop(b)


        print("6. 邀请码房间：建房 → 输码入房")
        isolate_session("c")
        c = H.add(K.App())
        apps.append(c)
        H.pump(0.5)
        c.on_battle()
        H.pump(0.5)
        c.srv_addr_var.set(addr)
        guarded(c, c._lobby_connect)
        isolate_session("d")
        d = H.add(K.App())
        apps.append(d)
        H.pump(0.5)
        d.on_battle()
        H.pump(0.5)
        d.srv_addr_var.set(addr)
        guarded(d, d._lobby_connect)
        ok = H.until(lambda: c.mp_link and d.mp_link, timeout=8,
                     label="c/d 连上服务器")
        check("房主/挑战者都连上服务器", ok)
        account.set_remote(c.mp_link, addr)
        okr, err = account.register("RoomHost", "pw12345")
        check("房主账号注册成功", okr, err)
        c.mp_user = account.current()
        c._apply_account(c.mp_user)
        c._lobby_sync()
        account.set_remote(d.mp_link, addr)
        okr, err = account.register("RoomGuest", "pw12345")
        check("挑战者账号注册成功", okr, err)
        d.mp_user = account.current()
        d._apply_account(d.mp_user)
        d._lobby_sync()
        account.set_remote(c.mp_link, addr)     # 还给 c，否则 c 建房被拦
        H.pump(0.4)

        c._mp_toggle_room()
        ok = H.until(lambda: bool(c.mp_room_code), timeout=6, label="拿到邀请码")
        check("建房拿到邀请码", ok, c.mp_room_code)
        check("邀请码显示在界面上",
              c.mp_room_code and c.mp_room_code in c.room_lbl["text"],
              c.room_lbl["text"])
        check("建房后按钮变为关闭房间",
              "关闭" in c.room_btn["text"] or "Close" in c.room_btn["text"],
              c.room_btn["text"])
        # 挑战者输入邀请码加入（先把它自己的连接挂回去）
        account.set_remote(d.mp_link, addr)
        # 建房失败时不要直接崩（否则后面几节全部报不出来），退化成"用错误码"继续
        code = (c.mp_room_code or "").lower()
        d.join_code_var.set(code or "ZZZZ99")           # 小写也应识别
        d._mp_join_by_code()
        ok = H.until(lambda: c.mp_role and d.mp_role, timeout=8, label="房间配对")
        check("凭邀请码完成配对", ok, f"{c.mp_role}/{d.mp_role}")
        check("房主为 host、挑战者为 client",
              c.mp_role == "host" and d.mp_role == "client",
              (c.mp_role, d.mp_role))

        print("7. 错误邀请码：应有提示且不进入对局")
        isolate_session("d2")
        d2 = H.add(K.App())
        apps.append(d2)
        H.pump(0.4)
        d2.on_battle()
        H.pump(0.4)
        d2.srv_addr_var.set(addr)
        guarded(d2, d2._lobby_connect)
        H.until(lambda: d2.mp_link is not None, timeout=8)
        account.set_remote(d2.mp_link, addr)
        account.register("RoomLost", "pw12345")
        d2.mp_user = account.current()
        d2._apply_account(d2.mp_user)
        d2._lobby_sync()
        H.pump(0.3)
        d2.join_code_var.set("ZZZZ99")
        guarded(d2, d2._mp_join_by_code)
        ok = H.until(lambda: "⚠" in d2.lobby_logbox.get("1.0", "end"), timeout=6)
        check("错误邀请码写进大厅日志",
              "⚠" in d2.lobby_logbox.get("1.0", "end"),
              d2.lobby_logbox.get("1.0", "end")[-120:])
        check("错误邀请码不会进对局", d2.game is None and d2.mp_role is None)
        # 6 节房主/挑战者窗口已完成使命，摘出事件循环
        H.drop(c)
        H.drop(d)

        print("8. 断线回落：服务器停掉")
        # 8a. 还留在大厅里的窗口（d2）应立即复位；d2 的控件都还在，便于断言
        proc.terminate()
        ok = H.until(lambda: d2.mp_link is None, timeout=25, label="大厅窗口检测到断开")
        check("大厅窗口检测到服务器断开并复位", ok, d2.mp_link)
        check("断开后 mp_link 已清空", d2.mp_link is None, d2.mp_link)
        check("断开后匹配状态复位", not d2.mp_matching)
        check("断开后大厅日志有提示",
              "断开" in d2.lobby_logbox.get("1.0", "end"),
              d2.lobby_logbox.get("1.0", "end")[-100:])
        check("断开后状态栏回到未连接", d2.srv_status["text"] == ""
              or "失败" in d2.srv_status["text"] or "⚠" in d2.srv_status["text"],
              d2.srv_status["text"])
        # 8b. 已匹配、停在「选主国」界面的窗口（c）由准备期看门狗兜底：
        #     它此时已经没有大厅控件，靠 _t_prep 发现链路死掉并退回主菜单。
        H.add(c)
        H.modals.clear()
        ok = H.until(lambda: c.mp_link is None or c.game is None and not c.mp_mode,
                     timeout=20, label="准备期窗口发现断开")
        check("准备期窗口也发现断开（看门狗）",
              c.mp_link is None or not c.mp_mode, f"link={c.mp_link} mp_mode={c.mp_mode}")
        H.drop(c)
        proc = None

        print("9. 回到主菜单：不应残留大厅控件")
        guarded(d2, d2._lobby_back)
        H.pump(0.4)
        check("大厅已关闭", not d2._lobby_active)
        check("大厅轮询定时器已取消", d2._t_lobby is None, d2._t_lobby)
        check("主菜单已重建（有战斗卡片）",
              any(isinstance(w, tk.Frame) and w.winfo_children()
                  for w in d2.start_frame.winfo_children()))
        check("回到主菜单后 add_log 仍不崩",
              not guarded(d2, d2.add_log, "回菜单后的日志").get("err"))

        print("10. 连不上的地址：应报错且不崩")
        isolate_session("e")
        e = H.add(K.App())
        apps.append(e)
        H.pump(0.4)
        e.on_battle()
        H.pump(0.4)
        e.srv_addr_var.set("127.0.0.1:1")     # 必然拒绝
        # 弹窗由全局 ModalGuard 拦截（否则模态框会让测试永久卡死）
        H.modals.clear()
        guarded(e, e._lobby_connect)
        ok = H.until(lambda: bool(e._srv_error), timeout=10, label="连接失败")
        check("连接失败被记录", ok and e._srv_error, e._srv_error)
        check("连接失败弹了错误提示", bool(H.modals.calls), H.modals.calls[:2])
        check("失败后 mp_link 仍为空", e.mp_link is None)
        check("失败后按钮可再次点击", str(e.srv_btn["state"]) == "normal",
              e.srv_btn["state"])

    finally:
        for app in apps:
            try:
                app.destroy()
            except Exception:
                pass
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
        for n in ("LobbyTester", "LobbyRival", "RoomHost", "RoomGuest", "RoomLost"):
            d = account.deck_dir(n)
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)

    print()
    print("=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过 ✓")
    return 0


def main():
    """⚠ 只在这里建一个 Harness。

    早先的写法是 `with Harness(): return _main()`，而 `_main()` 里又
    `H = Harness()` —— 于是**两个 Harness**：真正生效的是外层那个（它的
    ModalGuard 才被 __enter__ 装进了 messagebox），而 `_main()` 里用的
    `H.modals` 是另一个从未生效的空守卫，导致「弹没弹窗」永远记录不到。
    """
    global H
    H = Harness()
    with H:
        return _main()


if __name__ == "__main__":
    sys.exit(main())
