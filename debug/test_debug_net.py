# -*- coding: utf-8 -*-
"""--debug-on-net 自战模式冒烟测试：启动后等待就绪标志，确认双窗口进入联机对局。"""
import subprocess
import sys
import time

import os
PY = r"C:/Users/freet/AppData/Local/Programs/Python/Python313/python.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

proc = subprocess.Popen([PY, "-u", os.path.join(ROOT, "kards_gui.py"), "--debug-on-net"],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace")
ready = False
out = []
t0 = time.time()
while time.time() - t0 < 40:
    line = proc.stdout.readline()
    if not line:
        break
    out.append(line.rstrip())
    if "就绪" in line:
        ready = True
        break
    if "Traceback" in line or "MSG-ERROR" in line:
        # 再读一点堆栈
        for _ in range(12):
            extra = proc.stdout.readline()
            if not extra:
                break
            out.append(extra.rstrip())
        break
proc.terminate()
try:
    rest = proc.communicate(timeout=5)[0]
except Exception:
    pass
print("\n".join(out))
print("RESULT:", "PASS" if ready else "FAIL")
sys.exit(0 if ready else 1)
