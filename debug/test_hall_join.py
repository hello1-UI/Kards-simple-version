"""休战大厅回归（bug：大厅看不见别人）。

复现链路：真实 kards_server + 真实 HallView（SDL dummy，后台线程跑）+
一个裸 ServerLink 客户端 —— 校验：
  1. HallView.run() 会发 hall_join（曾经根本不发 = 全员隐身）；
  2. HallView 能收到对方的位置快照（others 出现对方）；
  3. 裸客户端能看到 HallView 玩家；
  4. 大厅期间收到非大厅消息（如 ready）不会被吞，留在 inbox 里。
"""
import os
import socket
import sys
import threading
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("KARDS_DATA_DIR",
                      os.path.join(ROOT, ".tmp_hall_test"))
os.makedirs(os.environ["KARDS_DATA_DIR"], exist_ok=True)

import kards_server as srv
import kards_net as net

passed = failed = 0


def check(ok, label, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [!!] {label}  {detail}")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def make_client(name):
    """注册+登录一个裸客户端，返回 ServerLink。"""
    s = socket.socket()
    s.settimeout(6)
    s.connect(("127.0.0.1", PORT))
    s.settimeout(None)          # ⚠ ServerLink 长期复用此 socket，不能留超时
    link = net.ServerLink(s, ("127.0.0.1", PORT))
    link.send({"m": "register", "user": name, "pw": "pw123456"})
    dl = time.time() + 6
    while time.time() < dl:
        try:
            m = link.inbox.get(timeout=0.3)
        except Exception:                      # noqa: BLE001
            continue
        if isinstance(m, dict) and m.get("m") == "auth_ok":
            return link
        if isinstance(m, dict) and m.get("m") == "auth_err":
            link.send({"m": "login", "user": name, "pw": "pw123456"})
            dl = time.time() + 4
    raise RuntimeError(f"{name} 登录失败")


def wait_state(link, want, timeout=8):
    """等 hall_state 快照里出现 want 名字，返回整份快照或 None。"""
    dl = time.time() + timeout
    while time.time() < dl:
        try:
            m = link.inbox.get(timeout=0.3)
        except Exception:                      # noqa: BLE001
            continue
        if isinstance(m, dict) and m.get("m") == "hall_state":
            names = {p.get("name") for p in m.get("players") or []}
            if want in names:
                return m
    return None


def wait_invite(link, timeout=6):
    """等 hall_invite 到达（途中其他消息丢弃）。"""
    dl = time.time() + timeout
    while time.time() < dl:
        try:
            m = link.inbox.get(timeout=0.3)
        except Exception:                      # noqa: BLE001
            continue
        if isinstance(m, dict) and m.get("m") == "hall_invite":
            return m
    return None


PORT = free_port()
import subprocess
srv_log = open(os.path.join(os.environ["KARDS_DATA_DIR"], "server.log"), "wb")
srv_proc = subprocess.Popen(
    [sys.executable, "kards_server.py", "--port", str(PORT)],
    cwd=ROOT, stdout=srv_log, stderr=subprocess.STDOUT)
th = None  # 服务器跑在子进程里
dl = time.time() + 10
while time.time() < dl:
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=0.4).close()
        break
    except OSError:
        time.sleep(0.1)

import kards_hall

print("=== 1. HallView 发 hall_join、双方互相可见 ===")
link_a = make_client("玩家甲")
link_b = make_client("玩家乙")

app = types.SimpleNamespace(mp_link=link_a, mp_user="玩家甲")
h = kards_hall.HallView(app)
th_hall = threading.Thread(target=h.run, kwargs={"max_frames": 900},
                           daemon=True)
th_hall.start()

# 乙进大厅 → 乙自己的 hall_join 会触发全量广播（广播只发给 in_hall 成员，
# 所以必须乙先进场，才能在快照里看到甲）
link_b.send({"m": "hall_join", "x": 400, "y": 300})
snap = wait_state(link_b, "玩家甲")
check(snap is not None, "乙进场后收到含玩家甲的 hall_state 快照")

# 甲的 HallView（正在跑）应在 others 里看到乙
dl = time.time() + 8
while time.time() < dl and "玩家乙" not in h.others:
    time.sleep(0.1)
check("玩家乙" in h.others, "玩家甲的大厅视图出现玩家乙",
      f"others={list(h.others)}")

print("\n=== 2. 大厅不吞开局协议消息（_drain 透传）===")
# 直接对 _drain 做单元测试：塞一条 ready 进 inbox，drain 一次后必须还在
link_a.inbox.put({"m": "ready", "nation": "德国", "deck": ["四号坦克"] * 20})
h._drain()
still = []
try:
    while True:
        still.append(link_a.inbox.get_nowait())
except Exception:                          # noqa: BLE001
    pass
check(any(isinstance(m, dict) and m.get("m") == "ready" for m in still),
      "ready 消息被归还 inbox（未吞）", f"inbox 剩余={still}")

print("\n=== 3. hall_invite 往返（大厅内互邀）===")
link_b.send({"m": "hall_invite", "to": "玩家甲"})
got_inv = wait_invite(link_a)
check(got_inv is not None, "玩家甲收到 hall_invite",
      "(若失败：邀请被别处抢走)")

h.running = False                    # 让 HallView 线程退出
th_hall.join(timeout=5)
srv_proc.terminate()

print(f"\n=== 结果：{passed} 过 / {failed} 败 ===")
sys.exit(1 if failed else 0)
