# -*- coding: utf-8 -*-
"""临时验收：拿**线上真实 Release** 跑一遍 检查 -> 下载 -> 解压 全链路。

这不是常规回归测试（要下 12.8MB，慢且依赖网络），只在发版后手工跑一次。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import kards_update as up                                    # noqa: E402

LOCAL = (1, 3, 0, 0)          # 模拟"旧版本"来触发更新路径

print("1. 检查最新版本")
t0 = time.time()
info = up.check_latest()
assert info.get("ok"), f"检查失败: {info}"
print(f"   线上最新 = v{info['version']}  ({time.time()-t0:.1f}s)")
print(f"   更新说明 = {len(info.get('notes') or '')} 字")

print("2. 是否需要更新（本地伪装成 1.2.0.3）")
old = (1, 2, 0, 3)
need = up.is_newer(info["version"], old)
print(f"   本地 v{up.version_str(old)} -> 最新 v{info['version']}：需要更新 = {need}")
assert need, "应该判定为需要更新"

print("3. 挑选资产")
asset = up.pick_asset(info["assets"])
assert asset, "没挑到可下载的资产"
print(f"   选中 {asset['name']}  {asset['size']/1048576:.1f} MB")

print("4. 下载（官方直连失败会自动走镜像）")
tmp = tempfile.mkdtemp(prefix="kards_e2e_")
dest = os.path.join(tmp, asset["name"])
seen = []


def progress(done, total):
    seen.append(done / total if total else 0.0)


t0 = time.time()
ok = up.download(asset, dest, progress=progress, timeout=300)
size = os.path.getsize(dest) if os.path.exists(dest) else 0
print(f"   下载完成 = {ok}  实际 {size/1048576:.1f} MB  ({time.time()-t0:.1f}s)")
print(f"   进度回调收到 {len(seen)} 次，最终 {seen[-1]*100:.0f}%" if seen else "   无进度回调")
assert ok and size > 1_000_000, "下载失败或文件过小"

print("5. 解压（应自动剥掉 KARDS/ 前缀）")
target = os.path.join(tmp, "install")
up.extract_zip(dest, target, strip_root="KARDS")
exe = os.path.join(target, "KARDS.exe")
print(f"   解压到 {target}")
print(f"   KARDS.exe 存在 = {os.path.isfile(exe)}")
listing = sorted(os.listdir(target))[:6]
print(f"   根目录内容 = {listing}")

server_py = os.path.join(target, "_internal", "kards_server.py")
print(f"   自带服务器脚本 = {os.path.isfile(server_py)}")

assert os.path.isfile(exe), "解压后找不到 KARDS.exe"

print()
print("=== E2E OK === 检查 -> 下载 -> 解压 全链路可用")
print(f"   临时目录: {tmp}")
