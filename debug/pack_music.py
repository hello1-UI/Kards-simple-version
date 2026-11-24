# -*- coding: utf-8 -*-
"""把散装曲库打成音乐包（music.zip / music-2.zip …），供首次启动自动解压

用法:
    python debug/pack_music.py                    # 打包 assets/music → assets/musicpack/
    python debug/pack_music.py --check            # 只看要不要重打
    python debug/pack_music.py --force            # 强制重建
    python debug/pack_music.py --max-mb 1500      # 每卷上限（默认 1500，GitHub 单文件 2GB）
    python debug/pack_music.py --exclude "*Hitler*" "*Explicit*"
    python debug/pack_music.py --verify           # 打完抽样校验（解到头/尾，比对大小）

为什么默认 1500MB 而不是 2048MB
--------------------------------------------------------------------------
GitHub Release 单个资产的硬上限是 2GB（2,000,000,000 字节级），再算上 HTTP
上传的开销和各家网盘的「2GB 以内」习惯，留 500MB 余量最稳。超了就用第二卷。

为什么默认 ZIP_STORED
--------------------------------------------------------------------------
.flac / .ogg 本身就是压缩格式，再 deflate 一遍通常只能省 1~2%，却要多花
几分钟 CPU。音乐包追求的是「一个文件好传输」，不是极限压缩 —— 所以直接
存储（--deflate 可强行压缩）。
"""
import argparse
import fnmatch
import hashlib
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

AUDIO_EXTS = (".ogg", ".wav", ".mp3", ".flac")
DEFAULT_SRC = os.path.join(ROOT, "assets", "music")
DEFAULT_OUT = os.path.join(ROOT, "assets", "musicpack")
HEADER_OVERHEAD = 256          # 每个成员的本地头 + 中央目录里的名字，粗估


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.1f %s" % (n, unit)) if unit != "B" else ("%d B" % n)
        n /= 1024.0
    return "%.1f GB" % n


def collect(src, excludes):
    """收集要打包的音频文件（平铺，不含子目录里的隐藏文件）。"""
    out = []
    try:
        names = sorted(os.listdir(src))
    except OSError as exc:
        print("[!] 读不到音乐目录 %s: %s" % (src, exc))
        return out
    for fn in names:
        if fn.startswith(".") or fn.endswith(".part"):
            continue
        if os.path.splitext(fn)[1].lower() not in AUDIO_EXTS:
            continue
        if any(fnmatch.fnmatch(fn.lower(), pat.lower()) for pat in excludes):
            print("  [跳过] %s" % fn)
            continue
        path = os.path.join(src, fn)
        if not os.path.isfile(path):
            continue
        out.append((fn, path, os.path.getsize(path)))
    return out


def plan(files, max_bytes):
    """按顺序装箱：每卷不超过 max_bytes（单个文件超限就独占一卷）。"""
    parts, cur, cur_size = [], [], 0
    for fn, path, size in files:
        need = size + HEADER_OVERHEAD
        if cur and cur_size + need > max_bytes:
            parts.append(cur)
            cur, cur_size = [], 0
        cur.append((fn, path, size))
        cur_size += need
    if cur:
        parts.append(cur)
    return parts


def _sha256(path, limit=None):
    h = hashlib.sha256()
    left = limit
    with open(path, "rb") as fh:
        while True:
            n = 4 * 1048576 if left is None else min(4 * 1048576, left)
            if n <= 0:
                break
            b = fh.read(n)
            if not b:
                break
            h.update(b)
            if left is not None:
                left -= len(b)
    return h.hexdigest()


def existing_parts(out_dir):
    try:
        names = os.listdir(out_dir)
    except OSError:
        return []
    return sorted(n for n in names
                  if n.lower().startswith("music") and n.lower().endswith(".zip"))


def up_to_date(out_dir, files):
    """粗略判断是否已是最新：有包、包不比源文件旧、且总体量对得上。"""
    parts = existing_parts(out_dir)
    if not parts:
        return False
    if not files:
        return True
    newest_src = max(os.path.getmtime(p) for _, p, _ in files)
    newest_zip = max(os.path.getmtime(os.path.join(out_dir, n)) for n in parts)
    if newest_zip < newest_src:
        return False
    total_src = sum(s for _, _, s in files)
    total_zip = sum(os.path.getsize(os.path.join(out_dir, n)) for n in parts)
    # 存储模式下 zip 比源文件多一点点头开销；差太多说明源变了
    return total_zip >= total_src and total_zip <= total_src * 1.03 + 1048576


def build(src, out_dir, max_mb=1500, compress="store", excludes=(), force=False,
          quiet=False):
    files = collect(src, excludes)
    if not files:
        print("[!] 没有可打包的音频文件：%s" % src)
        return 1
    total = sum(s for _, _, s in files)
    print("源目录 : %s" % src)
    print("待打包 : %d 个文件 / %s" % (len(files), human(total)))

    os.makedirs(out_dir, exist_ok=True)
    if not force and up_to_date(out_dir, files):
        print("[=] 已是最新（%s），跳过。要重建加 --force"
              % ", ".join(existing_parts(out_dir)))
        return 0

    for n in existing_parts(out_dir):        # 旧卷先删，避免 3 卷变 2 卷时留残卷
        try:
            os.remove(os.path.join(out_dir, n))
        except OSError as exc:
            print("[!] 删不掉旧包 %s: %s" % (n, exc))
            return 1

    parts = plan(files, max(64, max_mb) * 1048576)
    made = []
    for i, chunk in enumerate(parts, 1):
        name = "music.zip" if i == 1 else "music-%d.zip" % i
        path = os.path.join(out_dir, name)
        tmp = path + ".part"
        compression = (zipfile.ZIP_STORED if compress == "store"
                       else zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(tmp, "w", compression=compression, allowZip64=True) as zf:
            for fn, fpath, _size in chunk:
                zf.write(fpath, arcname=fn)
        os.replace(tmp, path)
        made.append((name, os.path.getsize(path), len(chunk)))
        if not quiet:
            print("  [%d/%d] %-14s %8s  %d 首" % (i, len(parts), name,
                                                  human(os.path.getsize(path)),
                                                  len(chunk)))
    print("输出目录: %s" % out_dir)
    print("共 %d 卷 / %s" % (len(made), human(sum(m[1] for m in made))))
    if len(made) > 1:
        print("⚠ 分卷必须放在同一个目录里，游戏会按 music.zip → music-2.zip 顺序解压")
    return 0


def verify(src, out_dir, sample=3):
    """抽样校验：从每卷抽出 1 个文件比大小，再对首尾文件做 sha256 全量比对。"""
    parts = existing_parts(out_dir)
    if not parts:
        print("[!] 没有可校验的包")
        return 1
    bad = 0
    for n in parts:
        path = os.path.join(out_dir, n)
        try:
            with zipfile.ZipFile(path) as zf:
                infos = [i for i in zf.infolist() if not i.is_dir()]
                picked = infos[:1] + infos[-1:]
                for info in picked:
                    fn = os.path.basename(info.filename)
                    local = os.path.join(src, fn)
                    if not os.path.isfile(local):
                        continue
                    if os.path.getsize(local) != info.file_size:
                        print("  [!!] %s 大小不符 (%d != %d)"
                              % (fn, os.path.getsize(local), info.file_size))
                        bad += 1
                        continue
                    with zf.open(info) as fh:
                        h1 = hashlib.sha256(fh.read()).hexdigest()
                    if h1 != _sha256(local):
                        print("  [!!] %s 内容不符" % fn)
                        bad += 1
        except (zipfile.BadZipFile, OSError) as exc:
            print("  [!!] 读不了 %s: %s" % (n, exc))
            bad += 1
    print("校验 %d 卷：%s" % (len(parts), "全部通过" if not bad else "%d 处不符" % bad))
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser(description="打包音乐包")
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--max-mb", type=int, default=1500)
    ap.add_argument("--deflate", action="store_true", help="压缩（默认只存储）")
    ap.add_argument("--exclude", nargs="*", default=[], help="按文件名通配排除")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--check", action="store_true", help="只判断是否需要重打")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    if args.verify:
        return verify(args.src, args.out)
    if args.check:
        files = collect(args.src, args.exclude)
        ok = up_to_date(args.out, files)
        print("需要重打" if not ok else "已是最新")
        return 0 if ok else 2
    return build(args.src, args.out, max_mb=args.max_mb,
                 compress="deflate" if args.deflate else "store",
                 excludes=args.exclude, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
