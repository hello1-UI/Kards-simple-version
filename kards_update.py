# -*- coding: utf-8 -*-
"""KARDS 简化版 · 游戏内自动更新

设计目标
    · **只用标准库**（urllib + json + zipfile），打包进 exe 也不增体积
    · 不依赖 git：直接问 GitHub Releases API「最新版是多少」
    · 有更新时下载 zip → 解压到程序目录（覆盖式）→ 提示重启
    · 全程**不阻塞界面**：网络请求与解压都在后台线程，主线程只轮询进度

⚠ 本机网络环境（见 .workbuddy/memory 的 DNS 投毒记录）：
    · github.com 可能被解析到不可达 IP；raw/codeload 被解析到内网
    · api.github.com 走系统代理才稳
    因此这里**优先用 api.github.com 的 release 资产 URL**（api 可达性最好），
    并在失败时回落到镜像站（gh-proxy），两者都失败才报错。

更新包格式约定（与发行包一致）：
    KARDS.zip 里可能带一层 `KARDS/` 前缀，解压时要剥掉（安装器同款处理）。
"""
import json
import os
import shutil
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile

OWNER, REPO = "hello1-UI", "Kards-simple-version"
API_LATEST = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{OWNER}/{REPO}/releases/latest"

# 下载镜像（按顺序尝试；直连失败时的兜底）。
# ⚠ 只对**下载资产**用镜像，API 查询仍走官方（镜像不镜像 API）。
_ASSET_MIRRORS = (
    "https://gh-proxy.com/{url}",
    "https://ghfast.top/{url}",
)

TIMEOUT_API = 12
TIMEOUT_DL = 90
_UA = "KARDS-SimpleVersion-Updater"


# ------------------------------------------------------------------ 版本比较

def parse_version(text):
    """'v1.2.0.3' / '1.2.0.3' / 'v1.2' → (1,2,0,3)；解析失败返回 ()"""
    if not text:
        return ()
    s = str(text).strip().lstrip("vV")
    parts = []
    for chunk in s.split("."):
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        if not num:
            break
        parts.append(int(num))
    return tuple(parts)


def is_newer(remote, local):
    """remote 是否比 local 新（元组逐位比较，短的一侧补 0）"""
    r, l = parse_version(remote), parse_version(local)
    if not r:
        return False
    n = max(len(r), len(l))
    r = r + (0,) * (n - len(r))
    l = l + (0,) * (n - len(l))
    return r > l


def version_str(ver):
    """(1,2,0,3) → '1.2.0.3'（本地 VERSION 元组用）"""
    if isinstance(ver, (tuple, list)):
        return ".".join(str(x) for x in ver)
    return str(ver)


# ------------------------------------------------------------------ 网络

def _opener():
    """带 UA 的 opener。走系统代理（环境变量），不额外配置。"""
    handlers = [urllib.request.HTTPSHandler(context=ssl.create_default_context())]
    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
    return urllib.request.build_opener(*handlers)


def _get(url, timeout, accept="application/json"):
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": accept,
    })
    return _opener().open(req, timeout=timeout)


def check_latest(timeout=TIMEOUT_API):
    """查询最新 Release。

    返回 dict：
        成功 → {"ok": True, "version": "1.2.0.4", "notes": "...", "page": "...",
                 "assets": [{"name": ..., "url": ..., "size": ...}, ...]}
        失败 → {"ok": False, "err": "原因"}
    """
    try:
        with _get(API_LATEST, timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ok": False, "err": "仓库还没有发布任何 Release"}
        return {"ok": False, "err": f"HTTP {e.code}"}
    except Exception as e:                       # noqa: BLE001 — 网络错误种类多
        return {"ok": False, "err": f"{type(e).__name__}: {e}"}

    tag = data.get("tag_name") or data.get("name") or ""
    assets = []
    for a in data.get("assets") or []:
        assets.append({
            "name": a.get("name") or "",
            "url": a.get("browser_download_url") or "",
            "size": a.get("size") or 0,
        })
    return {"ok": True, "version": version_str(parse_version(tag)) or tag,
            "notes": data.get("body") or "",
            "page": data.get("html_url") or RELEASES_PAGE,
            "assets": assets}


def pick_asset(assets, prefer=("KARDS.zip",)):
    """从资产里挑出要下载的那个：优先 KARDS.zip，其次任意 .zip"""
    for want in prefer:
        for a in assets:
            if a["name"].lower() == want.lower():
                return a
    for a in assets:
        if a["name"].lower().endswith(".zip"):
            return a
    return None


def download(asset, dest, progress=None, timeout=TIMEOUT_DL):
    """下载资产到 dest。progress(done, total) 会被周期性调用。

    ⚠ 会依次尝试「官方直连 → 各镜像」。官方 assets 域名
    (objects.githubusercontent.com) 在部分网络下不可达，镜像常能救回来。
    """
    url = asset["url"]
    urls = [url] + [m.format(url=url) for m in _ASSET_MIRRORS]
    total = int(asset.get("size") or 0)
    last_err = "未知错误"
    for i, u in enumerate(urls):
        tmp = dest + ".part"
        try:
            with _get(u, timeout, accept="application/octet-stream") as resp:
                length = int(resp.headers.get("Content-Length") or total or 0)
                done = 0
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(262144)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, length)
            if length and done != length:
                raise OSError(f"下载不完整：{done}/{length} 字节")
            os.replace(tmp, dest)
            return True, ""
        except Exception as e:                   # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            if i < len(urls) - 1:
                time.sleep(0.4)                  # 换镜像前稍等一下
    return False, last_err


# ------------------------------------------------------------------ 解压 / 安装

def extract_zip(zip_path, target_dir, strip_root=None, progress=None):
    """解压 zip 到 target_dir。

    strip_root=None 时自动判断：若 zip 内顶层只有一个目录（如 KARDS/），
    就剥掉它 —— 发行包就是这么打的（安装器同款逻辑）。
    """
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n and not n.endswith("/")]
        if strip_root is None:
            tops = {n.split("/", 1)[0] for n in names}
            if len(tops) == 1 and all("/" in n for n in names):
                strip_root = tops.pop() + "/"
            else:
                strip_root = ""
        os.makedirs(target_dir, exist_ok=True)
        base = os.path.abspath(target_dir)
        for i, info in enumerate(zf.infolist()):
            if info.is_dir():
                continue
            rel = info.filename
            if strip_root and rel.startswith(strip_root):
                rel = rel[len(strip_root):]
            if not rel:
                continue
            # 防 zip slip：目标必须仍在 target_dir 内
            out = os.path.abspath(os.path.join(target_dir, rel))
            if not (out == base or out.startswith(base + os.sep)):
                continue
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with zf.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if progress:
                progress(i + 1, len(names))
    return True, ""


def has_meipass():
    """是否是一体式（onefile）打包 —— 资源被解到临时目录 _MEIxxxx。"""
    return bool(getattr(sys, "_MEIPASS", None))


def can_self_update():
    """能否就地更新；返回「应该被覆盖的目录」。

    · **onedir 打包**：exe 与 _internal/ 是分开的。
      资源在 `_internal/`，所以数据文件（kards_server.py）要往 `_internal/` 里放；
      但 exe 本身在上一层，重启要靠那一层。这里返回 `_internal/`，
      调用方再用 `restart_dir()` 拿 exe 所在的目录。
    · **源码运行**：返回源码目录（避免把 AppData 用户数据目录当程序目录）。
    """
    if has_meipass():
        # onefile：临时目录不可写/会被清掉，不能就地更新
        return None
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.executable)
        exe_dir = os.path.dirname(exe)
        internal = os.path.join(exe_dir, "_internal")
        return internal if os.path.isdir(internal) else exe_dir
    return os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv else __file__))


def restart_dir():
    """重启 bat 应该 cd 进去并启动 exe 的目录。"""
    if has_meipass():
        return os.path.dirname(os.path.abspath(sys.executable))
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return can_self_update() or os.getcwd()


def restart_hint():
    """更新完怎么重启（界面提示用，返回需要重启的说明键，交给 i18n）"""
    return "update_restart_needed"


# ------------------------------------------------------------------ 后台任务

class UpdateTask:
    """把「查询 → 下载 → 解压」串成一个后台任务，供 GUI 轮询进度。

    用法：
        t = UpdateTask(local_version="1.2.0.3")
        t.start()
        # 主线程定时轮询：
        t.state     # "checking"/"no_update"/"found"/"downloading"/"extracting"/"done"/"error"
        t.progress  # 0.0~1.0
        t.message   # 出错原因 / 版本号
    """

    def __init__(self, local_version, auto_install=True, target_dir=None):
        self.local = version_str(local_version)
        self.auto_install = auto_install
        self.target_dir = target_dir or can_self_update()
        self.state = "idle"
        self.progress = 0.0
        self.message = ""
        self.info = None
        self.asset = None
        self._stop = threading.Event()
        self._th = None

    def start(self):
        if self._th is not None and self._th.is_alive():
            return False
        if not self.target_dir:
            # onefile 打包下无法就地替换；明确报错好过默默解压到临时目录
            self.state = "error"
            self.message = "当前为单文件版本，请到发布页下载新版"
            return False
        self.state, self.progress, self.message = "checking", 0.0, ""
        self._stop.clear()
        self._th = threading.Thread(target=self._run, daemon=True)
        self._th.start()
        return True

    def cancel(self):
        self._stop.set()

    def _run(self):
        info = check_latest()
        if not info.get("ok"):
            self.state, self.message = "error", info.get("err", "")
            return
        self.info = info
        if not is_newer(info["version"], self.local):
            self.state = "no_update"
            return
        asset = pick_asset(info.get("assets") or [])
        if asset is None:
            self.state, self.message = "error", "该版本没有可下载的 zip 资产"
            return
        self.asset = asset
        self.state = "found"
        if not self.auto_install:
            return
        self._download_and_install(asset)

    def _download_and_install(self, asset):
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="kards_update_")
        zpath = os.path.join(tmpdir, asset["name"] or "KARDS.zip")
        self.state, self.progress = "downloading", 0.0

        def on_dl(done, total):
            if total:
                self.progress = min(0.99, done / total)
            if self._stop.is_set():
                raise OSError("已取消")

        ok, err = download(asset, zpath, progress=on_dl)
        if not ok:
            self.state, self.message = "error", f"下载失败：{err}"
            self._cleanup(tmpdir)
            return
        self.state, self.progress = "extracting", 0.0

        def on_ex(done, total):
            if total:
                self.progress = min(0.99, done / total)

        ok, err = extract_zip(zpath, self.target_dir, progress=on_ex)
        if not ok:
            self.state, self.message = "error", f"解压失败：{err}"
            self._cleanup(tmpdir)
            return
        self._cleanup(tmpdir)
        self.progress = 1.0
        self.state = "done"
        self.message = self.info["version"]

    @staticmethod
    def _cleanup(path):
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:                        # noqa: BLE001
            pass


def write_update_bat(pid=None, exe=None, args=None):
    """生成一个「等本进程退出 → 覆盖 → 重启」的批处理。

    更新**正在运行的 exe** 时，Windows 会锁住 exe 本身，直接覆盖会
    WinError 32。稳妥做法：把替换动作交给一个独立的小 bat，
    它先等我们的 PID 消失，再复制文件并重启。
    ⚠ 文件内容必须是 **GBK 可编码** 的纯 ASCII，否则 cmd.exe 会乱码
    （见 windows-bat-chinese 经验）。
    """
    import tempfile
    pid = pid or os.getpid()
    exe = exe or sys.executable
    args = args or []
    bat = os.path.join(tempfile.gettempdir(), f"kards_update_{pid}.bat")
    exe_dir = restart_dir()
    wait = (
        "@echo off\r\n"
        "setlocal\r\n"
        f"set PID={pid}\r\n"
        ":wait\r\n"
        "tasklist /FI \"PID eq %PID%\" 2>NUL | find \"%PID%\" >NUL\r\n"
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >NUL\r\n"
        "  goto wait\r\n"
        ")\r\n"
        f'cd /d "{exe_dir}"\r\n'
    )
    launch = f'start "" "{os.path.basename(exe)}"'
    if args:
        launch += " " + " ".join(f'"{a}"' for a in args)
    content = wait + launch + "\r\n"
    try:
        with open(bat, "w", encoding="mbcs", errors="replace", newline="") as f:
            f.write(content)
    except (OSError, LookupError):
        try:
            with open(bat, "w", encoding="ascii", errors="replace", newline="") as f:
                f.write(content)
        except OSError:
            return None
    return bat
