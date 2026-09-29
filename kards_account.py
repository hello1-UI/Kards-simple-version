# -*- coding: utf-8 -*-
"""本地账号系统

- 注册 / 登录（SHA-256 加盐哈希，不上传任何数据）
- 记住当前账号（accounts.json 的 current 字段）
- 按账号隔离：自组卡组目录 decks_<账号>/、战绩统计（胜/负/平）
- 数据统一存放在 DATA_DIR（安装版 = %USERPROFILE%\\AppData\\Kards-Simple-Version）

仅被 GUI 使用；CLI 调试模式不启用。
"""
import hashlib
import json
import os
import re
import secrets
import time

from kards_engine import DATA_DIR

_PATH = os.path.join(DATA_DIR, "accounts.json")
_NAME_RE = re.compile(r"^[\w\-]{2,16}$")   # \w 含中文/字母/数字/下划线


def _load():
    try:
        with open(_PATH, encoding="utf-8") as f:
            db = json.load(f)
        if not isinstance(db, dict) or "users" not in db:
            raise ValueError
        return db
    except (OSError, ValueError):
        return {"current": None, "users": {}}


def _save(db):
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def _hash(salt, pw):
    return hashlib.sha256((salt + pw).encode("utf-8")).hexdigest()


def current():
    """当前登录的账号名，未登录返回 None"""
    return _load().get("current")


def register(name, pw):
    """注册并自动登录。返回 (ok, 错误信息)"""
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        return False, "用户名需 2-16 位（中文/字母/数字/下划线/连字符）"
    if not pw or len(pw) < 4:
        return False, "密码至少 4 位"
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
    os.makedirs(deck_dir(name), exist_ok=True)
    return True, ""


def login(name, pw):
    """登录。返回 (ok, 错误信息)"""
    name = (name or "").strip()
    u = _load()["users"].get(name)
    if not u or u["pw"] != _hash(u["salt"], pw or ""):
        return False, "用户名或密码错误"
    db = _load()
    db["current"] = name
    _save(db)
    os.makedirs(deck_dir(name), exist_ok=True)
    return True, ""


def logout():
    db = _load()
    db["current"] = None
    _save(db)


def deck_dir(name):
    """该账号的自组卡组目录（按账号隔离）"""
    safe = re.sub(r'[\\/:*?"<>|]', "_", name)
    return os.path.join(DATA_DIR, "decks_" + safe)


def get_stats(name):
    u = _load()["users"].get(name) or {}
    s = u.get("stats") or {}
    return {"win": s.get("win", 0), "lose": s.get("lose", 0), "draw": s.get("draw", 0)}


def stats_add(name, result):
    """记录一场对局结果: 'win' / 'lose' / 'draw'"""
    db = _load()
    u = db["users"].get(name)
    if not u:
        return
    st = u.setdefault("stats", {"win": 0, "lose": 0, "draw": 0})
    st[result] = st.get(result, 0) + 1
    _save(db)
