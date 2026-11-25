# -*- coding: utf-8 -*-
"""KARDS 云端默认服务器 —— HTTP 桥接（单端口常驻，零依赖）

把公网 HTTP 请求桥接到内嵌的真实 kards_server（TCP，回环临时端口）：

  客户端(HTTPS 长轮询) ⇄ 本桥 ⇄ kards_server(TCP)

每个 HTTP 会话对应一条到内嵌服务器的真 TCP 连接，协议原样透传
（换行分隔 JSON），服务器逻辑零改动。

接口：
  POST /c            创建会话 → {"sid": ...}
  POST /s {sid,d}    把原始 JSON 行文本写入内部服务器
  GET  /p?sid&w=20   长轮询内部服务器的输出 → {"m":[...]} / {"gone":true}
  POST /x {sid}      关闭会话
  GET  /             状态页（部署探活）

安全：所有内部连接源都是 127.0.0.1，必须关闭 is_local_peer（adopt
免密接管），否则任何互联网用户都能免密接管任意账号。
"""
import json
import os
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import kards_server as ks  # noqa: E402

# ---- 公网桥接安全 --------------------------------------------------------
# 桥接进来的连接源全部是 127.0.0.1（对内嵌服务器而言）。is_local_peer
# 只为「玩家在自己开的服上免密恢复」设计，云端不成立 —— 直接禁用。
ks.is_local_peer = lambda ip: False

MAX_SESSIONS = 400
SESSION_IDLE = 150          # HTTP 侧静默超过该秒数视为掉线
BODY_LIMIT = 65536


def _pick_db_path():
    # KARDS_DATA_DIR 优先（测试隔离用，与 kards_server 约定一致）
    candidates = []
    env_dir = os.environ.get("KARDS_DATA_DIR")
    if env_dir:
        candidates.append(env_dir)
    candidates += [os.path.join(HERE, "data"), "/tmp"]
    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            return os.path.join(d, "kards_cloud.db")
        except OSError:
            continue
    return os.path.join(os.getcwd(), "kards_cloud.db")


ks.DB = ks.Store(_pick_db_path())

_internal = ks.Server(("127.0.0.1", 0), ks.ClientHandler)
_INTERNAL_ADDR = _internal.server_address[:2]
threading.Thread(target=_internal.serve_forever, daemon=True).start()


class Session:
    """一个客户端会话 = 一条到内嵌服务器的 TCP 连接。"""

    def __init__(self):
        self.sid = secrets.token_urlsafe(16)
        self.sock = socket.create_connection(_INTERNAL_ADDR, timeout=6)
        self.sock.settimeout(None)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        self.out = bytearray()          # 内部服务器的原始输出
        self.cond = threading.Condition()
        self.last_http = time.time()
        self.alive = True
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            while self.alive:
                data = self.sock.recv(8192)
                if not data:
                    break
                with self.cond:
                    self.out += data
                    self.cond.notify_all()
        except OSError:
            pass
        finally:
            self.kill()

    def kill(self):
        if not self.alive:
            return
        self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        with self.cond:
            self.cond.notify_all()

    def touch(self):
        self.last_http = time.time()

    def send_text(self, text):
        self.sock.sendall(text.encode("utf-8"))

    def poll(self, wait_s):
        """等最多 wait_s 秒；返回消息列表 / None(超时) / "gone"(会话已死)。"""
        deadline = time.time() + wait_s
        with self.cond:
            while self.alive and b"\n" not in self.out:
                remain = deadline - time.time()
                if remain <= 0:
                    return None
                self.cond.wait(min(remain, 1.0))
            if not self.alive:
                return "gone"
            lines = self.out.split(b"\n")
            self.out = bytearray(lines.pop())     # 尾部不完整行留下
            msgs = []
            for ln in lines:
                if ln.strip():
                    try:
                        msgs.append(json.loads(ln.decode("utf-8")))
                    except (ValueError, UnicodeDecodeError):
                        pass
            return msgs


_SESSIONS = {}
_SESH_LOCK = threading.Lock()
_STARTED_AT = time.time()


def _gc_loop():
    while True:
        time.sleep(20)
        cutoff = time.time() - SESSION_IDLE
        with _SESH_LOCK:
            dead = [s for s in _SESSIONS.values() if s.last_http < cutoff]
        for s in dead:
            s.kill()
            with _SESH_LOCK:
                _SESSIONS.pop(s.sid, None)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "KardsRelay/1.0"

    def log_message(self, fmt, *args):     # 安静
        pass

    # ------------------------------------------------------------- 工具
    def _json(self, code, obj, body=None):
        data = body if body is not None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            pass

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if n <= 0 or n > BODY_LIMIT:
            return None
        return self.rfile.read(n)

    def _sess(self, sid):
        with _SESH_LOCK:
            s = _SESSIONS.get((sid or "").strip())
        if s is not None and s.alive:
            s.touch()
        return s

    # ------------------------------------------------------------- 路由
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            alive = sum(1 for s in list(_SESSIONS.values()) if s.alive)
            snap = ks.lobby_snapshot()
            hall = ks.hall_snapshot()
            html = (
                "<!doctype html><meta charset='utf-8'><title>KARDS 云端服务器</title>"
                "<body style='font-family:system-ui;background:#101418;color:#dcd6c8;"
                "max-width:520px;margin:8vh auto;line-height:1.7'>"
                "<h1>♥ KARDS 简化版 · 云端默认服务器</h1>"
                "<p>运行中 — 在游戏「战斗 → 服务器」里输入 <b>vitural:6000</b> 即可进入。</p>"
                f"<p>在线大厅 {len(snap)} 人 · 走动大厅 {len(hall)} 人 · 活跃会话 {alive}</p>"
                f"<p style='color:#777'>uptime {int(time.time() - _STARTED_AT)}s</p>"
                "</body>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            try:
                self.wfile.write(html)
            except OSError:
                pass
            return
        if u.path == "/healthz":
            self._json(200, {"ok": True})
            return
        if u.path == "/p":
            s = self._sess((q.get("sid") or [""])[0])
            if s is None:
                self._json(200, {"gone": True})
                return
            try:
                w = min(max(float((q.get("w") or ["20"])[0]), 0.0), 25.0)
            except ValueError:
                w = 20.0
            r = s.poll(w)
            if r == "gone":
                self._json(200, {"gone": True})
            elif r is None:
                self._json(200, {"m": []})
            else:
                self._json(200, {"m": r})
            return
        self._json(404, {"err": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        body = self._body()
        if body is None and u.path != "/c":
            self._json(400, {"err": "bad body"})
            return
        if u.path == "/c":
            with _SESH_LOCK:
                if len([s for s in _SESSIONS.values() if s.alive]) >= MAX_SESSIONS:
                    self._json(429, {"err": "服务器繁忙"})
                    return
            try:
                s = Session()
            except OSError as e:
                self._json(502, {"err": f"内部服务器不可达: {e}"})
                return
            with _SESH_LOCK:
                _SESSIONS[s.sid] = s
            self._json(200, {"sid": s.sid})
            return
        try:
            obj = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"err": "bad json"})
            return
        sid = obj.get("sid")
        if u.path == "/s":
            s = self._sess(sid)
            if s is None:
                self._json(200, {"gone": True})
                return
            try:
                s.send_text(str(obj.get("d") or ""))
                self._json(200, {"ok": True})
            except OSError:
                s.kill()
                self._json(200, {"gone": True})
            return
        if u.path == "/x":
            s = self._sess(sid)
            if s is not None:
                s.kill()
                with _SESH_LOCK:
                    _SESSIONS.pop(s.sid, None)
            self._json(200, {"ok": True})
            return
        self._json(404, {"err": "not found"})


def start_http(port=0):
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=_gc_loop, daemon=True).start()
    return httpd


def main():
    port = int(os.environ.get("PORT") or 8080)
    ks.log("=" * 56)
    ks.log("KARDS 简化版 · 云端默认服务器（HTTP 桥接）")
    ks.log(f"  数据库   : {ks.DB.path if hasattr(ks.DB, 'path') else _pick_db_path()}")
    ks.log(f"  内部 TCP : {_INTERNAL_ADDR[0]}:{_INTERNAL_ADDR[1]}")
    ks.log(f"  HTTP     : 0.0.0.0:{port}")
    ks.log("=" * 56)
    httpd = start_http(port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
