# -*- coding: utf-8 -*-
"""可选音乐包：从 GitHub Release 按需下载 → 校验 → 解压

和 kards_musicpack 的分工
--------------------------------------------------------------------------
kards_musicpack  只管「本地有 zip 时怎么解、怎么记标记」，不联网；
kards_musicdl    只管「本地没有 zip 时怎么从发布页拿下来」，不碰解压细节。

为什么做成可选包
--------------------------------------------------------------------------
曲库 4.3 GB / 251 首。随安装包发的话，每个只想打牌的人都要先吞 4 GB，
更新、校验、GitHub 2 GB 单资产限制也全被拖累。所以：

    · KARDS.zip / Setup.zip 里**没有任何音乐**
    · 音乐放在固定 tag `music-pack` 的 Release 里（分卷）
    · 玩家在 设置 → 其它 →「可选音乐包」按需下载，不用时零成本

数据流
--------------------------------------------------------------------------
    release()         查 tag=music-pack 的资产清单（按卷号排序）
    plan()            本地状态：已装几首、目标目录、要不要下载
    InstallTask       后台线程：查清单 → 逐卷下载（带 SHA256）→ 解压 → 清包
    下载落地在**数据目录**（settings.json 旁边）。这样即使解压中途失败，
    下次启动 kards_musicpack 也能捡到 zip 继续解 —— 不白下 4 GB。

⚠ 取消 / 断网之后**不删已下完的卷**：下次进来按大小 + 哈希判断，
  已完成的直接跳过（见 InstallTask._part_ready）。
"""
import os
import shutil
import threading
import time

import kards_musicpack as MP
import kards_update as UPD

# 音乐包 Release 的固定 tag。**不要**改成版本号：
# 版本号随每次发版变化，曲库却几周才动一次。
TAG = "music-pack"
PAGE = f"https://github.com/{UPD.OWNER}/{UPD.REPO}/releases/tag/{TAG}"
# 解压时数据盘至少要有「包体积 × 1.1 + 300MB」的余量，别把系统盘塞爆
SPACE_FACTOR = 1.1
SPACE_EXTRA_MB = 300


def _data_dir():
    try:
        from kards_engine import DATA_DIR
        return DATA_DIR
    except Exception:                                       # noqa: BLE001
        return os.path.expanduser("~")


def _is_pack_name(name):
    low = (name or "").lower()
    return low.startswith("music") and low.endswith(".zip")


def parts_of(assets):
    """从资产清单里挑出音乐分卷，按卷号排序（music → music-2 → music-10）。"""
    ps = [a for a in (assets or []) if _is_pack_name(a.get("name"))]
    ps.sort(key=lambda a: MP._part_key(a["name"]))
    return ps


def total_bytes(ps):
    return sum(int(a.get("size") or 0) for a in ps)


def release(timeout=12):
    """查音乐包 Release。→ {"ok":True,"parts":[...],"page":...} / {"ok":False,"err":...}"""
    info = UPD.check_release(TAG, timeout=timeout)
    if not info.get("ok"):
        return {"ok": False, "err": info.get("err") or "查询失败",
                "parts": [], "page": PAGE}
    ps = parts_of(info.get("assets"))
    if not ps:
        return {"ok": False, "err": "发布页里没有音乐包分卷",
                "parts": [], "page": info.get("page") or PAGE}
    return {"ok": True, "err": "", "parts": ps,
            "page": info.get("page") or PAGE,
            "sums": [a for a in (info.get("assets") or [])
                     if a["name"].lower().startswith("sha256sums")]}


def plan():
    """本地状态快照（不联网）。"""
    target = MP.target_dir()
    local = MP.packs()
    return {
        "target": target,
        "audio": MP._audio_count(target),
        "local_packs": [os.path.basename(p) for p in local],
        "pending": MP.pending(),
        "data_dir": _data_dir(),
        "page": PAGE,
    }


def free_mb(path=None):
    try:
        return shutil.disk_usage(path or _data_dir()).free / 1048576.0
    except OSError:
        return None


def download_dir():
    """zip 落在数据目录（kards_musicpack 会自动探测到这里）。"""
    d = _data_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def _part_ready(asset, dest):
    """这卷是不是已经下好且完好（断点续传的替代：已完成就不重下）。"""
    try:
        if not os.path.isfile(dest):
            return False
        if int(asset.get("size") or 0) and os.path.getsize(dest) != int(asset["size"]):
            return False
    except OSError:
        return False
    sha = asset.get("sha256") or ""
    if sha:
        try:
            return UPD._sha256_file(dest) == sha
        except OSError:
            return False
    return True                      # 没有校验值：大小对得上就当完成


class InstallTask:
    """后台安装任务。界面只读 state / progress / message，不直接碰线程。

    state: idle → checking → downloading → extracting → done / error / cancelled
    """

    def __init__(self, keep_zips=False, local_only=False):
        self.state = "idle"
        self.progress = 0.0          # 0..1（整体，不是单卷）
        self.message = ""
        self.parts = []
        self.total_mb = 0.0
        self.done_mb = 0.0
        self.installed = 0           # 解出的文件数
        self.audio = 0               # 解完后音乐目录里的曲目数
        self.page = PAGE
        self.verified = True         # 所有卷都过了哈希校验
        self.keep_zips = keep_zips
        self.local_only = local_only  # 只解本地已有的 zip（设置里的「重新解压」）
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ 对外
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self):
        self._stop.set()

    @property
    def cancelled(self):
        return self._stop.is_set()

    def _set(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    # ------------------------------------------------------------ 主流程
    def _run(self):
        try:
            self._install()
        except Exception as exc:                            # noqa: BLE001
            self._set(state="error", message=f"{type(exc).__name__}: {exc}")

    def _install(self):
        if self.local_only:
            return self._reextract_local()

        self._set(state="checking", message="")
        info = release()
        if not info["ok"]:
            self._set(state="error", message=info["err"])
            return
        ps = info["parts"]
        total = total_bytes(ps)
        self._set(parts=ps, total_mb=total / 1048576.0, page=info.get("page") or PAGE)
        if self.cancelled:
            self._set(state="cancelled")
            return

        need = total / 1048576.0 * SPACE_FACTOR + SPACE_EXTRA_MB
        # 下到数据目录、解到音乐目录，可能不在同一个分区：两边都得够
        frees = [f for f in (free_mb(download_dir()), free_mb(MP.target_dir()))
                 if f is not None]
        if frees and min(frees) < need:
            self._set(state="error",
                      message=f"insufficient_space:{int(need)}:{int(min(frees))}")
            return

        dest_dir = download_dir()
        sums = info.get("sums") or []
        sums_text = ""
        if sums:
            try:
                sums_text = UPD._fetch_sums_text(sums[0])
            except Exception:                              # noqa: BLE001
                sums_text = ""

        self._set(state="downloading")
        base = 0
        for i, asset in enumerate(ps):
            if self.cancelled:
                self._set(state="cancelled")
                return
            name = asset["name"]
            dest = os.path.join(dest_dir, name)
            if _part_ready(asset, dest):
                base += int(asset.get("size") or 0)
                self._set(progress=base / max(1, total),
                          done_mb=base / 1048576.0,
                          message=f"{name}（已有，跳过）")
                continue

            want = asset.get("sha256") or ""
            if not want and sums_text:
                want = UPD.parse_sums(sums_text, name)
            if not want:
                self._set(verified=False)

            offset = base

            def on_progress(done, length, _name=name, _off=offset):
                if self.cancelled:
                    raise UPD.Cancelled()
                got = _off + done
                self._set(progress=min(1.0, got / max(1, total)),
                          done_mb=got / 1048576.0,
                          message=_name)

            ok, err, meta = UPD.download_ex(
                asset, dest, progress=on_progress, want_sha=want,
                on_verify=lambda: self._set(message=f"{name}（校验中）"))
            if self.cancelled:
                self._set(state="cancelled")
                return
            if not ok:
                self._set(state="error", message=f"{name}: {err}")
                return
            if want and not meta.get("verified"):
                self._set(verified=False)
            base += int(asset.get("size") or 0)
            self._set(progress=base / max(1, total), done_mb=base / 1048576.0)

        # ---- 解压 ----
        # 进度按「已写字节 / 包内总字节」算：4 GB 的包解压要几十秒，
        # 没有进度会让人以为卡死。
        self._extract_and_finish([dest_dir])

        # ---- 清包（默认删掉，4.3 GB 留在数据目录里没有意义）----
        if not self.keep_zips:
            for asset in ps:
                try:
                    os.remove(os.path.join(dest_dir, asset["name"]))
                except OSError:
                    pass
        self._set(state="done", progress=1.0,
                  audio=MP._audio_count(MP.target_dir()))

    def _reextract_local(self):
        """只解本地已有的 zip（玩家自己放的包 / 上次中断留下的卷）。

        ⚠ 必须把**找到的包所在目录**传给 ensure_extracted，不能传 None：
          None 会退化成 candidate_dirs()，把随包/数据目录里的所有
          music*.zip 都重解一遍 —— 「重新解压」就变成了「全曲库重解」。
        """
        ps = MP.packs()
        if not ps:
            self._set(state="error", message="no_local_packs")
            return
        dirs = sorted({os.path.dirname(p) for p in ps})
        self._set(state="extracting", parts=[{"name": os.path.basename(p)}
                                             for p in ps])
        self._extract_and_finish(dirs)
        self._set(state="done", progress=1.0,
                  audio=MP._audio_count(MP.target_dir()))

    def _extract_and_finish(self, dirs):
        self._set(state="extracting", progress=0.0, message="")

        def on_extract(done, tot, name):
            frac = (done / tot) if tot else 0.0
            self._set(progress=max(0.0, min(1.0, frac)), message=name)

        res = MP.ensure_extracted(dirs=dirs, progress=on_extract,
                                  should_stop=lambda: self.cancelled)
        if res.get("aborted"):
            self._set(state="cancelled")
            return
        if res.get("errors"):
            self._set(state="error", message="; ".join(res["errors"][:3]))
            return
        self._set(installed=res.get("extracted", 0))


def open_page():
    """在系统浏览器打开音乐包发布页（手动下载的兜底路径）。"""
    try:
        import webbrowser
        webbrowser.open(PAGE)
        return True
    except Exception:                                      # noqa: BLE001
        return False


def status():
    """诊断快照（--check-music 里一起打印）。"""
    p = plan()
    p["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return p
