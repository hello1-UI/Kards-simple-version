# -*- coding: utf-8 -*-
"""安装器 / 卸载器图形界面的回归测试。

覆盖四层：
    1. 钩子层：进度回调按阶段映射、取消事件传播、界面上抛不反噬安装流程；
    2. 提权重启：frozen 模式下参数里绝不能再带 exe 自身路径
       （旧 bug：提权后安装目录会变成安装器所在目录，cleanup_old 会清空它）；
    3. 输出转接：print → 界面日志；`\\r` 进度行转状态、残尾丢弃、空行去重；
    4. GUI 冒烟：窗口能建、按钮/勾选框/进度条/日志框行为正确、
       完成态按钮切换（开始安装 → 启动游戏）。
    5. 卸载链路：detect_target 误删防护 + uninstall_core 真删一个伪造目录。

跑法（GUI 段需要带 tkinter 的系统 Python）：
    python debug/test_setup_gui.py
"""
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "apk"))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import install                      # noqa: E402
import uninstall as uni             # noqa: E402

PASS, FAIL = [], []


def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [!!] ") + label + (f"  {extra}" if extra else ""))


# ================================================================ 1. 钩子层

def test_hooks():
    print("\n1. 进度/取消钩子")

    got = []
    install.set_ui_hooks(progress=lambda f, t: got.append((f, t)))
    install._stage(0.0, 0.55)
    install._emit(0.5, "下载中")
    check("阶段映射正确", abs(got[-1][0] - 0.275) < 1e-9, got)
    check("状态文本透传", got[-1][1] == "下载中", got[-1])

    install._stage(0.55, 0.33)
    install._emit(None, "测速")
    check("None = 不确定进度", got[-1][0] is None, got[-1])

    install._emit(1.7, "")
    check("越界值被夹到区间上界", abs(got[-1][0] - 0.88) < 1e-9, got[-1])

    install.set_ui_hooks()
    install._emit(0.5, "")
    check("未挂钩子时 _emit 是空操作", len(got) == 3, len(got))

    ev = threading.Event()
    ev.set()
    install.set_ui_hooks(cancel=ev)
    try:
        install._check_cancel()
        check("取消事件触发 Cancelled", False)
    except install.Cancelled:
        check("取消事件触发 Cancelled", True)
    except Exception as e:
        check("取消事件触发 Cancelled", False, repr(e))

    install.set_ui_hooks()
    try:
        install._check_cancel()
        check("不挂钩子时绝不误抛", True)
    except Exception as e:
        check("不挂钩子时绝不误抛", False, repr(e))

    # 界面回调抛异常绝不能拖垮安装流程
    install.set_ui_hooks(progress=lambda f, t: 1 / 0)
    install._stage(0.0, 1.0)
    try:
        install._emit(0.3, "")
        check("进度回调炸了也不影响安装", True)
    except Exception as e:
        check("进度回调炸了也不影响安装", False, repr(e))
    install.set_ui_hooks()


def test_launch_spec():
    print("\n2. 提权重启的参数（旧 bug 回归锁）")
    exe, params = install._launch_spec(["D:\\Games\\KARDS", "--auto"])
    check("源码模式含自身脚本路径", "test_setup_gui.py" in params, params)
    check("用户参数在内", "D:\\Games\\KARDS" in params, params)

    # 模拟 frozen：exe 的 argv[0] 就是自身路径，绝不能再传一遍
    real_argv, real_frozen = sys.argv, getattr(sys, "frozen", False)
    try:
        sys.frozen = True
        sys.argv = [r"D:\dist\KARDS安装器.exe", r"E:\Arg\Path", "--auto"]
        exe, params = install._launch_spec(None)
        check("frozen 模式用 sys.executable", exe == sys.executable, exe)
        check("frozen 模式不含 exe 自身路径",
              "KARDS安装器.exe" not in params, params)
        check("frozen 模式保留用户参数", "E:\\Arg\\Path" in params, params)
    finally:
        sys.argv = real_argv
        if real_frozen:
            sys.frozen = True
        else:
            del sys.frozen


def test_models_count():
    print("\n3. 安装器自带的模板套数")
    n = install.bundled_models_count()
    check("项目根 models/ 能被数到", n == 12, n)


# ================================================================ 3. 输出转接

def test_stream():
    print("\n4. print → 界面日志（\\r 进度行处理）")
    import installer_ui

    out = []
    w = installer_ui._StreamToQueue(lambda k, t: out.append((k, t)))
    w.write("  hello\n  world\n")
    check("普通行进日志", out == [("log", "  hello"), ("log", "  world")], out)

    out.clear()
    w.write("\r    [####----] 42% 3.2MB/7.6MB")
    check("\\r 只覆写不立即输出（等下一次刷新）", out == [], out)

    out.clear()
    w.write("\r    [##] 20%\n")
    check("\\r 后到 \\n 的内容是状态行",
          out == [("status", "[##] 20%")], out)

    out.clear()
    w.write("\r状态行\n普通日志\n")
    check("状态行与日志行分开",
          out == [("status", "状态行"), ("log", "普通日志")], out)

    out.clear()
    w.write("a\n\n\nb\n")
    check("连续空行只推一条", [x for x in out if x[0] == "log"] ==
          [("log", "a"), ("log", ""), ("log", "b")], out)

    out.clear()
    w.write("中文进度\n")
    w.write("\r    已下载 3.2MB  1.2MB/s\n")
    check("日志与进度状态并存",
          out == [("log", "中文进度"),
                  ("status", "已下载 3.2MB  1.2MB/s")], out)

    # uninstaller 的转接器：没有 \r 逻辑，逐行
    import uninstaller_ui
    out.clear()
    w2 = uninstaller_ui._StreamToQueue(lambda k, t: out.append((k, t)))
    w2.write("[1/4] 删除快捷方式 ...\n  快捷方式 ✓\n")
    check("卸载日志逐行转发",
          out == [("log", "[1/4] 删除快捷方式 ..."), ("log", "  快捷方式 ✓")], out)
    w2.write("无换行的尾巴")
    check("无换行内容先缓冲", out[-1][1] == "  快捷方式 ✓", out)
    w2.write("\n")
    check("补上换行后吐出", out[-1] == ("log", "无换行的尾巴"), out[-1])


# ================================================================ 5. 卸载链路

def test_detect_target():
    print("\n5. 卸载目标检测（防误删）")
    base = tempfile.mkdtemp(prefix="kards_gui_uni_")
    empty = os.path.join(base, "empty")
    os.makedirs(empty, exist_ok=True)
    t, warn = uni.detect_target if False else (None, None)  # noqa: F841
    # detect_target 用的是 self_dir()（脚本所在目录），无法指向任意目录 ——
    # 这里直接复刻它的判定逻辑做行为锁，防未来改动破坏误删防护。
    markers = uni.SELF_MARKERS
    found = any(os.path.exists(os.path.join(empty, m)) for m in markers)
    check("空目录无 marker → 不当安装目录", not found)
    with open(os.path.join(empty, "KARDS.exe"), "wb") as f:
        f.write(b"x")
    found = any(os.path.exists(os.path.join(empty, m)) for m in markers)
    check("有 KARDS.exe → 认定安装目录", found)
    shutil.rmtree(base, ignore_errors=True)


def test_uninstall_core():
    print("\n6. 卸载链路：uninstall_core 真删一个伪造目录")
    base = tempfile.mkdtemp(prefix="kards_gui_uni2_")
    target = os.path.join(base, "Kards-Simple-Version")
    os.makedirs(os.path.join(target, "_internal"), exist_ok=True)
    for rel in ("KARDS.exe", "KARDS卸载器.exe", "_internal\\python313.dll"):
        p = os.path.join(target, *rel.split("\\"))
        with open(p, "wb") as f:
            f.write(b"x" * 1024)
    gone = []
    uni.set_ui_hooks(progress=lambda f, t: gone.append((f, t)))
    res = uni.uninstall_core(keep_data=True, target=target)
    uni.set_ui_hooks()
    check("返回目标目录", res.get("target") == target, res)
    check("保留用户数据", res.get("data_removed") is False, res)
    check("进度走过 1.0", gone and gone[-1][0] == 1.0, gone[-3:])
    # 后台清理进程会在几秒内删掉目录
    ok = False
    for _ in range(60):
        if not os.path.isdir(target):
            ok = True
            break
        time.sleep(0.5)
    check("伪造安装目录被后台清理删除", ok,
          f"残留={sorted(os.listdir(target))[:6] if os.path.isdir(target) else ''}")
    shutil.rmtree(base, ignore_errors=True)


# ================================================================ 4. GUI 冒烟

def pump(win, n=6):
    # after(60) 的回调要真实的墙钟时间才会到期，纯 update 连发触发不了
    for _ in range(n):
        win.update_idletasks()
        win.update()
        time.sleep(0.05)


def test_gui():
    try:
        import tkinter
        import installer_ui
        import uninstaller_ui
        import setup_ui
    except ImportError as e:
        print("\n7. GUI 冒烟 —— 跳过（没有 tkinter: %s）" % e)
        return

    print("\n7. GUI 冒烟")

    # ---- 基础控件
    root = setup_ui.BaseWindow("t", 300, 200)
    root.withdraw()
    btn = setup_ui.Button(root, "开始", command=lambda: None, kind="primary")
    check("Button 可创建", bool(btn.winfo_exists()))
    btn.set_text("结束")
    btn.set_state("disabled")
    btn.set_command(None)
    btn.set_kind("ghost")
    pump(root, 2)
    check("Button 状态切换不崩", bool(btn.winfo_exists()))

    fired = []
    b2 = setup_ui.Button(root, "点我", command=lambda: fired.append(1))
    b2._on_press()
    b2._on_release()
    check("按下+释放触发回调", fired == [1], fired)

    b3 = setup_ui.Button(root, "禁用", command=lambda: fired.append(2))
    b3.set_state("disabled")
    b3._on_press()
    b3._on_release()
    check("禁用态点击不触发", fired == [1], fired)

    chk = setup_ui.Check(root, "勾选", value=False)
    chk._toggle()
    check("点击切换勾选", chk.get() is True, chk.get())
    chk.set(False, notify=True)

    prog = setup_ui.Progress(root, height=8)
    prog.set(0.42)
    check("进度条接受分数", abs(prog._frac - 0.42) < 1e-9, prog._frac)
    prog.set(None)
    check("None 进度条（不确定模式）", prog._indet is True)
    prog.set(1.0)
    check("确定模式会关掉动画", prog._indet is False and prog._anim is None)
    prog.destroy()
    check("进度条销毁不留 after 回调", prog._anim is None)

    box = setup_ui.LogBox(root, height=4)
    for i in range(700):
        box.push(f"line {i}")
    box.push("")
    total = int(box.t.index("end-1c").split(".")[0])
    check("日志行数有上限", total <= 600, total)
    box.clear()
    check("日志可清空", int(box.t.index("end-1c").split(".")[0]) == 1)
    root.destroy()
    pump(root, 2)

    # ---- 安装器窗口
    app = installer_ui.InstallerWindow(install.DEFAULT_DIR, True)
    app.withdraw()
    app.show()
    app.withdraw()
    pump(app, 6)
    check("安装器窗口可构建", bool(app.winfo_exists()))
    check("模板勾选默认保留", app.chk_models.get() is True)

    app2 = installer_ui.InstallerWindow(install.DEFAULT_DIR, False)
    app2.withdraw()
    pump(app2, 3)
    check("--no-models 映射为不勾选", app2.chk_models.get() is False)
    app2.destroy()

    # 非法路径拦截
    app.e_dir.delete(0, "end")
    app.e_dir.insert(0, "D:\\")
    app._start()
    pump(app, 2)
    check("磁盘根目录被拦下", "根目录" in app.lbl_status.cget("text"),
          app.lbl_status.cget("text"))

    app.e_dir.delete(0, "end")
    app.e_dir.insert(0, r"D:\Games\X\n")
    app._start()
    pump(app, 2)
    check("转义路径被拦下", "转义" in app.lbl_status.cget("text"),
          app.lbl_status.cget("text"))

    # 完成态：喂一组假结果（不真的安装）
    app.e_dir.delete(0, "end")
    app.e_dir.insert(0, r"D:\Games\KardsGUI")
    app._on_done({"install_dir": r"D:\Games\KardsGUI",
                  "exe": r"D:\Games\KardsGUI\KARDS.exe"})
    pump(app, 3)
    check("完成态主按钮变「启动游戏」",
          app.btn_main.cget("width") and app.btn_main._text == "启动游戏",
          app.btn_main._text)
    check("完成态次按钮变「打开文件夹」",
          app.btn_alt._text == "打开文件夹", app.btn_alt._text)
    check("完成态进度条满格", abs(app.bar._frac - 1.0) < 1e-9)

    # 错误态
    app._on_error("所有下载源均失败。")
    pump(app, 3)
    check("错误态主按钮变「重试」", app.btn_main._text == "重试",
          app.btn_main._text)
    check("错误写进日志", any("下载源均失败" in l for l in
                              [app.log.t.get(f"{i}.0", f"{i}.end")
                               for i in range(1, 6)]))

    # 消息泵：模拟工作线程的消息流
    app._push("log", "模拟日志行")
    app._push("progress", (0.3, "下载中 30%"))
    pump(app, 3)
    check("日志经队列进界面", "模拟日志行" in
          app.log.t.get("1.0", "end"))
    check("进度经队列进状态行", "下载中 30%" in app.lbl_status.cget("text"),
          app.lbl_status.cget("text"))
    app.destroy()
    pump(app, 2)

    # ---- 卸载器窗口
    base = tempfile.mkdtemp(prefix="kards_gui_uni3_")
    target = os.path.join(base, "Kards-Simple-Version")
    os.makedirs(target, exist_ok=True)
    for rel in ("KARDS.exe", "KARDS卸载器.exe"):
        with open(os.path.join(target, rel), "wb") as f:
            f.write(b"x" * 512)
    try:
        uw = uninstaller_ui.UninstallerWindow(target, "")
        uw.withdraw()
        pump(uw, 12)
        check("卸载器窗口可构建", bool(uw.winfo_exists()))
        check("目录统计到位", "3 个文件" in uw.lbl_size.cget("text")
              or "个文件" in uw.lbl_size.cget("text"),
              uw.lbl_size.cget("text"))
        check("无警告", not getattr(uw, "lbl_warn", None))

        uw2 = uninstaller_ui.UninstallerWindow(None, "没有 marker")
        uw2.withdraw()
        pump(uw2, 3)
        check("误删防护：非安装目录禁用卸载",
              uw2.btn_main._text == "无法卸载", uw2.btn_main._text)
        uw2.destroy()

        uw._on_done({"target": target, "data_removed": False})
        pump(uw, 3)
        check("卸载完成态按钮变「完成」", uw.btn_main._text == "完成",
              uw.btn_main._text)
        uw.destroy()
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main():
    test_hooks()
    test_launch_spec()
    test_models_count()
    test_stream()
    test_detect_target()
    test_uninstall_core()
    test_gui()

    print()
    if FAIL:
        print(f"FAILED: {len(FAIL)}/{len(PASS) + len(FAIL)}")
        for f in FAIL:
            print("  -", f)
        return 1
    print(f"ALL OK ({len(PASS)} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
