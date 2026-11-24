# -*- coding: utf-8 -*-
"""可选音乐包下载器 kards_musicdl 的端到端测试

    python debug/test_musicdl.py

网络隔离：**不打真实 GitHub**。下载走 file:// 本地 zip（download_ex 对
非 GitHub 地址不会套镜像），清单查询打桩 UPD.check_release。
目录隔离：数据目录 / 音乐目录都指到临时目录。
"""
import hashlib
import io
import os
import shutil
import sys
import tempfile
import threading
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_musicpack as MP              # noqa: E402
import kards_musicdl as M                 # noqa: E402
import kards_update as UPD                # noqa: E402

PASS, FAIL = [], []
BASE = tempfile.mkdtemp(prefix="kards_mpdl_")
DATA = os.path.join(BASE, "data")
MUSDIR = os.path.join(BASE, "music")
os.makedirs(DATA, exist_ok=True)

# 目录隔离：下载落地与解压目标都指到临时目录
M._data_dir = lambda: DATA
MP.target_dir = lambda: MUSDIR


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name
          + (f"  [{extra}]" if extra and not cond else ""))


def make_zip(path, names):
    """造一卷真 zip：每个名字一个小 wav（曲库能扫的格式）。"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for n in names:
            zf.writestr(n, b"RIFF0000WAVEfmt " + n.encode("utf-8"))


def url_of(path):
    from urllib.request import pathname2url
    return "file://" + pathname2url(os.path.abspath(path))


def sha_of(path):
    return hashlib.sha256(io.open(path, "rb").read()).hexdigest()


def run(task, timeout=60):
    task.start()
    task._thread.join(timeout)
    assert not task._thread.is_alive(), "任务超时未结束"


# ---------------------------------------------------------------- 1. 分卷清单
print("1. parts_of 过滤与排序")
assets = [
    {"name": "SHA256SUMS.txt", "size": 10, "url": "x"},
    {"name": "music-10.zip", "size": 3, "url": "u10"},
    {"name": "music.zip", "size": 1, "url": "u1"},
    {"name": "music-2.zip", "size": 2, "url": "u2"},
    {"name": "setup.exe", "size": 9, "url": "e"},
    {"name": "other.zip", "size": 4, "url": "o"},
]
ps = M.parts_of(assets)
check("只挑 music*.zip", [a["name"] for a in ps]
      == ["music.zip", "music-2.zip", "music-10.zip"],
      [a["name"] for a in ps])
check("总大小求和", M.total_bytes(ps) == 6)

# ---------------------------------------------------------------- 2. release()
print("2. release 清单查询")
UPD.check_release = lambda tag=None, timeout=12: {"ok": False, "err": "HTTP 404"}
r = M.release()
check("404 → ok=False 且带 err", not r["ok"] and r["err"], r)

UPD.check_release = lambda tag=None, timeout=12: {
    "ok": True, "assets": assets, "page": "p"}
r = M.release()
check("正常返回 3 卷", r["ok"] and len(r["parts"]) == 3, r.get("parts"))
check("SHA256SUMS 被识别为校验文件", r["sums"]
      and r["sums"][0]["name"] == "SHA256SUMS.txt", r.get("sums"))

UPD.check_release = lambda tag=None, timeout=12: {"ok": True, "assets": []}
r = M.release()
check("没有分卷 → 明确报错", not r["ok"] and "分卷" in r["err"], r)

# ---------------------------------------------------------------- 3. 完整安装流
print("3. 下载 → 校验 → 解压 → 清理 全流程")
src = os.path.join(BASE, "remote")
os.makedirs(src, exist_ok=True)
z1 = os.path.join(src, "music.zip")
z2 = os.path.join(src, "music-2.zip")
make_zip(z1, ["a.wav", "b.wav"])
make_zip(z2, ["c.wav"])

UPD.check_release = lambda tag=None, timeout=12: {
    "ok": True, "page": "p",
    "assets": [{"name": "music.zip", "size": os.path.getsize(z1),
                "url": url_of(z1), "sha256": sha_of(z1)},
               {"name": "music-2.zip", "size": os.path.getsize(z2),
                "url": url_of(z2), "sha256": ""}]}
# 无校验值的卷 → verified 应变 False
task = M.InstallTask()
run(task)
check("安装完成", task.state == "done", (task.state, task.message))
check("下载了 2 卷", task.total_mb > 0 and task.progress == 1.0)
check("无哈希的卷标记为未校验", task.verified is False)
check("解出 3 首曲目", task.audio == 3, task.audio)
check("解压目标正确", sorted(os.listdir(MUSDIR))
      == [".musicpack.json", "a.wav", "b.wav", "c.wav"],
      os.listdir(MUSDIR))
check("zip 用完即删", not [f for f in os.listdir(DATA)
                          if f.endswith(".zip")], os.listdir(DATA))

# ---------------------------------------------------------------- 4. 断点续传
print("4. 中断续传：已有完整卷直接跳过下载")
downloads = []
_orig_dl = UPD.download_ex


def spy_dl(asset, dest, progress=None, timeout=90, want_sha="", on_verify=None):
    downloads.append(asset["name"])
    return _orig_dl(asset, dest, progress, timeout, want_sha, on_verify)


UPD.download_ex = spy_dl
shutil.copy(z1, os.path.join(DATA, "music.zip"))     # 第 1 卷已在本地
task = M.InstallTask()
run(task)
check("第 1 卷没重下", downloads == ["music-2.zip"], downloads)
check("仍然装满 3 首", task.state == "done" and task.audio == 3)
UPD.download_ex = _orig_dl
shutil.rmtree(MUSDIR, ignore_errors=True)

# ---------------------------------------------------------------- 5. 取消
print("5. 取消下载")


def slow_dl(asset, dest, progress=None, timeout=90, want_sha="", on_verify=None):
    def cb(done, total):
        raise UPD.Cancelled()
    return _orig_dl(asset, dest, cb, timeout, want_sha, on_verify)


UPD.download_ex = slow_dl
task = M.InstallTask()
task.cancel()                       # 先把取消标志立好，下载一启动就会被打断
run(task)
check("取消后状态 cancelled", task.state == "cancelled", task.state)
check("半截 .part 已清理", not [f for f in os.listdir(DATA)
                               if f.endswith(".part")], os.listdir(DATA))
UPD.download_ex = _orig_dl

# ---------------------------------------------------------------- 6. 空间检查
print("6. 磁盘空间不足")
M.free_mb = lambda path=None: 1.0
task = M.InstallTask()
run(task)
check("报 insufficient_space", task.state == "error"
      and task.message.startswith("insufficient_space:"),
      (task.state, task.message))
check("错误信息带需要/剩余 MB",
      len(task.message.split(":")) == 3, task.message)
M.free_mb = shutil.disk_usage and (lambda path=None: 1 << 40)

# ---------------------------------------------------------------- 7. 仅本地重解
print("7. local_only：只解本地已有的 zip")
# 打桩 packs()：只看数据目录那两卷，别把仓库里真实存在的 assets/musicpack
# 卷进来（源码运行时它们就在探测路径上）。
_real_packs = MP.packs
MP.packs = lambda dirs=None: ([os.path.join(DATA, "music.zip"),
                               os.path.join(DATA, "music-2.zip")]
                              if dirs is None else _real_packs(dirs))
shutil.copy(z1, os.path.join(DATA, "music.zip"))
shutil.copy(z2, os.path.join(DATA, "music-2.zip"))
task = M.InstallTask(local_only=True)
run(task)
check("不走网络（无下载）", downloads == ["music-2.zip"], downloads)
check("解出 3 首", task.state == "done" and task.audio == 3,
      (task.state, task.audio))
check("不清玩家的 zip（local_only 不删）",
      len([f for f in os.listdir(DATA) if f.endswith(".zip")]) == 2)

os.remove(os.path.join(DATA, "music.zip"))
os.remove(os.path.join(DATA, "music-2.zip"))
MP.packs = lambda dirs=None: []
task = M.InstallTask(local_only=True)
run(task)
check("本地没包 → 明确报错", task.state == "error"
      and task.message == "no_local_packs", task.message)
MP.packs = _real_packs

print()
print("=" * 56)
print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
if FAIL:
    for f in FAIL:
        print("  -", f)
    shutil.rmtree(BASE, ignore_errors=True)
    sys.exit(1)
shutil.rmtree(BASE, ignore_errors=True)
print("全部通过")
sys.exit(0)
