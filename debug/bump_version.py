# -*- coding: utf-8 -*-
"""版本号升级工具

用法:
    python debug/bump_version.py d     # 补丁修复  (1.0.0.0 -> 1.0.0.1)
    python debug/bump_version.py c     # 赛季更新  (1.0.0.5 -> 1.0.1.0)
    python debug/bump_version.py b     # 卡牌更新  (1.0.1.0 -> 1.1.0.0)
    python debug/bump_version.py a     # 重要修复  (1.2.0.0 -> 2.0.0.0)

规则: 版本 a.b.c.d —— a:重要修复(1位) b:卡牌更新(2位) c:赛季更新(2位) d:补丁修复(3位)
     某位 +1 后, 其右侧所有位清零。
自动完成: 修改 kards_gui.py 的 VERSION 元组 + git 提交。
（推送到 GitHub 用: GITHUB_TOKEN=xxx python debug/push_via_api.py）
"""
import re
import subprocess
import sys

TARGET = "kards_gui.py"
SEG_NAMES = {"a": "重要修复", "b": "卡牌更新", "c": "赛季更新", "d": "补丁修复"}
SEG_IDX = {"a": 0, "b": 1, "c": 2, "d": 3}
PATTERN = re.compile(r"^VERSION = \((\d+), (\d+), (\d+), (\d+)\)", re.M)


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SEG_NAMES:
        print(__doc__)
        sys.exit(1)
    seg = sys.argv[1]

    src = open(TARGET, encoding="utf-8").read()
    m = PATTERN.search(src)
    if not m:
        sys.exit("错误: 未在 kards_gui.py 中找到 VERSION 元组")
    old = [int(x) for x in m.groups()]
    idx = SEG_IDX[seg]
    new = old[:idx] + [old[idx] + 1] + [0] * (3 - idx)
    ver = ".".join(map(str, new))

    src = src[:m.start()] + f"VERSION = ({new[0]}, {new[1]}, {new[2]}, {new[3]})" + src[m.end():]
    open(TARGET, "w", encoding="utf-8", newline="").write(src)

    msg = f"版本升级至 v{ver}（{SEG_NAMES[seg]}）"
    git("add", TARGET)
    git("commit", "-m", msg)
    print(f"{old} -> {new}")
    print(f"已提交: {msg}")
    print("推送到 GitHub: GITHUB_TOKEN=<token> python debug/push_via_api.py")


if __name__ == "__main__":
    main()
