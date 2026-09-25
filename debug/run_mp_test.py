# -*- coding: utf-8 -*-
"""联机测试驱动：启动 host/client 两个子进程，收集快照并比对同步性。"""
import re
import subprocess
import sys
import time

import os
PY = r"C:/Users/freet/AppData/Local/Programs/Python/Python313/python.exe"
HERE = os.path.dirname(os.path.abspath(__file__))


def run_role(role):
    return subprocess.Popen([PY, os.path.join(HERE, "test_mp.py"), role],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")


def main():
    host = run_role("host")
    time.sleep(1.0)
    client = run_role("client")
    try:
        hout = host.communicate(timeout=90)[0]
    except subprocess.TimeoutExpired:
        host.kill()
        hout = host.communicate()[0]
    try:
        cout = client.communicate(timeout=90)[0]
    except subprocess.TimeoutExpired:
        client.kill()
        cout = client.communicate()[0]

    print("===== HOST 输出 =====")
    print(hout)
    print("===== CLIENT 输出 =====")
    print(cout)

    hs = re.search(r"SNAPSHOT\[host\]=(.*)", hout)
    cs = re.search(r"SNAPSHOT\[client\]=(.*)", cout)
    hw = re.findall(r"WINNER\[host\]=(\S+) real=(\S+)", hout)
    cw = re.findall(r"WINNER\[client\]=(\S+) real=(\S+)", cout)
    ok = True
    if host.returncode != 0 or client.returncode != 0:
        print("FAIL: 子进程退出码异常", host.returncode, client.returncode)
        ok = False
    if not hs or not cs:
        print("FAIL: 缺少快照")
        ok = False
    else:
        if hs.group(1).strip() == cs.group(1).strip():
            print("PASS: 双方局面快照完全一致")
        else:
            print("FAIL: 双方局面不同步!")
            print("HOST :", hs.group(1)[:400])
            print("CLIENT:", cs.group(1)[:400])
            ok = False
        if "GAME-OVER" not in hs.group(1):
            print("对局仍在进行中（时间到正常收兵），快照已比对")
    # 胜者一致性：只比对「真实终局」的记录（断线判胜不计）
    # host 的 me = client 的 opponent（视角互补）
    real_h = [s for s, r in hw if r == "True"]
    real_c = [s for s, r in cw if r == "True"]
    if real_h and real_c:
        pair = {real_h[0], real_c[0]}
        if pair == {"me", "opponent"}:
            print(f"PASS: 胜者判定一致（host: {real_h[0]} / client: {real_c[0]}）")
        else:
            print(f"FAIL: 胜者判定不一致 host={real_h} client={real_c}")
            ok = False
    else:
        print(f"WARN: 缺少真实终局记录 host={hw} client={cw}（对局可能未打完或经断线判胜）")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
