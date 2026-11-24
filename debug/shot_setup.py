"""安装器 / 卸载器图形界面的截图 —— 人眼验收用。

自动化测试能证明「按钮点了会走流程」，但看不出「标题区和内容区比例是否
协调、按钮是不是挤在一起、进度条在深色底上够不够明显」。抓图看。

    21_installer.png        安装器初始态
    22_installer_done.png   安装完成态（按钮变成 启动游戏 / 打开文件夹 / 关闭）
    23_uninstaller.png      卸载器初始态
    24_uninstaller_done.png 卸载完成态

用法：python debug/shot_setup.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "apk"))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk

from PIL import ImageGrab

OUT = os.path.join(ROOT, "debug", "shots")


def _dpi_scale(win):
    """安装器调用了 SetProcessDpiAwareness(1)，tk 坐标已是物理像素 → scale=1；
    只有非感知进程才需要按系统缩放换算。"""
    try:
        import ctypes
        dpi = ctypes.windll.user32.GetDpiForSystem()
        if dpi != 96:            # 感知进程拿到的是真实 DPI
            return 1.0
        return ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100.0
    except Exception:                                      # noqa: BLE001
        return 1.0


def grab(win, name):
    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        HWND_TOPMOST = -1
        SWP_NOMOVE_NOSIZE = 0x0001 | 0x0002
        ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                          SWP_NOMOVE_NOSIZE)
    except Exception:                                      # noqa: BLE001
        pass
    win.lift()
    win.focus_force()
    for _ in range(10):
        win.update_idletasks()
        win.update()
    s = _dpi_scale(win)
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    img = ImageGrab.grab(bbox=(round(x * s), round(y * s),
                               round((x + w) * s), round((y + h) * s)))
    path = os.path.join(OUT, name + ".png")
    img.save(path)
    print("saved", path, img.size)
    return path


def shot_installer():
    import install
    import installer_ui

    app = installer_ui.InstallerWindow(install.DEFAULT_DIR, True)
    app.show()
    for _ in range(6):
        app.update()
    grab(app, "21_installer")

    # 完成态：喂一组假结果，只看按钮与状态行
    app._on_done({"install_dir": r"C:\Program Files\Kards-Simple-Version",
                  "exe": r"C:\Program Files\Kards-Simple-Version\KARDS.exe"})
    app.lbl_status.configure(text="安装完成  ·  桌面已创建快捷方式")
    for _ in range(6):
        app.update()
    grab(app, "22_installer_done")
    app.destroy()


def shot_uninstaller():
    import uninstaller_ui

    base = tempfile.mkdtemp(prefix="kards_shot_uni_")
    target = os.path.join(base, "Kards-Simple-Version")
    os.makedirs(os.path.join(target, "_internal"), exist_ok=True)
    for rel in ("KARDS.exe", "KARDS卸载器.exe", "_internal\\base_library.zip"):
        with open(os.path.join(target, *rel.split("\\")), "wb") as f:
            f.write(b"x" * 4096)
    try:
        app = uninstaller_ui.UninstallerWindow(target, "")
        app.show()
        for _ in range(10):
            app.update()
        app.after(300, lambda: None)
        for _ in range(10):
            app.update()
        grab(app, "23_uninstaller")
        app._on_done({"target": target, "data_removed": False})
        for _ in range(6):
            app.update()
        grab(app, "24_uninstaller_done")
        app.destroy()
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    shot_installer()
    shot_uninstaller()
    print("done")


if __name__ == "__main__":
    main()
