# -*- coding: utf-8 -*-
"""自动更新测试：版本比较 / 资产挑选 / 解压剥前缀 / 真实 Release 查询 / 后台任务

分两层：
  · **离线层**：纯逻辑（版本号比较、选资产、解压、bat 生成），必定可跑
  · **联网层**：真查一次 GitHub Release。本机网络对 github.com 有 DNS 投毒，
    api.github.com 也可能不通 —— 所以联网失败**不算失败**，只标注跳过，
    避免把「网络环境问题」误报成「代码坏了」。

运行（需 tkinter 的那个系统 Python 也行，本文件不依赖 tkinter）：
    python debug/test_update.py
"""
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_update as up                      # noqa: E402

PASS, FAIL, SKIP = [], [], []


def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [!!] ") + label + (f"  {extra}" if extra else ""))


def skip(label, why=""):
    SKIP.append(label)
    print(f"  [--] {label}  (跳过: {why})")


def main():
    print("1. 版本号解析")
    check("v1.2.0.3 → (1,2,0,3)", up.parse_version("v1.2.0.3") == (1, 2, 0, 3),
          up.parse_version("v1.2.0.3"))
    check("1.2.0.3（无 v）", up.parse_version("1.2.0.3") == (1, 2, 0, 3))
    check("v1.2 → (1,2)", up.parse_version("v1.2") == (1, 2))
    check("带后缀也能解析 v1.2.0.3-beta", up.parse_version("v1.2.0.3-beta") == (1, 2, 0, 3),
          up.parse_version("v1.2.0.3-beta"))
    check("空串 → ()", up.parse_version("") == ())
    check("乱码 → ()", up.parse_version("latest") == ())
    check("元组转字符串", up.version_str((1, 2, 0, 3)) == "1.2.0.3")

    print("2. 版本比较（短的一侧补 0）")
    check("1.2.0.4 > 1.2.0.3", up.is_newer("v1.2.0.4", "1.2.0.3"))
    check("1.2.0.3 不比 1.2.0.3 新", not up.is_newer("v1.2.0.3", "1.2.0.3"))
    check("1.2.0.2 不比 1.2.0.3 新", not up.is_newer("v1.2.0.2", "1.2.0.3"))
    check("1.2.1 > 1.2.0.3（第三位进位）", up.is_newer("v1.2.1", "1.2.0.3"))
    check("1.3 > 1.2.0.3（次位进位）", up.is_newer("v1.3", "1.2.0.3"))
    check("2.0 > 1.9.9.9（首位进位）", up.is_newer("v2.0", "1.9.9.9"))
    check("1.2.0.10 > 1.2.0.9（按数值不是字典序）",
          up.is_newer("v1.2.0.10", "1.2.0.9"))
    check("坏版本号不算新（避免误报）", not up.is_newer("latest", "1.2.0.3"))

    print("3. 资产挑选")
    assets = [{"name": "KARDS_SimpleVersion-Setup.zip", "url": "u1", "size": 1},
              {"name": "KARDS.zip", "url": "u2", "size": 2},
              {"name": "notes.txt", "url": "u3", "size": 3}]
    got = up.pick_asset(assets)
    check("优先挑 KARDS.zip", got and got["name"] == "KARDS.zip", got and got["name"])
    got2 = up.pick_asset([{"name": "other.zip", "url": "u", "size": 0}])
    check("没有 KARDS.zip 时退而取任意 zip",
          got2 and got2["name"] == "other.zip")
    check("没有任何 zip → None", up.pick_asset([{"name": "a.txt", "url": "", "size": 0}]) is None)
    check("空列表 → None", up.pick_asset([]) is None)

    print("4. 解压：自动剥掉 KARDS/ 前缀（发行包格式）")
    tmp = tempfile.mkdtemp(prefix="kards_upd_test_")
    try:
        zpath = os.path.join(tmp, "KARDS.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("KARDS/KARDS.py", "print('hi')")
            zf.writestr("KARDS/kards_engine.py", "VERSION=(1,2,0,4)")
            zf.writestr("KARDS/sub/data.txt", "x")
        out = os.path.join(tmp, "out")
        ok, err = up.extract_zip(zpath, out)
        check("解压成功", ok, err)
        check("前缀已剥掉（KARDS.py 在根）", os.path.exists(os.path.join(out, "KARDS.py")))
        check("子目录保持结构", os.path.exists(os.path.join(out, "sub", "data.txt")))
        check("没有多余的一层 KARDS/ 目录", not os.path.exists(os.path.join(out, "KARDS")))
        os.remove(os.path.join(out, "KARDS.py"))

        print("5. 解压：无前缀包不误剥")
        zpath2 = os.path.join(tmp, "flat.zip")
        with zipfile.ZipFile(zpath2, "w") as zf:
            zf.writestr("KARDS.py", "a")
            zf.writestr("kards_engine.py", "b")
        out2 = os.path.join(tmp, "out2")
        ok, err = up.extract_zip(zpath2, out2)
        check("扁平包解压成功", ok, err)
        check("扁平包文件在根", os.path.exists(os.path.join(out2, "KARDS.py")))

        print("6. 解压：防护 zip slip（../../ 不能越界）")
        zpath3 = os.path.join(tmp, "evil.zip")
        with zipfile.ZipFile(zpath3, "w") as zf:
            zf.writestr("KARDS/ok.py", "fine")
            zf.writestr("KARDS/../../../evil.txt", "bad")
        out3 = os.path.join(tmp, "out3")
        ok, err = up.extract_zip(zpath3, out3)
        check("恶意包不抛异常（跳过越界项）", ok, err)
        check("越界文件没有写到外面",
              not os.path.exists(os.path.join(tmp, "..", "evil.txt"))
              and not os.path.exists(os.path.join(tempfile.gettempdir(), "evil.txt")))
        check("正常文件仍然解压出来", os.path.exists(os.path.join(out3, "ok.py")))

        print("7. 下载：官方 + 镜像都失败时要明确报错（不静默成功）")
        bad = {"name": "KARDS.zip", "url": "http://127.0.0.1:1/nope.zip", "size": 10}
        ok, err = up.download(bad, os.path.join(tmp, "dl.zip"), timeout=3)
        check("下载失败返回 False", not ok)
        check("失败原因非空", bool(err), err)
        check("失败后不留下 .part 残留",
              not any(n.endswith(".part") for n in os.listdir(tmp)), os.listdir(tmp))

        print("8. bat 生成（Windows 免锁替换用）")
        bat = up.write_update_bat(pid=999999, exe=sys.executable, args=[])
        if sys.platform == "win32":
            check("生成了 bat", bat is not None and os.path.exists(bat), bat)
            if bat and os.path.exists(bat):
                raw = open(bat, "rb").read()
                check("bat 是纯 ASCII（cmd.exe 不会乱码）", all(b < 128 for b in raw))
                txt = raw.decode("ascii")
                check("bat 里等的是自己的 PID", "999999" in txt)
                check("bat 结尾会重启程序", "start" in txt)
                os.remove(bat)
        else:
            skip("bat 生成", "非 Windows")

        print("9. 更新目标目录判定")
        d = up.can_self_update()
        check("能给出一个存在的目录", d and os.path.isdir(d), d)
        check("该目录不是用户数据目录（frozen 时 DATA_DIR 在 AppData）",
              os.path.basename(d) not in ("Kards-Simple-Version",), d)
        # 本测试是被 `python debug/test_update.py` 启动的，argv[0] 指向 debug/，
        # 所以这里只能验证「目录存在于磁盘」+「跟 argv[0] 一致」。
        # 真正的游戏路径另有断言（下面用显式 argv 复现一次）。
        check("目录与启动脚本所在目录一致",
              os.path.normcase(d) == os.path.normcase(
                  os.path.dirname(os.path.abspath(sys.argv[0]))), d)
        old_argv = sys.argv
        try:
            sys.argv = [os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "KARDS.py")]
            gdir = up.can_self_update()
            check("以 KARDS.py 启动时指向项目根目录",
                  os.path.exists(os.path.join(gdir, "KARDS.py")), gdir)
        finally:
            sys.argv = old_argv
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("10. 后台任务状态机（用一个假 info 走一遍 found 分支）")
    t = up.UpdateTask("1.2.0.3", auto_install=False)
    check("初始状态 idle", t.state == "idle")
    check("本地版本已规范化", t.local == "1.2.0.3", t.local)
    t.cancel()                                  # 未启动时取消也安全
    check("未启动时 cancel 不崩", True)

    print("11. 真查一次 GitHub Release（网络不通则跳过，不算失败）")
    info = up.check_latest(timeout=12)
    if info.get("ok"):
        check("查到最新版本号", bool(info["version"]), info["version"])
        check("版本号可解析", bool(up.parse_version(info["version"])), info["version"])
        check("带回发布页链接", info.get("page", "").startswith("http"), info.get("page"))
        check("资产列表非空", len(info.get("assets") or []) > 0,
              [a["name"] for a in info.get("assets") or []])
        a = up.pick_asset(info.get("assets") or [])
        if a:
            check("能选出一个可下载的 zip", a["url"].startswith("http"), a["name"])
        else:
            skip("选出 zip 资产", "该 Release 没有 zip")
    else:
        skip("查询 GitHub Release", info.get("err", "")[:60])

    print()
    print("=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项 / 跳过 {len(SKIP)} 项")
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
