# -*- coding: utf-8 -*-
"""
KARDS 联机模块：两种连接方式 + 行动同步通道。

1. **局域网 TCP 直连**（主机 / 加入）
   `Acceptor` + `connect_async`，两端直接对话，无需服务器。

2. **服务器中转**（推荐，公网可用）
   `ServerLink` 连到 `kards_server.py`，由服务器负责账号、大厅、
   匹配/邀请码房间，并转发对局行动。玩家之间不需要互相能连通。

同步模型（锁定步 lockstep）：
  双方各自运行一份完全相同的对局状态，网络上只交换「行动指令」
  （出牌 / 攻击 / 机动 / 结束回合 / 投降）。开局时由主机生成随机
  种子发给对方，双方用同一种子 + 相同的行动序列保证抽牌与随机
  效果完全一致。

消息格式：换行分隔的 JSON（UTF-8）。
信封字段固定为 **"m"**（message）。
  注意：对局行动里 "t" 表示「目标槽位」，与信封字段绝不能同名，
  否则会被 unpack 覆盖（历史 bug，已修）。
"""

import json
import queue
import socket
import threading
import time


class NetLink:
    """一条已建立的 TCP 连接：后台线程收包入队，send() 线程安全。"""

    def __init__(self, sock, addr=None):
        self.sock = sock
        self.addr = addr
        self.inbox = queue.Queue()
        self.alive = True
        self._buf = b""
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _recv_loop(self):
        try:
            while self.alive:
                data = self.sock.recv(4096)
                if not data:
                    break
                self._buf += data
                while b"\n" in self._buf:
                    line, self._buf = self._buf.split(b"\n", 1)
                    if line.strip():
                        try:
                            self.inbox.put(json.loads(line.decode("utf-8")))
                        except (ValueError, UnicodeDecodeError):
                            pass  # 坏包直接丢弃，不让连接崩掉
        except OSError:
            pass
        finally:
            self.close()

    def send(self, obj):
        if not self.alive:
            return False
        try:
            payload = json.dumps(obj, ensure_ascii=False) + "\n"
            self.sock.sendall(payload.encode("utf-8"))
            return True
        except OSError:
            self.close()
            return False

    def close(self):
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


class Acceptor:
    """主机端：后台监听指定端口，等待对手连接。

    用法：
        acc = Acceptor(5555)
        ...轮询 acc.result...
        acc.result == (NetLink,)          连接成功
        acc.result == ("err", "原因")     出错
        acc.cancel()                      取消等待
    """

    def __init__(self, port):
        self.result = None
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("", port))
        self._srv.listen(1)
        self._srv.settimeout(0.5)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while self.result is None:
            try:
                sock, addr = self._srv.accept()
                self.result = (NetLink(sock, addr),)
                return
            except socket.timeout:
                continue
            except OSError as e:
                self.result = ("err", str(e))
                return

    def cancel(self):
        try:
            self._srv.close()
        except OSError:
            pass
        if self.result is None:
            self.result = ("err", "已取消")


def connect_async(ip, port, holder):
    """客户端：后台连接 ip:port，结果写入 holder["result"]。

    成功：holder["result"] = (NetLink,)
    失败：holder["result"] = ("err", "原因")
    """
    def run():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(6)
        try:
            sock.connect((ip, port))
            sock.settimeout(None)
            holder["result"] = (NetLink(sock, (ip, port)),)
        except OSError as e:
            try:
                sock.close()
            except OSError:
                pass
            holder["result"] = ("err", str(e))
    threading.Thread(target=run, daemon=True).start()


def get_local_ips():
    """返回本机在局域网中的 IP 列表（用于告诉对手连接地址）。"""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    if not ips:
        try:
            ips.append(socket.gethostbyname(socket.gethostname()))
        except OSError:
            pass
    return ips or ["127.0.0.1"]


# ================================================================ 服务器中转

DEFAULT_SERVER = "127.0.0.1:6000"


class ServerLink:
    """一条与 kards_server 的长连接。

    与 NetLink 的区别：多了「请求/应答」语义。
        send(obj)                 单向发送（信封字段用 "m"）
        request(obj, timeout)     发送并阻塞等待应答

    应答的配对规则（见 kards_server.py 的 ClientHandler）：
      · **回显式**：形如 {"id": 5, "m": "stats", ...} —— 服务器把请求里
        的 "id" 原样带回来，客户端靠它精准配对。
      · **命令映射式**：login → auth_ok，match → matched/matching，
        create_room → room_created 等。
    两者都在 on_reply 回调里筛掉，这样 GUI 的 inbox 里只剩「真事件」。
    """

    def __init__(self, sock, addr=None):
        self.sock = sock
        self.addr = addr
        self.inbox = queue.Queue()          # 未被回调消费的推送事件
        self.alive = True
        self._buf = b""
        self._lock = threading.RLock()
        self._pending = {}                  # id -> queue.Queue
        self._cbs = []                      # [(pred, q)] 命令映射式等待者
        self._seq = 0
        self.on_event = None                # 可选：每个非应答包都回调一次
        threading.Thread(target=self._recv_loop, daemon=True).start()

    # -------------------------------------------------- 收

    def _recv_loop(self):
        try:
            while self.alive:
                data = self.sock.recv(4096)
                if not data:
                    break
                self._buf += data
                while b"\n" in self._buf:
                    line, self._buf = self._buf.split(b"\n", 1)
                    if line.strip():
                        try:
                            self._dispatch(json.loads(line.decode("utf-8")))
                        except (ValueError, UnicodeDecodeError):
                            pass  # 坏包直接丢弃，不让连接崩掉
        except OSError:
            pass
        finally:
            self.close()

    def _dispatch(self, obj):
        if not isinstance(obj, dict):
            return
        if self._consume_reply(obj):
            return
        self.inbox.put(obj)
        cb = self.on_event
        if cb is not None:
            try:
                cb(obj)
            except Exception:
                pass

    def _consume_reply(self, obj):
        """把应答从队列里摘走，返回 True 表示这是应答不是事件。"""
        mid = obj.get("id")
        with self._lock:
            if mid is not None:
                q = self._pending.pop(mid, None)
                if q is not None:
                    q.put(obj)
                    return True
            sub = obj.get("m")
            for pred, q in list(self._cbs):
                if pred(obj, sub):
                    self._cbs.remove((pred, q))
                    q.put(obj)
                    return True
        return False

    # -------------------------------------------------- 发

    def send(self, obj):
        if not self.alive:
            return False
        try:
            payload = json.dumps(obj, ensure_ascii=False) + "\n"
            with self._lock:
                self.sock.sendall(payload.encode("utf-8"))
            return True
        except OSError:
            self.close()
            return False

    def request(self, obj, timeout=6.0, key=None):
        """发一条请求并等应答。超时 / 断线返回 None。

        key 缺省时自动登记一个唯一 "id"（服务器会原样回显）；
        key 给定时按「命令 → 应答类型」映射等待，用于服务器不回显 id 的接口。
        """
        obj = dict(obj)
        q = queue.Queue()
        with self._lock:
            if key is None:
                self._seq += 1
                obj["id"] = self._seq
                tid = obj["id"]
                self._pending[tid] = q
            else:
                pred = _REPLY_MAP.get(key)
                if pred is None:
                    return None
                self._cbs.append((pred, q))
        if not self.send(obj):
            with self._lock:
                self._pending.pop(obj.get("id"), None)
                for item in list(self._cbs):
                    if item[1] is q:
                        self._cbs.remove(item)
            return None
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            with self._lock:
                self._pending.pop(obj.get("id"), None)
                for item in list(self._cbs):
                    if item[1] is q:
                        self._cbs.remove(item)
            return None

    def close(self):
        if not self.alive:
            return
        self.alive = False
        with self._lock:
            for q in self._pending.values():
                q.put(None)
            self._pending.clear()
            for _, q in self._cbs:
                q.put(None)
            self._cbs.clear()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# 命令 → 「哪个应答属于我」的判定（服务器部分接口不回显 id）
def _m_is(*names):
    def pred(obj, sub):
        return sub in names and obj.get("id") is None
    return pred


_REPLY_MAP = {
    "login":        _m_is("auth_ok", "auth_err"),
    "register":     _m_is("auth_ok", "auth_err"),
    "resume":       _m_is("auth_ok", "auth_err"),
    "match":        _m_is("matched", "matching", "err"),
    "create_room":  _m_is("room_created", "err"),
    "join_room":    _m_is("matched", "join_err", "err"),
    "cancel_match": _m_is("match_cancelled", "err"),
}


def parse_addr(text, default_port=6000):
    """把 "1.2.3.4:6000" / "1.2.3.4" 解析成 (host, port)，非法返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    host, _, port_s = text.rpartition(":")
    if not host:                     # 没写冒号 → 整个是 host
        host, port_s = text, str(default_port)
    try:
        port = int(port_s)
    except ValueError:
        return None
    if not (1 <= port <= 65535) or not host:
        return None
    return host, port


def connect_server_async(addr, holder, timeout=6.0):
    """后台连服务器，结果写 holder["result"]。

    成功：holder["result"] = (ServerLink,)
    失败：holder["result"] = ("err", "原因")
    """
    parsed = parse_addr(addr)
    if parsed is None:
        holder["result"] = ("err", "地址格式应为 主机:端口，例如 127.0.0.1:6000")
        return
    host, port = parsed

    def run():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            sock.settimeout(None)
            holder["result"] = (ServerLink(sock, (host, port)),)
        except OSError as e:
            try:
                sock.close()
            except OSError:
                pass
            holder["result"] = ("err", str(e))
    threading.Thread(target=run, daemon=True).start()


class ServerPoller:
    """轮询 ServerLink 连接结果（GUI 主线程用）。"""

    def __init__(self, addr):
        self.addr = addr
        self.holder = {}
        self._link = None
        connect_server_async(addr, self.holder)

    @property
    def ready(self):
        return self.holder.get("result") is not None

    def take(self):
        """返回 (ServerLink,) 或 ("err", 原因)；尚未完成返回 None。"""
        res = self.holder.get("result")
        if res is None:
            return None
        self.holder["result"] = None
        return res


def now():
    return time.time()
