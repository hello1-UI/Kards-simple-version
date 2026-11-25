# -*- coding: utf-8 -*-
"""把最新 kards_server.py / kards_rank.py 同步进云端桥接部署目录。

用法：
    python debug/pack_relay.py          # 同步 + 校验
    python debug/pack_relay.py --check  # 只校验不覆盖（CI/发版前用）

云端部署目录 cloud/kards_relay/ 里的 kards_server.py 是独立副本
（部署沙箱只上传该目录）。改了服务器代码后先跑本脚本再重新发布，
否则云端跑的还是旧协议。
"""
import hashlib
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELAY = os.path.join(ROOT, "cloud", "kards_relay")
FILES = ["kards_server.py", "kards_rank.py"]


def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    check_only = "--check" in sys.argv
    bad = []
    for name in FILES:
        src = os.path.join(ROOT, name)
        dst = os.path.join(RELAY, name)
        if not os.path.exists(dst):
            bad.append((name, "副本缺失"))
            continue
        if digest(src) != digest(dst):
            bad.append((name, "副本与主文件不一致"))
    if check_only:
        if bad:
            for name, why in bad:
                print(f"  ✗ {name}: {why}")
            print("云端副本过期 —— 先跑 python debug/pack_relay.py 再重新发布")
            sys.exit(1)
        print("云端副本与主文件一致 ✓")
        return
    for name in FILES:
        shutil.copy2(os.path.join(ROOT, name), os.path.join(RELAY, name))
        print(f"  → 已同步 {name}")
    print("同步完成。重新发布 cloud/kards_relay 后生效。")


if __name__ == "__main__":
    main()
