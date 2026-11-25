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
import urllib.error
import urllib.parse
import urllib.request


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


def _keepalive(sock):
    """开着 TCP keepalive：跨公网时运营商的 NAT 更容易掐断空连接，
    有保活包就稳得多（服务器端还有 60 秒 ping，双保险）。"""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        pass


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
            _keepalive(sock)
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
    """返回本机所有网卡的 IP（用于判断「这个地址是不是本机」）。

    ⚠ 只返回 UDP 探测到的那一个 IP 是不够的：多网卡机器（Wi-Fi + 有线 +
    VMware/Hyper-V/WSL 虚拟网卡 + Tailscale）上，玩家从系统设置里看到、
    或者大厅自动填的地址，可能不是默认路由那张网卡的地址。此时
    `_is_self_host()` 会判 False → `same_server()` 判成「换了服务器」→
    免密令牌作废 → 进服时被弹回登录框（用户报的「进服退登」）。

    这里把主机名解析出的所有 IPv4 一并收进来，尽量覆盖全部网卡。
    回环只在最后兜底，调用方（local_addr）取第一个用于展示。
    """
    ips = []

    def add(ip):
        if ip and not ip.startswith("127.") and ip not in ips:
            ips.append(ip)

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    # 多网卡：主机名通常能解析出所有网卡地址（含虚拟网卡）
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            add(ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


# ================================================================ 服务器中转

# 云端默认服务器：地址栏输 vitural:6000（virtual/vt 同义）即走 HTTPS 桥接，
# 无需任何人开服。VT_URL 由打包时注入 / 发版时更新。
VT_HOST = "vitural"
VT_HOSTS = {"vitural", "virtual", "vt", "cloud"}
# 云端默认服务器（WorkBuddy 云上常驻，HTTP 桥接内嵌 kards_server）。
# sharecode 是平台分享链接的固定门牌，缺了会被网关 403。
VT_URL = "https://kards-cloud-server.app.workbuddy.host/?sharecode=NUCBKJ7U64"

DEFAULT_SERVER = "vitural:6000"


# 命令 → 「哪个应答属于我」的判定（服务器部分接口不回显 id）
def _m_is(*names):
    def pred(obj, sub):
        return sub in names and obj.get("id") is None
    return pred


_REPLY_MAP = {
    "login":        _m_is("auth_ok", "auth_err"),
    "register":     _m_is("auth_ok", "auth_err"),
    "resume":       _m_is("auth_ok", "auth_err"),
    "adopt":        _m_is("auth_ok", "auth_err"),
    "match":        _m_is("matched", "matching", "err"),
    "create_room":  _m_is("room_created", "err"),
    "join_room":    _m_is("matched", "join_err", "err"),
    "cancel_match": _m_is("match_cancelled", "err"),
    # 战绩类（stats_add / stats_seed 的应答也是 "stats"）
    "stats":        _m_is("stats", "err"),
    "stats_add":    _m_is("stats", "err"),
    "stats_seed":   _m_is("stats", "err"),
    # 段位 / 排行榜（rank_add / rank_add_ai / rank_seed 的应答也是 "rank"）
    "rank":         _m_is("rank", "err"),
    "rank_add":     _m_is("rank", "err"),
    "rank_add_ai":  _m_is("rank", "err"),
    "rank_seed":    _m_is("rank", "err"),
    "rank_board":   _m_is("rank_board", "err"),
    # 删除账号（应答 account_deleted 带 ok 字段；服务端拒绝时 err）
    "delete_account": _m_is("account_deleted", "err"),
}


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


class HttpServerLink(ServerLink):
    """与云端桥接服务器的 HTTPS 长轮询连接。

    与 ServerLink 的接口完全一致（send/request/inbox/on_event/close）。
    实现：内部建一条 socketpair，把 ServerLink 的收发循环原样跑在
    socketpair 的一端，另外两个泵线程负责 HTTP 侧：

      · 下行泵：GET /p 长轮询 → 把服务器事件写进 socketpair
        （ServerLink._recv_loop 从另一端读到，逻辑零改动）
      · 上行泵：从 socketpair 读出客户端消息 → POST /s
        （顺带 25s 心跳，抵消服务器 60s 掉线判定）

    会话先 POST /c 创建（服务器侧为每个会话保持一条真 TCP 连接）。
    """

    POLL_WAIT = 20          # 长轮询挂起秒数
    HEARTBEAT_S = 25        # 上行静默多久补一次 ping
    MAX_POLL_ERR = 3        # 连续失败多少次判掉线

    def __init__(self, base_url, addr=None):
        self.addr = addr
        self.inbox = queue.Queue()
        self.alive = True
        self._buf = b""
        self._lock = threading.RLock()
        self._pending = {}
        self._cbs = []
        self._seq = 0
        self.on_event = None
        self._base = (base_url or "").rstrip("/")
        # 平台分享链接带 sharecode（缺了会被网关 403「链接不完整」）——
        # 把基址拆成 origin + 固定查询串，每个请求都带上。
        _sp = urllib.parse.urlsplit(self._base)
        self._origin = urllib.parse.urlunsplit(
            (_sp.scheme, _sp.netloc, _sp.path.rstrip("/"), "", ""))
        self._share = _sp.query
        a, b = socket.socketpair()
        self.sock = a                 # ServerLink 收发循环用这一端
        self._sockb = b               # 泵线程用另一端
        self._sid = self._req("/c", {}, timeout=12.0).get("sid")
        if not self._sid:
            raise OSError("云端服务器创建会话失败")
        self._last_up = time.time()
        self._poll_err = 0
        threading.Thread(target=self._recv_loop, daemon=True).start()
        threading.Thread(target=self._up, daemon=True).start()
        threading.Thread(target=self._down, daemon=True).start()

    # -------------------------------------------------- HTTP 底座
    def _req(self, path, payload=None, timeout=30.0):
        url = self._origin + path
        if self._share:
            url += ("&" if "?" in url else "?") + self._share
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    # -------------------------------------------------- 泵
    def _up(self):
        """socketpair → POST /s（客户端消息上行）。"""
        try:
            self._sockb.settimeout(0.5)
            while self.alive:
                chunk = None
                try:
                    chunk = self._sockb.recv(8192)
                except socket.timeout:
                    pass
                if chunk:
                    self._req("/s", {"sid": self._sid,
                                     "d": chunk.decode("utf-8", "replace")})
                    self._last_up = time.time()
                elif self.alive and time.time() - self._last_up > self.HEARTBEAT_S:
                    self._req("/s", {"sid": self._sid, "d": '{"m":"ping"}\n'})
                    self._last_up = time.time()
        except Exception:
            pass
        finally:
            self.close()

    def _down(self):
        """GET /p 长轮询 → socketpair（服务器事件下行）。"""
        while self.alive:
            try:
                r = self._req(f"/p?sid={self._sid}&w={self.POLL_WAIT}",
                              timeout=self.POLL_WAIT + 15)
                self._poll_err = 0
            except Exception:
                if not self.alive:
                    return
                self._poll_err += 1
                if self._poll_err >= self.MAX_POLL_ERR:
                    break
                time.sleep(1.5)
                continue
            if not self.alive:
                return
            if r.get("gone"):
                break
            msgs = r.get("m") or []
            if msgs:
                payload = "".join(
                    json.dumps(m, ensure_ascii=False) + "\n" for m in msgs)
                try:
                    self._sockb.sendall(payload.encode("utf-8"))
                except OSError:
                    break
        self.close()

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
        for s in (self.sock, self._sockb):
            try:
                s.close()
            except OSError:
                pass
        try:
            self._req("/x", {"sid": self._sid}, timeout=3.0)
        except Exception:
            pass


def parse_addr(text, default_port=6000):
    """把 "1.2.3.4:6000" / "1.2.3.4" 解析成 (host, port)，非法返回 None。

    云端默认服务器的别名（vitural / virtual / vt / cloud）统一归一成
    "vitural" —— 这样 same_server("vitural:6000", "virtual:6000") 判同一台，
    免密令牌不会因拼写不同而作废。
    """
    text = (text or "").strip()
    if not text:
        return None
    host, _, port_s = text.rpartition(":")
    if not host:                     # 没写冒号 → 整个是 host
        host, port_s = text, str(default_port)
    host = host.strip()
    if host.lower() in VT_HOSTS:
        host = VT_HOST
    try:
        port = int(port_s)
    except ValueError:
        return None
    if not (1 <= port <= 65535) or not host:
        return None
    return host, port


# 本机对外的公网 IP（UPnP 端口映射成功后由 kards_host 登记）。
#
# 为什么需要：大厅「一键改为公网」会把地址框填成 `公网IP:端口`。玩家接着
# 点「连接」时，如果它不被认作本机，就会同时踩两个坑：
#   ① `same_server()` 判成「换了一台服务器」→ resume 被跳过 → 免密令牌
#      作废 → 已登录的玩家被打回登录框（用户报的「进服就退登」）；
#   ② 真去连自己的公网 IP → 很多家用路由器不支持 hairpin NAT，直接超时，
#      玩家看到的是「连接失败」。
# 登记之后这两个地址就是同一台服务器，连接也会走回环（见 connect_server_async）。
_PUBLIC_IPS = set()


def register_public_ip(ip):
    """登记本机的公网 IP（幂等；空值/回环忽略）。"""
    ip = (ip or "").strip()
    if ip and ip not in ("0.0.0.0", "127.0.0.1", "::1"):
        _PUBLIC_IPS.add(ip)


def clear_public_ip():
    """撤销登记（端口映射被撤掉时调用）。"""
    _PUBLIC_IPS.clear()


def _is_self_host(host):
    """host 是否指本机（回环 / localhost / 本机局域网 IP / 本机公网 IP）"""
    if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0", ""):
        return True
    if host in _PUBLIC_IPS:
        return True
    try:
        return host in get_local_ips()
    except Exception:                        # noqa: BLE001
        return False


def is_self_host(host):
    """对外别名：这个 host 是不是本机（大厅判断「我是不是主机」用）。"""
    return _is_self_host(host)


def same_server(a, b):
    """两个 "host:port" 是否指向**同一台服务器**。

    为什么不能直接比字符串：本机开服时大厅会把地址填成局域网地址
    （192.168.x.x:6000），而玩家之前可能是用 127.0.0.1:6000 登录的 ——
    字符串不同，其实是同一台机器、同一个端口，也就是同一台服务器。

    旧代码直接比字符串，于是「点『建立服务器』」= 换了服务器 →
    缓存的免密令牌被判无效 → 已登录的玩家被打回登录框
    （用户报的「开服就退登」）。
    """
    pa, pb = parse_addr(a), parse_addr(b)
    if not pa or not pb:
        return False
    ha, port_a = pa
    hb, port_b = pb
    if port_a != port_b:
        return False
    if ha == hb:
        return True
    # 端口相同、两台主机都指本机 → 同一台（回环地址与局域网地址互通）
    return _is_self_host(ha) and _is_self_host(hb)


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
    # 云端默认服务器（vitural:6000）：走 HTTPS 长轮询桥接，不走 TCP。
    if host == VT_HOST:
        def run_cloud():
            if not VT_URL:
                holder["result"] = ("err", "云端服务器地址未配置")
                return
            try:
                holder["result"] = (HttpServerLink(VT_URL, (host, port)),)
            except Exception as e:               # noqa: BLE001  网络层异常统一变连接失败
                holder["result"] = ("err", f"云端服务器连接失败: {e}")
        threading.Thread(target=run_cloud, daemon=True).start()
        return
    # 公网地址指向本机 → 走回环。家用路由器普遍不支持 hairpin NAT
    # （内网访问自己的公网 IP 会超时），直连 127.0.0.1 才稳。
    if host in _PUBLIC_IPS:
        host = "127.0.0.1"

    def run():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            _keepalive(sock)
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
