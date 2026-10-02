# -*- coding: utf-8 -*-
"""清理安装器测试残留：注册表项 + 桌面/开始菜单快捷方式"""
import os
import subprocess
import winreg

KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Kards-Simple-Version"

for hive, name in ((winreg.HKEY_CURRENT_USER, "HKCU"),
                   (winreg.HKEY_LOCAL_MACHINE, "HKLM")):
    try:
        winreg.DeleteKey(hive, KEY)
        print(f"已清理 {name} 注册项")
    except FileNotFoundError:
        print(f"{name} 注册项不存在（已干净）")
    except PermissionError:
        print(f"{name} 需要管理员权限（跳过，解压版本就没有）")
    except OSError as e:
        print(f"{name}: {e}")

try:
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "[Environment]::GetFolderPath('Desktop')"],
                       capture_output=True, text=True, timeout=20)
    desk = r.stdout.strip()
except Exception:
    desk = os.path.join(os.path.expanduser("~"), "Desktop")

targets = [
    os.path.join(desk, "KARDS 简化版.lnk"),
    os.path.join(os.path.expanduser("~"), "Desktop", "KARDS 简化版.lnk"),
    os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                 "Start Menu", "Programs", "KARDS 简化版.lnk"),
]
for lnk in dict.fromkeys(targets):
    if os.path.isfile(lnk):
        try:
            os.remove(lnk)
            print("已删除快捷方式:", lnk)
        except OSError as e:
            print("删除失败:", lnk, e)
    else:
        print("不存在（已干净）:", lnk)
