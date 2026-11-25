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

完整性校验（SHA256）
    更新是「下载一个 zip → 覆盖程序目录」，等于把任意代码请进本机。
    只比 Content-Length 是不够的（长度对得上、内容被换掉照样能过），
    所以这里补一条哈希链，取值优先级：

        1. Release API 给资产算的 digest（`sha256:xxxx`，官方替我们算的）
        2. 同版本里发布的 `SHA256SUMS.txt` / `KARDS.zip.sha256`

    ⚠ 校验值**只从官方源取**（api.github.com / github.com），zip 本体
      允许走镜像 —— 镜像是传输通道，不是信任通道：哈希对不上就换源重下。
      只有「一个校验值都拿不到」时才降级为「官方优先、镜像兜底」，
      并把结果标记成未校验，让界面如实告诉玩家。
"""
import json
import os
import shutil
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
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

# Release 里可能附带的校验文件名（全部小写比较）。
# 前两个是 `sha256sum` 的通用输出；后两个是「单个文件 + 只有一列哈希」的写法。
_SUMS_ASSET_NAMES = (
    "sha256sums.txt", "sha256sums",
    "kards.zip.sha256", "kards.zip.sha256.txt",
)

TIMEOUT_API = 12
TIMEOUT_DL = 90
_UA = "KARDS-SimpleVersion-Updater"


class Cancelled(Exception):
    """用户取消 —— **不能**当成一次"这个源失败了、换个源再试"。
    进度回调里抛这个异常，download_ex() 会立刻收手并清掉半截文件。"""


# ------------------------------------------------------------------ 版本比较

def parse_version(text):
    """'v1.2.0.3' / '1.2.0.3' / 'v1.2' / (1,2,0,3) → (1,2,0,3)；解析失败返回 ()

    ⚠ 必须能吃元组：调用方很容易顺手把 KARDS.py 的 `VERSION = (1,3,0,0)`
      直接传进来。曾经这里只走 `str()`，于是 `str((1,3,0,0))` = "(1, 3, 0, 0)"
      在第一个字符 '(' 处就断了，返回空元组 —— 而 is_newer 看到空元组会把
      本地版本补成 (0,0,0,0)，导致**全宇宙任何版本号都被判成"有更新"**。
      这种"静默地把未知当成最旧"的降级方式，比直接报错危险得多。
    """
    if text is None or text == "":
        return ()
    if isinstance(text, (tuple, list)):
        out = []
        for x in text:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                return ()
        return tuple(out) if out else ()
    if isinstance(text, int):
        return (text,)
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
    """remote 是否比 local 新（元组逐位比较，短的一侧补 0）

    任一侧解析不出来时一律返回 False —— 宁可"这次不提示更新"，
    也不要因为解析失败就每次都弹一个假更新窗。
    """
    r, l = parse_version(remote), parse_version(local)
    if not r or not l:
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
                 "assets": [{"name": ..., "url": ..., "size": ..., "sha256": ...}, ...]}
        失败 → {"ok": False, "err": "原因"}

    asset 里的 sha256 来自 GitHub 给资产算的 digest（形如 `sha256:abc…`）；
    老版本 Release 的资产没有 digest，这里留空字符串，交给
    resolve_checksum() 去同版本的校验文件里找。
    """
    return check_release(None, timeout=timeout)


def check_release(tag=None, timeout=TIMEOUT_API):
    """查询**指定 tag** 的 Release；tag 为空则查最新。

    用途：可选音乐包挂在固定 tag（music-pack）上，不能靠 /releases/latest
    —— 那个只反映游戏版本。返回结构与 check_latest 一致（同样带 assets），
    只是多一个 "tag" 字段，方便调用方核对。
    """
    if tag:
        url = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/tags/{tag}"
    else:
        url = API_LATEST
    try:
        with _get(url, timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            if tag:
                return {"ok": False, "err": f"没有 tag 为 {tag} 的 Release"}
            return {"ok": False, "err": "仓库还没有发布任何 Release"}
        return {"ok": False, "err": f"HTTP {e.code}"}
    except Exception as e:                       # noqa: BLE001 — 网络错误种类多
        return {"ok": False, "err": f"{type(e).__name__}: {e}"}

    tag_name = data.get("tag_name") or data.get("name") or ""
    assets = []
    for a in data.get("assets") or []:
        assets.append({
            "name": a.get("name") or "",
            "url": a.get("browser_download_url") or "",
            "size": a.get("size") or 0,
            "sha256": digest_to_sha256(a.get("digest")),
        })
    return {"ok": True, "tag": tag_name,
            "version": version_str(parse_version(tag_name)) or tag_name,
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


def digest_to_sha256(digest):
    """API 的 `sha256:abc…` → `abc…`；不认识的格式返回 ""

    ⚠ 宁可返回空串（= 当作没有校验值），也不要返回半截字符串：
      一个残缺的哈希会让每次下载都「校验失败」，等于把更新功能整个搞挂。
    """
    d = (digest or "").strip().lower()
    if d.startswith("sha256:"):
        d = d.split(":", 1)[1].strip()
    if len(d) == 64 and all(c in "0123456789abcdef" for c in d):
        return d
    return ""


def _sha256_file(path, progress=None):
    """算文件 SHA256（分块读，47 MB 的包也不吃内存）"""
    import hashlib
    h = hashlib.sha256()
    try:
        total = os.path.getsize(path) or 1
    except OSError:
        total = 1
    done = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(262144)
            if not chunk:
                break
            h.update(chunk)
            done += len(chunk)
            _safe_progress(progress, done, total)
    return h.hexdigest()


def parse_sums(text, filename):
    """从校验文件文本里挑出 filename 那一行的哈希；取不到返回 ""

    兼容三种写法：
        <64位hex>  <文件名>          ← sha256sum 的标准输出
        <64位hex> *<文件名>          ← sha256sum -b（二进制模式）
        <64位hex>                    ← 单文件校验（`KARDS.zip.sha256` 常见）
    """
    want = (filename or "").strip().lower()
    want_base = os.path.basename(want)
    lone = []                                  # 只有哈希、没有文件名的行
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace("\t", " ").split()
        cand = parts[0].strip().lower()
        if len(cand) != 64 or any(c not in "0123456789abcdef" for c in cand):
            continue
        if len(parts) == 1:
            lone.append(cand)
            continue
        name = " ".join(parts[1:]).lstrip("*").strip().lstrip("./").lower()
        if name == want or os.path.basename(name) == want_base:
            return cand
    # 整份文件只有一条「光杆哈希」时才敢当成是这个资产的校验值
    return lone[0] if len(lone) == 1 else ""


def _fetch_sums_text(asset, timeout=TIMEOUT_API):
    """取回校验文件的文本（只走官方 URL，最多 64 KB）"""
    try:
        with _get(asset["url"], timeout, accept="application/octet-stream") as resp:
            return resp.read(65536).decode("utf-8", "replace")
    except Exception:                            # noqa: BLE001
        return ""


def resolve_checksum(assets, asset):
    """定出这个资产该用哪个 SHA256 校验。→ (sha256_hex, source)

    source: "digest"（API 算的）/ "sums"（发布页附带的校验文件）/ ""（没有）

    ⚠ 校验文件本身**只从官方源取**：它要是也能从镜像拿，
      「改 zip + 顺手改校验文件」就成了一个自洽的伪造包。
    """
    if not asset:
        return "", ""
    sha = digest_to_sha256(asset.get("sha256") or "")
    if sha:
        return sha, "digest"
    for a in assets or []:
        name = (a.get("name") or "").lower()
        if name in _SUMS_ASSET_NAMES:
            text = _fetch_sums_text(a)
            got = parse_sums(text, asset.get("name") or "")
            if got:
                return got, "sums"
            break                                # 找到校验文件但里面没我们的条目
    return "", ""


def _safe_progress(progress, done, total):
    """调用进度回调，**吞掉回调自身的异常**。

    ⚠ 这里必须自己 try：download() 外面那层 `except Exception` 是拿来换镜像的，
    如果调用方的进度回调写错了（比如签名少个参数），异常会被当成"下载失败"，
    于是白白把所有镜像再重试一遍，还报一个牛头不对马嘴的错误。
    下载本身没问题，就不该因为 UI 回调崩掉而失败。
    """
    if not progress:
        return
    try:
        progress(done, total)
    except Cancelled:
        raise                                    # 取消不是"回调写错了"
    except Exception:                                # noqa: BLE001
        pass


def _rm(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def download_ex(asset, dest, progress=None, timeout=TIMEOUT_DL, want_sha="",
                on_verify=None):
    """下载资产到 dest，按需校验 SHA256。→ (ok, err, meta)

    meta = {"verified": bool, "sha256": 实际算出的哈希, "url": 真正成功的地址}

    源的选择取决于**有没有校验值**：
      · 有 want_sha：官方 → 镜像 都可以试。任何一个源下下来的包，哈希
        对得上就收，对不上就删掉换下一个 —— 镜像是**传输**通道，不是
        **信任**通道，这正是"镜像不可信但仍然可用"的正确解法。
      · 没有 want_sha：先官方直连；官方失败才降级到镜像，并回传
        verified=False，让界面如实告诉玩家"这一次没能校验"。

    on_verify：下载完成、开始算哈希之前调一次，供界面把状态切到"校验中"
    （47 MB 的包算哈希要零点几秒，进度条已经 100% 却不动会让人以为卡死）。
    """
    url = asset["url"]
    # 镜像只对「GitHub 托管的 http(s) 资产」有意义：
    #   · file:// 之类的本地地址套镜像模板只会造出垃圾 URL
    #   · 非 GitHub 的地址（比如自建更新源）套 gh-proxy 也没有意义
    # 而且镜像站在部分网络下会让 DNS/连接干等很久，无谓地拖慢失败路径。
    host = urllib.parse.urlsplit(url).netloc.lower()
    githubish = (url.lower().startswith("http")
                 and (host.endswith("github.com")
                      or host.endswith("githubusercontent.com")))
    mirrors = [m.format(url=url) for m in _ASSET_MIRRORS] if githubish else []
    urls = [url] + mirrors if want_sha else [url]
    total = int(asset.get("size") or 0)
    last_err = "未知错误"
    i = 0
    while i < len(urls):
        u = urls[i]
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
                        _safe_progress(progress, done, length)
            if length and done != length:
                raise OSError(f"下载不完整：{done}/{length} 字节")
            got = ""
            if want_sha:
                if on_verify:
                    try:
                        on_verify()
                    except Exception:            # noqa: BLE001 — UI 回调不该拖垮下载
                        pass
                got = _sha256_file(tmp)
                if got != want_sha:
                    raise OSError(
                        f"SHA256 不匹配（期望 {want_sha[:10]}…，实得 {got[:10]}…）")
            os.replace(tmp, dest)
            return True, "", {"verified": bool(want_sha), "sha256": got, "url": u}
        except Cancelled:
            _rm(tmp)
            return False, "已取消", {"verified": False, "sha256": "", "url": u}
        except Exception as e:                   # noqa: BLE001 — 换源继续试
            last_err = f"{type(e).__name__}: {e}"
            _rm(tmp)
            # 没有校验值时才允许在官方源失败后追加镜像（并保持 verified=False）
            if not want_sha and i == len(urls) - 1 and mirrors:
                urls.extend(mirrors)
            if i < len(urls) - 1:
                time.sleep(0.4)                  # 换源前稍等一下
        i += 1
    return False, last_err, {"verified": False, "sha256": "", "url": ""}


def download(asset, dest, progress=None, timeout=TIMEOUT_DL, want_sha=""):
    """兼容旧签名的薄封装：只回 (ok, err)。要校验结果用 download_ex()。"""
    ok, err, _meta = download_ex(asset, dest, progress, timeout, want_sha)
    return ok, err


# ------------------------------------------------------------------ 解压 / 安装

def extract_zip(zip_path, target_dir, strip_root=None, progress=None):
    """解压 zip 到 target_dir。

    strip_root=None 时自动判断：若 zip 内顶层只有一个目录（如 KARDS/），
    就剥掉它 —— 发行包就是这么打的（安装器同款逻辑）。
    也可以显式传 'KARDS' 或 'KARDS/'，两种写法都接受（见下）。
    """
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n and not n.endswith("/")]
        if strip_root is None:
            tops = {n.split("/", 1)[0] for n in names}
            if len(tops) == 1 and all("/" in n for n in names):
                strip_root = tops.pop() + "/"
            else:
                strip_root = ""
        elif strip_root:
            # ⚠ 必须归一化成「带结尾斜杠」再当前缀剥。
            #   传 'KARDS'（不带斜杠）时，'KARDS/x.exe'.startswith('KARDS') 会命中，
            #   剥完得到 '/x.exe' —— 这在 Windows 上是**绝对路径**，
            #   os.path.join 会直接丢掉 target_dir，于是被 zip-slip 守卫全部拦下，
            #   结果是「一个文件都没解压，却返回成功」。自更新走到这里 =
            #   把用户的游戏目录清成空目录，是最坏的一种失败。
            if not strip_root.endswith("/"):
                strip_root += "/"
        os.makedirs(target_dir, exist_ok=True)
        base = os.path.abspath(target_dir)

        # 第一步：先规划出「真正要写的文件」清单。
        # ⚠ 必须先规划再写，否则进度分母没有正确来源：
        #   - 用 infolist() 的长度当分母 → 含目录项、含被 zip-slip 拦掉的条目，
        #     进度永远到不了 100%（实测卡在 83%）。
        plan = []
        for info in zf.infolist():
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
            plan.append((info, out))

        # 第二步：按计划写盘
        total = len(plan) or 1
        for i, (info, out) in enumerate(plan):
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with zf.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            _safe_progress(progress, i + 1, total)

    # ⚠ 兜底哨兵：包里有文件、我们却一个都没写出来 —— 一定是前缀/路径逻辑出了问题。
    #   宁可报错让更新中止，也绝不能"成功"地装上一个空目录。
    if names and not plan:
        return False, (f"解压结果为空：包内有 {len(names)} 个文件，但一个都没能写出"
                       f"（strip_root={strip_root!r}）")
    return True, ""


def has_meipass():
    """是否是一体式（onefile）打包 —— 资源被解到临时目录 _MEIxxxx。

    ⚠ **不能**拿「有没有 sys._MEIPASS」当判据：
      PyInstaller 6 起对 **onedir 也会设置 _MEIPASS**（指向 exe 旁的
      `_internal/`），照旧判断会把安装版误报成单文件版，
      `can_self_update()` 返回 None → 「无法更新」bug（v1.6.3.8 实测）。
    正确判据：_MEIPASS 是否落在 exe 所在目录**之内**。
      · onedir（新旧布局都算）：exe_dir 或 exe_dir/_internal → 目录内 → False
      · onefile：%TEMP%/_MEIxxxx 临时目录 → 目录外 → True
    """
    if not getattr(sys, "frozen", False):
        return False
    mei = getattr(sys, "_MEIPASS", None)
    if not mei:
        return False
    try:
        rel = os.path.relpath(os.path.abspath(mei),
                              os.path.dirname(os.path.abspath(sys.executable)))
    except ValueError:            # Windows 跨盘符（TEMP 与 exe 不同盘）→ 临时目录
        return True
    return rel.startswith("..")


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
        t.state     # "checking"/"no_update"/"found"/"downloading"/"verifying"
                    #   /"extracting"/"done"/"error"
        t.progress  # 0.0~1.0
        t.message   # 出错原因 / 版本号
        t.verified  # True 已校验 / False 未校验 / None 还没下到
        t.checksum_source  # "digest" / "sums" / ""
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
        self.checksum = ""             # 期望的 SHA256（空 = 这个版本没提供校验值）
        self.checksum_source = ""      # "digest" / "sums" / ""
        self.verified = None           # 到手的包到底校验过没有
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
        # 定校验值要额外抓一次校验文件，可能慢几百毫秒 —— 放在确认「有新版本」
        # 之后做，避免每次启动检查更新都白付这笔开销。
        self.checksum, self.checksum_source = resolve_checksum(
            info.get("assets") or [], asset)
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
                raise Cancelled()

        def on_verify():
            self.state, self.progress = "verifying", 1.0

        ok, err, meta = download_ex(asset, zpath, progress=on_dl,
                                    want_sha=self.checksum, on_verify=on_verify)
        self.verified = bool(meta.get("verified"))
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
