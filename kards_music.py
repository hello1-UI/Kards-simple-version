# -*- coding: utf-8 -*-
"""KARDS 简化版 —— 背景音乐（BGM）管理 + 自选曲库

设计取向（和 kards_board.sfx 的"音效钩子"一脉相承）：
- **没有资源也要能跑**。音乐目录里一个文件都没有时，所有接口静默失效，
  游戏照常运行（玩家只是听不到声音），绝不因为缺音乐崩掉或弹窗。
- **曲库 + 分场景自选**。扫描音乐目录里的所有音频文件组成曲库，玩家在设置里
  给 主菜单 / 对战 / 结算 三个场景各挑一首（也可以选「随机」或「静音」），
  选择写进 settings.json，下次启动原样恢复。
- **单通道 + 场景切换**。pygame.mixer.music 只有一个播放位，所以按场景切歌；
  同一首正在放就不重头开始，避免每次刷界面都把音乐掐回开头。
- 场景没选曲子 / 选的曲子被删了 → 按 默认曲 → 同名文件 → 曲库第一首 依次兜底，
  总比突然静音自然。

对外接口：
    play(scene) / stop() / pause() / resume() / preview(name) / end_preview()
    set_enabled / is_enabled / toggle / set_volume / get_volume
    library() / library_names() / find(name) / refresh() / user_music_dir()
    scene_choice(scene) / scene_track(scene) / set_scene_choice(scene, choice)
    status() / track_path(name) / available() / scan_problems()

玩家换曲子：把 .ogg / .wav / .mp3 / .flac 丢进音乐目录（源码版是 assets/music/，
安装版是 %USERPROFILE%\\AppData\\Kards-Simple-Version\\music\\），游戏会自己扫到，
然后在 设置 → 背景音乐 → 曲目「选择」里挑。**不用重新打包**。

⚠ .m4a / .aac / .wma 这些 pygame 解不了（SDL_mixer 不带 AAC 解码），
用 debug/convert_music.py（依赖 imageio-ffmpeg）转成 .ogg 即可。
"""
import os
import random
import sys

# 场景（顺序即设置界面的显示顺序）
SCENES = ("menu", "battle", "result")

# pygame/SDL_mixer 能直接解码的扩展名
SUPPORTED_EXTS = (".ogg", ".wav", ".mp3", ".flac")

# 认得出、但放不了的格式：扫描到就在设置里提示转换，免得玩家以为功能坏了
UNSUPPORTED_EXTS = (".m4a", ".aac", ".wma", ".opus", ".aiff", ".mid", ".midi")

# 场景选曲的三个特殊值
PICK_NONE = "__none__"        # 该场景不放音乐
PICK_RANDOM = "__random__"    # 每次进场景随机挑一首（尽量不连着重复）

# 场景选「默认」时优先用的曲子（随包附带的曲库）；找不到就退到同名文件/第一首
DEFAULT_PICK = {"menu": "GP Demo", "battle": "DnKt Demo", "result": "MHrp Demo"}

# 极端兜底：某场景彻底没曲子时借别的场景的（避免"进对局突然没声"）
FALLBACK = {"battle": "menu", "result": "menu"}

_PREF_VOLUME = "music_volume"
_PREF_ENABLED = "music_enabled"
_PREF_SCENE = {"menu": "music_menu", "battle": "music_battle", "result": "music_result"}
DEFAULT_VOLUME = 55

# 运行期状态（模块级单例，整个进程共用一套音乐）
_state = {
    "ready": None,      # None=还没试过 / True=音频子系统可用 / False=不可用
    "error": "",        # 不可用原因，方便状态栏与日志展示
    "scene": None,      # 当前**真正在放**的场景名
    "name": None,       # 当前在放的曲子名（随机模式下每次都可能不同）
    "wanted": None,     # 最后一次请求的场景名（静音时也记，恢复时接着放）
    "preview": False,   # 正在试听（试听不循环，且不占场景位）
    "volume": None,     # 懒加载的缓存，None 表示还没从 settings.json 读
    "enabled": None,
    "choices": None,    # 场景选曲缓存 {scene: choice}
    "lib": None,        # 曲库缓存
    "lib_sig": None,    # 曲库缓存对应的文件签名（任何音频文件变了就重扫）
    "picks": {},        # 随机模式下每个场景当前抽中的曲子（不重复抽，界面/播放一致）
    "play_error": "",   # 最近一次加载失败的曲子（设置界面据此提示）
}


# ---------------------------------------------------------------- 目录与扫描

def _pref_module():
    import kards_i18n
    return kards_i18n


def _asset_roots():
    """随包资源根目录，优先级与 kards_board.asset_roots 保持一致。"""
    roots = []
    if getattr(sys, "frozen", False):
        try:
            roots.append(os.path.join(
                os.path.dirname(os.path.abspath(sys.executable)), "assets"))
        except Exception:                                  # noqa: BLE001
            pass
    here = os.path.dirname(os.path.abspath(__file__))
    roots.append(os.path.join(here, "assets"))
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        p = os.path.join(mei, "assets")
        if p not in roots:
            roots.append(p)
    return roots


def user_music_dir(create=False):
    """玩家自己的音乐目录（放进去的曲子在设置里可选，无需重新打包）。

    - 安装版：%USERPROFILE%\\AppData\\Kards-Simple-Version\\music（和 settings.json 同级）
    - 源码版：就是 assets/music/，改完立刻能在游戏里看到
    """
    d = None
    try:
        if getattr(sys, "frozen", False):
            d = os.path.join(os.path.dirname(_pref_module()._SETTINGS_PATH), "music")
        else:
            d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "music")
    except Exception:                                      # noqa: BLE001
        d = None
    if not d:
        d = os.path.join(os.path.expanduser("~"), "AppData",
                         "Kards-Simple-Version", "music")
    if create:
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
    return d


def _music_dirs():
    """扫描顺序：玩家目录优先（同名覆盖随包曲目），再是随包 assets/music。"""
    dirs = [user_music_dir()]
    for root in _asset_roots():
        dirs.append(os.path.join(root, "music"))
    out = []
    for d in dirs:
        try:
            real = os.path.abspath(d)
        except OSError:
            continue
        if real not in out and os.path.isdir(real):
            out.append(real)
    return out


def _dirs_sig(dirs):
    """曲库缓存签名：目录 + 每个文件的 (名字, mtime, 大小)。

    只看目录 mtime 是不够的 —— 同名覆盖（换掉文件内容）、原地改写都不会
    改目录 mtime，签名得细到文件才认得出"曲子被换了"。
    """
    sig = []
    for d in dirs:
        items = []
        try:
            names = sorted(os.listdir(d))
        except OSError:
            names = []
        for fn in names:
            try:
                st = os.stat(os.path.join(d, fn))
            except OSError:
                continue
            items.append((fn, int(st.st_mtime), st.st_size))
        sig.append((d, tuple(items)))
    return tuple(sig)


def _scan(dirs):
    """把一个目录里的音频文件收成曲库条目列表（不递归，音乐目录本就该是平的）。"""
    entries = []
    seen = set()
    user = os.path.abspath(user_music_dir())
    for d in dirs:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for fn in names:
            stem, ext = os.path.splitext(fn)
            if ext.lower() not in SUPPORTED_EXTS:
                continue
            key = stem.lower()
            if key in seen:                    # 玩家目录优先，同名随包曲子被盖掉
                continue
            path = os.path.join(d, fn)
            if not os.path.isfile(path):
                continue
            try:
                size = os.path.getsize(path) / 1048576.0
            except OSError:
                size = 0.0
            seen.add(key)
            entries.append({"name": stem, "path": path, "ext": ext.lower(),
                            "mb": round(size, 1), "user": os.path.abspath(d) == user})
    entries.sort(key=lambda e: e["name"].lower())
    return entries


def library():
    """当前曲库（按名字排序）。目录 mtime 变了会自动重扫，玩家丢新歌不用重启。"""
    dirs = _music_dirs()
    sig = _dirs_sig(dirs)
    if _state["lib"] is not None and _state["lib_sig"] == sig:
        return list(_state["lib"])
    lib = _scan(dirs)
    _state["lib"] = lib
    _state["lib_sig"] = sig
    return list(lib)


def library_names():
    return [e["name"] for e in library()]


def refresh():
    """强制重扫曲库（玩家在设置里点「刷新」或在文件夹里刚丢过歌时用）。"""
    _state["lib"] = None
    _state["lib_sig"] = None
    return library()


def find(name):
    """按曲名（不含扩展名，大小写不敏感）在曲库里找条目，找不到返回 None。"""
    if not name:
        return None
    low = str(name).lower()
    for e in library():
        if e["name"].lower() == low:
            return e
    return None


def track_path(name):
    """返回该曲子的绝对路径；曲库里没有就返回 None。"""
    e = find(name)
    return e["path"] if e else None


def scan_problems():
    """列出目录里认得出但放不了的音频文件（如 .m4a），设置界面据此提示转换。"""
    bad = []
    for d in _music_dirs():
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for fn in names:
            ext = os.path.splitext(fn)[1].lower()
            if ext in UNSUPPORTED_EXTS:
                bad.append(fn)
    return bad


def available():
    """曲库里有至少一首可放的曲子 —— 设置界面据此提示"未找到音乐文件"。"""
    return bool(library())


# ---------------------------------------------------------------- 混音器

def _ensure_mixer():
    """按需初始化 pygame 混音器。返回是否可用。

    ⚠ 用 pygame.mixer.get_init() 判断而不是自己的标志：棋盘音效
    （kards_board.sfx）也会初始化混音器，两边共用同一个实例，重复 init 会
    重置正在播放的音乐。
    """
    if _state["ready"] is not None:
        return _state["ready"]
    try:
        import pygame
    except Exception as exc:                               # noqa: BLE001
        _state["ready"] = False
        _state["error"] = "no-pygame: %s" % exc
        return False
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
        _state["ready"] = True
    except Exception as exc:                               # noqa: BLE001
        _state["ready"] = False
        _state["error"] = "no-mixer: %s" % exc
    return _state["ready"]


# ---------------------------------------------------------------- 偏好读写

def get_volume():
    """音量 0-100（整数）。读不到配置就用默认值。"""
    if _state["volume"] is None:
        try:
            v = int(_pref_module().get_pref(_PREF_VOLUME, DEFAULT_VOLUME))
        except (TypeError, ValueError):
            v = DEFAULT_VOLUME
        _state["volume"] = max(0, min(100, v))
    return _state["volume"]


def is_enabled():
    """音乐开关。settings.json 里可能被手改成 "0"/"false"，统一按真假解析。"""
    if _state["enabled"] is None:
        raw = _pref_module().get_pref(_PREF_ENABLED, True)
        if isinstance(raw, str):
            _state["enabled"] = raw.strip().lower() not in ("0", "false", "off", "no", "")
        else:
            _state["enabled"] = bool(raw)
    return _state["enabled"]


def _apply_volume():
    if not _ensure_mixer():
        return
    import pygame
    try:
        pygame.mixer.music.set_volume(get_volume() / 100.0 if is_enabled() else 0.0)
    except Exception:                                      # noqa: BLE001
        pass


def set_volume(v):
    """设置音量（0-100），立即生效并落盘。返回实际生效的值。"""
    try:
        v = int(v)
    except (TypeError, ValueError):
        v = DEFAULT_VOLUME
    v = max(0, min(100, v))
    _state["volume"] = v
    try:
        _pref_module().set_pref(_PREF_VOLUME, v)
    except Exception:                                      # noqa: BLE001
        pass
    _apply_volume()
    return v


def _choices():
    if _state["choices"] is None:
        ch = {}
        for scene in SCENES:
            try:
                raw = _pref_module().get_pref(_PREF_SCENE[scene], "")
            except Exception:                              # noqa: BLE001
                raw = ""
            ch[scene] = "" if raw is None else str(raw)
        _state["choices"] = ch
    return _state["choices"]


def scene_choice(scene):
    """该场景的原始选择：曲名 / PICK_RANDOM / PICK_NONE / ""（=默认）。"""
    return _choices().get(scene, "")


def _pick_random(avoid=None):
    lib = library()
    if not lib:
        return None
    if len(lib) > 1 and avoid:
        pool = [e for e in lib if e["name"] != avoid]
        if pool:
            lib = pool
    return random.choice(lib)["name"]


def _random_for(scene, new=False):
    """随机模式：**同一场景内固定一首**，只有换场景 / 点了「使用」才重抽。

    以前每次调用都重抽，导致设置界面显示的歌名和实际在放的不是同一首，
    每次刷界面还会跳 —— 看上去就像"选曲没生效 / 音乐没重载"。
    """
    picks = _state["picks"]
    name = None if new else picks.get(scene)
    if name and find(name):
        return name
    name = _pick_random(_state["name"] if _state["scene"] == scene else None)
    if name:
        picks[scene] = name
    return name


def scene_track(scene):
    """解析该场景最终要放哪首曲子（曲名）；没有可放的返回 None。

    优先级：玩家选的曲子 → 默认曲 → 与该场景同名的文件 → 曲库第一首 → 借用别场景
    """
    if scene not in SCENES:            # 未知场景一律不播（别拿曲库第一首糊弄调用方）
        return None
    choice = scene_choice(scene)
    if choice == PICK_NONE:
        return None
    if choice == PICK_RANDOM:
        return _random_for(scene)
    if choice:
        hit = find(choice)
        if hit:
            return hit["name"]
        # 选的曲子被玩家删了：不明说也知道，静默回落到默认
    for cand in (DEFAULT_PICK.get(scene), scene):
        hit = find(cand) if cand else None
        if hit:
            return hit["name"]
    lib = library()
    if lib:
        return lib[0]["name"]
    alt = FALLBACK.get(scene)
    if alt and alt != scene:
        return scene_track(alt)
    return None


def set_scene_choice(scene, choice):
    """给某场景指定曲子（曲名 / PICK_RANDOM / PICK_NONE / ""=默认）并落盘。

    如果这个场景正在播放，立刻切过去——点完就能听见换没换。
    """
    if scene not in SCENES:
        return False
    choice = "" if choice is None else str(choice)
    _choices()[scene] = choice
    try:
        _pref_module().set_pref(_PREF_SCENE[scene], choice)
    except Exception:                                      # noqa: BLE001
        pass
    # 这个场景就是玩家眼前的场景（正在放、或最近请求过）→ 立刻换过去，
    # 点完就能听见换没换。用 wanted 兜底：音乐被关过 / 上次播放失败时
    # scene 是 None，但它仍然是"当前界面该放的那首"。
    target = _state["scene"] or _state["wanted"]
    if target == scene and not _state["preview"]:
        if scene_track(scene) is None:
            # 选成「静音」/曲子被删：正在放的这首也要停下来，否则点了没反应
            stop(fade_ms=300)
        else:
            play(scene, fade_ms=350, force=True)
    return True


# ---------------------------------------------------------------- 播放控制

def _play_file(path, fade_ms, loops=-1):
    """加载并播放。失败时**自愈一次**：混音器若被别处 quit 掉，重新初始化再试。"""
    import pygame
    _state["play_error"] = ""
    for attempt in (0, 1):
        try:
            if not pygame.mixer.get_init():
                raise RuntimeError("mixer not initialized")
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(get_volume() / 100.0)
            # loops=-1 无限循环；fade_ms 让进场景时不是"啪"一下起来
            pygame.mixer.music.play(loops, fade_ms=max(0, int(fade_ms)))
            _state["ready"] = True
            return True
        except Exception as exc:                           # noqa: BLE001
            if attempt == 0:
                # 混音器被别的模块（或一次异常退出）关掉了：重开再试一次，
                # 否则后面所有曲子都会静默失败 —— 表现就是"音乐不会重载"。
                try:
                    if not pygame.mixer.get_init():
                        pygame.mixer.init(frequency=44100, size=-16,
                                          channels=2, buffer=1024)
                    _state["ready"] = True
                    continue
                except Exception:                          # noqa: BLE001
                    pass
            _state["error"] = "play-failed: %s" % exc
            _state["play_error"] = os.path.basename(path)
            return False
    return False


def play(scene, fade_ms=700, force=False):
    """切到某个场景的音乐（循环播放）。返回是否真的放起来了。

    - 同一场景正在放：什么都不做（避免刷界面把音乐拽回开头）
    - 音乐被关掉：只记下"想要哪个场景"，重新打开时接着放
    - 该场景没选曲子：按 默认曲 → 同名文件 → 曲库第一首 兜底，实在没有就停
    """
    if scene not in SCENES:
        return False
    _state["wanted"] = scene
    if not is_enabled():
        return False
    if not _ensure_mixer():
        return False
    if scene_choice(scene) == PICK_RANDOM and (force or _state["scene"] != scene):
        _random_for(scene, new=True)      # 换场景 / 手动重播才换一首
    name = scene_track(scene)
    path = track_path(name)
    if path is None:
        return False
    if not force and not _state["preview"] and _state["scene"] == scene and _music_busy():
        return True
    if force:
        # 强制重载（用户点了「使用」/ 同一个文件被替换过）：先彻底停掉再打开，
        # 否则某些平台会继续用已经打开的文件句柄，听不出新内容
        try:
            import pygame
            pygame.mixer.music.stop()
        except Exception:                                  # noqa: BLE001
            pass
    elif _music_busy() and not _state["preview"]:
        # 硬切之前先淡出：老的曲子往下走，新的淡入接上来，听感上像交叉淡化
        try:
            import pygame
            pygame.mixer.music.fadeout(180)
        except Exception:                                  # noqa: BLE001
            pass
    ok = _play_file(path, fade_ms)
    _state["preview"] = False
    _state["scene"] = scene if ok else None
    _state["name"] = name if ok else None
    return ok


def preview(name, fade_ms=0):
    """试听某首曲子（只放一遍，不循环）。用于设置里的「试听」按钮。"""
    if not _ensure_mixer():
        return False
    path = track_path(name)
    if path is None:
        return False
    if _music_busy():
        try:
            import pygame
            pygame.mixer.music.fadeout(120)
        except Exception:                                  # noqa: BLE001
            pass
    ok = _play_file(path, fade_ms, loops=0)
    if ok:
        _state["preview"] = True
        _state["scene"] = None          # 关掉试听后重新进场景一定会重放
        _state["name"] = str(name)
    return ok


def end_preview(scene=None):
    """结束试听：静音并（可选）把场景音乐接回来。"""
    if not _state["preview"]:
        return False
    _state["preview"] = False
    _state["scene"] = None
    _state["name"] = None
    stop(fade_ms=0)
    if scene:
        play(scene, fade_ms=250, force=True)
    return True


def _music_busy():
    if not _state["ready"]:
        return False
    try:
        import pygame
        return bool(pygame.mixer.music.get_busy())
    except Exception:                                      # noqa: BLE001
        return False


def stop(fade_ms=400):
    """停止播放（淡出）。不改变开关偏好。"""
    _state["scene"] = None
    _state["name"] = None
    _state["preview"] = False
    if not _state["ready"]:
        return
    import pygame
    try:
        if fade_ms > 0:
            pygame.mixer.music.fadeout(int(fade_ms))
        else:
            pygame.mixer.music.stop()
    except Exception:                                      # noqa: BLE001
        pass


def pause():
    if not _state["ready"]:
        return
    import pygame
    try:
        pygame.mixer.music.pause()
    except Exception:                                      # noqa: BLE001
        pass


def resume():
    if not _state["ready"] or not is_enabled():
        return
    import pygame
    try:
        pygame.mixer.music.unpause()
    except Exception:                                      # noqa: BLE001
        pass


def set_enabled(flag, resume_track=None, fade_ms=600):
    """开关音乐。关闭=淡出并记住想放的曲子；打开=接着放那首（默认主菜单）。"""
    flag = bool(flag)
    _state["enabled"] = flag
    try:
        _pref_module().set_pref(_PREF_ENABLED, flag)
    except Exception:                                      # noqa: BLE001
        pass
    if flag:
        track = resume_track or _state["wanted"] or "menu"
        play(track, fade_ms=fade_ms)
    else:
        stop(fade_ms=300)
    return flag


def toggle(resume_track=None):
    """切换开关，返回切换后的状态（True=开）。"""
    return set_enabled(not is_enabled(), resume_track=resume_track)


# ---------------------------------------------------------------- 状态查询

def status():
    """给设置界面 / 诊断用的一份快照。"""
    return {
        "enabled": is_enabled(),
        "volume": get_volume(),
        "scene": _state["scene"],
        "name": _state["name"],
        "preview": _state["preview"],
        "wanted": _state["wanted"],
        "has_audio": available(),
        "tracks": len(library()),
        "busy": _music_busy(),
        "choices": dict(_choices()),
        "play_error": _state["play_error"],
        "error": _state["error"],
        "mixer": _state["ready"],
    }


def last_error():
    """最近一次播放失败的曲子名（没有失败就是空串）。"""
    return _state["play_error"]


def reset_cache():
    """测试用：清掉运行期缓存（偏好重新从 settings.json 读、曲库重扫）。"""
    _state.update({"ready": None, "error": "", "scene": None, "name": None,
                   "wanted": None, "preview": False, "volume": None,
                   "enabled": None, "choices": None, "lib": None, "lib_sig": None,
                   "picks": {}, "play_error": ""})
