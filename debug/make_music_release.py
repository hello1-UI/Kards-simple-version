# -*- coding: utf-8 -*-
"""把「可选音乐包」发布成独立 Release（固定 tag = music-pack）

为什么单独发
--------------------------------------------------------------------------
曲库 4.3 GB / 251 首，既超过 GitHub 单资产 2 GB 限制（要切 3 卷），
也不该让每个只想玩牌的人先下 4 GB。所以：

    · 游戏安装包（KARDS.zip / Setup.zip）**不含任何音乐**
    · 音乐只放在 tag=`music-pack` 的 Release 里，按需下载

⚠ 这个 Release 必须标成 **prerelease**：GitHub 的 `/releases/latest`
   取的是「最近一个非预发布 Release」，不标就会把音乐包顶成"最新版"，
   客户端的自动更新会以为自己有新版本可装。

用法:
    GITHUB_TOKEN=<token> python debug/make_music_release.py
    GITHUB_TOKEN=<token> python debug/make_music_release.py --check
    GITHUB_TOKEN=<token> python debug/make_music_release.py --dir assets/musicpack

行为:
    1. 收集 assets/musicpack/music*.zip（分卷顺序：music.zip、music-2.zip…）
    2. 本地算 SHA256，生成 SHA256SUMS.txt 一起上传（客户端逐卷校验）
    3. Release 已存在 → 复用；缺失/多余的资产按名字对齐（删旧传新）
    4. 单卷 > 2 GB 直接报错（GitHub 硬限制），提示用 pack_music.py 重切

与 debug/make_release.py 的分工:
    那个发**游戏版本**（v1.3.0.6 之类，latest 会被它更新）；
    这个发**资源包**（tag 固定，内容随曲库变，不参与版本比较）。
"""
import hashlib
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# GitHub 域名一律直连（本机代理对大请求会 502）
_GH_HOSTS = ("api.github.com,uploads.github.com,github.com,"
             "codeload.github.com,raw.githubusercontent.com,"
             "objects.githubusercontent.com")
for _k in ("no_proxy", "NO_PROXY"):
    os.environ[_k] = ",".join(x for x in (os.environ.get(_k, ""), _GH_HOSTS) if x)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gh_dns                                        # noqa: E402

gh_dns.install()

OWNER, REPO = "hello1-UI", "Kards-simple-version"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"
TAG = "music-pack"
TOKEN = os.environ.get("GITHUB_TOKEN")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MAX_ASSET = 2 * 1024 ** 3 - 4096        # GitHub 单资产上限 2 GB（留点余量）

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def api(method, url, payload=None, timeout=60, tries=3):
    data, headers = None, {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    last = "?"
    for i in range(1, tries + 1):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {TOKEN}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("Connection", "close")
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                return r.status, (json.loads(body) if body else {})
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                body = json.loads(body)
            except Exception:                        # noqa: BLE001
                body = body[:300]
            if e.code in (429, 500, 502, 503, 504) and i < tries:
                last = f"HTTP {e.code}"
            else:
                return e.code, body
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            last = f"{type(e).__name__}: {e}"[:120]
        if i < tries:
            wait = min(2 * i, 15)
            print(f"    网络异常（{last}），{wait}s 后重试 {i}/{tries - 1}")
            time.sleep(wait)
    return 0, f"连续 {tries} 次网络失败：{last}"


def collect(folder):
    """收集分卷 zip，按「卷号」排序（music.zip → music-2.zip → music-10.zip）"""
    out = []
    if not os.path.isdir(folder):
        return out
    for fn in os.listdir(folder):
        low = fn.lower()
        if low.startswith("music") and low.endswith(".zip"):
            out.append(os.path.join(folder, fn))

    def key(p):
        stem = os.path.splitext(os.path.basename(p))[0].lower()
        digits = "".join(ch if ch.isdigit() else " " for ch in stem).split()
        return (0 if len(stem) <= 5 else 1, [int(x) for x in digits] or [0], stem)

    out.sort(key=key)
    return out


def sha256_file(path, chunk=1024 * 1024, label=""):
    h = hashlib.sha256()
    total = os.path.getsize(path) or 1
    done = 0
    t0 = time.time()
    last = 0.0
    with open(path, "rb") as f:
        for blob in iter(lambda: f.read(chunk), b""):
            h.update(blob)
            done += len(blob)
            now = time.time()
            if label and now - last > 0.5:
                last = now
                pct = done * 100.0 / total
                speed = done / 1048576.0 / max(0.001, now - t0)
                print(f"\r    {label}: {pct:5.1f}%  {speed:6.1f} MB/s",
                      end="", flush=True)
    if label:
        print("\r" + " " * 60 + "\r", end="")
    return h.hexdigest()


def write_sums(paths, sums_path):
    lines = []
    for p in paths:
        digest = sha256_file(p, label=os.path.basename(p))
        lines.append(f"{digest}  {os.path.basename(p)}")
        print(f"  {os.path.basename(p)}  {digest[:16]}…")
    with open(sums_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return sums_path


def upload_stream(rid, path):
    """流式上传（不把 1.5 GB 读进内存）。返回 (ok, msg)"""
    name = os.path.basename(path)
    size = os.path.getsize(path)
    if size > MAX_ASSET:
        return False, (f"{name} 有 {size/1024**3:.2f} GB，超过 GitHub 单资产 2 GB 限制；"
                       "请用 debug/pack_music.py 重新切分为更小的卷")
    q = urllib.parse.quote(name)
    url_path = f"/repos/{OWNER}/{REPO}/releases/{rid}/assets?name={q}"
    t0 = time.time()
    sent = 0
    try:
        conn = http.client.HTTPSConnection("uploads.github.com", timeout=1800)
        conn.putrequest("POST", url_path)
        conn.putheader("Authorization", f"Bearer {TOKEN}")
        conn.putheader("Accept", "application/vnd.github+json")
        conn.putheader("Content-Type", "application/zip")
        conn.putheader("Content-Length", str(size))
        conn.putheader("Connection", "close")
        conn.endheaders()
        with open(path, "rb") as f:
            while True:
                blob = f.read(1024 * 1024)
                if not blob:
                    break
                conn.send(blob)
                sent += len(blob)
                if sent % (64 * 1024 * 1024) < 1024 * 1024:
                    pct = sent * 100.0 / max(1, size)
                    speed = sent / 1048576.0 / max(0.001, time.time() - t0)
                    print(f"\r    {name}: {pct:5.1f}%  {speed:6.2f} MB/s",
                          end="", flush=True)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        print("\r" + " " * 64 + "\r", end="")
        if resp.status in (200, 201):
            try:
                info = json.loads(body or b"{}")
            except Exception:                        # noqa: BLE001
                info = {}
            return True, f"{info.get('size', size)/1048576:.1f} MB"
        return False, f"HTTP {resp.status} {body[:200].decode('utf-8', 'replace')}"
    except (http.client.HTTPException, OSError, TimeoutError) as e:
        print("\r" + " " * 64 + "\r", end="")
        return False, f"{type(e).__name__}: {e}"


def ensure_release(notes):
    st, rel = api("GET", f"{API}/releases/tags/{TAG}")
    if st == 200:
        print(f"  复用 Release (id={rel['id']})")
        if not rel.get("prerelease"):
            st2, _ = api("PATCH", f"{API}/releases/{rel['id']}",
                         {"prerelease": True, "body": notes})
            if st2 == 200:
                print("  已标记为预发布（避免抢占 /releases/latest）")
        return rel
    if st != 404:
        raise SystemExit(f"查询 Release 失败: {st} {rel}")
    st, rel = api("POST", f"{API}/releases", {
        "tag_name": TAG,
        "name": "KARDS 简化版 · 可选音乐包",
        "body": notes,
        "draft": False,
        "prerelease": True,          # 关键：不进 latest
    })
    if st not in (200, 201):
        raise SystemExit(f"创建 Release 失败: {st} {rel}")
    print(f"  创建成功: {rel['html_url']}")
    return rel


def main():
    if not TOKEN:
        raise SystemExit("请设置 GITHUB_TOKEN=<token>")

    folder = os.path.join(ROOT, "assets", "musicpack")
    args = sys.argv[1:]
    if "--dir" in args:
        folder = os.path.abspath(args[args.index("--dir") + 1])

    paths = collect(folder)
    if not paths:
        raise SystemExit(f"{folder} 里没有 music*.zip；先跑 python debug/pack_music.py")

    total = sum(os.path.getsize(p) for p in paths)
    print(f"目录 = {folder}")
    print(f"分卷 = {len(paths)} 个 / {total/1024**3:.2f} GB")
    for p in paths:
        print(f"  {os.path.basename(p)}  {os.path.getsize(p)/1048576:.1f} MB")
    too_big = [p for p in paths if os.path.getsize(p) > MAX_ASSET]
    if too_big:
        raise SystemExit("以下分卷超过 2 GB，GitHub 传不上去：\n  "
                         + "\n  ".join(os.path.basename(p) for p in too_big))

    notes = ("KARDS 简化版 · 可选音乐包\n\n"
             f"{len(paths)} 卷共 {total/1024**3:.1f} GB。游戏默认不带曲库：\n\n"
             "- 游戏内：设置 → 其它 →「可选音乐包」→ 下载并安装\n"
             "- 或手动把 music*.zip 放到数据目录（设置里能看到路径），重启游戏自动解压\n\n"
             "分卷必须全部下载，缺一卷会少一部分曲目（不影响游戏运行）。")

    if "--check" in args:
        st, rel = api("GET", f"{API}/releases/tags/{TAG}")
        if st != 200:
            print("远端：还没有 music-pack Release")
            return
        have = {a["name"]: a["size"] for a in rel.get("assets") or []}
        print("远端：")
        missing = []
        for p in paths:
            n = os.path.basename(p)
            size = have.get(n)
            if size is None:
                missing.append(n)
                print(f"  ✗ {n} 缺失")
            elif size != os.path.getsize(p):
                missing.append(n)
                print(f"  ≠ {n} 大小不同（远端 {size/1048576:.1f} MB）")
            else:
                print(f"  ✓ {n} {size/1048576:.1f} MB")
        print("需要重新上传" if missing else "远端已是最新")
        return

    rel = ensure_release(notes)
    rid = rel["id"]
    sums = write_sums(paths, os.path.join(ROOT, "SHA256SUMS.music.txt"))

    # 远端已有同名资产 → 先删，再传（GitHub 不允许同名覆盖）
    st, cur = api("GET", f"{API}/releases/{rid}/assets?per_page=100")
    existing = {}
    if st == 200:
        for a in cur if isinstance(cur, list) else []:
            existing[a["name"]] = a
    want = {os.path.basename(p): p for p in paths}
    want["SHA256SUMS.txt"] = sums
    # 先清掉远端多出来的旧资产（比如原来切了 4 卷、现在只有 3 卷）。
    # 同名资产留给下面的上传循环判断：大小一致就跳过（1.5 GB 重传很贵）。
    for name, a in existing.items():
        if name not in want:
            print(f"  删除多余资产 {name}")
            api("DELETE", f"{API}/releases/assets/{a['id']}")

    failed = []
    for name, p in want.items():
        if name in existing and name != "SHA256SUMS.txt":
            size = existing[name].get("size")
            if size == os.path.getsize(p):
                print(f"  跳过（远端已存在 {size/1048576:.1f} MB）: {name}")
                continue
            print(f"  替换 {name}（远端 {size/1048576:.1f} MB ≠ 本地 "
                  f"{os.path.getsize(p)/1048576:.1f} MB）")
            api("DELETE", f"{API}/releases/assets/{existing[name]['id']}")
        elif name in existing:
            api("DELETE", f"{API}/releases/assets/{existing[name]['id']}")

        done = False
        for attempt in range(1, 4):
            print(f"  上传 {name}（第 {attempt} 次）…")
            ok, msg = upload_stream(rid, p)
            if ok:
                print(f"    完成 {msg}")
                done = True
                break
            print(f"    失败: {msg}")
            time.sleep(3 * attempt)
        if not done:
            failed.append(name)

    if failed:
        raise SystemExit(f"\n=== MUSIC_RELEASE_PARTIAL === 上传失败: {failed}\n"
                         f"Release: {rel['html_url']}（重跑本脚本会跳过已完成的卷）")
    print(f"\n=== MUSIC_RELEASE_OK === {rel['html_url']}")


if __name__ == "__main__":
    main()
