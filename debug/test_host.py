# -*- coding: utf-8 -*-
"""`KARDS --server` 入口 + kards_host 开服模块的回归测试。

为什么要有这个测试
    「主程序兼任服务器」这条路径很容易悄悄坏掉，而且坏掉的方式很隐蔽：
      · 忘了在创建 Tk 窗口**之前**分流 → 双击 --server 会先弹出游戏界面
      · 子进程 stdout 用 PIPE 又没人读 → Windows 上写满缓冲区后卡死
      · 打包后数据库落到 Program Files → 只读，注册直接崩
    所以这里必须**真的把服务器拉起来、真的连上去登录一次**，
    而不是只断言几个函数存在。

用系统 Python 跑（受管 Python 没有 tkinter）：
    python debug/test_host.py
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _pick_python():
    """挑一个**带 tkinter** 的解释器来跑 KARDS.py。

    ⚠ KARDS.py 顶部就 `import tkinter`，而受管 Python 没有 tkinter。
    以 `--server` 启动同样会先 import 到 tkinter 然后 ModuleNotFoundError，
    所以这里不能直接用 sys.executable（受管解释器），
    必须先找到一个能 import tkinter 的。
    """
    candidates = [sys.executable]
    for p in (r"C:\Users\freet\AppData\Local\Programs\Python\Python313\python.exe",
              shutil.which("python"), shutil.which("py")):
        if p and p not in candidates:
            candidates.append(p)
    for p in candidates:
        try:
            r = subprocess.run([p, "-c", "import tkinter"],
                               capture_output=True, timeout=25)
            if r.returncode == 0:
                return p
        except (OSError, subprocess.SubprocessError):
            continue
    return sys.executable


PY = _pick_python()
KARDS = os.path.join(ROOT, "KARDS.py")

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    mark = "[OK]" if ok else "[!!]"
    print(f"  {mark} {name}" + (f"  {detail}" if detail else ""))
    return bool(ok)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def header(t):
    print()
    print(t)


def _has_tk(p):
    try:
        return subprocess.run([p, "-c", "import tkinter"],
                              capture_output=True, timeout=25).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main():
    import kards_host

    header(f"0. 解释器：{PY}")
    check("找到带 tkinter 的解释器", PY != sys.executable or _has_tk(sys.executable),
          PY)

    # ------------------------------------------------------------ 1
    header("1. 模块形态与资源定位")
    check("kards_host 可导入", True)
    check("resource_dir() 存在", os.path.isdir(kards_host.resource_dir()),
          kards_host.resource_dir())
    script = kards_host.server_script()
    check("能找到 kards_server.py", script is not None and os.path.isfile(script),
          str(script))
    check("can_host() 为真（有脚本）", kards_host.can_host())

    # ------------------------------------------------------------ 2
    header("2. 端口探测")
    port = free_port()
    check("空闲端口探测为「未占用」", not kards_host.port_in_use(port=port),
          f"port={port}")
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)
    time.sleep(0.1)
    check("被 listen 的端口探测为「占用」", kards_host.port_in_use(port=port),
          f"port={port}")
    srv.close()

    # ------------------------------------------------------------ 3
    header("3. 真的把服务器拉起来（子进程）+ 客户端能连上")
    port = free_port()
    ok, err = kards_host.start(port=port)
    check("kards_host.start() 成功", ok, err)
    if not ok:
        return finish()

    # 等端口起来（最多 8 秒）
    up = False
    for _ in range(80):
        if kards_host.port_in_use(port=port):
            up = True
            break
        time.sleep(0.1)
    check("服务器端口已监听", up, f"port={port}")
    check("running() 为真", kards_host.running())

    if up:
        import kards_net
        import kards_account
        # 用真实协议走一遍：连上 → 注册 → 大厅快照
        link, e = None, ""
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            link = kards_net.ServerLink(sock, ("127.0.0.1", port))
        except OSError as ex:
            e = f"{type(ex).__name__}: {ex}"
        check("客户端 TCP 能连上", link is not None, e)
        if link is not None:
            name = "HostT" + str(int(time.time()) % 100000)   # 长度 <= 16
            link.send({"m": "register", "user": name, "pw": "pw123456"})
            got = None
            deadline = time.time() + 6
            while time.time() < deadline:
                try:
                    msg = link.inbox.get(timeout=0.3)
                except Exception:                 # noqa: BLE001
                    continue
                if isinstance(msg, dict) and msg.get("m") in ("auth_ok", "auth_err"):
                    got = msg
                    break
            check("注册成功（服务器真的在干活）",
                  bool(got and got.get("m") == "auth_ok"),
                  (f"name={name} " + str(got)[:120]) if got else "无应答")
            link.close()

    kards_host.stop()
    time.sleep(0.4)
    check("stop() 后 running() 为假", not kards_host.running())
    check("stop() 后端口已释放", not kards_host.port_in_use(port=port), f"port={port}")

    # ------------------------------------------------------------ 4
    header("4. KARDS.exe --server 入口（源码方式直接跑）")
    port = free_port()
    data_dir = tempfile.mkdtemp(prefix="kards_host_data_")
    env = dict(os.environ)
    env["KARDS_DATA_DIR"] = data_dir
    proc = subprocess.Popen(
        [PY, KARDS, "--server", "--port", str(port), "--host", "127.0.0.1"],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        up = False
        died = False
        for _ in range(100):
            if proc.poll() is not None:
                died = True
                break
            try:
                socket.create_connection(("127.0.0.1", port), timeout=1).close()
                up = True
                break
            except OSError:
                time.sleep(0.1)
        check("--server 起得来并监听端口", up,
              f"port={port}" + ("（进程提前退出）" if died else ""))
        check("--server 进程在监听期间保持存活", up and not died,
              f"poll={proc.poll()}")
        db = os.path.join(data_dir, "kards_server.db")
        check("数据库落在 KARDS_DATA_DIR 里（不是项目根）", os.path.isfile(db), db)
        if up:
            # 走一遍真实协议，证明这个「自己起的服务器」能注册
            import kards_net
            sock = socket.create_connection(("127.0.0.1", port), timeout=5)
            link = kards_net.ServerLink(sock, ("127.0.0.1", port))
            name = "SrvEntry" + str(int(time.time()) % 10000)
            link.send({"m": "register", "user": name, "pw": "pw123456"})
            got = None
            deadline = time.time() + 6
            while time.time() < deadline:
                try:
                    msg = link.inbox.get(timeout=0.3)
                except Exception:                 # noqa: BLE001
                    continue
                if isinstance(msg, dict) and msg.get("m") in ("auth_ok", "auth_err"):
                    got = msg
                    break
            check("--server 起来的服务器能注册账号",
                  bool(got and got.get("m") == "auth_ok"),
                  (f"name={name} " + str(got)[:120]) if got else "无应答")
            link.close()
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:                         # noqa: BLE001
            try:
                proc.kill()
            except Exception:                     # noqa: BLE001
                pass
    check("--server 被 terminate 后确实退出了", proc.poll() is not None,
          f"rc={proc.poll()}")

    # ------------------------------------------------------------ 5
    header("5. 端口占用时给出可读错误（不是崩溃）")
    port = free_port()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)
    env2 = dict(os.environ)
    env2["KARDS_DATA_DIR"] = tempfile.mkdtemp(prefix="kards_host_data2_")
    proc = subprocess.Popen(
        [PY, KARDS, "--server", "--port", str(port), "--host", "127.0.0.1",
         "--silent-server-errors"],
        cwd=ROOT, env=env2,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        rc = proc.wait(timeout=25)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = None
    srv.close()
    check("端口被占用时进程会自己退出（不挂死）", rc is not None, f"rc={rc}")
    check("退出码非 0（明确报错而不是假装成功）", rc not in (None, 0), f"rc={rc}")

    # ------------------------------------------------------------ 6
    header("6. `--host-selftest` 自检入口（打包后也用同一条命令验收）")
    r = subprocess.run([PY, KARDS, "--host-selftest"],
                       cwd=ROOT, capture_output=True, timeout=120)
    out = (r.stdout or b"").decode("utf-8", "replace")
    err = (r.stderr or b"").decode("utf-8", "replace")
    check("自检退出码为 0", r.returncode == 0, f"rc={r.returncode} {err[-200:]}")
    check("自检报告 can_host=True", "can_host = True" in out)
    check("自检报告端口已监听", "已监听 = True" in out)
    check("自检报告注册成功", "'auth_ok'" in out)
    check("自检输出 SELFTEST OK", "SELFTEST OK" in out)

    # ------------------------------------------------------------ 7
    header("7. 更新目标目录：onedir 应指向 _internal")
    import kards_update as upd
    # 模拟 frozen + _internal 布局
    tmp_root = tempfile.mkdtemp(prefix="kards_frozen_")
    internal = os.path.join(tmp_root, "_internal")
    os.makedirs(internal, exist_ok=True)
    fake_exe = os.path.join(tmp_root, "KARDS.exe")
    open(fake_exe, "wb").close()
    orig_frozen = getattr(sys, "frozen", False)
    orig_exe = sys.executable
    try:
        sys.frozen = True
        sys.executable = fake_exe
        check("onedir：target 指向 _internal", upd.can_self_update() == internal,
              str(upd.can_self_update()))
        check("onedir：restart_dir 指向 exe 那层", upd.restart_dir() == tmp_root,
              str(upd.restart_dir()))
        os.rmdir(internal)
        check("无 _internal 时退回 exe 目录", upd.can_self_update() == tmp_root,
              str(upd.can_self_update()))
    finally:
        if orig_frozen is False:
            try:
                del sys.frozen
            except AttributeError:
                pass
        elif orig_frozen is not False:
            sys.frozen = orig_frozen
        sys.executable = orig_exe

    # onefile 模拟
    try:
        sys._MEIPASS = tempfile.gettempdir()
        check("onefile：can_self_update() 为 None（不能就地更新）",
              upd.can_self_update() is None)
        t = upd.UpdateTask("1.0.0.0")
        started = t.start()
        check("onefile：UpdateTask.start() 拒绝启动并给出原因",
              (not started) and t.state == "error",
              f"state={t.state}")
    finally:
        try:
            del sys._MEIPASS
        except AttributeError:
            pass

    return finish()


def finish():
    print()
    print("=" * 56)
    ok = sum(1 for _n, o, _d in RESULTS if o)
    bad = len(RESULTS) - ok
    print(f"通过 {ok} 项 / 失败 {bad} 项")
    if bad:
        for n, o, d in RESULTS:
            if not o:
                print(f"  FAIL: {n}  {d}")
        print("存在失败 ✗")
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
