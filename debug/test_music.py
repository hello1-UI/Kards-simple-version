# -*- coding: utf-8 -*-
"""背景音乐（kards_music）回归测试

覆盖四块：
  1. 资源发现：assets/music 下的曲子能被找到，缺失时返回 None
  2. 播放控制：切歌 / 同一首不重头 / 未知场景不崩
  3. 偏好：音量与开关写进 settings.json 并能恢复（测试用临时配置文件，不污染真实设置）
  4. 降级：没有 pygame 的机器上所有接口静默失效（子进程验证）
外加一小段 GUI 验证：主菜单 ♪ 按钮、设置窗音乐区块、结算/回菜单切歌。

必须用系统 Python（受管 Python 无 tkinter）：
    py debug/test_music.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")   # 无声卡也能初始化混音器
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.argv.append("--no-fullscreen")
sys.argv.append("--no-update-check")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tkinter as tk                              # noqa: E402

import kards_i18n as i18n                         # noqa: E402
import kards_music as music                       # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


def wait(ms):
    """给淡出/淡入一点时间（pygame 混音器在后台线程推进）"""
    time.sleep(ms / 1000.0)


def main():
    # 偏好文件改到临时目录：绝不能把测试音量写进玩家真实的 settings.json
    tmpdir = tempfile.mkdtemp(prefix="kards_music_")
    tmp_settings = os.path.join(tmpdir, "settings.json")
    i18n._SETTINGS_PATH = tmp_settings
    music.reset_cache()

    print("== 1. 资源发现 ==")
    p = music.track_path("menu")
    check("assets/music/menu 能被找到", bool(p) and p.lower().endswith(".wav"), str(p))
    check("available() 为真（至少一首）", music.available())
    check("未知场景返回 None", music.track_path("no-such-track") is None)

    print("== 2. 播放控制 ==")
    ok = music.play("menu")
    check("播放主菜单曲成功", ok)
    check("当前曲目=menu", music.status()["track"] == "menu", str(music.status()))
    check("重复请求同一首不报错", music.play("menu") is True)
    check("重复请求后曲目仍是 menu", music.status()["track"] == "menu")
    ok = music.play("battle")
    check("切到对局曲成功", ok and music.status()["track"] == "battle", str(music.status()))
    ok = music.play("no-such-track")
    check("未知场景播放返回 False 而不抛异常", ok is False)
    check("未知场景不改动当前曲目", music.status()["track"] == "battle")

    print("== 3. 音量与开关（含落盘） ==")
    check("默认音量在合理区间", 0 <= music.get_volume() <= 100)
    check("音量上限截到 100", music.set_volume(150) == 100)
    check("音量下限截到 0", music.set_volume(-5) == 0)
    check("非法音量回落默认值", music.set_volume("abc") == music.DEFAULT_VOLUME)
    check("音量设为 40", music.set_volume(40) == 40)
    saved = {}
    try:
        with open(tmp_settings, encoding="utf-8") as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        pass
    check("settings.json 已写入 music_volume", saved.get("music_volume") == 40, str(saved))
    music.reset_cache()
    check("重载偏好后音量仍是 40", music.get_volume() == 40)

    check("默认开启音乐", music.is_enabled() is True)
    music.set_enabled(False)
    wait(450)                                     # 等淡出走完
    check("关闭后没有音频在播", music.status()["mixer"] is not True
          or _busy() is False)
    try:
        with open(tmp_settings, encoding="utf-8") as fh:
            saved = json.load(fh)
    except (OSError, ValueError):
        saved = {}
    check("settings.json 已写入 music_enabled=False", saved.get("music_enabled") is False, str(saved))
    check("关闭状态下 play() 返回 False", music.play("menu") is False)
    check("关闭时仍记住想放的曲目", music.status()["wanted"] == "menu", str(music.status()))
    on = music.set_enabled(True)
    check("重新开启后恢复播放", on is True and music.status()["track"] == "menu", str(music.status()))
    st = music.toggle()
    check("toggle 从开到关", st is False)
    st = music.toggle(resume_track="battle")
    check("toggle 从关到开并续放指定曲目",
          st is True and music.status()["track"] == "battle", str(music.status()))
    music.stop(fade_ms=0)
    check("stop 后当前曲目清空", music.status()["track"] is None)

    print("== 4. 没有 pygame 时的降级 ==")
    code = (
        "import sys; sys.modules['pygame'] = None\n"
        "sys.path.insert(0, %r)\n"
        "import kards_music as m\n"
        "r = m.play('menu')\n"
        "print('ok' if (r is False and m.status()['error'].startswith('no-pygame')) else 'bad')\n"
    ) % ROOT
    try:
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, timeout=60, encoding="utf-8", errors="replace")
        tail = (out.stdout or "").strip().splitlines()[-1:] or [""]
        check("缺 pygame：play 安全返回 False", tail[0] == "ok", (out.stdout or "") + (out.stderr or "")[-200:])
    except Exception as exc:                      # noqa: BLE001
        check("缺 pygame：play 安全返回 False", False, repr(exc))

    print("== 5. GUI 接入 ==")
    import KARDS as gui
    gui.account.stats_add = lambda *a, **k: None
    gui.account.currency_reward = lambda *a, **k: {"gold": 0, "diamonds": 0}
    app = gui.App()
    try:
        txt = app.music_btn.cget("text")
        check("主菜单有 ♪ 音乐按钮", "♪" in txt, txt)
        before = music.is_enabled()
        app._toggle_music()
        after = music.is_enabled()
        check("点击按钮翻转开关", before != after, f"{before}->{after}")
        check("按钮文字随状态变化", app.music_btn.cget("text") != txt)
        app._toggle_music()
        check("再点一次回到原状态", music.is_enabled() == before)

        app.open_start_settings()
        win = None
        for w in app.winfo_children():
            if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == "start_settings":
                win = w
        scales = _find(win, tk.Scale) if win else []
        check("设置窗内有音量滑块", bool(scales), str(win))
        if scales:
            check("滑块初值=当前音量", int(float(scales[0].get())) == music.get_volume())
        if win:
            win.destroy()

        # 结算 / 回菜单切歌：真棋盘 + 真引擎（与 test_finish 同款打法）
        import kards_engine as K
        db = K.card_database()
        p1 = K.Player("我", "德国", [db["步兵班"]] * K.DECK_SIZE)
        p2 = K.Player("敌", "苏联", [db["动员兵"]] * K.DECK_SIZE)
        g = K.Game(p1, p2, interactive=False)
        g.draw_cards(p1, 8)
        g.draw_cards(p2, 8)
        app.game = g
        board = app._activate_pyboard()
        if board is not None:
            board.sync()
        check("棋盘激活（供结算测试）", board is not None)
        music.play("battle")
        try:
            app.finish(winner=p1)
            ok = True
        except Exception as exc:                  # noqa: BLE001
            ok = False
            print("      异常:", repr(exc))
        check("finish() 不抛异常", ok)
        check("结算切到 result 曲", music.status()["track"] == "result", str(music.status()))
        app.game = None
        app.back_to_menu()
        check("回主菜单切回 menu 曲", music.status()["track"] == "menu", str(music.status()))
    finally:
        try:
            app.destroy()
        except Exception:                         # noqa: BLE001
            pass
        music.stop(fade_ms=0)

    print("\n===== %d PASS / %d FAIL =====" % (len(PASS), len(FAIL)))
    if FAIL:
        for n in FAIL:
            print("  FAILED:", n)
        return 1
    return 0


def _busy():
    try:
        import pygame
        return bool(pygame.mixer.music.get_busy())
    except Exception:                             # noqa: BLE001
        return False


def _find(widget, cls):
    """递归找某类控件（设置窗里的 tk.Scale）"""
    out = []
    if widget is None:
        return out
    try:
        kids = widget.winfo_children()
    except tk.TclError:
        return out
    for k in kids:
        if isinstance(k, cls):
            out.append(k)
        out.extend(_find(k, cls))
    return out


if __name__ == "__main__":
    sys.exit(main())
