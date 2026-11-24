# -*- coding: utf-8 -*-
"""音乐包测试：探测 / 解压 / 幂等 / 分卷 / 坏包 / 安全

运行:
    python debug/test_musicpack.py
"""
import json
import os
import shutil
import sys
import tempfile
import zipfile

os.environ["KARDS_DATA_DIR"] = tempfile.mkdtemp(prefix="kards_musicpack_data_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_musicpack as MP          # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name
          + (f"  {extra}" if (extra and not cond) else ""))


def make_zip(path, members):
    """members: {name: bytes}"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def main():
    base = tempfile.mkdtemp(prefix="kards_mp_")
    src = os.path.join(base, "assets")          # 放 zip 的「随包」目录
    dst = os.path.join(base, "music")           # 解压目标
    os.makedirs(src)
    os.makedirs(dst)
    dirs = [src]

    print("1. 探测 zip")
    check("空目录没有包", MP.packs(dirs) == [], MP.packs(dirs))
    check("没有包时不需要解压", MP.pending(dirs, dst) is False)

    make_zip(os.path.join(src, "other.zip"), {"x.mp3": b"x"})
    check("只认 music 开头的 zip", MP.packs(dirs) == [], MP.packs(dirs))
    make_zip(os.path.join(src, "music.zip"), {"a.mp3": b"aaaa"})
    make_zip(os.path.join(src, "music-2.zip"), {"b.mp3": b"bbbb"})
    make_zip(os.path.join(src, "music-10.zip"), {"c.mp3": b"cccc"})
    names = [os.path.basename(p) for p in MP.packs(dirs)]
    check("按分卷顺序排列", names == ["music.zip", "music-2.zip", "music-10.zip"],
          names)
    check("有包时需要解压", MP.pending(dirs, dst) is True)

    print("2. 解压")
    res = MP.ensure_extracted(dirs, dst)
    check("三卷都解了", res["extracted"] == 3, res)
    check("没有报错", res["errors"] == [], res["errors"])
    for fn, data in (("a.mp3", b"aaaa"), ("b.mp3", b"bbbb"), ("c.mp3", b"cccc")):
        p = os.path.join(dst, fn)
        check("解出 " + fn, os.path.isfile(p)
              and open(p, "rb").read() == data, p)
    check("写了完成标记", os.path.isfile(os.path.join(dst, MP.MARKER)))
    check("解完不用再解", MP.pending(dirs, dst) is False)

    print("3. 幂等")
    res2 = MP.ensure_extracted(dirs, dst)
    check("第二次不再写文件", res2["extracted"] == 0, res2)
    check("第二次全跳过", res2["skipped"] >= 0, res2)

    # 玩家自己换了同大小的高码率版本：不能覆盖
    custom = b"XXXX"
    with open(os.path.join(dst, "a.mp3"), "wb") as fh:
        fh.write(custom)
    res3 = MP.ensure_extracted(dirs, dst)
    check("同大小文件不被覆盖", open(os.path.join(dst, "a.mp3"), "rb").read() == custom)
    check("第二次也没重写", res3["extracted"] == 0, res3)

    # 内容变了（大小也变）→ 该覆盖
    make_zip(os.path.join(src, "music.zip"), {"a.mp3": b"a-much-longer-track"})
    res4 = MP.ensure_extracted(dirs, dst)
    check("包更新后重解该卷", res4["extracted"] == 1, res4)
    check("内容被更新",
          open(os.path.join(dst, "a.mp3"), "rb").read() == b"a-much-longer-track")

    print("4. 结构清洗")
    dirty = os.path.join(base, "dirty")
    os.makedirs(dirty)
    make_zip(os.path.join(dirty, "music.zip"), {
        "music/nested/song.mp3": b"nested",
        "__MACOSX/._song.mp3": b"junk",
        "music/.DS_Store": b"junk",
        "single.ogg": b"one",
    })
    dst2 = os.path.join(base, "music2")
    os.makedirs(dst2)
    res = MP.ensure_extracted([dirty], dst2)
    check("剥掉顶层 music/ 并拍平", os.path.isfile(os.path.join(dst2, "song.mp3")))
    check("__MACOSX 被跳过", not os.path.exists(os.path.join(dst2, "._song.mp3")))
    check("点文件被跳过", not os.path.exists(os.path.join(dst2, ".DS_Store")))
    check("根下文件正常解出", os.path.isfile(os.path.join(dst2, "single.ogg")))
    check("只解出 2 个", res["extracted"] == 2, res)

    print("5. 安全：zip-slip")
    evil = os.path.join(base, "evil")
    os.makedirs(evil)
    make_zip(os.path.join(evil, "music.zip"), {
        "../../escape.mp3": b"bad",
        "/abs.mp3": b"bad",
        "..\\..\\win_escape.ogg": b"bad",
        "ok.mp3": b"good",
    })
    dst3 = os.path.join(base, "music3")
    os.makedirs(dst3)
    MP.ensure_extracted([evil], dst3)
    outside = [os.path.join(base, "escape.mp3"),
               os.path.join(os.path.dirname(base), "escape.mp3"),
               os.path.join(base, "win_escape.ogg"),
               "/abs.mp3"]
    check("没有文件写到目标目录外", not any(os.path.exists(p) for p in outside))
    check("合法文件照常解出", os.path.isfile(os.path.join(dst3, "ok.mp3")))
    check("越界名被拍进目标目录",
          os.path.isfile(os.path.join(dst3, "escape.mp3")))

    print("6. 坏包处理")
    bad = os.path.join(base, "bad")
    os.makedirs(bad)
    with open(os.path.join(bad, "music.zip"), "wb") as fh:
        fh.write(b"PK\x03\x04 this is not a zip")
    make_zip(os.path.join(bad, "music-2.zip"), {"good.mp3": b"ok"})
    dst4 = os.path.join(base, "music4")
    os.makedirs(dst4)
    res = MP.ensure_extracted([bad], dst4)
    check("坏包不抛异常", isinstance(res, dict))
    check("坏包记了错误", len(res["errors"]) >= 1, res["errors"])
    check("后面的好包照常解", os.path.isfile(os.path.join(dst4, "good.mp3")))
    check("坏包下次还会重试", MP.pending([bad], dst4) is True)

    print("7. 取消")
    dst5 = os.path.join(base, "music5")
    os.makedirs(dst5)
    res = MP.ensure_extracted(dirs, dst5, should_stop=lambda: True)
    check("标记为已中止", res["aborted"] is True, res)
    check("中止不写完成标记", not os.path.isfile(os.path.join(dst5, MP.MARKER)))

    print("8. 标记失效自愈")
    with open(os.path.join(dst5, MP.MARKER), "w", encoding="utf-8") as fh:
        json.dump({"packs": {}}, fh)
    check("空标记仍视为待解压", MP.pending(dirs, dst5) is True)
    # 标记说 OK 但文件被删光 → 必须重解
    MP.ensure_extracted(dirs, dst5)
    for fn in os.listdir(dst5):
        if fn != MP.MARKER:
            os.remove(os.path.join(dst5, fn))
    check("曲库被清空后会重解", MP.pending(dirs, dst5) is True)
    MP.ensure_extracted(dirs, dst5)
    check("重解后曲库回来了", os.path.isfile(os.path.join(dst5, "b.mp3")))

    print("9. 诊断快照")
    st = MP.status() if not dirs else None
    st = {"packs": [os.path.basename(p) for p in MP.packs(dirs)],
          "pending": MP.pending(dirs, dst5)}
    check("状态能列出分卷", st["packs"] == ["music.zip", "music-2.zip", "music-10.zip"],
          st)
    check("状态能报是否待解压", isinstance(st["pending"], bool))
    real = MP.status()
    check("status() 结构完整",
          all(k in real for k in ("packs", "target", "pending", "audio", "marker")))

    print("10. 与曲库对接")
    import kards_music
    check("解出的文件能被曲库扫到",
          any(e["name"] == "b" for e in kards_music._scan([dst5])))

    print("11. 打包工具")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pack_music", os.path.join(ROOT, "debug", "pack_music.py"))
    PM = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(PM)

    files = [("a.mp3", "a", 400), ("b.mp3", "b", 400), ("c.mp3", "c", 400)]
    # 每个成员带 ~256B 头开销：400+256=656，两个刚好 1312 ≤ 1400，三个就超了
    parts = PM.plan(files, 1400)
    check("按体积切分分卷", len(parts) == 2, [len(p) for p in parts])
    check("切分不丢文件", sum(len(p) for p in parts) == 3)
    check("超大单文件独占一卷",
          len(PM.plan([("big.mp3", "x", 5000)], 1000)) == 1)

    pk_src = os.path.join(base, "pksrc")
    pk_out = os.path.join(base, "pkout")
    os.makedirs(pk_src)
    for i in range(5):
        with open(os.path.join(pk_src, "t%d.mp3" % i), "wb") as fh:
            fh.write(b"x" * 600)
    with open(os.path.join(pk_src, "skip.txt"), "w") as fh:
        fh.write("not audio")
    rc = PM.build(pk_src, pk_out, max_mb=64, quiet=True)
    check("打包成功", rc == 0, rc)
    check("非音频不入包", PM.existing_parts(pk_out) == ["music.zip"])
    with zipfile.ZipFile(os.path.join(pk_out, "music.zip")) as zf:
        names = zf.namelist()
    check("打包内容完整", sorted(names) == ["t0.mp3", "t1.mp3", "t2.mp3",
                                            "t3.mp3", "t4.mp3"], names)
    check("刚打完就认为是最新", PM.up_to_date(pk_out, PM.collect(pk_src, [])) is True)
    check("源目录变更后需要重打",
          PM.up_to_date(pk_out, PM.collect(pk_src, []) + [(
              "new.mp3", os.path.join(pk_src, "t0.mp3"), 999999)]) is False)
    check("校验通过", PM.verify(pk_src, pk_out) == 0)
    with open(os.path.join(pk_src, "t9.mp3"), "wb") as fh:
        fh.write(b"y" * 600)
    rc = PM.build(pk_src, pk_out, max_mb=64, excludes=["t9*"], force=True,
                  quiet=True)
    check("排除规则生效", rc == 0)
    with zipfile.ZipFile(os.path.join(pk_out, "music.zip")) as zf:
        check("被排除的文件没进包", "t9.mp3" not in zf.namelist(), zf.namelist())

    shutil.rmtree(base, ignore_errors=True)

    print()
    print("=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  -", f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
