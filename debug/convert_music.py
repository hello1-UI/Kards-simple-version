# -*- coding: utf-8 -*-
"""把 assets/music 下的 .m4a 转成 pygame 能播的 .ogg（libvorbis q4）

pygame 的 SDL_mixer 不支持 AAC/m4a，所以用户投放的 m4a 必须转换。
原始 m4a 移到仓库外备份，避免仓库里同一份音乐存两份。
"""
import os
import shutil
import subprocess
import sys

import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "music")
BACKUP = os.path.abspath(os.path.join(ROOT, "..", "music_src_m4a"))
FF = imageio_ffmpeg.get_ffmpeg_exe()

os.makedirs(BACKUP, exist_ok=True)
made = []
for fn in sorted(os.listdir(SRC)):
    if not fn.lower().endswith(".m4a"):
        continue
    src = os.path.join(SRC, fn)
    stem = os.path.splitext(fn)[0]
    dst = os.path.join(SRC, stem + ".ogg")
    cmd = [FF, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
           "-vn", "-map_metadata", "-1", "-c:a", "libvorbis", "-q:a", "4", dst]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("FAIL", fn, r.stderr.strip()[:200])
        continue
    print("%-18s -> %-18s %5.1f MB" % (fn, os.path.basename(dst),
                                       os.path.getsize(dst) / 1048576))
    made.append(dst)

for fn in sorted(os.listdir(SRC)):
    if fn.lower().endswith(".m4a"):
        shutil.move(os.path.join(SRC, fn), os.path.join(BACKUP, fn))

print("ogg:", len(made), "备份目录:", BACKUP)
