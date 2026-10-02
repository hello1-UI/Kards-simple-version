# -*- coding: utf-8 -*-
"""GitHub Release 上传工具

用法:
    GITHUB_TOKEN=<token> python debug/make_release.py [tag] [资产1 资产2 ...]

不带参数时：
    tag  = 从 KARDS.py 的 VERSION 推导（v1.2.0.3）
    资产 = KARDS.zip + KARDS_SimpleVersion-Setup.zip（存在才上传）

行为：
    1. 若同名 tag 的 Release 已存在，先删掉（便于反复执行）
    2. POST /releases 创建 Release
    3. 逐个上传资产（二进制 POST，timeout 放宽到 600s）

配套: 推送代码用 debug/push_via_api.py（推送 ≠ 发 Release，两者分开）
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gh_dns                                        # noqa: E402
gh_dns.install()

OWNER, REPO = "hello1-UI", "Kards-simple-version"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"
TOKEN = os.environ.get("GITHUB_TOKEN")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def api(method, url, payload=None, raw=None, ctype=None, timeout=60):
    data, headers = None, {}
    if raw is not None:
        data = raw
        headers["Content-Type"] = ctype or "application/octet-stream"
    elif payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
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
        except Exception:
            body = body[:400]
        return e.code, body


def version_tag():
    src = open(os.path.join(ROOT, "KARDS.py"), encoding="utf-8").read()
    m = re.search(r"^VERSION\s*=\s*\(([^)]+)\)", src, re.M)
    if not m:
        raise SystemExit("找不到 VERSION 常量")
    nums = [p.strip() for p in m.group(1).split(",") if p.strip()]
    return "v" + ".".join(nums)


def main():
    if not TOKEN:
        raise SystemExit("请设置 GITHUB_TOKEN=<token>")

    args = sys.argv[1:]
    tag = args[0] if args and args[0].startswith("v") else version_tag()
    if args and args[0].startswith("v"):
        assets = args[1:]
    else:
        assets = args or ["KARDS.zip", "KARDS_SimpleVersion-Setup.zip"]

    paths = []
    for a in assets:
        p = a if os.path.isabs(a) else os.path.join(ROOT, a)
        if os.path.isfile(p):
            paths.append(p)
        else:
            print(f"⚠ 跳过（不存在）: {a}")
    if not paths:
        raise SystemExit("没有可上传的资产")

    print(f"tag = {tag}")
    print("资产:")
    for p in paths:
        print(f"  {os.path.basename(p)}  {os.path.getsize(p)/1048576:.1f} MB")

    # 1. 删掉同名 tag 的旧 Release（可重复执行）
    st, rel = api("GET", f"{API}/releases/tags/{tag}")
    if st == 200:
        print(f"  已存在 Release (id={rel['id']})，先删除 ...")
        api("DELETE", f"{API}/releases/{rel['id']}")
    elif st != 404:
        raise SystemExit(f"查询 Release 失败: {st} {rel}")

    # 2. 创建 Release
    body = (f"KARDS 简化版 {tag}\n\n"
            "下载 `KARDS_SimpleVersion-Setup.zip` → 解压 → 双击 `KARDS安装器.exe`，"
            "安装时可自定义安装路径。")
    st, rel = api("POST", f"{API}/releases", {
        "tag_name": tag,
        "name": f"KARDS 简化版 {tag}",
        "body": body,
        "draft": False,
        "prerelease": False,
    })
    if st not in (200, 201):
        raise SystemExit(f"创建 Release 失败: {st} {rel}")
    print(f"  创建成功: {rel['html_url']}")

    # 3. 上传资产
    up = rel["upload_url"].split("{")[0]
    for p in paths:
        name = os.path.basename(p)
        print(f"  上传 {name} ...", end="", flush=True)
        with open(p, "rb") as f:
            blob = f.read()
        st, res = api("POST", f"{up}?name={urllib.parse.quote(name)}",
                      raw=blob, ctype="application/zip", timeout=600)
        if st in (200, 201):
            print(f" ✓ {res.get('size', 0)/1048576:.1f} MB")
        else:
            print(f" ✗ {st} {res}")

    print(f"\n=== RELEASE_OK === {rel['html_url']}")


if __name__ == "__main__":
    main()
