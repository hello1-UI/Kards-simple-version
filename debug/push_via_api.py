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
import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone, timedelta

OWNER, REPO = "hello1-UI", "Kards-simple-version"
REPO_API = f"https://api.github.com/repos/{OWNER}/{REPO}"
TOKEN = os.environ["GITHUB_TOKEN"]


def api(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        return json.loads(body) if body else {}


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

    return {"tree": f["tree"], "parents": f["parents"].split(),
            "author": ident(f["author"]), "committer": ident(f["committer"]),
            "message": msg}


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
            content = git("cat-file", "blob", bsha)
            r = api("POST", f"{REPO_API}/git/blobs",
                    {"content": base64.b64encode(content).decode(),
                     "encoding": "base64"})
            assert r["sha"] == bsha, f"blob SHA 不一致 {path}"
            uploaded_blobs.add(bsha)
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

    api("PATCH", f"{REPO_API}/git/refs/heads/main", {"sha": local, "force": False})
    git("update-ref", "refs/remotes/origin/main", local)
    print(f"=== PUSH_OK ===  main -> {local[:8]}")


if __name__ == "__main__":
    main()
