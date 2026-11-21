# -*- coding: utf-8 -*-
"""从 codeload.github.com 下载 tag 快照（支持断点续传 + 重试）。"""
import sys, os, time, urllib.request, zipfile, shutil

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TAG = sys.argv[1] if len(sys.argv) > 1 else "v1.6.1.3"
OUT = "_upstream_%s.zip" % TAG.lstrip("v").replace(".", "")
DST = "_upstream_" + TAG.lstrip("v").replace(".", "")
URL = "https://codeload.github.com/hello1-UI/Kards-simple-version/zip/refs/tags/" + TAG
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))

pos = os.path.getsize(OUT) if os.path.exists(OUT) else 0
for attempt in range(20):
    try:
        headers = {"User-Agent": "KARDS"}
        if pos:
            headers["Range"] = "bytes=%d-" % pos
        req = urllib.request.Request(URL, headers=headers)
        r = op.open(req, timeout=60)
        if pos and r.status != 206:
            pos = 0                      # 服务器不支持续传，重来
            continue
        mode = "ab" if pos else "wb"
        with open(OUT, mode) as f, r:
            while True:
                b = r.read(1 << 18)
                if not b:
                    break
                f.write(b)
                pos += len(b)
        print("done: %.1f MB" % (pos / 1048576), flush=True)
        break
    except Exception as e:
        print("attempt %d failed at %.1f MB: %s: %s"
              % (attempt + 1, pos / 1048576, type(e).__name__, e), flush=True)
        pos = os.path.getsize(OUT) if os.path.exists(OUT) else 0
        time.sleep(2)
else:
    sys.exit("give up after 20 attempts")

if os.path.isdir(DST):
    shutil.rmtree(DST)
with zipfile.ZipFile(OUT) as z:
    names = z.namelist()
    print("zip entries:", len(names), "| top:", names[0].split("/")[0], flush=True)
    z.extractall(DST)
print("extracted ->", os.listdir(DST), flush=True)
