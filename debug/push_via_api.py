# -*- coding: utf-8 -*-
"""通过 GitHub REST API（api.github.com）推送本地内容 —— 绕过被阻断的 github.com git 端口

C0（README 引导提交）已由 Contents API 创建。本脚本：
  1. 复用远端 C0，向 API 上传全部 blob → tree（应与本地 66338e7 一致）
  2. API 创建远端 C1（parent=C0，message/作者/时间取自本地原提交 d9e642c）
  3. 本地按 GitHub 对象字节规则复刻 C1（hash-object 校验 SHA 相等后才 update-ref）
  4. 远端 PATCH refs/heads/main，本地 update-ref 对齐
令牌从环境变量 GITHUB_TOKEN 读取，不落盘。
"""
import base64
import hashlib
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
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {url} -> HTTP {e.code}: "
                           f"{e.read().decode(errors='replace')[:300]}")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def parse_ident(raw_value):
    name_mail, rest = raw_value.rsplit(">", 1)
    name, mail = name_mail.rsplit("<", 1)
    ts, off = rest.split()
    tz = timezone(timedelta(hours=int(off[:3]), minutes=int(off[0] + off[3:])))
    return {"name": name.strip(), "email": mail.rstrip(">"),
            "ts": int(ts), "off": off}


# ---- 0. 远端 C0（README 引导提交，已存在）----
ref = api("GET", f"{REPO_API}/git/refs/heads/main")
c0 = ref["object"]["sha"]
c0_obj = api("GET", f"{REPO_API}/git/commits/{c0}")
print(f"远端 C0 = {c0[:12]}…  tree={c0_obj['tree']['sha'][:12]}…  "
      f"msg={c0_obj['message'].splitlines()[0][:30]!r}")

# ---- 1. 本地原提交字段 + 新 tree（含 README，已 write-tree）----
old_raw = git("cat-file", "commit", "HEAD").decode()
head, old_msg = old_raw.split("\n\n", 1)
f = {}
for line in head.splitlines():
    k, _, v = line.partition(" ")
    f[k] = v
new_tree = git("write-tree").decode().strip()
print(f"本地新 tree = {new_tree[:12]}…  原提交 = {f['tree'][:12]}…")

# ---- 2. 上传 blob → tree ----
entries = []
for rec in git("ls-tree", "-r", "-z", new_tree).decode().split("\0"):
    if rec:
        meta, path = rec.split("\t", 1)
        mode, typ, sha = meta.split()
        entries.append({"path": path, "mode": mode, "type": typ, "sha": sha})

for i, e in enumerate(entries, 1):
    content = git("cat-file", "blob", e["sha"])
    r = api("POST", f"{REPO_API}/git/blobs",
            {"content": base64.b64encode(content).decode(), "encoding": "base64"})
    if r["sha"] != e["sha"]:
        raise RuntimeError(f"blob SHA 不一致 {e['path']}: {r['sha']} != {e['sha']}")
    print(f"  blob {i}/{len(entries)} OK  {e['path'][:50]}")

r_tree = api("POST", f"{REPO_API}/git/trees",
             {"tree": [{"path": e["path"], "mode": e["mode"], "type": "blob",
                        "sha": e["sha"]} for e in entries]})
print(f"tree: remote={r_tree['sha'][:12]}… local={new_tree[:12]}… "
      f"{'一致' if r_tree['sha'] == new_tree else '!!不一致!!'}")

# ---- 3. API 创建远端 C1 ----
au, co = parse_ident(f["author"]), parse_ident(f["committer"])
r_commit = api("POST", f"{REPO_API}/git/commits", {
    "message": old_msg, "tree": r_tree["sha"], "parents": [c0],
    "author": {"name": au["name"], "email": au["email"],
               "date": datetime.fromtimestamp(au["ts"], timezone(
                   timedelta(hours=int(au["off"][:3]),
                             minutes=int(au["off"][0] + au["off"][3:])))).isoformat()},
    "committer": {"name": co["name"], "email": co["email"],
                  "date": datetime.fromtimestamp(co["ts"], timezone(
                      timedelta(hours=int(co["off"][:3]),
                                minutes=int(co["off"][0] + co["off"][3:])))).isoformat()}})
c1_remote = r_commit["sha"]
print(f"远端 C1 = {c1_remote[:12]}…")

# ---- 4. 本地复刻 C1 对象（SHA 必须相等才提交）----
obj = (f"tree {r_tree['sha']}\nparent {c0}\n"
       f"author {au['name']} <{au['email']}> {au['ts']} {au['off']}\n"
       f"committer {co['name']} <{co['email']}> {co['ts']} {co['off']}\n\n")
c1_local = None
for msg in (old_msg, old_msg.rstrip("\n") + "\n", old_msg.rstrip("\n"),
            old_msg.strip() + "\n"):
    candidate = (obj + msg).encode()
    sha = hashlib.sha1(b"commit %d\0" % len(candidate) + candidate).hexdigest()
    if sha == c1_remote:
        c1_local = sha
        subprocess.run(["git", "hash-object", "-t", "commit", "-w", "--stdin"],
                       input=candidate, check=True, capture_output=True)
        print(f"本地复刻成功: {sha[:12]}…")
        break
if c1_local is None:
    raise RuntimeError("无法复刻远端提交对象（消息字节不匹配）")

# ---- 5. 双端对齐 main ----
subprocess.run(["git", "update-ref", "refs/heads/main", c1_local],
               check=True, capture_output=True)
subprocess.run(["git", "reset", "--hard"], check=True, capture_output=True)
api("PATCH", f"{REPO_API}/git/refs/heads/main",
    {"sha": c1_remote, "force": False})

local_head = git("rev-parse", "HEAD").decode().strip()
ref2 = api("GET", f"{REPO_API}/git/refs/heads/main")
commits = api("GET", f"{REPO_API}/commits?per_page=10")
print(f"本地 HEAD = {local_head[:12]}…  远端 main = {ref2['object']['sha'][:12]}…  "
      f"{'一致' if local_head == ref2['object']['sha'] else '!!不一致!!'}")
print(f"远端提交 {len(commits)} 个: "
      + " | ".join(c["commit"]["message"].splitlines()[0][:20] for c in commits))
print("\n=== API_PUSH_OK ===" if local_head == ref2["object"]["sha"]
      else "\n=== 需人工检查 ===")
