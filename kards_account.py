# -*- coding: utf-8 -*-
"""账号系统（服务器账号 + 本地回退）

两种后端，自动择优：

1. **服务器后端**（推荐，多人联机必须）
   账号存在 `kards_server.py` 的 SQLite 里，跨设备通用。
   登录成功拿到会话令牌（token），缓存到 `DATA_DIR/session.json`，
   下次启动直接 `resume` 免密重连，令牌有效期 30 天。

2. **本地后端**（回退）
   连不上服务器也能单机玩：账号存在 `DATA_DIR/accounts.json`
   （SHA-256 加盐哈希，不上传任何数据）。

对外 API 与旧版本完全兼容，GUI 侧无需改动即可跑通单机流程；
联机流程另外调用 `set_remote(remote)` 把账号操作代理到服务器。

数据目录：DATA_DIR
  - 安装版 = %USERPROFILE%\\AppData\\Kards-Simple-Version
  - 源码运行 = 项目目录

仅被 GUI 使用；CLI 调试模式不启用。
"""
import hashlib
import json
import os
import re
import secrets
import time

from kards_engine import DATA_DIR

_NAME_RE = re.compile(r"^[\w\-]{2,16}$")   # \w 含中文/字母/数字/下划线

_ACCOUNTS = os.path.join(DATA_DIR, "accounts.json")
_SESSION = os.path.join(DATA_DIR, "session.json")

# 当前后端状态
_BACKEND = "local"      # "local" / "server"
_REMOTE = None          # 服务器连接对象（见 set_remote），需要有 .request()/.send()/.alive
_TOKEN = None           # 服务器会话令牌
_SERVER = None          # 服务器地址（host:port），用于校验缓存令牌是否同一台服务器
_CACHED = None          # 内存中的本地账号库


# ---------------------------------------------------------------- 底层读写

def _load():
    global _CACHED
    if _CACHED is not None:
        return _CACHED
    try:
        with open(_ACCOUNTS, encoding="utf-8") as f:
            db = json.load(f)
        if not isinstance(db, dict) or "users" not in db:
            raise ValueError
    except (OSError, ValueError):
        db = {"current": None, "users": {}}
    _CACHED = db
    return db


def _save(db):
    global _CACHED
    _CACHED = db
    try:
        with open(_ACCOUNTS, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _hash(salt, pw):
    return hashlib.sha256((salt + pw).encode("utf-8")).hexdigest()


def _load_session():
    try:
        with open(_SESSION, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise ValueError
        return d
    except (OSError, ValueError):
        return {}


def _save_session(d):
    try:
        with open(_SESSION, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------- 服务器后端

def set_remote(remote, server=None):
    """挂载/解绑服务器连接。

    remote 需提供：
        alive            连接是否存活
        send(obj)        发送一条消息（dict，信封字段 "m"）
        request(obj)     发送并阻塞等待对应的应答（返回 dict 或 None）
    server 是 "host:port" 字符串，用于判断缓存令牌是否属于同一台服务器。
    """
    global _REMOTE, _SERVER, _BACKEND
    _REMOTE = remote
    if server is not None:
        _SERVER = server
    _BACKEND = "server" if remote is not None else "local"
    if remote is None:
        _drop_session()


def _drop_session():
    global _TOKEN
    _TOKEN = None
    _save_session({})


def _try_resume():
    """用缓存令牌尝试免密登录。成功返回用户名，失败返回 None。"""
    global _TOKEN
    if _REMOTE is None or not _REMOTE.alive:
        return None
    d = _load_session()
    tok = d.get("token")
    if not tok:
        return None
    if d.get("server") and _SERVER and d["server"] != _SERVER:
        return None                      # 换了服务器，旧令牌无效
    try:
        rep = _REMOTE.request({"m": "resume", "token": tok})
    except Exception:
        return None
    if isinstance(rep, dict) and rep.get("m") == "auth_ok":
        _TOKEN = tok
        return rep.get("user") or rep.get("name") or d.get("name")
    _drop_session()
    return None


def _rpc(msg, timeout=6.0):
    """向服务器发一条请求并等应答；未接服务器时返回 None。"""
    if _REMOTE is None or not _REMOTE.alive:
        return None
    try:
        return _REMOTE.request(msg, timeout=timeout)
    except Exception:
        return None


def _remote_register(name, pw):
    # ⚠ 服务器读的字段是 "user"，不是 "name"（见 kards_server.handshake）。
    # 应答里回显的也是 "user"。
    rep = _rpc({"m": "register", "user": name, "pw": pw})
    if rep is None:
        return None                      # 服务器不可用 → 交给调用方回退
    if rep.get("m") == "auth_ok":
        _accept_token(rep, name)
        return True, ""
    return False, _err_text(rep, "注册失败")


def _remote_login(name, pw):
    rep = _rpc({"m": "login", "user": name, "pw": pw})
    if rep is None:
        return None
    if rep.get("m") == "auth_ok":
        _accept_token(rep, name)
        return True, ""
    return False, _err_text(rep, "用户名或密码错误")


def _accept_token(rep, fallback_name=None):
    global _TOKEN
    _TOKEN = rep.get("token")
    if _TOKEN:
        _save_session({"server": _SERVER, "token": _TOKEN,
                       "name": rep.get("user") or rep.get("name") or fallback_name})


def _err_text(rep, default):
    return (rep or {}).get("err") or (rep or {}).get("msg") or default


# ---------------------------------------------------------------- 对外 API

def backend():
    """当前生效的后端："server" / "local" """
    return _BACKEND


def online():
    """是否已连上服务器（联机与云卡组需要）"""
    return _REMOTE is not None and getattr(_REMOTE, "alive", False)


def connect(name_hint=None):
    """连上服务器后调用：先尝试令牌免密登录。

    返回 (ok, 用户名或错误信息)。
    """
    got = _try_resume()
    if got:
        _mkdir_decks(got)
        return True, got
    return False, "need_login"


def current():
    """当前登录的账号名，未登录返回 None"""
    if _BACKEND == "server":
        d = _load_session()
        return d.get("name")
    return _load().get("current")


def validate_credentials(name, pw):
    """本地校验用户名/密码格式（不发网络请求），返回 (ok, 错误信息)"""
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        return False, "用户名需 2-16 位（中文/字母/数字/下划线/连字符）"
    if not pw or len(pw) < 4:
        return False, "密码至少 4 位"
    if len(pw) > 64:
        return False, "密码最长 64 位"
    return True, ""


def register(name, pw):
    """注册并自动登录。返回 (ok, 错误信息)"""
    ok, err = validate_credentials(name, pw)
    if not ok:
        return False, err
    name = name.strip()
    if _BACKEND == "server":
        rep = _remote_register(name, pw)
        if rep is not None:
            if rep[0]:
                _mkdir_decks(name)
            return rep
        # 服务器掉线 → 回退本地
    db = _load()
    if name in db["users"]:
        return False, "该用户名已被注册"
    salt = secrets.token_hex(8)
    db["users"][name] = {
        "salt": salt,
        "pw": _hash(salt, pw),
        "created": int(time.time()),
        "stats": {"win": 0, "lose": 0, "draw": 0},
    }
    db["current"] = name
    _save(db)
    _mkdir_decks(name)
    return True, ""


def login(name, pw):
    """登录。返回 (ok, 错误信息)"""
    name = (name or "").strip()
    if _BACKEND == "server":
        rep = _remote_login(name, pw)
        if rep is not None:
            if rep[0]:
                _mkdir_decks(name)
            return rep
    u = _load()["users"].get(name)
    if not u or u["pw"] != _hash(u["salt"], pw or ""):
        return False, "用户名或密码错误"
    db = _load()
    db["current"] = name
    _save(db)
    _mkdir_decks(name)
    return True, ""


def logout():
    if _BACKEND == "server" and _REMOTE is not None:
        # 只清本地令牌，不占用服务器连接（同一连接还要用于对局中转）
        _drop_session()
        return
    db = _load()
    db["current"] = None
    _save(db)


def _mkdir_decks(name):
    try:
        os.makedirs(deck_dir(name), exist_ok=True)
    except OSError:
        pass


def deck_dir(name):
    """该账号的自组卡组目录（按账号隔离）"""
    safe = re.sub(r'[\\/:*?"<>|]', "_", name or "guest")
    return os.path.join(DATA_DIR, "decks_" + safe)


# ---------------------------------------------------------------- 战绩

def get_stats(name):
    """返回 {"win":n,"lose":n,"draw":n}；在线时优先问服务器。"""
    if _BACKEND == "server" and name:
        rep = _rpc({"m": "stats"})
        if isinstance(rep, dict):
            st = rep.get("stats") or rep
            if isinstance(st, dict) and any(k in st for k in ("win", "lose", "draw")):
                return {"win": int(st.get("win", 0)),
                        "lose": int(st.get("lose", 0)),
                        "draw": int(st.get("draw", 0))}
    u = _load()["users"].get(name) or {}
    s = u.get("stats") or {}
    return {"win": s.get("win", 0), "lose": s.get("lose", 0), "draw": s.get("draw", 0)}


def stats_add(name, result):
    """记录一场对局结果: 'win' / 'lose' / 'draw'"""
    if result not in ("win", "lose", "draw"):
        return
    if _BACKEND == "server" and name:
        if _rpc({"m": "stats_add", "result": result}) is not None:
            return
    db = _load()
    u = db["users"].get(name)
    if not u:
        return
    st = u.setdefault("stats", {"win": 0, "lose": 0, "draw": 0})
    st[result] = st.get(result, 0) + 1
    _save(db)
