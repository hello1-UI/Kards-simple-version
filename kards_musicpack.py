# -*- coding: utf-8 -*-
"""音乐包：曲库以 zip 分发，首次启动自动解压到音乐目录

为什么要有这个模块
--------------------------------------------------------------------------
曲库动辄几个 GB、几百个文件，直接散在 assets/music/ 里带来三个麻烦：

1. **打包体积/文件数爆炸** —— PyInstaller 会把整目录搬进发行包，
   几百个 flac 让安装包变成一头巨兽，解压、更新、校验都变慢。
2. **仓库与传输** —— 单个文件上传（Release / 网盘）只方便传一个大文件，
   逐个小文件传既慢又容易中断。
3. **命名问题** —— 散装文件名直接暴露在目录里，想避免也没办法。

所以：**发行时只带 `music*.zip`，第一次打开游戏时解压到音乐目录**。
解压完写一个标记（`.musicpack.json`），之后启动只比对 zip 的大小/时间戳，
命中就瞬间跳过 —— 不会每次都解压。

约定
--------------------------------------------------------------------------
- zip 可以放在这些位置（按顺序探测）：
    * `assets/music*.zip`            —— 随包分发（打包进 _internal/assets）
    * `assets/musicpack/music*.zip`  —— 想和图片资源分开放时
    * 数据目录下的 `music*.zip`       —— 玩家自己下载的补充包
      （安装版是 `%USERPROFILE%\\AppData\\Kards-Simple-Version\\`）
- **支持分卷**：`music.zip`、`music-2.zip`、`music-3.zip`……
  按文件名自然排序，逐个解开。单个文件超过 2GB 时 GitHub Release 传不上去，
  用 `debug/pack_music.py` 自动切分。
- zip 内可以带也可以不带顶层 `music/` 目录，会自动剥掉。
- **已在磁盘上的同名文件不覆盖**（玩家自己换过的高码率版本不能被包冲掉），
  只有大小不一致才重写。写入走「临时文件 + os.replace」，中途断电不会留下
  半个文件把下次解压卡死。
- 坏 zip / 加密 zip / 解到一半没权限：只记录错误，**绝不抛异常打断启动**，
  下次启动会自动重试（失败的那一卷不写成功标记）。

对外接口：
    packs(dirs=None)            当前探测到的 zip 列表
    target_dir()                解压目标目录（= kards_music.user_music_dir()）
    pending(dirs=None)          是否还需要解压（标记是否过期）
    ensure_extracted(...)       执行解压（幂等；带进度/取消回调）
    ensure_extracted_gui()      带进度窗的版本（启动时调用，无事发生则秒过）
    status()                    诊断快照
"""
import json
import os
import sys
import time
import zipfile

MARKER = ".musicpack.json"
# 磁盘剩余空间的安全余量（解压大包别把系统盘塞满）
MIN_FREE_MB = 200
# 小于这个体积不弹进度窗（几 MB 的包一闪而过，弹窗反而碍眼）
PROGRESS_MIN_MB = 30

_STATE = {"error": "", "last": {}}


# ---------------------------------------------------------------- 目录探测

def _asset_roots():
    """随包资源根目录（与 kards_board / kards_music 的优先级保持一致）。"""
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


def _data_dir():
    """数据目录（settings.json / 下载的补充包放这里）。"""
    try:
        from kards_engine import DATA_DIR
        return DATA_DIR
    except Exception:                                      # noqa: BLE001
        return ""


def candidate_dirs():
    out = []
    for root in _asset_roots():
        for d in (root, os.path.join(root, "musicpack")):
            if d not in out:
                out.append(d)
    d = _data_dir()
    if d and d not in out:
        out.append(d)
    return out


def _part_key(name):
    """分卷排序键：music.zip 排第一，music-2.zip 第二……

    直接按字符串排会把 `music-10.zip` 排在 `music-2.zip` 前面，解压顺序就乱了；
    这里把文件名里的数字段抽出来按数值比。
    """
    stem = os.path.splitext(name)[0].lower()
    digits = "".join(ch if ch.isdigit() else " " for ch in stem).split()
    return (0 if "music" in stem and len(stem) <= 5 else 1,
            [int(x) for x in digits] or [0], stem)


def packs(dirs=None):
    """探测所有音乐包 zip（按分卷顺序）。目录不存在/没权限都静默跳过。"""
    found = []
    seen = set()
    for d in (dirs if dirs is not None else candidate_dirs()):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for fn in names:
            low = fn.lower()
            if not low.endswith(".zip") or not low.startswith("music"):
                continue
            path = os.path.abspath(os.path.join(d, fn))
            if path in seen:
                continue
            try:
                if not os.path.isfile(path):
                    continue
            except OSError:
                continue
            seen.add(path)
            found.append(path)
    found.sort(key=lambda p: _part_key(os.path.basename(p)))
    return found


def target_dir():
    """解压目标 = 玩家的音乐目录（kards_music 扫描时优先级最高的那个）。"""
    try:
        import kards_music
        return kards_music.user_music_dir(create=True)
    except Exception:                                      # noqa: BLE001
        d = os.path.join(os.path.expanduser("~"), "AppData",
                         "Kards-Simple-Version", "music")
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        return d


def _sig(path):
    try:
        st = os.stat(path)
        return [int(st.st_size), int(st.st_mtime)]
    except OSError:
        return None


def _read_marker(target):
    try:
        with open(os.path.join(target, MARKER), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_marker(target, data):
    path = os.path.join(target, MARKER)
    tmp = path + ".part"
    try:
        os.makedirs(target, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _audio_count(target):
    """目标目录里已解出多少音频（标记说完成但一个文件都没有 → 得重解）。"""
    try:
        import kards_music
        exts = kards_music.SUPPORTED_EXTS
    except Exception:                                      # noqa: BLE001
        exts = (".ogg", ".wav", ".mp3", ".flac")
    n = 0
    try:
        for fn in os.listdir(target):
            if os.path.splitext(fn)[1].lower() in exts:
                n += 1
    except OSError:
        pass
    return n


def _all_present(ps, target):
    """包里每个成员是否都已在目标目录且大小一致（只读 zip 中央目录，很快）。

    用途：源码版里音乐本来就是散装放在 assets/music（= 解压目标）的，
    没有标记文件，光看标记会误判成「需要解压」，白白弹一次进度窗。
    另外玩家手工解压过、或上次解完没来得及写标记的情况也靠它兜住。
    """
    for p in ps:
        try:
            with zipfile.ZipFile(p) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    rel = _safe_name(info.filename)
                    if rel is None:
                        continue
                    dest = os.path.join(target, *rel.split("/"))
                    try:
                        if (not os.path.isfile(dest)
                                or os.path.getsize(dest) != info.file_size):
                            return False
                    except OSError:
                        return False
        except (zipfile.BadZipFile, OSError):
            return False
    return True


def pending(dirs=None, target=None):
    """是否还需要解压。命中标记时是纯文件系统 stat，几毫秒。"""
    ps = packs(dirs)
    if not ps:
        return False
    target = target or target_dir()
    mark = _read_marker(target)
    done = mark.get("packs") if isinstance(mark.get("packs"), dict) else {}
    if _audio_count(target) > 0:
        ok = True
        for p in ps:
            rec = done.get(os.path.basename(p))
            if not isinstance(rec, dict) or not rec.get("ok") or rec.get("sig") != _sig(p):
                ok = False
                break
        if ok:
            return False
        # 标记缺失/过期：也可能文件本来就在（源码版散装曲库、手工解压过）
        return not _all_present(ps, target)
    return True


# ---------------------------------------------------------------- 解压

def _safe_name(name):
    """把 zip 成员名变成安全相对路径；不安全/无意义返回 None。

    - 反斜杠统一成正斜杠（Windows 打的包常见）
    - 丢掉空段和 `..`（zip-slip：把文件写到音乐目录外面）
    - 剥掉顶层 `music/`（打包时习惯整个目录塞进去）
    - 跳过 macOS 的 `__MACOSX/` 与点文件（.DS_Store 之类）
    """
    n = str(name or "").replace("\\", "/").strip()
    if not n or n.endswith("/"):
        return None
    parts = [p for p in n.split("/") if p not in ("", ".", "..")]
    if not parts:
        return None
    if any(p.lower() == "__macosx" for p in parts):
        return None
    base = parts[-1]
    if base.startswith("."):
        return None
    if len(parts) > 1 and parts[0].lower() in ("music", "musics"):
        parts = parts[1:]
    # 曲库是**平铺扫描**的（不递归），压进子目录的文件解出来也看不见 →
    # 统一拍平到根目录。同名冲突时后写的覆盖先写的，和 zip 顺序一致。
    return parts[-1]


def _extract_one(path, target, progress=None, should_stop=None,
                 force=False, stats=None):
    """解一卷 zip。返回 (ok, extracted, skipped, errors)。"""
    ok, extracted, skipped, errors = True, 0, 0, []
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        return False, 0, 0, ["%s: %s" % (os.path.basename(path), exc)]
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        for info in infos:
            if should_stop and should_stop():
                return False, extracted, skipped, errors
            rel = _safe_name(info.filename)
            if rel is None:
                skipped += 1
                continue
            dest = os.path.join(target, *rel.split("/"))
            counted = False
            try:
                if (not force and os.path.isfile(dest)
                        and os.path.getsize(dest) == info.file_size):
                    skipped += 1
                else:
                    os.makedirs(os.path.dirname(dest) or target, exist_ok=True)
                    tmp = dest + ".part"
                    with zf.open(info) as src, open(tmp, "wb") as out:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                            if stats is not None:
                                stats["done"] += len(chunk)
                            counted = True
                            if progress:
                                try:
                                    progress(stats["done"] if stats else 0,
                                             stats["total"] if stats else 0, rel)
                                except Exception:              # noqa: BLE001
                                    pass
                            if should_stop and should_stop():
                                out.close()
                                try:
                                    os.remove(tmp)
                                except OSError:
                                    pass
                                return False, extracted, skipped, errors
                    os.replace(tmp, dest)
                    extracted += 1
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                # 单个文件失败（权限/加密/坏块）不该毁掉整包：记下来继续
                errors.append("%s: %s" % (rel, exc))
                try:
                    os.remove(dest + ".part")
                except OSError:
                    pass
            if stats is not None and not counted:
                stats["done"] += info.file_size    # 跳过的也要推进进度条
            if progress and not counted:
                try:
                    progress(stats["done"] if stats else 0,
                             stats["total"] if stats else 0, rel)
                except Exception:                          # noqa: BLE001
                    pass
    if errors:
        ok = False
    return ok, extracted, skipped, errors


def ensure_extracted(dirs=None, target=None, progress=None, should_stop=None,
                     force=False):
    """把探测到的音乐包解到音乐目录。**幂等**，可以在每次启动时无脑调用。

    返回 dict(pending, packs, extracted, skipped, errors, aborted, at)。
    - 已有同名同大小文件 → 跳过（所以手工换过的高码率版本不会被冲掉）
    - force=True → 覆盖重解（设置里的「重新解压音乐包」用）
    """
    ps = packs(dirs)
    target = target or target_dir()
    res = {"pending": False, "packs": len(ps), "extracted": 0, "skipped": 0,
           "errors": [], "aborted": False, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if not ps:
        return res
    res["pending"] = True
    mark = _read_marker(target)
    done = mark.get("packs") if isinstance(mark.get("packs"), dict) else {}
    # ⚠ 标记说「都解过了」但目标目录里一个音频都没有（玩家清空了 / 换机拷了
    # 标记没带文件）→ 标记不可信，当没解过处理，否则永远补不回来。
    if _audio_count(target) == 0:
        force = True
    new_done = dict(done)
    total = 0
    try:
        for p in ps:
            with zipfile.ZipFile(p) as zf:
                total += sum(i.file_size for i in zf.infolist() if not i.is_dir())
    except Exception:                                      # noqa: BLE001
        total = 0
    stats = {"done": 0, "total": total}

    for p in ps:
        name = os.path.basename(p)
        rec = done.get(name)
        if (not force and isinstance(rec, dict) and rec.get("ok")
                and rec.get("sig") == _sig(p)):
            continue                      # 这一卷上次已经成功解过
        ok, ex, sk, errs = _extract_one(p, target, progress=progress,
                                        should_stop=should_stop, force=force,
                                        stats=stats)
        res["extracted"] += ex
        res["skipped"] += sk
        res["errors"].extend(errs)
        if should_stop and should_stop():
            res["aborted"] = True
            break
        new_done[name] = {"sig": _sig(p), "ok": ok and not errs,
                          "files": ex, "at": res["at"]}
    if not res["aborted"]:
        _write_marker(target, {"packs": new_done, "at": res["at"],
                               "audio": _audio_count(target)})
        try:
            import kards_music
            kards_music.refresh()          # 解完立刻进曲库，不用重启
        except Exception:                  # noqa: BLE001
            pass
    _STATE["last"] = res
    return res


# ---------------------------------------------------------------- 启动用进度窗

def ensure_extracted_gui(force=False):
    """启动时调用：需要解压就弹一个进度窗，否则直接返回（几乎零开销）。

    4GB 的包解压要几分钟，静默卡住会让人以为游戏挂了；进度窗里可以点「跳过」，
    跳过后下次启动会接着解（已解出的文件按大小比对，不重复写）。
    """
    if not force and not pending():
        return {"pending": False, "packs": 0, "extracted": 0, "skipped": 0,
                "errors": [], "aborted": False}
    ps = packs()
    try:
        total = 0
        for p in ps:
            with zipfile.ZipFile(p) as zf:
                total += sum(i.file_size for i in zf.infolist() if not i.is_dir())
    except Exception:                                      # noqa: BLE001
        total = 0
    if total < PROGRESS_MIN_MB * 1048576:
        return ensure_extracted(force=force)   # 小包：直接解，不折腾界面

    try:
        import tkinter as tk
    except Exception:                                      # noqa: BLE001
        return ensure_extracted(force=force)

    state = {"stop": False}
    root = tk.Tk()
    root.title("KARDS")
    root.configure(bg="#1b2128")
    w, h = 460, 168
    try:
        root.resizable(False, False)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 2))
    except Exception:                                      # noqa: BLE001
        pass
    tk.Label(root, text="首次启动：正在解压音乐包", bg="#1b2128",
             fg="#e8eef4", font=("Microsoft YaHei UI", 13, "bold")
             ).pack(pady=(22, 4))
    sub = tk.Label(root, text="正在准备曲库…", bg="#1b2128", fg="#8fa3b5",
                   font=("Microsoft YaHei UI", 9))
    sub.pack()
    bar = tk.Canvas(root, width=w - 72, height=10, bg="#2a323c",
                    highlightthickness=0, bd=0)
    bar.pack(pady=14)
    fill = bar.create_rectangle(0, 0, 0, 10, fill="#4a9eff", width=0)
    btn = tk.Button(root, text="跳过（下次启动继续）", bg="#2f3a45", fg="#c8d4e0",
                    font=("Microsoft YaHei UI", 9), bd=0, padx=12, pady=4,
                    activebackground="#3a4652", activeforeground="#ffffff",
                    cursor="hand2",
                    command=lambda: state.__setitem__("stop", True))
    btn.pack(pady=(0, 12))
    root.update()

    def on_progress(done, tot, name):
        pct = 0 if not tot else min(100, int(done * 100 / tot))
        try:
            bar.coords(fill, 0, 0, (w - 72) * pct / 100.0, 10)
            sub.configure(text="%d%%  %s" % (pct, name[:38]))
            root.update()
        except Exception:                                  # noqa: BLE001
            pass

    try:
        return ensure_extracted(progress=on_progress,
                                should_stop=lambda: state["stop"], force=force)
    finally:
        try:
            root.destroy()
        except Exception:                                  # noqa: BLE001
            pass


def status():
    """诊断快照（设置界面 / --check-music 用）。"""
    ps = packs()
    target = target_dir()
    mark = _read_marker(target)
    return {
        "packs": [{"name": os.path.basename(p), "mb": round(
            (os.path.getsize(p) / 1048576.0) if os.path.exists(p) else 0, 1)}
            for p in ps],
        "target": target,
        "pending": pending(),
        "audio": _audio_count(target),
        "marker": mark,
        "last": _STATE["last"],
        "error": _STATE["error"],
    }
