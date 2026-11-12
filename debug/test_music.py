# -*- coding: utf-8 -*-
"""背景音乐（kards_music）回归测试 —— 曲库 + 自选

覆盖：
  1. 曲库扫描：目录里的 .ogg/.wav/.mp3/.flac 被收进来，玩家目录同名覆盖随包、
     .m4a 之类认得出但放不了的格式被单独提示
  2. 场景解析：默认 → 玩家选曲 → 随机 → 静音 → 选曲被删后的回落
  3. 播放控制：切场景 / 同一场景不重头 / 试听不占场景位
  4. 偏好：选曲 / 音量 / 开关写进 settings.json（测试用临时配置，不污染真实设置）
  5. 降级：没有 pygame 的机器上所有接口静默失效（子进程验证）
  6. GUI：设置窗三行曲目 + 选择器 + 主菜单 ♪ 按钮 + 结算/回菜单切歌

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


def read_settings(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def main():
    # 偏好文件改到临时目录：绝不能把测试音量/选曲写进玩家真实的 settings.json
    tmpdir = tempfile.mkdtemp(prefix="kards_music_")
    tmp_settings = os.path.join(tmpdir, "settings.json")
    i18n._SETTINGS_PATH = tmp_settings
    music.reset_cache()

    real_user_dir = music.user_music_dir()
    user_dir = os.path.join(tmpdir, "music")
    os.makedirs(user_dir, exist_ok=True)
    music.user_music_dir = lambda create=False: user_dir
    music.refresh()

    print("== 1. 曲库扫描 ==")
    lib = music.library()
    names = [e["name"] for e in lib]
    check("扫到随包曲库（≥9 首）", len(lib) >= 9, str(names))
    check("全部是 pygame 能播的格式",
          all(e["ext"] in music.SUPPORTED_EXTS for e in lib),
          str({e["ext"] for e in lib}))
    check("曲库按名字排序", names == sorted(names, key=str.lower), str(names))
    check("available() 为真", music.available() is True)
    check("find() 大小写不敏感", bool(music.find("gp demo")) and bool(music.find("GP Demo")))
    check("find() 找不到返回 None", music.find("no-such-track") is None)
    check("track_path 返回真实文件",
          os.path.isfile(music.track_path("GP Demo") or ""), str(music.track_path("GP Demo")))

    # 玩家目录：丢一首进去应立刻被扫到（不用重启），且同名可覆盖随包曲
    with open(os.path.join(user_dir, "我的战歌.ogg"), "wb") as fh:
        fh.write(b"OggS" + b"\0" * 32)
    with open(os.path.join(user_dir, "GP Demo.ogg"), "wb") as fh:
        fh.write(b"OggS" + b"\0" * 32)
    music.refresh()
    lib = music.library()
    hit = music.find("我的战歌")
    check("玩家目录的新曲子被扫到", hit is not None)
    check("玩家目录标记为自选", bool(hit and hit["user"]), str(hit))
    gp = music.find("GP Demo")
    check("同名时玩家目录覆盖随包曲",
          bool(gp and os.path.dirname(gp["path"]) == os.path.abspath(user_dir)), str(gp))
    check("覆盖后曲库不出现重复曲名",
          len([e for e in lib if e["name"] == "GP Demo"]) == 1)

    # 认得出但放不了的格式：单独提示，不进曲库
    with open(os.path.join(user_dir, "手机录的.m4a"), "wb") as fh:
        fh.write(b"\0\0\0\x18ftypM4A " + b"\0" * 16)
    music.refresh()
    check("m4a 不进曲库", music.find("手机录的") is None)
    check("m4a 出现在格式提示里", "手机录的.m4a" in music.scan_problems(),
          str(music.scan_problems()))
    os.remove(os.path.join(user_dir, "手机录的.m4a"))
    os.remove(os.path.join(user_dir, "GP Demo.ogg"))
    os.remove(os.path.join(user_dir, "我的战歌.ogg"))
    music.refresh()

    print("== 2. 场景解析（默认 / 选曲 / 随机 / 静音） ==")
    for scene in music.SCENES:
        check("%s 默认可解析出曲目" % scene, bool(music.scene_track(scene)),
              str(music.scene_track(scene)))
    check("menu 默认曲取 DEFAULT_PICK", music.scene_track("menu") == music.DEFAULT_PICK["menu"],
          str(music.scene_track("menu")))

    music.set_scene_choice("battle", "TSax Demo")
    check("选曲生效", music.scene_track("battle") == "TSax Demo")
    saved = read_settings(tmp_settings)
    check("选曲写进 settings.json（music_battle）", saved.get("music_battle") == "TSax Demo",
          str(saved))
    music.reset_cache()          # 模拟重开游戏
    check("重开游戏后选曲仍在", music.scene_track("battle") == "TSax Demo")

    music.set_scene_choice("battle", "已经被删掉的曲子.ogg")
    check("选曲被删 → 回落默认", music.scene_track("battle") == music.DEFAULT_PICK["battle"],
          str(music.scene_track("battle")))

    music.set_scene_choice("battle", music.PICK_NONE)
    check("选「不放音乐」→ 该场景无曲", music.scene_track("battle") is None)

    music.set_scene_choice("battle", music.PICK_RANDOM)
    first = music.scene_track("battle")
    check("随机模式落在曲库内", first in music.library_names(), str(first))
    same = {music.scene_track("battle") for _ in range(12)}
    check("随机在同一场景内固定（界面显示与播放一致，不跳歌）",
          same == {first}, str(same))
    seen = set()
    for _ in range(20):
        music._random_for("battle", new=True)
        seen.add(music._state["picks"]["battle"])
    check("点了重播 / 换场景才会重抽", len(seen) > 1, str(seen))
    avoid = music._pick_random("GP Demo")
    check("随机尽量避开正在放的那首", avoid != "GP Demo", avoid)

    music.set_scene_choice("battle", "")
    check("选「默认」→ 回到默认曲", music.scene_track("battle") == music.DEFAULT_PICK["battle"])

    print("== 2b. 重载（同名替换 / 播放失败可诊断） ==")
    sig1 = music._dirs_sig(music._music_dirs())
    victim = os.path.join(user_dir, "GP Demo.ogg")
    with open(victim, "wb") as fh:              # 同名替换内容（目录 mtime 不变）
        fh.write(b"OggS" + b"\2" * 400)
    sig2 = music._dirs_sig(music._music_dirs())
    check("同名替换（只改内容）也能被曲库签名识别", sig1 != sig2)
    music.refresh()
    check("重扫后同名曲子仍在库里", music.find("GP Demo") is not None)
    os.remove(victim)
    music.refresh()
    check("删掉自选同名曲后回落到随包那一首",
          bool(music.find("GP Demo")) and not music.find("GP Demo")["user"],
          str(music.find("GP Demo")))

    bad = os.path.join(user_dir, "坏文件.ogg")
    with open(bad, "wb") as fh:                 # 假 ogg：pygame 解不了
        fh.write(b"not really an ogg" * 8)
    music.refresh()
    music.set_scene_choice("result", "坏文件")
    okb = music.play("result", force=True)
    check("坏文件播放返回 False 而不崩", okb is False)
    check("坏文件被记进 last_error（设置窗可提示）",
          music.last_error() == "坏文件.ogg", repr(music.last_error()))
    os.remove(bad)
    music.refresh()
    music.set_scene_choice("result", "")
    music.play("menu", force=True)

    print("== 3. 播放控制 ==")
    ok = music.play("menu")
    check("播放主菜单曲成功", ok and music.status()["scene"] == "menu", str(music.status()))
    check("status 报告当前曲名", music.status()["name"] == music.scene_track("menu"),
          str(music.status()))
    check("重复请求同一场景不报错", music.play("menu") is True)
    check("重复请求后仍是 menu", music.status()["scene"] == "menu")
    ok = music.play("battle")
    check("切到对局曲成功", ok and music.status()["scene"] == "battle", str(music.status()))
    check("未知场景播放返回 False 而不抛异常", music.play("no-such-scene") is False)
    check("未知场景不改动当前场景", music.status()["scene"] == "battle")

    music.set_scene_choice("battle", "JzOr Demo")
    check("当前场景换曲立即生效",
          music.status()["name"] == "JzOr Demo", str(music.status()))
    music.set_scene_choice("battle", music.PICK_NONE)
    wait(350)
    check("当前场景选「不放音乐」立即停", music.status()["scene"] is None, str(music.status()))
    music.set_scene_choice("battle", "")

    previewed = music.preview("EPno Demo")
    check("试听返回成功", previewed)
    st = music.status()
    check("试听状态被记录", st["preview"] is True and st["name"] == "EPno Demo", str(st))
    check("试听不占场景位（结束能接回场景曲）",
          st["scene"] is None and music.end_preview("menu") is True)
    check("试听结束后接回场景曲",
          music.status()["scene"] == "menu", str(music.status()))

    print("== 3b. 混音器被外部关掉后自愈 ==")
    import pygame as _pg
    music.play("menu", force=True)
    _pg.mixer.quit()
    healed = music.play("battle", force=True)
    check("混音器被别处 quit 后仍能重载播放", healed is True, str(music.status()))
    check("自愈后曲目正确", music.status()["scene"] == "battle", str(music.status()))

    print("== 4. 音量与开关（含落盘） ==")
    check("默认音量在合理区间", 0 <= music.get_volume() <= 100)
    check("音量上限截到 100", music.set_volume(150) == 100)
    check("音量下限截到 0", music.set_volume(-5) == 0)
    check("非法音量回落默认值", music.set_volume("abc") == music.DEFAULT_VOLUME)
    check("音量设为 40", music.set_volume(40) == 40)
    check("settings.json 已写入 music_volume",
          read_settings(tmp_settings).get("music_volume") == 40)
    music.reset_cache()
    check("重载偏好后音量仍是 40", music.get_volume() == 40)

    check("默认开启音乐", music.is_enabled() is True)
    music.set_enabled(False)
    wait(450)                                     # 等淡出走完
    check("关闭后没有音频在播", music.status()["busy"] is False)
    check("settings.json 已写入 music_enabled=False",
          read_settings(tmp_settings).get("music_enabled") is False)
    check("关闭状态下 play() 返回 False", music.play("menu") is False)
    check("关闭时仍记住想放的场景", music.status()["wanted"] == "menu", str(music.status()))
    on = music.set_enabled(True)
    check("重新开启后恢复播放", on is True and music.status()["scene"] == "menu",
          str(music.status()))
    check("toggle 从开到关", music.toggle() is False)
    st = music.toggle(resume_track="battle")
    check("toggle 从关到开并续放指定场景",
          st is True and music.status()["scene"] == "battle", str(music.status()))
    music.stop(fade_ms=0)
    check("stop 后当前场景清空", music.status()["scene"] is None)

    print("== 5. 没有 pygame 时的降级 ==")
    code = (
        "import sys; sys.modules['pygame'] = None\n"
        "sys.path.insert(0, %r)\n"
        "import kards_music as m\n"
        "r = m.play('menu')\n"
        "p = m.preview('GP Demo')\n"
        "print('ok' if (r is False and p is False and m.status()['error'].startswith('no-pygame')) else 'bad')\n"
    ) % ROOT
    try:
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, timeout=60, encoding="utf-8", errors="replace")
        tail = (out.stdout or "").strip().splitlines()[-1:] or [""]
        check("缺 pygame：play/preview 安全返回 False", tail[0] == "ok",
              (out.stdout or "") + (out.stderr or "")[-200:])
    except Exception as exc:                      # noqa: BLE001
        check("缺 pygame：play/preview 安全返回 False", False, repr(exc))

    print("== 6. GUI 接入 ==")
    import KARDS as gui
    gui.account.stats_add = lambda *a, **k: None
    gui.account.currency_reward = lambda *a, **k: {"gold": 0, "diamonds": 0}
    app = gui.App()
    try:
        txt = app.music_btn.cget("text")
        check("主菜单有 ♪ 音乐按钮", "♪" in txt, txt)
        before = music.is_enabled()
        app._toggle_music()
        check("点击按钮翻转开关", before != music.is_enabled())
        check("按钮文字随状态变化", app.music_btn.cget("text") != txt)
        app._toggle_music()
        check("再点一次回到原状态", music.is_enabled() == before)

        app.open_start_settings()
        win = None
        for w in app.winfo_children():
            if isinstance(w, tk.Toplevel) and getattr(w, "role", "") == "start_settings":
                win = w
        check("设置窗已打开", win is not None)
        scales = _find(win, tk.Scale) if win else []
        check("设置窗内有音量滑块", bool(scales), str(win))
        if scales:
            check("滑块初值=当前音量", int(float(scales[0].get())) == music.get_volume())

        scene_btns = getattr(app, "_music_scene_btns", {})
        check("设置窗有三行场景曲目",
              all(s in scene_btns for s in music.SCENES), str(list(scene_btns)))
        check("曲目按钮显示当前曲名",
              scene_btns["menu"].cget("text") == music.scene_track("menu"),
              str(scene_btns["menu"].cget("text")))

        # 选择器：条目 = 默认/随机/静音 + 整库
        dlg = app._music_pick_dialog("menu")
        lb = _find(dlg, tk.Listbox)[0]
        check("选择器列出 默认/随机/静音 + 全部曲目",
              lb.size() == 3 + len(music.library()), "%d vs %d" % (lb.size(), 3 + len(music.library())))
        labels = [lb.get(i) for i in range(lb.size())]
        check("选择器前三项是 默认/随机/不放音乐",
              i18n.t("music_opt_default") in labels[0]
              and i18n.t("music_opt_random") in labels[1]
              and i18n.t("music_opt_none") in labels[2], str(labels[:3]))

        # 选中第 4 项（曲库第一首）+ 点「使用」
        target = music.library()[0]["name"]
        lb.selection_clear(0, "end")
        lb.selection_set(3)
        apply_btn = [b for b in _find(dlg, tk.Button) if b.cget("text") == i18n.t("music_apply")][0]
        apply_btn.invoke()
        check("选择后写进偏好", music.scene_choice("menu") == target,
              "%s vs %s" % (music.scene_choice("menu"), target))
        check("选择后按钮文案跟着变",
              app._music_scene_btns["menu"].cget("text") == target,
              str(app._music_scene_btns["menu"].cget("text")))
        check("选择器已关闭", not dlg.winfo_exists())
        music.set_scene_choice("menu", "")
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
        check("结算切到 result 曲", music.status()["scene"] == "result", str(music.status()))
        app.game = None
        app.back_to_menu()
        check("回主菜单切回 menu 曲", music.status()["scene"] == "menu", str(music.status()))
    finally:
        try:
            app.destroy()
        except Exception:                         # noqa: BLE001
            pass
        music.stop(fade_ms=0)
        music.user_music_dir = lambda create=False: real_user_dir

    print("\n===== %d PASS / %d FAIL =====" % (len(PASS), len(FAIL)))
    if FAIL:
        for n in FAIL:
            print("  FAILED:", n)
        return 1
    return 0


def _find(widget, cls):
    """递归找某类控件（设置窗里的 tk.Scale / 选择器里的 Listbox）"""
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
