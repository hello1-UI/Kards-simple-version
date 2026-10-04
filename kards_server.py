# -*- coding: utf-8 -*-
"""
KARDS 简化版 —— 联机服务器（纯标准库，单文件，零依赖）

功能：
  1. 账号系统   ：注册 / 登录 / 会话 token / 战绩统计 / 卡组云同步（SQLite）
  2. 在线大厅   ：在线玩家列表实时广播
  3. 匹配撮合   ：自动匹配 + 房间邀请码
  4. 对局中转   ：双方只连服务器，服务器转发行动指令（解决 NAT / 防火墙问题）
  5. 断线处理   ：掉线通知对手，房间自动回收

启动：
    python kards_server.py                    # 默认 0.0.0.0:6000
    python kards_server.py --port 6000        # 指定端口
    python kards_server.py --db server.db     # 指定数据库
    python kards_server.py --host 127.0.0.1   # 只监听本机（仅本机客户端可连）

协议：TCP + 换行分隔 JSON（UTF-8）。
     信封字段用 "m" 表示消息类型（message），**不要用 "t"** ——
     游戏内的行动指令里有 "t" 表示目标槽位，用 "t" 做信封会被覆盖。
     首条消息必须是 {"m":"login"/"register"/"resume", ...}，
     之后服务器回 {"m":"auth_ok"}/{"m":"auth_err"}。
     认证失败回 auth_err 后**连接保留**，可在同一连接上重试
     （客户端的本地账号迁移依赖这一点）；协议级垃圾才直接断开。
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import socket
import socketserver
import sqlite3
import sys
import threading
import time

DEFAULT_PORT = 6000
SESSION_TTL = 30 * 24 * 3600      # 会话 token 有效期 30 天
HEARTBEAT_TIMEOUT = 60            # 超过该秒数没收到任何消息则判定掉线
PRINT_LOCK = threading.Lock()


def user_data_db():
    """打包运行时的数据库路径（%USERPROFILE%\\AppData\\Kards-Simple-Version）。

    安装目录常在 Program Files 下，普通用户没有写权限；把库放那儿
    第一次注册就会炸。用户数据目录与游戏主体（settings/logs/decks）保持一致。
    """
    base = os.environ.get("KARDS_DATA_DIR")
    if not base:
        base = os.path.join(os.path.expanduser("~"), "AppData", "Kards-Simple-Version")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        return os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                            "kards_server.db")
    return os.path.join(base, "kards_server.db")


def log(msg):
    with PRINT_LOCK:
        sys.stdout.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        sys.stdout.flush()


# ----------------------------------------------------------------- 数据库

DB_LOCK = threading.RLock()


class Store:
    """SQLite 封装：所有写操作加全局锁（sqlite3 连接不能跨线程共享）。"""

    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init()

    def _init(self):
        with DB_LOCK:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    name    TEXT PRIMARY KEY,
                    salt    TEXT NOT NULL,
                    pw      TEXT NOT NULL,
                    created INTEGER NOT NULL,
                    last_seen INTEGER,
                    win     INTEGER NOT NULL DEFAULT 0,
                    lose    INTEGER NOT NULL DEFAULT 0,
                    draw    INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token   TEXT PRIMARY KEY,
                    name    TEXT NOT NULL,
                    created INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decks (
                    name    TEXT NOT NULL,
                    nation  TEXT NOT NULL,
                    title   TEXT NOT NULL,
                    content TEXT NOT NULL,
                    updated INTEGER NOT NULL,
                    PRIMARY KEY (name, nation, title)
                );
                """
            )
            self.conn.commit()

    def q(self, sql, args=()):
        with DB_LOCK:
            return self.conn.execute(sql, args).fetchall()

    def x(self, sql, args=()):
        with DB_LOCK:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    # ---- 账号 ----

    @staticmethod
    def hash_pw(salt, pw):
        return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"),
                                   salt.encode("utf-8"), 60000).hex()

    def register(self, name, pw):
        if self.q("SELECT 1 FROM users WHERE name=?", (name,)):
            return None, "该用户名已被注册"
        salt = secrets.token_hex(16)
        self.x("INSERT INTO users(name,salt,pw,created,last_seen) VALUES(?,?,?,?,?)",
               (name, salt, self.hash_pw(salt, pw), int(time.time()), int(time.time())))
        return self.new_session(name), ""

    def login(self, name, pw):
        rows = self.q("SELECT salt,pw FROM users WHERE name=?", (name,))
        if not rows or rows[0]["pw"] != self.hash_pw(rows[0]["salt"], pw):
            return None, "用户名或密码错误"
        self.x("UPDATE users SET last_seen=? WHERE name=?", (int(time.time()), name))
        return self.new_session(name), ""

    def new_session(self, name):
        tok = secrets.token_urlsafe(24)
        self.x("INSERT INTO sessions(token,name,created) VALUES(?,?,?)",
               (tok, name, int(time.time())))
        return tok

    def who(self, token):
        """token -> 用户名（无效返回 None）"""
        if not token:
            return None
        rows = self.q("SELECT name,created FROM sessions WHERE token=?", (token,))
        if not rows:
            return None
        if time.time() - rows[0]["created"] > SESSION_TTL:
            self.x("DELETE FROM sessions WHERE token=?", (token,))
            return None
        return rows[0]["name"]

    def drop_session(self, token):
        self.x("DELETE FROM sessions WHERE token=?", (token,))

    def stats(self, name):
        rows = self.q("SELECT win,lose,draw FROM users WHERE name=?", (name,))
        if not rows:
            return {"win": 0, "lose": 0, "draw": 0}
        r = rows[0]
        return {"win": r["win"], "lose": r["lose"], "draw": r["draw"]}

    def stats_add(self, name, result):
        if result not in ("win", "lose", "draw"):
            return
        self.x(f"UPDATE users SET {result}={result}+1 WHERE name=?", (name,))

    def stats_seed(self, name, win, lose, draw):
        """一次性写入初始战绩（本地账号迁移上云用）。

        ⚠ 只在账号当前战绩全 0 时生效：防止有人对已有战绩的账号
        反复 seed 灌水。迁移场景下服务器账号是刚注册的，必然全 0。
        """
        self.x("UPDATE users SET win=?, lose=?, draw=?"
               " WHERE name=? AND win=0 AND lose=0 AND draw=0",
               (max(0, int(win)), max(0, int(lose)), max(0, int(draw)), name))

    def exists(self, name):
        return bool(self.q("SELECT 1 FROM users WHERE name=?", (name,)))

    # ---- 卡组云同步 ----

    def deck_save(self, name, nation, title, content):
        self.x("INSERT OR REPLACE INTO decks(name,nation,title,content,updated)"
               " VALUES(?,?,?,?,?)",
               (name, nation, title, content, int(time.time())))

    def deck_list(self, name):
        rows = self.q("SELECT nation,title,updated FROM decks WHERE name=?"
                      " ORDER BY updated DESC", (name,))
        return [{"nation": r["nation"], "title": r["title"],
                 "updated": r["updated"]} for r in rows]

    def deck_get(self, name, nation, title):
        rows = self.q("SELECT content FROM decks WHERE name=? AND nation=? AND title=?",
                      (name, nation, title))
        return rows[0]["content"] if rows else None

    def deck_del(self, name, nation, title):
        self.x("DELETE FROM decks WHERE name=? AND nation=? AND title=?",
               (name, nation, title))


DB = None          # 全局 Store 实例，main() 中赋值


# ----------------------------------------------------------------- 房间 / 大厅

class Room:
    """一场对局：两名玩家 + 角色分配。行动指令由服务器转发。"""

    _next_id = 1

    def __init__(self, a, b):
        with DB_LOCK:
            self.id = Room._next_id
            Room._next_id += 1
        # a = host（先手判定方 / 发种子方），b = guest
        self.host = a
        self.guest = b
        a.room = self
        a.role = "host"
        b.room = self
        b.role = "guest"
        self.created = time.time()
        self.seed = None

    def other(self, cli):
        return self.guest if cli is self.host else self.host

    def alive(self):
        return (self.host is not None and self.host.alive
                and self.guest is not None and self.guest.alive)


# 大厅全局状态
LOBBY_LOCK = threading.RLock()
CLIENTS = {}       # name -> ClientHandler（同一账号只允许一个连接）
MATCH_QUEUE = []   # 等待匹配的 ClientHandler 列表
ROOMS = []         # 进行中的房间
ROOMS_BY_CODE = {} # 邀请码 -> Room


def lobby_snapshot():
    return [{"name": c.name, "stats": DB.stats(c.name), "in_game": c.room is not None}
            for c in CLIENTS.values()]


def broadcast_lobby():
    """给所有在大厅（未进入对局）的玩家推送在线列表"""
    snap = lobby_snapshot()
    for c in list(CLIENTS.values()):
        if c.room is None:
            c.push({"m": "lobby", "players": snap})


# ----------------------------------------------------------------- 连接处理

class ClientHandler(socketserver.BaseRequestHandler):
    """一条客户端连接。所有业务消息都在这里的 handle() 循环里处理。"""

    # ---------- 底层收发 ----------

    def setup(self):
        self.sock = self.request
        self.sock.settimeout(HEARTBEAT_TIMEOUT)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.wlock = threading.Lock()
        self.alive = True
        self.name = None       # 登录后的用户名
        self.token = None
        self.room = None
        self.role = None
        self.code = None       # 自己创建的房间邀请码（等待对手加入）
        self.last_rx = time.time()
        self._buf = b""

    def push(self, obj):
        """线程安全发送；返回是否成功（供房间对象判断存活）"""
        return self.send(obj)

    def send(self, obj):
        if not self.alive:
            return False
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        with self.wlock:
            try:
                self.sock.sendall(data)
                return True
            except OSError:
                self.alive = False
                return False

    def recv_obj(self):
        """取一条完整消息（连接关闭返回 None，超时抛 socket.timeout）"""
        while b"\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                return None
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        line = line.strip()
        if not line:
            return {}
        try:
            return json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # ---------- 主循环 ----------

    def handle(self):
        log(f"连接来自 {self.client_address[0]}:{self.client_address[1]}")
        try:
            # 第一步：登录握手。
            # ⚠ 认证失败（密码错 / 令牌失效 / 重名）**不断开连接**：
            #   客户端的「本地账号自动迁移」要在登录被拒后紧接着用
            #   同一条连接发 register；断开会让重试和迁移全部哑火，
            #   用户改个密码重输也得重连一次。只有协议垃圾 / 超时 /
            #   空报文才直接关闭（那种多半不是我们的客户端）。
            while True:
                state = self.handshake()
                if state == "ok":
                    break
                if state == "close":
                    return
            while self.alive:
                try:
                    msg = self.recv_obj()
                except socket.timeout:
                    self.send({"m": "ping"})
                    continue
                except OSError:
                    break
                if msg is None:
                    break
                self.last_rx = time.time()
                self.dispatch(msg)
        except Exception as e:                       # 单连接异常不影响服务器
            log(f"连接异常({self.client_address[0]}): {e!r}")
        finally:
            self.cleanup()

    # ---------- 握手 ----------

    def handshake(self):
        """登录/注册/续期。

        返回 "ok"（认证通过）/ "retry"（认证被拒，连接保留，等下一条
        握手消息）/ "close"（协议垃圾 / 超时 / 断开，直接关连接）。
        """
        try:
            msg = self.recv_obj()
        except socket.timeout:
            log(f"握手超时({self.client_address[0]})")
            return "close"
        except OSError as e:
            log(f"握手读失败({self.client_address[0]}): {e!r}")
            return "close"
        if msg is None:
            log(f"握手前连接关闭({self.client_address[0]})")
            return "close"
        if not msg:
            self.send({"m": "auth_err", "err": "协议错误：首条消息必须是 login/register/resume"})
            return "close"
        t = msg.get("m")
        log(f"握手请求({self.client_address[0]}): t={t} user={msg.get('user')!r}")

        if t == "register":
            name, err = norm_name(msg.get("user"))
            if err:
                self.send({"m": "auth_err", "err": err})
                return "retry"
            err = norm_pw(msg.get("pw"))
            if err:
                self.send({"m": "auth_err", "err": err})
                return "retry"
            with DB_LOCK:
                tok, err = DB.register(name, msg["pw"])
            if err:
                self.send({"m": "auth_err", "err": err})
                return "retry"
        elif t == "login":
            name, err = norm_name(msg.get("user"))
            if err:
                self.send({"m": "auth_err", "err": err})
                return "retry"
            with DB_LOCK:
                tok, err = DB.login(name, msg.get("pw") or "")
            if err:
                self.send({"m": "auth_err", "err": err})
                return "retry"
        elif t == "resume":
            name = DB.who(msg.get("token"))
            if not name:
                self.send({"m": "auth_err", "err": "会话已失效，请重新登录"})
                return "retry"
            tok = msg["token"]
        else:
            self.send({"m": "auth_err", "err": "协议错误：首条消息必须是 login/register/resume"})
            return "close"

        tok, err = self.bind_name(name, tok)
        if err:
            self.send({"m": "auth_err", "err": err})
            return "retry"
        return "ok"

    def bind_name(self, name, tok):
        """把连接与账号绑定；同一账号重复登录会踢掉旧连接。

        注意：踢人动作不能在 LOBBY_LOCK 里做 —— 旧连接的 cleanup() 也会去
        抢同一把锁，会造成死锁。这里只做「查出旧连接」，锁外再踢。
        """
        with LOBBY_LOCK:
            old = CLIENTS.get(name)
            self.name = name
            self.token = tok
            CLIENTS[name] = self

        if old is not None and old is not self:
            # 先告知原因再切断。
            # 注意顺序：不能先置 alive=False —— send() 开头就是
            # `if not self.alive: return False`，置了 False 这条 kick 就发不出去，
            # 被踢的一方只会看到连接被无声断开。
            old.send({"m": "kick", "err": "该账号已在别处登录"})
            old.alive = False

        self.send({"m": "auth_ok", "user": name, "token": tok,
                   "stats": DB.stats(name)})

        if old is not None and old is not self:
            try:
                old.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        log(f"登录: {name}")
        broadcast_lobby()
        return tok, ""

    # ---------- 消息分发 ----------

    def dispatch(self, msg):
        t = msg.get("m")
        if t == "ping":
            self.send({"m": "pong"})
        elif t == "pong":
            pass
        elif t == "lobby":
            self.send({"m": "lobby", "players": lobby_snapshot()})
        elif t == "match":
            self.do_match()
        elif t == "cancel_match":
            self.do_cancel_match()
        elif t == "create_room":
            self.do_create_room()
        elif t == "join_room":
            self.do_join_room(msg.get("code"))
        elif t in ("act", "seed", "ready", "concede", "chat"):
            self.do_relay(msg)
        elif t == "stats":
            self.send({"m": "stats", "stats": DB.stats(self.name)})
        elif t == "stats_add":
            DB.stats_add(self.name, msg.get("result"))
            self.send({"m": "stats", "stats": DB.stats(self.name)})
        elif t == "stats_seed":
            DB.stats_seed(self.name, msg.get("win", 0),
                          msg.get("lose", 0), msg.get("draw", 0))
            self.send({"m": "stats", "stats": DB.stats(self.name)})
        elif t == "deck_save":
            DB.deck_save(self.name, msg.get("nation", ""), msg.get("title", ""),
                         msg.get("content", ""))
            self.send({"m": "deck_saved", "title": msg.get("title")})
        elif t == "deck_list":
            self.send({"m": "deck_list", "decks": DB.deck_list(self.name)})
        elif t == "deck_get":
            c = DB.deck_get(self.name, msg.get("nation", ""), msg.get("title", ""))
            self.send({"m": "deck_data", "title": msg.get("title"), "content": c})
        elif t == "deck_del":
            DB.deck_del(self.name, msg.get("nation", ""), msg.get("title", ""))
            self.send({"m": "deck_list", "decks": DB.deck_list(self.name)})
        elif t == "leave_room":
            self.do_leave_room()
        else:
            self.send({"m": "err", "err": f"未知消息类型 {t}"})

    # ---------- 匹配 / 房间 ----------

    def do_match(self):
        if self.room is not None:
            self.send({"m": "err", "err": "你已在对局中"})
            return
        with LOBBY_LOCK:
            if self in MATCH_QUEUE:
                return
            # 找一个活着的、还没进房间的对手
            foe = None
            while MATCH_QUEUE:
                cand = MATCH_QUEUE.pop(0)
                if cand.alive and cand.room is None and cand is not self:
                    foe = cand
                    break
            if foe is None:
                MATCH_QUEUE.append(self)
                self.send({"m": "matching"})
                return
            room = Room(foe, self)
            ROOMS.append(room)
        log(f"匹配成功: {foe.name} vs {self.name} (房间 #{room.id})")
        foe.send({"m": "matched", "room": room.id, "role": "host", "opp": self.name})
        self.send({"m": "matched", "room": room.id, "role": "guest", "opp": foe.name})
        broadcast_lobby()

    def do_cancel_match(self):
        with LOBBY_LOCK:
            if self in MATCH_QUEUE:
                MATCH_QUEUE.remove(self)
        self.send({"m": "match_cancelled"})

    def do_create_room(self):
        if self.room is not None:
            self.send({"m": "err", "err": "你已在对局中"})
            return
        code = secrets.token_hex(3).upper()
        with LOBBY_LOCK:
            if self.code:
                ROOMS_BY_CODE.pop(self.code, None)
            self.code = code
            ROOMS_BY_CODE[code] = self      # 先存房主，对手进来后替换成 Room
        self.send({"m": "room_created", "code": code})

    def do_join_room(self, code):
        code = (code or "").strip().upper()
        if self.room is not None:
            self.send({"m": "err", "err": "你已在对局中"})
            return
        with LOBBY_LOCK:
            host = ROOMS_BY_CODE.get(code)
            if host is None:
                self.send({"m": "join_err", "err": "邀请码无效或房主已离开"})
                return
            if host is self:
                self.send({"m": "join_err", "err": "不能加入自己创建的房间"})
                return
            if not host.alive or host.room is not None:
                ROOMS_BY_CODE.pop(code, None)
                host.code = None
                self.send({"m": "join_err", "err": "房主已进入其他对局"})
                return
            if self in MATCH_QUEUE:
                MATCH_QUEUE.remove(self)
            room = Room(host, self)
            ROOMS.append(room)
            ROOMS_BY_CODE.pop(code, None)
            host.code = None
        log(f"房间 {code} 开局: {host.name} vs {self.name}")
        host.send({"m": "matched", "room": room.id, "role": "host", "opp": self.name})
        self.send({"m": "matched", "room": room.id, "role": "guest", "opp": host.name})
        broadcast_lobby()

    def do_relay(self, msg):
        """把行动指令转发给房间里的对手（服务器不理解游戏内容）"""
        room = self.room
        if room is None:
            self.send({"m": "err", "err": "当前不在对局中"})
            return
        foe = room.other(self)
        if foe is None or not foe.alive:
            self.send({"m": "peer_left"})
            return
        out = dict(msg)
        out["from_role"] = self.role
        if not foe.send(out):
            self.send({"m": "peer_left"})

    def do_leave_room(self):
        self.teardown_room(notify=True)

    # ---------- 清理 ----------

    def teardown_room(self, notify=False):
        room, self.room = self.room, None
        self.role = None
        if self.code:
            with LOBBY_LOCK:
                ROOMS_BY_CODE.pop(self.code, None)
            self.code = None
        if room is None:
            return
        with LOBBY_LOCK:
            if room in ROOMS:
                ROOMS.remove(room)
        foe = room.other(self)
        if foe is not None:
            foe.room = None
            foe.role = None
            if notify and foe.alive:
                foe.send({"m": "peer_left"})
        log(f"房间 #{room.id} 结束")

    def cleanup(self):
        self.alive = False
        self.teardown_room(notify=True)
        with LOBBY_LOCK:
            if self in MATCH_QUEUE:
                MATCH_QUEUE.remove(self)
            if self.name and CLIENTS.get(self.name) is self:
                CLIENTS.pop(self.name, None)
            if self.code:
                ROOMS_BY_CODE.pop(self.code, None)
        if self.name:
            log(f"断开: {self.name}")
        try:
            self.sock.close()
        except OSError:
            pass
        broadcast_lobby()


# ----------------------------------------------------------------- 校验

_NAME_RE = re.compile(r"^[\w\-]{2,16}$")


def norm_name(name):
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        return None, "用户名需 2-16 位（中文/字母/数字/下划线/连字符）"
    return name, ""


def norm_pw(pw):
    if not pw or len(pw) < 4:
        return "密码至少 4 位"
    if len(pw) > 64:
        return "密码过长（最多 64 位）"
    return ""


# ----------------------------------------------------------------- 启动

class Server(socketserver.ThreadingTCPServer):
    """联机服务器。

    ⚠ `allow_reuse_address` 在 Windows 上的语义与 Unix **完全不同**：
    它不是「等 TIME_WAIT 结束后能立刻重绑」，而是「两个 socket 可以同时
    绑到同一个端口」—— 于是第二个服务器进程会**静默抢走**第一个的端口，
    两边都以为自己监听着（实测：先开的进程还在 serve_forever，后开的
    照样 bind 成功）。玩家连的是谁全看运气。

    典型触发场景：大厅里点了两次「建立服务器」，或者游戏进程没退干净
    又启动了一个。这时应该**明确报错「端口已被占用」**，而不是默默起两个。

    Unix 上则相反：TIME_WAIT 期间不设 SO_REUSEADDR 会导致「刚重启就连不上」。
    所以按平台分开设。
    """
    allow_reuse_address = (os.name != "nt")
    daemon_threads = True


def main():
    global DB
    ap = argparse.ArgumentParser(description="KARDS 简化版 联机服务器")
    ap.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口（默认 6000）")
    ap.add_argument("--db", default=None, help="数据库文件（默认同目录 kards_server.db）")
    args = ap.parse_args()

    if getattr(sys, "frozen", False):
        # ⚠ 打包后 __file__ 指向 _internal/ 里的数据文件，同目录可能是只读的
        # 安装目录（Program Files）。数据库必须落到用户数据目录，
        # 否则第一次写入就 PermissionError。user_data_db() 内部已经
        # 优先认 KARDS_DATA_DIR（测试隔离用）。
        db_default = user_data_db()
    else:
        # 源码运行：KARDS_DATA_DIR 优先（测试/便携），否则放脚本同目录
        env_dir = os.environ.get("KARDS_DATA_DIR")
        if env_dir:
            try:
                os.makedirs(env_dir, exist_ok=True)
            except OSError:
                pass
            db_default = os.path.join(env_dir, "kards_server.db")
        else:
            db_default = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "kards_server.db")
    db_path = args.db or db_default
    DB = Store(db_path)

    log("=" * 56)
    log("KARDS 简化版 联机服务器")
    log(f"  数据库 : {db_path}")
    log(f"  监听   : {args.host}:{args.port}")
    if args.host == "0.0.0.0":
        for ip in local_ips():
            log(f"  局域网 : {ip}:{args.port}")
    log("  Ctrl+C 停止")
    log("=" * 56)

    srv = Server((args.host, args.port), ClientHandler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("正在关闭…")
    finally:
        srv.server_close()


def local_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return ips or ["127.0.0.1"]


if __name__ == "__main__":
    main()
