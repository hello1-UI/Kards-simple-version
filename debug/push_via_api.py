# -*- coding: utf-8 -*-
"""通用 GitHub API 推送工具 —— 本机 github.com git 端口被阻断时的替代通道

用法:
    GITHUB_TOKEN=<classic token, repo 权限> python debug/push_via_api.py

原理: 经 api.github.com 用 Git Data API 逐对象上传（blob→tree→commit），最后移动
refs/heads/main。所有对象按内容寻址，提交逐字节复刻本地对象，SHA 与本地完全一致。
限制: 仅支持快进（远程 main 是本地 HEAD 的祖先）；历史分叉需人工处理。

配套: 版本升级用 python debug/bump_version.py a|b|c|d
"""
import base64
import http.client
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

# 本机代理对 GitHub 的大请求会 502 / 中途掐断（10053 / IncompleteRead），
# GitHub 相关域名一律绕过代理直连，可达 IP 由 gh_dns 负责。
_GH_HOSTS = ("api.github.com,uploads.github.com,github.com,"
             "codeload.github.com,raw.githubusercontent.com,"
             "objects.githubusercontent.com")
for _k in ("no_proxy", "NO_PROXY"):
    _cur = os.environ.get(_k, "")
    os.environ[_k] = ",".join(x for x in (_cur, _GH_HOSTS) if x)

# 本机 DNS 对 github.com 系列域名返回被污染的不可达 IP，这里做进程级解析重定向
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gh_dns
gh_dns.install()

OWNER, REPO = "hello1-UI", "Kards-simple-version"
REPO_API = f"https://api.github.com/repos/{OWNER}/{REPO}"
TOKEN = os.environ["GITHUB_TOKEN"]


def api(method, url, payload=None, tries=5, timeout=180, allow=()):
    """调一次 API；网络抖动 / 5xx / 429 自动退避重试。

    allow 里的状态码不抛错而是返回 None（用于 blob 存在性探测的 404）。
    """
    data = json.dumps(payload).encode() if payload is not None else None
    last = "?"
    for i in range(1, tries + 1):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {TOKEN}")
        req.add_header("Accept", "application/vnd.github+json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        req.add_header("Connection", "close")     # 代理环境关掉长连接，避免复用被掐
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            body = e.read()
            if e.code in allow:
                return None
            if e.code in (429, 500, 502, 503, 504) and i < tries:
                last = f"HTTP {e.code}"
            else:
                try:
                    msg = json.loads(body).get("message", "")
                except Exception:
                    msg = body[:200].decode("utf-8", "replace")
                raise SystemExit(f"{method} {url[:80]} -> HTTP {e.code} {msg}")
        except (urllib.error.URLError, http.client.HTTPException,
                socket.timeout, OSError) as e:
            last = f"{type(e).__name__}: {e}"[:120]
        if i < tries:
            wait = min(2 * i, 15)
            print(f"    网络异常（{last}），{wait}s 后重试 {i}/{tries - 1}")
            time.sleep(wait)
    raise SystemExit(f"{method} {url[:80]} 连续 {tries} 次失败：{last}")


def blob_present(sha):
    """远端是否已有该 blob（注意：会连内容一起下载，只适合小文件）"""
    return api("GET", f"{REPO_API}/git/blobs/{sha}", allow=(404,), tries=3) is not None


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def parse_commit(sha):
    """解析本地提交对象 -> 字段字典"""
    raw = git("cat-file", "commit", sha).decode()
    head, msg = raw.split("\n\n", 1)
    f = dict(l.partition(" ")[::2] for l in head.splitlines())

    def ident(v):
        nm, rest = v.rsplit(">", 1)
        name, mail = nm.rsplit("<", 1)
        ts, off = rest.split()
        tz = timezone(timedelta(hours=int(off[:3]), minutes=int(off[0] + off[3:])))
        return {"name": name.strip(), "email": mail.rstrip(">"),
                "date": datetime.fromtimestamp(int(ts), tz).isoformat()}

    return {"tree": f["tree"], "parents": f.get("parent", "").split(),
            "author": ident(f["author"]), "committer": ident(f["committer"]),
            "message": msg}


def remote_blobs():
    """origin/main 树里已存在的 blob —— 远端必然已存，缺内容也不用上传

    本仓库是 blob:none 部分克隆，历史里没检出过的文件本地没有内容，
    懒加载又要访问被墙的 github.com；这些老文件远端本来就有，直接跳过即可。
    """
    try:
        tree = git("rev-parse", "origin/main^{tree}").decode().strip()
        out = git("ls-tree", "-r", "-z", tree).decode()
    except subprocess.CalledProcessError:
        return set()
    shas = set()
    for rec in out.split("\0"):
        if rec:
            shas.add(rec.split("\t")[0].split()[-1])
    return shas


def fetch_blob(sha):
    """内容既不在本地、又不在远端旧树里：经 API 取回来写进本地对象库"""
    d = api("GET", f"{REPO_API}/git/blobs/{sha}", timeout=600)
    raw = base64.b64decode(d["content"])
    r = subprocess.run(["git", "hash-object", "-w", "--stdin"],
                       input=raw, capture_output=True, check=True)
    got = r.stdout.decode().strip()
    assert got == sha, f"取回的 blob SHA 不一致 {got} != {sha}"
    return raw


def iso_parts(ident):
    z = datetime.fromisoformat(ident["date"]).strftime("%z")
    return ident["date"][:19] + z[:3] + ":" + z[3:]


def main():
    remote_ref = api("GET", f"{REPO_API}/git/refs/heads/main")
    remote = remote_ref["object"]["sha"]
    local = git("rev-parse", "HEAD").decode().strip()
    if local == remote:
        print("本地与远程一致，无需推送")
        return

    to_push = git("rev-list", "--reverse", f"{remote}..{local}").decode().split()
    if not to_push:
        raise SystemExit("远程不在本地历史中（需要 force），本工具不支持——请人工处理")
    print(f"待推送 {len(to_push)} 个提交: " + " | ".join(s[:8] for s in to_push))

    uploaded_blobs = set()
    keep = remote_blobs()
    n_new = n_skip = 0
    for sha in to_push:
        c = parse_commit(sha)
        # 上传该提交树引用的全部 blob（内容寻址，重复上传无害、自动去重）
        for rec in git("ls-tree", "-r", "-z", c["tree"]).decode().split("\0"):
            if not rec:
                continue
            meta, path = rec.split("\t", 1)
            _, _, bsha = meta.split()
            if bsha in uploaded_blobs:
                continue
            if bsha in keep:
                # 老版本已存在远端的文件，本地没内容也不必管
                uploaded_blobs.add(bsha)
                n_skip += 1
                continue
            try:
                content = git("cat-file", "blob", bsha)
            except subprocess.CalledProcessError:
                content = fetch_blob(bsha)
                print(f"    从远端取回缺失内容 {path}（{len(content)/1048576:.1f} MB）")
            big = len(content) >= 1048576
            if big:
                print(f"    ↑ 上传大文件 {len(content)/1048576:5.1f} MB  {path}")
            r = api("POST", f"{REPO_API}/git/blobs",
                    {"content": base64.b64encode(content).decode(),
                     "encoding": "base64"},
                    timeout=600 if big else 180)
            assert r["sha"] == bsha, f"blob SHA 不一致 {path}"
            uploaded_blobs.add(bsha)
            n_new += 1
        # tree
        entries = []
        for rec in git("ls-tree", "-r", "-z", c["tree"]).decode().split("\0"):
            if rec:
                meta, path = rec.split("\t", 1)
                mode, _, bsha = meta.split()
                entries.append({"path": path, "mode": mode,
                                "type": "blob", "sha": bsha})
        rt = api("POST", f"{REPO_API}/git/trees", {"tree": entries})
        assert rt["sha"] == c["tree"], f"tree SHA 不一致: {rt['sha']} != {c['tree']}"
        # commit
        rc = api("POST", f"{REPO_API}/git/commits", {
            "message": c["message"], "tree": rt["sha"], "parents": c["parents"],
            "author": {**c["author"], "date": iso_parts(c["author"])},
            "committer": {**c["committer"], "date": iso_parts(c["committer"])}})
        assert rc["sha"] == sha, f"commit SHA 不一致: {rc['sha']} != {sha}"
        print(f"  已上传 {sha[:8]}  {c['message'].splitlines()[0][:40]}")

    print(f"blob: 新传 {n_new} 个，复用远端已有 {n_skip} 个")
    api("PATCH", f"{REPO_API}/git/refs/heads/main", {"sha": local, "force": False})
    git("update-ref", "refs/remotes/origin/main", local)
    print(f"=== PUSH_OK ===  main -> {local[:8]}")


if __name__ == "__main__":
    main()
