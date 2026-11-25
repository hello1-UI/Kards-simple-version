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
     首条消息必须是 {"m":"login"/"register"/"resume"/"adopt", ...}，
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

import kards_rank as rank

DEFAULT_PORT = 6000
SESSION_TTL = 30 * 24 * 3600      # 会话 token 有效期 30 天
HEARTBEAT_TIMEOUT = 60            # 超过该秒数没收到任何消息则判定掉线
PRINT_LOCK = threading.Lock()
MAX_LINE = 256 * 1024             # 单条消息上限（字节）——防御内存 DoS：
                                  # 恶意客户端发超大行不换行，缓冲会无限涨


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


# ---- 「本机来源」判定（免密接管用）------------------------------------------

def is_local_peer(ip):
    """连接来源是否就是服务器所在的这台机器。

    ⚠ 只比 IP：同一局域网的玩家连过来时源地址是**他们自己的**地址，
    不可能落在服务器的网卡列表里，所以不会被误判成本机。
    """
    if ip in ("127.0.0.1", "::1", "localhost"):
        return True
    try:
        return ip in local_ips()
    except Exception:                    # noqa: BLE001
        return False


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
                    draw    INTEGER NOT NULL DEFAULT 0,
                    rank    TEXT
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
            # ---- 老库迁移：rank 列是后加的段位/排行榜状态（JSON） ----
            # CREATE TABLE IF NOT EXISTS 不会给已存在的表补列，必须显式 ALTER。
            cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(users)")}
            if "rank" not in cols:
                self.conn.execute("ALTER TABLE users ADD COLUMN rank TEXT")
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
        if not rows:
            return None, "用户名或密码错误"
        stored = rows[0]["pw"]
        if stored.startswith("sha256:"):
            # 本机免密建号时保存的是客户端本地账号的 sha256(salt+pw)，
            # 这里按同一算法校验 —— 玩家以后用原密码照样能登录。
            import hashlib as _h
            ok = stored[7:] == _h.sha256(
                (rows[0]["salt"] + pw).encode("utf-8")).hexdigest()
        else:
            ok = stored == self.hash_pw(rows[0]["salt"], pw)
        if not ok:
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

    def delete_account(self, name):
        """彻底删除账号：用户行 + 所有会话 + 云卡组。

        返回删除的用户行数（0 = 账号本来就不存在）。
        会话必须一起删 —— 否则残留的 token 还能 resume 成一个
        「不存在但已登录」的幽灵账号。
        """
        with DB_LOCK:
            cur = self.conn.execute("DELETE FROM users WHERE name=?", (name,))
            deleted = cur.rowcount or 0
            self.conn.execute("DELETE FROM sessions WHERE name=?", (name,))
            self.conn.execute("DELETE FROM decks WHERE name=?", (name,))
            self.conn.commit()
        return deleted

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

    # ---- 段位 / 排行榜 ----

    @staticmethod
    def _rank_parse(raw):
        if not raw:
            return rank.new_state()
        try:
            d = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            d = None
        return rank.normalize(d)

    def rank_save(self, name, st):
        self.x("UPDATE users SET rank=? WHERE name=?",
               (json.dumps(st, ensure_ascii=False), name))

    def rank_get(self, name, roll=True):
        """读段位状态；跨赛季则就地结算（懒结算，玩家不登录也会在
        第一次读取时补上，避免"缺席一年回来还是 1 段"）。"""
        rows = self.q("SELECT rank FROM users WHERE name=?", (name,))
        if not rows:
            return rank.new_state()
        st = self._rank_parse(rows[0]["rank"])
        if roll:
            st2, rolled = rank.roll_season(st)
            if rolled:
                self.rank_save(name, st2)
            st = st2
        return st

    def rank_add(self, name, result):
        st = self.rank_get(name)
        st, change = rank.apply_result(st, result)
        self.rank_save(name, st)
        return st, change

    def rank_add_ai(self, name, result):
        """人机对局结算：每 2 胜 1 星，负场不动。

        单独一条，别和排位的 rank_add 混用 —— 两者的加成、连败、
        榜单计分完全不同，混在一起最容易「刷 AI 上榜」。
        """
        st = self.rank_get(name)
        st, change = rank.apply_ai_result(st, result)
        self.rank_save(name, st)
        return st, change

    def rank_seed(self, name, st):
        """账号迁移时把本机段位搬上云。

        只在服务器账号还是「全新」（25 段 0 星、从未上榜）时生效，
        否则任何人都能反复 seed 刷段位。赛季按服务端时间推进，
        客户端传来的旧赛季不会触发多次扣星。
        """
        cur = self.rank_get(name, roll=False)
        pristine = (cur["tier"] == rank.START_TIER and cur["stars"] == 0
                    and not cur["lb_active"] and cur["lb_pts"] == 0)
        if not pristine:
            return cur
        st = rank.normalize(st)
        st, _ = rank.roll_season(st)
        self.rank_save(name, st)
        return st

    def rank_board(self, limit=50):
        """全服排行榜（按当前赛季）。返回 (前 limit 名, 完整榜)。

        顺带把每个人的赛季结算补上 —— 结算需要写库，所以这里会按需
        rank_save；用户量级很小（单服几十到几百人），可接受。
        """
        rows = self.q("SELECT name, rank FROM users")
        entries = []
        for r in rows:
            st = self._rank_parse(r["rank"])
            st, rolled = rank.roll_season(st)
            if rolled:
                self.rank_save(r["name"], st)
            entries.append((r["name"], st))
        full = rank.board_rows(entries, 0)
        return (full[:int(limit)] if limit else full), full

    def adopt(self, name, salt="", pw_hash=""):
        """本机免密接管 / 免密建号（只允许 peer_is_local 的调用方使用）。

        为什么要有：账号是**按服务器**存的。玩家在自己机器上开服时，
        本机服务器是独立数据库 —— 已登录的玩家一「切」过去就要重新
        输密码，体验上就是「开服就退登」。

        两种情况都处理：
          · 服务器上已有该账号 → 直接发会话（玩家之前在本机服登录过）
          · 服务器上没有、但客户端带了自己本地账号的 salt + sha256 哈希
            → 用这个哈希建号（不传明文密码），玩家以后用原密码也能登录

        ⚠ 只接受本机来源：局域网其他玩家传来哈希就能接管账号是不行的。
        """
        if not self.q("SELECT 1 FROM users WHERE name=?", (name,)):
            if not (salt and pw_hash):
                return None, "本机服务器上还没有这个账号，请先登录或注册一次"
            now = int(time.time())
            self.x("INSERT INTO users(name,salt,pw,created,last_seen)"
                   " VALUES(?,?,?,?,?)",
                   (name, salt, "sha256:" + pw_hash, now, now))
            log(f"本机免密建号: {name}")
        self.x("UPDATE users SET last_seen=? WHERE name=?",
               (int(time.time()), name))
        return self.new_session(name), ""

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


def _rank_brief(name):
    """大厅列表用的精简段位信息（失败不该拖垮大厅）。"""
    try:
        st = DB.rank_get(name)
        return {"tier": st["tier"], "stars": st["stars"],
                "lb": st["lb_pts"] if st["lb_active"] else None}
    except Exception:                # noqa: BLE001
        return None


def lobby_snapshot():
    """在线玩家快照。

    ⚠ 必须在 LOBBY_LOCK 内**拷贝**出客户端列表再遍历：登录/断线是在别的
    线程改 CLIENTS 的，直接迭代 .values() 会撞上 RuntimeError: dictionary
    changed size during iteration —— 实测两人同时登录时，先登的那条连接
    会被这个异常直接掐断（服务器日志：连接异常 RuntimeError(...)）。
    账号统计查询放到锁外做，避免 sqlite 读写长时间占着大厅锁。
    """
    with LOBBY_LOCK:
        clients = list(CLIENTS.values())
    snap = []
    for c in clients:
        if not getattr(c, "alive", False) or not c.name:
            continue
        try:
            snap.append({"name": c.name, "stats": DB.stats(c.name),
                         "rank": _rank_brief(c.name),
                         "in_game": c.room is not None})
        except Exception:            # noqa: BLE001  单个玩家查询失败不该拖垮大厅
            continue
    return snap


def broadcast_lobby():
    """给所有在大厅（未进入对局）的玩家推送在线列表"""
    snap = lobby_snapshot()
    with LOBBY_LOCK:
        targets = [c for c in CLIENTS.values() if c.room is None]
    for c in targets:
        try:
            c.send({"m": "lobby", "players": snap})
        except Exception:            # noqa: BLE001  单条推送失败不影响其他玩家
            continue


HALL_CHAT_TTL = 8.0              # 聊天气泡展示秒数，过期随快照自然消失
HALL_CHAT_MAX = 120              # 单条聊天长度上限（防御性截断）


def hall_snapshot():
    """走动大厅在线快照：所有 in_hall 玩家的名字 / 坐标 / 气泡。

    与 lobby_snapshot 相同的坑：必须在 LOBBY_LOCK 内拷贝列表再遍历。
    """
    now_t = time.time()
    with LOBBY_LOCK:
        clients = [c for c in list(CLIENTS.values())
                   if getattr(c, "in_hall", False) and c.alive and c.name]
    snap = []
    for c in clients:
        chat = c.hchat if (c.hchat and now_t - c.hchat_t <= HALL_CHAT_TTL) else None
        snap.append({"name": c.name, "x": round(c.hx, 1), "y": round(c.hy, 1),
                     "chat": chat})
    return snap


def broadcast_hall():
    """把走动大厅快照推给所有在场的玩家（位置/气泡变化时调用）"""
    snap = hall_snapshot()
    with LOBBY_LOCK:
        targets = [c for c in list(CLIENTS.values())
                   if getattr(c, "in_hall", False) and c.alive]
    for c in targets:
        try:
            c.send({"m": "hall_state", "players": snap})
        except Exception:            # noqa: BLE001
            continue


def hall_leave(c):
    """把一个连接从走动大厅摘除（进场失败 / 进对局 / 断线时调用）。

    只在确实在场时才广播，避免无关的状态抖动；返回是否真的离开了。
    """
    if not getattr(c, "in_hall", False):
        return False
    c.in_hall = False
    c.hchat = None
    broadcast_hall()
    return True


# ----------------------------------------------------------------- 连接处理

class ClientHandler(socketserver.BaseRequestHandler):
    """一条客户端连接。所有业务消息都在这里的 handle() 循环里处理。"""

    # ---------- 底层收发 ----------

    def setup(self):
        self.sock = self.request
        self.sock.settimeout(HEARTBEAT_TIMEOUT)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # 跨公网的长连接：开 keepalive 抵消运营商 NAT 的空闲回收
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass
        self.wlock = threading.Lock()
        self.alive = True
        self.name = None       # 登录后的用户名
        self.token = None
        self.room = None
        self.role = None
        self.code = None       # 自己创建的房间邀请码（等待对手加入）
        self.match_casual = False  # 匹配/房间是否为休闲模式（None/False = 排位）
        # ---- 走动大厅（hall）状态：位置 + 最近一句话 ----
        # 与旧「大厅列表」(lobby_snapshot) 不同：hall 是可走动房间场景，
        # 玩家以坐标出现，别人能看到自己站在哪、头顶聊了什么。
        self.in_hall = False
        self.hx = 0.0
        self.hy = 0.0
        self.hchat = None       # 最近一条聊天文本（带时间戳，过期不再下发）
        self.hchat_t = 0.0
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
            if len(self._buf) > MAX_LINE:
                # 超大行 = 协议攻击，断开（外层 finally 会 cleanup）
                raise OSError(f"消息超长({len(self._buf)}B)")
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
                # 拖慢在线爆破：PBKDF2 6 万轮已经不便宜，再垫 0.3s，
                # 自动化脚本逐个试密码的成本显著上升（正常玩家无感）
                time.sleep(0.3)
                self.send({"m": "auth_err", "err": err})
                return "retry"
        elif t == "adopt":
            # 本机免密恢复：自己开的服，账号本来就在这台机器上，
            # 不该因为"换了个服务器实例"就要求重新输密码。
            if not is_local_peer(self.client_address[0]):
                self.send({"m": "auth_err",
                           "err": "免密恢复仅限本机：请在服务器那台机器上操作"})
                return "retry"
            name, err = norm_name(msg.get("user"))
            if err:
                self.send({"m": "auth_err", "err": err})
                return "retry"
            with DB_LOCK:
                tok, err = DB.adopt(name, msg.get("salt") or "",
                                    msg.get("pw") or "")
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
                   "stats": DB.stats(name), "rank": DB.rank_get(name)})

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
            self.do_match(msg.get("casual"))
        elif t == "cancel_match":
            self.do_cancel_match()
        elif t == "create_room":
            self.do_create_room(msg.get("casual"))
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
        elif t == "rank":
            self.send({"m": "rank", "rank": DB.rank_get(self.name)})
        elif t == "rank_add":
            st, ch = DB.rank_add(self.name, msg.get("result"))
            self.send({"m": "rank", "rank": st, "change": ch})
        elif t == "rank_add_ai":
            st, ch = DB.rank_add_ai(self.name, msg.get("result"))
            self.send({"m": "rank", "rank": st, "change": ch})
        elif t == "rank_seed":
            st = DB.rank_seed(self.name, msg.get("rank"))
            self.send({"m": "rank", "rank": st})
        elif t == "rank_board":
            # limit 是客户端传的，坏值不能把整条连接打挂（int("x") 会抛异常）
            try:
                lim = int(msg.get("limit") or 50)
            except (TypeError, ValueError):
                lim = 50
            top, full = DB.rank_board(max(1, min(lim, 200)))
            me = None
            for r in full:
                if r["name"] == self.name:
                    me = r
                    break
            self.send({"m": "rank_board", "rows": top, "total": len(full),
                       "me": me, "season": rank.season_id()})
        elif t == "deck_save":
            # 尺寸校验：卡组内容其实只有几十 KB，超限直接拒绝，
            # 防止恶意账号往 SQLite 里灌垃圾把磁盘撑爆
            nation = str(msg.get("nation", ""))[:24]
            title = str(msg.get("title", ""))[:60]
            content = msg.get("content", "")
            if not isinstance(content, str) or len(content.encode("utf-8")) > 128 * 1024:
                self.send({"m": "err", "err": "卡组内容过大（上限 128KB）"})
            else:
                DB.deck_save(self.name, nation, title, content)
                self.send({"m": "deck_saved", "title": msg.get("title")})
        elif t == "deck_list":
            self.send({"m": "deck_list", "decks": DB.deck_list(self.name)})
        elif t == "deck_get":
            c = DB.deck_get(self.name, msg.get("nation", ""), msg.get("title", ""))
            self.send({"m": "deck_data", "title": msg.get("title"), "content": c})
        elif t == "deck_del":
            DB.deck_del(self.name, msg.get("nation", ""), msg.get("title", ""))
            self.send({"m": "deck_list", "decks": DB.deck_list(self.name)})
        elif t == "delete_account":
            self.do_delete_account()
        elif t == "leave_room":
            self.do_leave_room()
        elif t == "hall_join":
            self.do_hall_join(msg)
        elif t == "hall_move":
            self.do_hall_move(msg)
        elif t == "hall_leave":
            hall_leave(self)
        elif t == "hall_chat":
            self.do_hall_chat(msg)
        elif t == "hall_invite":
            self.do_hall_invite(msg.get("to"))
        elif t == "hall_accept":
            self.do_hall_accept(msg.get("to"))
        elif t == "hall_decline":
            self.do_hall_decline(msg.get("to"))
        else:
            self.send({"m": "err", "err": f"未知消息类型 {t}"})

    # ---------- 匹配 / 房间 ----------

    def do_match(self, casual=False):
        """快速匹配。casual=True 走休闲池，与排位池**互不配对**。

        池子隔离而不是"同一局里带个标记"：排位玩家匹配到休闲玩家，双方对
        「这局算不算星」的预期必然冲突（排位方认为该加，休闲方认为不该加），
        服务器又没有权威胜负判定，事后无从纠正。分开队列最省事也最安全。
        """
        if self.room is not None:
            self.send({"m": "err", "err": "你已在对局中"})
            return
        casual = bool(casual)
        with LOBBY_LOCK:
            if self in MATCH_QUEUE:
                return
            self.match_casual = casual
            # 找一个活着、还没进房间、**模式一致**的对手。
            # 注意不能像以前那样 pop 掉不合适的候选就丢：那些是别人的排队，
            # 误删会让对方永远等不到匹配（静默卡死）。逐个挑，剩下的原序放回。
            foe = None
            keep = []
            for cand in MATCH_QUEUE:
                if (foe is None and cand is not self and cand.alive
                        and cand.room is None
                        and bool(getattr(cand, "match_casual", False)) == casual):
                    foe = cand
                else:
                    keep.append(cand)
            MATCH_QUEUE[:] = keep
            if foe is None:
                MATCH_QUEUE.append(self)
                self.send({"m": "matching", "casual": casual})
                return
            room = Room(foe, self)
            ROOMS.append(room)
            hall_leave(foe)
            hall_leave(self)
        log(f"匹配成功: {foe.name} vs {self.name} (房间 #{room.id}"
            f"{'，休闲' if casual else ''})")
        foe.send({"m": "matched", "room": room.id, "role": "host",
                  "opp": self.name, "casual": casual})
        self.send({"m": "matched", "room": room.id, "role": "guest",
                   "opp": foe.name, "casual": casual})
        broadcast_lobby()

    def do_cancel_match(self):
        with LOBBY_LOCK:
            if self in MATCH_QUEUE:
                MATCH_QUEUE.remove(self)
        self.send({"m": "match_cancelled"})

    def do_create_room(self, casual=False):
        if self.room is not None:
            self.send({"m": "err", "err": "你已在对局中"})
            return
        code = secrets.token_hex(3).upper()
        casual = bool(casual)
        with LOBBY_LOCK:
            if self.code:
                ROOMS_BY_CODE.pop(self.code, None)
            self.code = code
            self.match_casual = casual
            ROOMS_BY_CODE[code] = self      # 先存房主，对手进来后替换成 Room
        self.send({"m": "room_created", "code": code, "casual": casual})

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
            casual = bool(getattr(host, "match_casual", False))
            hall_leave(host)
            hall_leave(self)
        log(f"房间 {code} 开局: {host.name} vs {self.name}"
            f"{'（休闲）' if casual else ''}")
        host.send({"m": "matched", "room": room.id, "role": "host",
                   "opp": self.name, "casual": casual})
        self.send({"m": "matched", "room": room.id, "role": "guest",
                   "opp": host.name, "casual": casual})
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

    # ---------- 走动大厅 ----------

    def do_hall_join(self, msg):
        """进入走动大厅：登记坐标并回一张全量快照，随后广播给在场者。"""
        if self.room is not None:
            self.send({"m": "err", "err": "你已在对局中"})
            return
        try:
            x = float(msg.get("x", 0))
            y = float(msg.get("y", 0))
        except (TypeError, ValueError):
            x, y = 0.0, 0.0
        self.hx, self.hy = x, y
        self.in_hall = True
        self.hchat = None
        # 只广播一次（含本人）：进场者也从这条广播拿到全量快照。
        # 不能再单独 self.send 一份 —— 否则本人手里会有两份 hall_state
        # （自己的旧快照 + 全量），客户端按序消费会永远慢一拍（实测）。
        broadcast_hall()

    def do_hall_move(self, msg):
        """位置更新。客户端已按 ~100ms 节流，服务器端再加 50ms 硬节流：
        恶意客户端全速发 hall_move 会触发全员广播风暴。"""
        if not self.in_hall:
            return
        now = time.time()
        if now - getattr(self, "_hall_move_t", 0.0) < 0.05:
            return
        self._hall_move_t = now
        try:
            self.hx = float(msg.get("x", self.hx))
            self.hy = float(msg.get("y", self.hy))
        except (TypeError, ValueError):
            return
        broadcast_hall()

    def do_hall_chat(self, msg):
        """大厅聊天：记在头上（气泡）并广播。1 秒一条的硬节流防刷屏。"""
        if not self.in_hall:
            return
        now = time.time()
        if now - getattr(self, "_hall_chat_t", 0.0) < 1.0:
            return
        text = str(msg.get("text") or "").strip()[:HALL_CHAT_MAX]
        if not text:
            return
        self._hall_chat_t = now
        self.hchat = text
        self.hchat_t = now
        broadcast_hall()

    def do_hall_invite(self, to):
        """向在场玩家发出对战邀请（服务器只中转，不创建房间）。"""
        if self.room is not None or not self.in_hall:
            self.send({"m": "err", "err": "你已不在大厅"})
            return
        with LOBBY_LOCK:
            tgt = CLIENTS.get(to)
            ok = (tgt is not None and tgt.alive and tgt.in_hall
                  and tgt.room is None and tgt is not self)
        if not ok:
            self.send({"m": "hall_gone", "to": to})
            return
        tgt.send({"m": "hall_invite", "from": self.name})

    def do_hall_accept(self, to):
        """接受邀请 → 直接开一局（复用邀请码房间的建房路径）。

        走动大厅的邀请局按休闲处理：不打段位，战绩/金币照常记 ——
        玩家在大厅里喊人打一场，不该被突然掉星。
        """
        if self.room is not None:
            self.send({"m": "err", "err": "你已在对局中"})
            return
        with LOBBY_LOCK:
            inviter = CLIENTS.get(to)
            if (inviter is None or not inviter.alive or inviter.room is not None
                    or not inviter.in_hall or inviter is self):
                self.send({"m": "hall_gone", "to": to})
                return
            if self in MATCH_QUEUE:
                MATCH_QUEUE.remove(self)
            inviter.match_casual = True
            self.match_casual = True
            room = Room(inviter, self)
            ROOMS.append(room)
            hall_leave(inviter)
            hall_leave(self)
        log(f"大厅邀请开局: {inviter.name} vs {self.name} (房间 #{room.id}，休闲)")
        inviter.send({"m": "matched", "room": room.id, "role": "host",
                      "opp": self.name, "casual": True})
        self.send({"m": "matched", "room": room.id, "role": "guest",
                   "opp": inviter.name, "casual": True})

    def do_hall_decline(self, to):
        """婉拒邀请：只通知邀请方，不动大厅状态。"""
        with LOBBY_LOCK:
            inviter = CLIENTS.get(to)
        if inviter is not None and inviter.alive:
            inviter.send({"m": "hall_decline", "from": self.name})

    def do_delete_account(self):
        """删除当前账号（连接已认证，不必再输密码）。

        顺序很重要：
          1. 先退房间 / 退出匹配队列 —— 否则对手会对着一个已删除的
             账号继续等待，"幽灵对局"永远不会结束；
          2. 删库（users + sessions + decks）；
          3. 从在线名单摘掉，再把本条连接的 name/token 置空。
        会话一起删：残留 token 还能 resume，会变成"不存在但已登录"。
        """
        name = self.name
        if not name:
            self.send({"m": "account_deleted", "ok": False, "err": "未登录"})
            return
        self.teardown_room(notify=True)
        with LOBBY_LOCK:
            if self in MATCH_QUEUE:
                MATCH_QUEUE.remove(self)

        n = DB.delete_account(name)
        if not n:
            self.send({"m": "account_deleted", "ok": False, "err": "账号不存在"})
            return

        with LOBBY_LOCK:
            if CLIENTS.get(name) is self:
                CLIENTS.pop(name, None)
        self.name = None
        self.token = None
        self.send({"m": "account_deleted", "ok": True})
        log(f"删除账号: {name}")
        broadcast_lobby()

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
        hall_leave(self)          # 从走动大厅摘除并广播（不在场时是空操作）
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
    """本机全部网卡 IPv4（多网卡时每条都算「本机来源」）。

    只取默认路由那一个是不够的：玩家可能从另一张网卡（有线/虚拟网卡）
    连本机服务器，此时源地址不在单 IP 列表里，免密接管会被误拒。
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
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass
    return ips or ["127.0.0.1"]


if __name__ == "__main__":
    main()
