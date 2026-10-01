# -*- coding: utf-8 -*-
"""打包安装器发布包 KARDS_SimpleVersion-Setup.zip（含安装说明）"""
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "KARDS_SimpleVersion-Setup.zip")

README = """KARDS 简化版 —— 安装说明
========================================

【方式一】自动安装（推荐）
  1. 确保已安装 Python 3.8 或更高版本
     （下载 https://www.python.org/downloads/ ，安装时勾选 Add Python to PATH）
  2. 双击 install.py，或在命令行运行：
         python install.py
     也可直接指定安装目录：
         python install.py "D:\\Games\\KARDS"
  3. 按提示完成，桌面会出现「KARDS 简化版」快捷方式

  安装器会自动：
    - 从多个镜像源中并发测速，选最快的一个下载（通常 10 秒左右完成）
    - 解压到指定目录（默认 C:\\Program Files\\Kards-Simple-Version）
    - 创建用户数据目录 %USERPROFILE%\\AppData\\Kards-Simple-Version
    - 创建桌面 + 开始菜单快捷方式
    - 注册到系统「应用和功能」，可一键卸载

【方式二】免安装（绿色版）
  直接下载 KARDS.zip 解压到任意目录，双击 KARDS.exe 即可运行。
  用户数据同样保存在 %USERPROFILE%\\AppData\\Kards-Simple-Version

【卸载】
  方式一安装的：设置 -> 应用 -> 找到「KARDS Simplified」-> 卸载
  绿色版的：    直接删除解压出来的文件夹即可

【常见问题】
  Q: 安装过程卡在下载不动？
  A: 安装器会自动测速换源，并带有停滞检测（连续 45 秒无数据自动换源）。
     若所有源都缓慢，说明本机网络受限，可手动下载 KARDS.zip 或用绿色版。

  Q: 提示没有权限？
  A: 安装到 Program Files 需要管理员权限，安装器会弹出 UAC 窗口，请点「是」。
     若不想提权，可装到用户目录，例如 python install.py "D:\\Games\\KARDS"

  Q: 用户数据在哪？
  A: %USERPROFILE%\\AppData\\Kards-Simple-Version
     包含 settings（设置）/ logs（日志）/ decks（自组卡组）

  Q: 能装到别的盘吗？
  A: 可以。运行时带上路径参数即可，路径含空格请用双引号包起来。
"""


def main():
    files = [
        (os.path.join(ROOT, "apk", "install.py"), "install.py"),
        (os.path.join(ROOT, "apk", "uninstall.py"), "uninstall.py"),
    ]
    for src, _ in files:
        if not os.path.isfile(src):
            raise SystemExit(f"缺少文件: {src}")

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for src, arc in files:
            z.write(src, arc)
        z.writestr("安装说明.txt", README)

    print(f"打包完成: {OUT}")
    print(f"大小: {os.path.getsize(OUT) / 1024:.1f} KB")
    print("内容:")
    with zipfile.ZipFile(OUT) as z:
        for info in z.infolist():
            print(f"  {info.filename:20s} {info.file_size:>8d} B")


if __name__ == "__main__":
    main()
