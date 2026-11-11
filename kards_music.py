# -*- coding: utf-8 -*-
"""KARDS 简化版 —— 背景音乐（BGM）管理

设计取向（和 kards_board.sfx 的"音效钩子"一脉相承）：
- **没有资源也要能跑**。assets/music 里一个文件都没有时，所有接口静默失效，
  游戏照常运行（玩家只是听不到声音），绝不因为缺音乐崩掉或弹窗。
- **单通道 + 场景切换**。pygame.mixer.music 只有一个播放位，所以按场景
  （menu / battle / result）切歌；同一首正在放就不重头开始，避免每次刷界面
  都把音乐掐回开头。
- **偏好落地**。开关与音量写进 settings.json（music_enabled / music_volume），
  下次启动原样恢复。
- 找不到某场景的曲子时按 FALLBACK 退到别的曲子（比如结算没配乐就用主菜单的），
  总比突然静音自然。

对外接口：
    play(name) / stop() / pause() / resume()
    set_enabled(flag) / is_enabled() / toggle()
    set_volume(0-100) / get_volume()
    status() / track_path(name) / available()

玩家想换曲子：把 menu.ogg / battle.ogg / result.ogg（也支持 .wav / .mp3）
丢进 assets/music/ 即可，源码版和安装版都认（安装版放在 exe 同级的 assets 下，
不用重新打包）。
"""
import os
import sys

# 场景 → 允许的扩展名（按优先级）。ogg 体积小、循环无缝，最推荐。
TRACKS = ("menu", "battle", "result")
_EXTS = (".ogg", ".wav", ".mp3")

# 某场景没配乐时的退路（避免"进对局突然没声"）
FALLBACK = {"battle": "menu", "result": "menu"}

_PREF_VOLUME = "music_volume"
_PREF_ENABLED = "music_enabled"
DEFAULT_VOLUME = 55

# 运行期状态（模块级单例，整个进程共用一套音乐）
_state = {
    "ready": None,      # None=还没试过 / True=音频子系统可用 / False=不可用
    "error": "",        # 不可用原因，方便状态栏与日志展示
    "track": None,      # 当前**真正在放**的场景名
    "wanted": None,     # 最后一次请求的场景名（静音时也记，恢复时接着放）
    "volume": None,     # 懒加载的缓存，None 表示还没从 settings.json 读
    "enabled": None,
}


def _asset_roots():
    """音乐目录的搜索路径，优先级与 kards_board.asset_roots 保持一致。"""
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


def track_path(name):
    """返回该场景曲子的绝对路径；没有这个文件返回 None。"""
    for root in _asset_roots():
        for ext in _EXTS:
            p = os.path.join(root, "music", name + ext)
            if os.path.isfile(p):
                return p
    return None


def available():
    """至少配了一首曲子才为 True —— 设置界面据此提示"未找到音乐文件"。"""
    return any(track_path(n) for n in TRACKS)


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

def _pref_module():
    import kards_i18n
    return kards_i18n


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


# ---------------------------------------------------------------- 播放控制

def _play_file(path, fade_ms):
    import pygame
    try:
        pygame.mixer.music.load(path)
        pygame.mixer.music.set_volume(get_volume() / 100.0)
        # loops=-1 无限循环；fade_ms 让进场景时不是"啪"一下起来
        pygame.mixer.music.play(-1, fade_ms=max(0, int(fade_ms)))
        return True
    except Exception as exc:                               # noqa: BLE001
        _state["error"] = "play-failed: %s" % exc
        return False


def play(name, fade_ms=700, force=False):
    """切到某个场景的音乐（循环播放）。返回是否真的放起来了。

    - 同名曲子正在放：什么都不做（避免刷界面把音乐拽回开头）
    - 音乐被关掉：只记下"想要哪首"，重新打开时接着放
    - 该场景没配曲子：按 FALLBACK 找替代，找不到就停
    """
    _state["wanted"] = name
    if not is_enabled():
        return False
    if not _ensure_mixer():
        return False
    path = track_path(name)
    if path is None:
        alt = FALLBACK.get(name)
        if alt:
            return play(alt, fade_ms=fade_ms, force=force) if alt != name else False
        return False
    if not force and _state["track"] == name and _music_busy():
        return True
    if _music_busy() and _state["track"] not in (None, name):
        # 硬切之前先淡出：老的曲子往下走，新的淡入接上来，听感上像交叉淡化
        try:
            import pygame
            pygame.mixer.music.fadeout(180)
        except Exception:                                  # noqa: BLE001
            pass
    ok = _play_file(path, fade_ms)
    _state["track"] = name if ok else None
    return ok


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
    _state["track"] = None
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
        "track": _state["track"],
        "wanted": _state["wanted"],
        "has_audio": available(),
        "error": _state["error"],
        "mixer": _state["ready"],
    }


def reset_cache():
    """测试用：清掉运行期缓存（偏好重新从 settings.json 读）。"""
    _state.update({"ready": None, "error": "", "track": None, "wanted": None,
                   "volume": None, "enabled": None})
