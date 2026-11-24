# -*- coding: utf-8 -*-
"""把打包好的游戏目录压成发布用的 KARDS.zip

用法:
  python debug/pack_game.py [dist目录] [输出zip]

默认:
  dist目录 = pyinst/dist/KARDS
  输出     = KARDS.zip

关键点（踩过的坑）:
  1. 顶层必须只有 `KARDS/` 一项 —— 安装器解压时会按 `KARDS/` 前缀剥离，
     自动更新的 updater 也按这个约定找 KARDS.exe。
  2. 必须写入 `KARDS/VERSION.txt`：安装器按它校验下载到的包版本，
     没有标记的包会被当成「1.6.3.1 之前的旧包」而拒装。
  3. 内置 UI 模板在 `KARDS/_internal/models/`（PyInstaller 6 的 datas 落点），
     打包时检查一下，缺了要吭声。
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def game_version():
    with open(os.path.join(ROOT, "KARDS.py"), encoding="utf-8") as f:
        m = re.search(r"^VERSION\s*=\s*\(([^)]+)\)", f.read(), re.M)
    if not m:
        raise SystemExit("KARDS.py 里找不到 VERSION 常量")
    return ".".join(x.strip() for x in m.group(1).split(",") if x.strip())


def count_files(base):
    n = 0
    for _root, _dirs, files in os.walk(base):
        n += len(files)
    return n


def main():
    dist = os.path.join(ROOT, "pyinst", "dist", "KARDS")
    out = os.path.join(ROOT, "KARDS.zip")
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        dist = args[0]
    if len(args) > 1:
        out = args[1]
    if not os.path.isdir(dist):
        raise SystemExit(f"找不到打包目录: {dist}\n（先跑 python debug/build_game.py）")

    exe = os.path.join(dist, "KARDS.exe")
    if not os.path.isfile(exe):
        raise SystemExit(f"目录里没有 KARDS.exe: {dist}")

    ver = game_version()
    models = os.path.join(dist, "_internal", "models")
    n_models = 0
    if os.path.isdir(models):
        n_models = len([x for x in os.listdir(models) if x.lower().endswith(".json")])
    else:
        print("⚠ 没找到 _internal/models —— 这个包没有内置 UI 模板")

    total = count_files(dist)
    print(f"源目录: {dist}（{total} 个文件）")
    print(f"版本:   v{ver}")
    print(f"模板:   {n_models} 套")

    tmp = out + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(dist):
            for name in files:
                src = os.path.join(root, name)
                rel = os.path.relpath(src, dist).replace("\\", "/")
                z.write(src, "KARDS/" + rel)
        # 版本标记（位于顶层 KARDS/ 下，安装器按后缀匹配）
        z.writestr("KARDS/VERSION.txt", ver + "\n")
    os.replace(tmp, out)

    size = os.path.getsize(out) / 1048576
    print(f"\n打包完成: {out}  {size:.1f} MB")
    with zipfile.ZipFile(out) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
    print(f"条目: {len(names)} 个")
    print(f"顶层: {sorted({n.split('/')[0] for n in names})}")
    print("含 VERSION.txt:", "KARDS/VERSION.txt" in names)
    print("含 models:", any(n.startswith("KARDS/_internal/models/") for n in names))


if __name__ == "__main__":
    main()
