# -*- coding: utf-8 -*-
"""一次性推送驱动：远程 main（e7b4569）不在本地历史（本地 v1.6.1.3 为快照重建），
push_via_api.main() 的 rev-list 会炸。已核实远程领先提交的两个文件与本地逐字节
一致（blob SHA 相同），故把提交列表改为 63da1d1..HEAD（本地已知远端内容等价），
上传全部对象后 force 移动远程 ref，最后把 origin/main 对齐到本地 HEAD。
"""
import base64
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import push_via_api as P          # noqa: E402  （模块导入即完成 gh_dns.install）

BASE = "63da1d17eee07c9bab27ff02d5bcbdad8d3337ca"


def main():
    local = P.git("rev-parse", "HEAD").decode().strip()
    to_push = P.git("rev-list", "--reverse", f"{BASE}..{local}").decode().split()
    print(f"待推送 {len(to_push)} 个提交: "
          + " | ".join(s[:8] for s in to_push))

    uploaded_blobs = set()
    keep = P.remote_blobs()
    print(f"远端已有 blob {len(keep)} 个（按本地 origin/main 树估算）")
    n_new = n_skip = 0
    for sha in to_push:
        c = P.parse_commit(sha)
        for rec in P.git("ls-tree", "-r", "-z", c["tree"]).decode().split("\0"):
            if not rec:
                continue
            meta, path = rec.split("\t", 1)
            _, _, bsha = meta.split()
            if bsha in uploaded_blobs:
                continue
            if bsha in keep:
                uploaded_blobs.add(bsha)
                n_skip += 1
                continue
            try:
                content = P.git("cat-file", "blob", bsha)
            except subprocess.CalledProcessError:
                content = P.fetch_blob(bsha)
                print(f"    从远端取回缺失内容 {path}"
                      f"（{len(content)/1048576:.1f} MB）")
            big = len(content) >= 1048576
            if big:
                print(f"    ↑ 上传大文件 {len(content)/1048576:5.1f} MB  {path}")
            r = P.api("POST", f"{P.REPO_API}/git/blobs",
                      {"content": base64.b64encode(content).decode(),
                       "encoding": "base64"},
                      timeout=600 if big else 180)
            assert r["sha"] == bsha, f"blob SHA 不一致 {path}"
            uploaded_blobs.add(bsha)
            n_new += 1
        entries = []
        for rec in P.git("ls-tree", "-r", "-z", c["tree"]).decode().split("\0"):
            if rec:
                meta, path = rec.split("\t", 1)
                mode, _, bsha = meta.split()
                entries.append({"path": path, "mode": mode,
                                "type": "blob", "sha": bsha})
        rt = P.api("POST", f"{P.REPO_API}/git/trees", {"tree": entries})
        assert rt["sha"] == c["tree"], f"tree SHA 不一致: {rt['sha']} != {c['tree']}"
        rc = P.api("POST", f"{P.REPO_API}/git/commits", {
            "message": c["message"], "tree": rt["sha"],
            "parents": c["parents"],
            "author": {**c["author"], "date": P.iso_parts(c["author"])},
            "committer": {**c["committer"], "date": P.iso_parts(c["committer"])}})
        assert rc["sha"] == sha, f"commit SHA 不一致: {rc['sha']} != {sha}"
        print(f"  已上传 {sha[:8]}  {c['message'].splitlines()[0][:40]}")

    print(f"blob: 新传 {n_new} 个，复用远端已有 {n_skip} 个")
    P.api("PATCH", f"{P.REPO_API}/git/refs/heads/main",
          {"sha": local, "force": True})
    P.git("update-ref", "refs/remotes/origin/main", local)
    print(f"=== PUSH_OK ===  main -> {local[:8]}")


if __name__ == "__main__":
    main()
