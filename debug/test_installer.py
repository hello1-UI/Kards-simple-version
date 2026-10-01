# -*- coding: utf-8 -*-
"""安装器端到端自测：下载 -> 解压 -> 卸载器 -> 快捷方式，逐项校验路径一致性"""
import contextlib
import io
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "inst", os.path.join(ROOT, "apk", "install.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

base = os.path.join(tempfile.gettempdir(), "kards_full_e2e")
shutil.rmtree(base, ignore_errors=True)
install_dir = os.path.join(base, "Kards-Simple-Version")
ok_all = True


def check(label, cond):
    global ok_all
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    ok_all = ok_all and bool(cond)


print("=" * 56)
print("  安装器端到端自测")
print("=" * 56)

# ---- [1/4] 下载 ----
print("\n[1/4] 下载")
zip_path = os.path.join(base, "KARDS.zip")
os.makedirs(base, exist_ok=True)
t0 = time.time()
with contextlib.redirect_stdout(io.StringIO()):
    dl_ok = m.download(zip_path)
size = os.path.getsize(zip_path) if os.path.isfile(zip_path) else 0
print(f"  耗时 {time.time() - t0:.1f}s，{size / 1048576:.1f} MB")
check("下载成功", dl_ok)
check("文件大小 > 1MB", size > 1048576)

# ---- [2/4] 解压 ----
print("\n[2/4] 解压")
with contextlib.redirect_stdout(io.StringIO()):
    m.extract(zip_path, install_dir)
exe = os.path.join(install_dir, "KARDS.exe")
check("KARDS.exe 位于 install_dir 下", os.path.isfile(exe))
check("_internal 目录存在", os.path.isdir(os.path.join(install_dir, "_internal")))
n_files = sum(len(f) for _, _, f in os.walk(install_dir))
check(f"文件数合理（{n_files}）", n_files > 900)
check("未多套一层 KARDS/ 目录",
      not os.path.exists(os.path.join(install_dir, "KARDS", "KARDS.exe")))

# ---- [3/4] 用户数据目录 + 卸载器 ----
print("\n[3/4] 用户数据目录 + 卸载器")
data_dir = os.path.join(base, "AppData")
for sub in ("", "logs", "decks"):
    os.makedirs(os.path.join(data_dir, sub), exist_ok=True)
uni = os.path.join(install_dir, "uninstall.py")
shutil.copy2(os.path.join(ROOT, "apk", "uninstall.py"), uni)
check("uninstall.py 已复制到安装目录", os.path.isfile(uni))

# ---- [4/4] 快捷方式 ----
print("\n[4/4] 快捷方式")
lnk = os.path.join(base, "KARDS 简化版.lnk")
try:
    m.make_shortcut(lnk, exe, data_dir, "KARDS Simplified")
    check("lnk 文件已创建", os.path.isfile(lnk))
    ps = ("$s=New-Object -ComObject WScript.Shell;"
          f"$s.CreateShortcut('{lnk}').TargetPath")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=30)
    target = r.stdout.strip()
    print(f"         lnk 指向: {target}")
    check("lnk 指向正确的 KARDS.exe",
          os.path.normcase(target) == os.path.normcase(exe))
except Exception as e:
    check(f"快捷方式创建（异常 {type(e).__name__}: {e}）", False)

# ---- 卸载（保持系统干净）----
print("\n[清理] 删除测试安装目录")
shutil.rmtree(base, ignore_errors=True)
check("测试目录已清理", not os.path.exists(base))

print()
print("=" * 56)
print("  结果: 全部通过" if ok_all else "  结果: 存在失败项")
print("=" * 56)
sys.exit(0 if ok_all else 1)
