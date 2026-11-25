# -*- coding: utf-8 -*-
"""云端桥接（vitural:6000）端到端测试 —— 桥接进程内启动，客户端走 HTTP 长轮询。

覆盖：注册/登录 → 快速匹配 → 对局行动中转 → 走动大厅 presence →
心跳/断线清理 → parse_addr 归一化。全部通过 HttpServerLink 真实走 HTTP。
"""
import importlib.util
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import kards_net as net  # noqa: E402

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}: {detail}")


def wait_inbox(link, mtype, timeout=8.0):
    """从 inbox（或事件队列）等一条指定类型消息；非事件应答会被 request 消费掉。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            obj = link.inbox.get(timeout=0.3)
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("m") == mtype:
            return obj
    return None


# ---------------------------------------------------------------- 桥接进程内启动
# 数据库隔离：指到临时目录，不污染桥接部署副本与本地服务器
import tempfile  # noqa: E402
_TMP = tempfile.mkdtemp(prefix="kards_relay_test_")
os.environ["KARDS_DATA_DIR"] = _TMP

_spec = importlib.util.spec_from_file_location(
    "kards_relay_app",
    os.path.join(os.path.dirname(__file__), "..", "cloud", "kards_relay", "app.py"))
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)
httpd = app.start_http(0)
PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"
print(f"1. 桥接已就绪（HTTP :{PORT}）")

# ---------------------------------------------------------------- 地址归一化
r = net.parse_addr("vitural:6000")
check("parse_addr(vitural:6000)", r == ("vitural", 6000), r)
r = net.parse_addr("virtual:6000")
check("parse_addr(virtual:6000) 归一", r == ("vitural", 6000), r)
check("same_server 拼写变体判同服", net.same_server("vitural:6000", "virtual:6000"))
check("普通地址不受影响", net.parse_addr("1.2.3.4:6000") == ("1.2.3.4", 6000))

# ---------------------------------------------------------------- 注册/登录
A_NAME, B_NAME, PW = "桥接测试甲", "桥接测试乙", "pass1234"
la = net.HttpServerLink(BASE)
check("HttpServerLink 建立会话", la.alive and la._sid)
r = la.request({"m": "register", "user": A_NAME, "pw": PW}, key="register")
check("注册账号 A", r is not None and r.get("m") == "auth_ok", r)

lb = net.HttpServerLink(BASE)
r = lb.request({"m": "register", "user": B_NAME, "pw": PW}, key="register")
check("注册账号 B", r is not None and r.get("m") == "auth_ok", r)

r = la.request({"m": "stats"}, key="stats")
check("战绩查询走云端", r is not None and r.get("m") == "stats", r)

# ---------------------------------------------------------------- 匹配 + 行动中转
# 排位池与休闲池互不配对，两边都走休闲池
r = la.request({"m": "match", "casual": True}, key="match")
check("A 进入匹配队列", r is not None and r.get("m") in ("matching", "matched"), r)
r = lb.request({"m": "match", "casual": True}, key="match")
check("B 匹配成功", r is not None and r.get("m") == "matched", r)
ev = wait_inbox(la, "matched")
check("A 收到 matched 事件", ev is not None, "A 没等到 matched")

# 对局行动：A act → 服务器转发给 B
la.send({"m": "act", "k": "end", "t": None})
act = wait_inbox(lb, "act")
check("行动指令云端中转 B→收到", act is not None and act.get("k") == "end", act)
lb.send({"m": "act", "k": "concede"})
act = wait_inbox(la, "act")
check("行动指令云端中转 A→收到", act is not None and act.get("k") == "concede", act)

# ---------------------------------------------------------------- 走动大厅
# 先退出刚才的对局房间（对局中不允许进大厅）
la.send({"m": "leave_room"})
lb.send({"m": "leave_room"})
time.sleep(0.6)
la.inbox.queue.clear()
lb.inbox.queue.clear()
lb.send({"m": "hall_join", "x": 220, "y": 180})
wait_inbox(lb, "hall_state")          # 消费 B 自己进场的快照
la.send({"m": "hall_join", "x": 100, "y": 120})
st = wait_inbox(la, "hall_state")
check("A hall_join 收到快照", st is not None, "没等到 hall_state")
ev = wait_inbox(lb, "hall_state")
names = [p.get("name") for p in (ev or {}).get("players", [])]
check("B 收到 A 进场广播", ev is not None and A_NAME in names, str(names))
la.send({"m": "hall_move", "x": 300, "y": 200})
ev = wait_inbox(lb, "hall_state")
pa = next((p for p in (ev or {}).get("players", []) if p.get("name") == A_NAME), None)
check("移动快照广播（位置更新）", pa is not None and pa.get("x") == 300, ev)
la.send({"m": "hall_chat", "text": "你好"})
ev = wait_inbox(lb, "hall_state")
pa = next((p for p in (ev or {}).get("players", []) if p.get("name") == A_NAME), None)
check("聊天气泡随快照广播", pa is not None and pa.get("chat") == "你好", ev)

# ---------------------------------------------------------------- 心跳与断线
la.send({"m": "ping"})
pong = wait_inbox(la, "pong")
check("ping/pong 往返", pong is not None, "没收到 pong")

sid_a = la._sid
la.close()
check("close 后 alive 置 False", not la.alive)
with app._SESH_LOCK:
    s_a = app._SESSIONS.get(sid_a)
check("会话已在桥接侧注销", s_a is None or not s_a.alive, s_a)

# B 仍在：再查一次战绩确认通道健康
r = lb.request({"m": "stats"}, key="stats")
check("A 断开后 B 通道仍健康", r is not None and r.get("m") == "stats", r)
lb.close()

# ---------------------------------------------------------------- 掉线清理（服务器视角）
time.sleep(0.5)
with app._SESH_LOCK:
    left = sum(1 for s in app._SESSIONS.values() if s.alive)
check("桥接无残留会话", left == 0, left)

print(f"\n共 {PASS + FAIL} 项：✓{PASS} ✗{FAIL}")
sys.exit(1 if FAIL else 0)
