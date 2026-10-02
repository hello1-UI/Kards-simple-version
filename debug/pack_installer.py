# -*- coding: utf-8 -*-
"""打包安装器发布包 KARDS_SimpleVersion-Setup.zip

内容：
  KARDS安装器.exe   双击即用（无需安装 Python）
  KARDS卸载器.exe   由安装器复制到安装目录，并注册到「应用和功能」
  安装说明.txt

同时保留源码版 install.py / uninstall.py，方便想用 Python 跑的用户。
"""
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "KARDS_SimpleVersion-Setup.zip")

README = """KARDS 简化版 —— 安装说明
========================================

【方式一】自动安装（推荐，无需安装 Python）
  1. 把 KARDS安装器.exe 和 KARDS卸载器.exe 放在同一个文件夹里
  2. 双击 KARDS安装器.exe
  3. 提示「安装路径」时直接回车用默认目录
     （默认 C:\\Program Files\\Kards-Simple-Version），也可输入别的路径
  4. 等进度跑完（通常 10~30 秒），桌面会出现「KARDS 简化版」快捷方式

  安装器会自动：
    - 从多个镜像源中并发测速，选最快的一个下载（多数情况 10 秒左右）
    - 解压到指定目录
    - 把 KARDS卸载器.exe 一并放进安装目录
    - 创建用户数据目录 %USERPROFILE%\\AppData\\Kards-Simple-Version
    - 创建桌面 + 开始菜单快捷方式
    - 注册到系统「应用和功能」，可一键卸载

  ⚠ 两个 exe 必须放在同一目录，否则卸载器不会被安装进去。

【方式二】免安装（绿色版）
  直接下载 KARDS.zip，解压到任意目录，双击 KARDS.exe 即可运行。
  用户数据同样保存在 %USERPROFILE%\\AppData\\Kards-Simple-Version

【方式三】用 Python 跑源码（开发者）
  python install.py                    # 默认路径
  python install.py "D:\\Games\\KARDS"  # 指定路径

【卸载】
  方式一安装的：设置 -> 应用 -> 找到「KARDS Simplified」-> 卸载
              或直接双击安装目录里的 KARDS卸载器.exe
  绿色版的：    直接删除解压出来的文件夹即可

【常见问题】
  Q: 双击没反应 / 一闪而过？
  A: 安装器是控制台程序，请确认没有被杀毒软件拦截。
     若确实闪退，可改成用 Python 跑（方式三），能看到完整报错。

  Q: 安装过程卡在下载不动？
  A: 安装器会自动测速换源，并带有停滞检测（连续 45 秒无数据自动换源）。
     若所有源都缓慢，说明本机网络受限，可手动下载 KARDS.zip 或用绿色版。

  Q: 提示没有权限？
  A: 装到 Program Files 需要管理员权限，安装器会弹出 UAC 窗口，请点「是」。
     若不想提权，可装到用户目录，例如输入 D:\\Games\\KARDS

  Q: 卸载时问「同时删除用户数据?」怎么选？
  A: 选 N（直接回车）会保留设置/日志/自组卡组，下次重装还能用；
     选 y 会把它们一起删掉。

  Q: 用户数据在哪？
  A: %USERPROFILE%\\AppData\\Kards-Simple-Version
     包含 settings.json（设置）/ logs（日志）/ decks（自组卡组）

  Q: 能装到别的盘吗？
  A: 可以。安装时直接输入路径，路径含空格也没问题。
"""


def main():
    # 发布包以 exe 为主；源码作为可选补充一起塞进去
    files = [
        (os.path.join(ROOT, "dist_tools", "KARDS安装器.exe"), "KARDS安装器.exe"),
        (os.path.join(ROOT, "dist_tools", "KARDS卸载器.exe"), "KARDS卸载器.exe"),
        (os.path.join(ROOT, "apk", "install.py"), "源码版/install.py"),
        (os.path.join(ROOT, "apk", "uninstall.py"), "源码版/uninstall.py"),
    ]
    for src, _ in files:
        if not os.path.isfile(src):
            raise SystemExit(f"缺少文件: {src}\n（exe 请先运行 PyInstaller 打包）")

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for src, arc in files:
            z.write(src, arc)
        z.writestr("安装说明.txt", README)

    print(f"打包完成: {OUT}")
    print(f"大小: {os.path.getsize(OUT) / 1048576:.1f} MB")
    print("内容:")
    with zipfile.ZipFile(OUT) as z:
        for info in z.infolist():
            print(f"  {info.filename:24s} {info.file_size / 1048576:>7.1f} MB")


if __name__ == "__main__":
    main()
