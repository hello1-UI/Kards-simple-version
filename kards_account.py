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
import shutil
import sys
import time

from kards_engine import DATA_DIR
import kards_rank as rank

_NAME_RE = re.compile(r"^[\w\-]{2,16}$")   # \w 含中文/字母/数字/下划线

_ACCOUNTS = os.path.join(DATA_DIR, "accounts.json")
_SESSION = os.path.join(DATA_DIR, "session.json")

# 当前后端状态
_BACKEND = "local"      # "local" / "server"
_REMOTE = None          # 服务器连接对象（见 set_remote），需要有 .request()/.send()/.alive
_TOKEN = None           # 服务器会话令牌
_SERVER = None          # 服务器地址（host:port），用于校验缓存令牌是否同一台服务器
_CACHED = None          # 内存中的本地账号库

# ---- 游客（未登录）身份 -------------------------------------------------------
# 产品规则（用户 2026-10-02 指定）：
#   · 未登录 = 游客；游客**可以玩人机**，但**不能联机**、不能用云卡组、不记战绩。
#   · 游客是**临时会话，退出即弃**：不写 accounts.json、不落 session.json、
#     不建 decks_ 目录，避免在用户数据目录里留垃圾。
# 因此这里只用一个模块级内存变量表示"当前是游客"，进程结束即消失。
GUEST = "__guest__"     # 游客的哨兵账号名（不会与真实用户名冲突）
_is_guest = False       # 是否处于游客状态


def is_guest():
    """当前是否游客身份（未登录）。

    ⚠ 语义：**只有明确设为游客、且当前没有正式账号时**才算游客。
    判定顺序很重要 —— 先看有没有正式账号（服务器会话 / 本地 current），
    都没有才看 `_is_guest`。这样即使用户先设了游客、随后又登录成功，
    也不会被误判成游客。
    """
    return _is_guest and current() is None


def start_guest():
    """进入游客模式（不写任何文件）"""
    global _is_guest, _TOKEN
    _is_guest = True
    _TOKEN = None
    return GUEST


def as_guest():
    """当前玩家显示名：已登录 → 账号名；游客 → 游客哨兵；都不是 → None。

    返回值是**哨兵 GUEST**（而不是本地化文字），由调用方翻译成界面文案，
    这样本模块不必依赖 kards_i18n。
    """
    name = current()
    if name:
        return name
    return GUEST if _is_guest else None


def can_play_online():
    """是否具备联机资格（游客不能联机）"""
    return not is_guest() and online()


def _leave_guest():
    """登录/注册成功 → 离开游客状态"""
    global _is_guest
    _is_guest = False


def guest_decks_dir():
    """游客的卡组目录 —— 放系统临时目录，**退出即弃**（产品规则）。

    不放在 DATA_DIR 下，是为了不在用户数据目录里留任何游客痕迹；
    游客仍可自由组卡、打人机，只是关掉游戏就没了。
    """
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "KardsGuestDecks")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return None
    return d


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


# ---- 本地凭据落盘加密（Windows DPAPI，纯标准库 ctypes）----
# accounts.json / session.json 里存的是账号口令哈希与会话 token —— 明文
# 落盘一旦文件被拷走（恶意软件 / 网盘同步 / 别人借用电脑），弱密码可被
# 离线秒破、token 可直接顶号。DPAPI 把密文绑定到「当前 Windows 用户」，
# 换个用户或换个机器都解不开，拷走文件也只是一串废字节。
# 兼容：旧明文文件照常能读，下次保存时自动转为加密。
_DPAPI_MAGIC = b"DPAPI1:"
_ON_WINDOWS = sys.platform == "win32"


def _dpapi_crypt(data, protect):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    src = ctypes.create_string_buffer(data, len(data))
    bin_ = BLOB(len(data), ctypes.cast(src, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    fn = (ctypes.windll.crypt32.CryptProtectData if protect
          else ctypes.windll.crypt32.CryptUnprotectData)
    if not fn(ctypes.byref(bin_), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI 失败")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _read_creds(path):
    """读凭据文件 → dict。旧明文 / 新加密都能读；损坏返回空。"""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return {}
    if raw.startswith(_DPAPI_MAGIC):
        try:
            raw = _dpapi_crypt(raw[len(_DPAPI_MAGIC):], protect=False)
        except OSError:
            return {}                     # 换用户/换机器解不开 → 视作无凭据
    try:
        d = json.loads(raw.decode("utf-8"))
        return d if isinstance(d, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def _write_creds(path, d):
    """写凭据文件。Windows 下加密落盘；加密失败退回明文（宁明文不丢数据）。"""
    raw = json.dumps(d, ensure_ascii=False, indent=2).encode("utf-8")
    if _ON_WINDOWS:
        try:
            raw = _DPAPI_MAGIC + _dpapi_crypt(raw, protect=True)
        except OSError:
            pass                          # 退回明文
    try:
        with open(path, "wb") as f:
            f.write(raw)
    except OSError:
        pass


def _load_session():
    return _read_creds(_SESSION)


def _save_session(d):
    _write_creds(_SESSION, d)


# ---------------------------------------------------------------- 服务器后端

def set_remote(remote, server=None):
    """挂载/解绑服务器连接。

    remote 需提供：
        alive            连接是否存活
        send(obj)        发送一条消息（dict，信封字段 "m"）
        request(obj)     发送并阻塞等待对应的应答（支持 key= 命令映射）
    server 是 "host:port" 字符串，用于判断缓存令牌是否属于同一台服务器。

    ⚠ 解绑（remote=None）时**只清内存里的连接，不删会话缓存**。
    会话缓存的语义是「这台机器上次登录过哪台服务器的哪个账号」，
    重连（断线重连、回主菜单、重开大厅）后要靠它免密 resume；
    若在解绑时清掉，用户每次重连都得重新输密码 —— 实测踩过。
    真正要让会话失效时请显式调用 `_drop_session()`（logout 已如此处理）。
    """
    global _REMOTE, _SERVER, _BACKEND
    _REMOTE = remote
    if server is not None:
        _SERVER = server
    _BACKEND = "server" if remote is not None else "local"


def _drop_session():
    global _TOKEN
    _TOKEN = None
    _save_session({})


def _same_server(a, b):
    """两台服务器是否是同一台（容错 127.0.0.1 / localhost / 本机局域网 IP）。

    这里**只能**用 kards_net 的判定：本机开服时地址写法会从 127.0.0.1:6000
    变成 192.168.x.x:6000，字符串不等但就是同一台。旧代码直接比字符串，
    导致点「建立服务器」后免密令牌被判无效、玩家被打回登录框（用户报）。
    """
    try:
        import kards_net
        return kards_net.same_server(a, b)
    except Exception:                        # noqa: BLE001
        return a == b


def _try_resume():
    """用缓存令牌尝试免密登录。成功返回用户名，失败返回 None。"""
    global _TOKEN
    if _REMOTE is None or not _REMOTE.alive:
        return None
    d = _load_session()
    tok = d.get("token")
    if not tok:
        return None
    if d.get("server") and _SERVER and not _same_server(d["server"], _SERVER):
        return None                      # 换了服务器，旧令牌无效
    try:
        rep = _rpc({"m": "resume", "token": tok}, key="resume")
    except Exception:
        return None
    if isinstance(rep, dict):
        # 服务器**明确拒绝**才清会话缓存；网络原因（rep is None，超时/断线）
        # 不动缓存 —— 否则一次抖动就把 30 天令牌抹了，下次还得重输密码。
        _drop_session()
        if rep.get("m") == "auth_ok":
            _TOKEN = tok
            return rep.get("user") or rep.get("name") or d.get("name")
    return None


def has_session_token(server=None):
    """本地是否还留着免密令牌（只读缓存，不验证）。

    用途：GUI 要区分「服务器明确拒绝登录」和「这次只是网络超时」。
    前者 `_try_resume` 已经把 session 清掉；后者令牌还在 —— 这种情况
    把玩家弹回登录框就是「退登」，应当重试而不是要求重新输密码。
    """
    d = _load_session()
    if not d.get("token"):
        return False
    srv = server if server is not None else _SERVER
    if d.get("server") and srv and not _same_server(d["server"], srv):
        return False
    return True


def session_name():
    """会话缓存里记住的账号名（令牌可能已失效，名字仍有参考价值）。"""
    return _load_session().get("name")


def _rpc(msg, timeout=6.0, key=None):
    """向服务器发一条请求并等应答；未接服务器时返回 None。

    ⚠ 关键：**必须传 key**（命令名）。
    ServerLink.request() 有两种配对方式：
      · key is None → 自己加一个 "id" 让服务器回显
      · key 给定   → 按 _REPLY_MAP 的「命令 → 应答类型」映射等待
    而 kards_server 的**所有**应答都不回显 id（handshake 回 auth_ok/auth_err，
    dispatch 回 stats/deck_saved/lobby…），所以不传 key 就一定等超时、
    恒返回 None —— 后果是账号注册/登录在服务器模式下**静默失效**（已修）。
    """
    if _REMOTE is None or not _REMOTE.alive:
        return None
    key = key or msg.get("m")
    try:
        return _REMOTE.request(msg, timeout=timeout, key=key)
    except Exception:
        return None


def _remote_register(name, pw):
    # ⚠ 服务器读的字段是 "user"，不是 "name"（见 kards_server.handshake）。
    # 应答里回显的也是 "user"。
    rep = _rpc({"m": "register", "user": name, "pw": pw}, key="register")
    if rep is None:
        return None                      # 服务器不可用 → 交给调用方回退
    if rep.get("m") == "auth_ok":
        _accept_token(rep, name)
        return True, ""
    return False, _err_text(rep, "注册失败")


def _remote_login(name, pw):
    rep = _rpc({"m": "login", "user": name, "pw": pw}, key="login")
    if rep is None:
        return None
    if rep.get("m") == "auth_ok":
        _accept_token(rep, name)
        return True, ""
    return False, _err_text(rep, "用户名或密码错误")


def adopt_local(name):
    """在本机服务器上免密接管已存在的账号。

    场景：玩家在自己机器上开服（本机服务器是独立数据库）。旧行为是
    换过去就得重新输密码 —— 用户称之为「开服就退登」。既然服务器就在
    这台机器上，本机来源直接继承账号即可（服务器端 `is_local_peer` 把关，
    局域网里的其他玩家不会被放行）。

    返回 True 表示已登录；False 表示账号不在该服务器上 / 连接不可用，
    此时调用方应正常弹登录框（首次开服仍然要注册一次，这是正确的）。
    """
    if _REMOTE is None or not _REMOTE.alive:
        return False
    name = (name or "").strip()
    if not name:
        return False
    msg = {"m": "adopt", "user": name}
    # 本机服务器上还没有这个账号时，带上本地账号的 salt + 哈希，
    # 让服务器"免密建号"（不传明文密码）。这样换了服务器实例也不用
    # 重新注册；玩家以后用原密码照样能 login（服务器按 sha256 校验）。
    u = _load()["users"].get(name) or {}
    if u.get("salt") and u.get("pw"):
        msg["salt"] = u["salt"]
        msg["pw"] = u["pw"]
    rep = _rpc(msg, key="adopt")
    if isinstance(rep, dict) and rep.get("m") == "auth_ok":
        _accept_token(rep, name)
        _mkdir_decks(name)
        _leave_guest()
        return True
    return False


def local_verify(name, pw):
    """校验「用户名 + 明文密码」是否与本地账号库匹配（不碰服务器）。

    用于账号迁移：联机登录被服务器拒绝、但本地存在同名同密码账号时，
    说明这是个只在本地注册过的账号 —— 用输入的明文密码先过本地哈希
    校验确认身份，再把它自动注册到服务器（见 _migrate_to_server）。
    """
    name = (name or "").strip()
    u = _load()["users"].get(name)
    if not u:
        return False
    return u["pw"] == _hash(u["salt"], pw or "")


def _local_stats(name):
    u = _load()["users"].get(name) or {}
    s = u.get("stats") or {}
    return {"win": s.get("win", 0), "lose": s.get("lose", 0), "draw": s.get("draw", 0)}


def _seed_stats(name):
    """本地有战绩且当前在服务器模式 → 把战绩搬上服务器（幂等，失败静默）"""
    st = _local_stats(name)
    if any(st.values()):
        _rpc({"m": "stats_seed", "win": st["win"], "lose": st["lose"],
              "draw": st["draw"]}, key="stats_seed")


def _seed_rank(name):
    """本地有段位且当前在服务器模式 → 把段位搬上服务器（服务器只收新账号）"""
    st = _local_rank(name)
    if st["tier"] != rank.START_TIER or st["stars"] or st["lb_pts"]:
        _rpc({"m": "rank_seed", "rank": st}, key="rank_seed")


def _migrate_to_server(name, pw):
    """把本地账号迁移到服务器（登录被拒 + 本地密码核对通过时调用）。

    服务器 register 成功即视为迁移完成（token 已在 _remote_register
    里收下）；本地战绩非零则顺手 seed 上去（服务器只认全 0 的新账号）。

    返回：
        None          连接不可用 → 交回调用方走本地回退
        (True, "")    迁移成功，已登录
        (False, err)  迁移失败（多半是服务器已有同名账号但密码不同）
    """
    # ⚠ 必须走 _remote_register：成功后它会 _accept_token 把令牌
    #   写进会话缓存 —— 直接用裸 _rpc 会让迁移"登录了却没登录"。
    rep = _remote_register(name, pw)
    if rep is None:
        return None
    if not rep[0]:
        err = rep[1]
        if "已被注册" in err:
            err = ("服务器上已有同名账号，但密码与本地记录不同。"
                   "请输入该账号在服务器上注册时用的密码。")
        return False, err
    _seed_stats(name)
    _seed_rank(name)
    return True, ""


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


def server_addr():
    """当前（或最近一次）连接的服务器地址；从未连过返回 None"""
    return _SERVER


def email_of():
    """当前账号绑定的邮箱（脱敏显示），未绑定/未联网返回 None"""
    rep = _rpc({"m": "email_of"}, key="email_of")
    if rep is None or not rep.get("bound"):
        return None
    return rep.get("email") or None


def request_email_code(email, purpose="bind"):
    """请求发验证码。返回 (ok, err)；err 为空且 cooldown>0 时是限频"""
    rep = _rpc({"m": "email_code", "purpose": purpose, "email": email},
               key="email_code", timeout=15.0)
    if rep is None:
        return False, "服务器无响应"
    if rep.get("m") == "email_code_ok":
        return True, ""
    return False, rep.get("err") or "发送失败"


def bind_email(email, code):
    """绑定邮箱（需先 request_email_code 拿码）。返回 (ok, 脱敏邮箱或错误)"""
    rep = _rpc({"m": "bind_email", "email": email, "code": code},
               key="bind_email", timeout=15.0)
    if rep is None:
        return False, "服务器无响应"
    if rep.get("m") == "bind_email_ok":
        return True, rep.get("email") or ""
    return False, rep.get("err") or "绑定失败"


def change_password(old, new):
    """修改密码（需验旧密码）。

    服务器后端：change_pw 协议 —— 服务器作废其它会话（本机保留）；
    本地后端：直接重哈希。两边的本地账号哈希都同步更新 —— 免密接管 /
    本地校验用的就是这份哈希，不同步会出现「改了密码本地还认旧密码」
    的裂缝。
    """
    if len(new or "") < 6:
        return False, "新密码至少 6 位（建议混合字母和数字）"
    name = current()
    if _BACKEND == "server":
        rep = _rpc({"m": "change_pw", "old": old, "new": new},
                   key="change_pw", timeout=15.0)
        if rep is None:
            return False, "服务器无响应"
        if rep.get("m") != "change_ok":
            return False, rep.get("err") or "修改失败"
    else:
        u = _load()["users"].get(name)
        if not u or u["pw"] != _hash(u["salt"], old or ""):
            return False, "旧密码错误"
    if name:
        db = _load()
        u = db["users"].get(name)
        if u is not None:
            u["salt"] = secrets.token_hex(8)
            u["pw"] = _hash(u["salt"], new)
            _save(db)
    return True, ""


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
                _leave_guest()
                # 本地若有同名账号（老玩家换机器/重装后重新注册），
                # 把本地战绩一并搬上去
                _seed_stats(name)
                _seed_rank(name)
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
    _leave_guest()
    return True, ""


def login(name, pw):
    """登录。返回 (ok, 错误信息)

    服务器模式下登录被拒时，若本地存在「同名 + 同密码」的账号，
    会自动把该账号迁移上服务器（register + 战绩 seed）再登录 ——
    本地注册过的玩家进联机不该被要求换一套账号（2026-10-04 修）。
    """
    name = (name or "").strip()
    if _BACKEND == "server":
        rep = _remote_login(name, pw)
        if rep is not None:
            if rep[0]:
                _mkdir_decks(name)
                _leave_guest()
                return rep
            # 服务器明确拒绝：先看是不是「只在本地注册过」的账号
            if local_verify(name, pw):
                mig = _migrate_to_server(name, pw)
                if mig is None:
                    return rep              # 连接其实已断 → 走本地回退
                if mig[0]:
                    _mkdir_decks(name)
                    _leave_guest()
                    return True, ""
                return mig                  # 服务器同名但密码不同等情况
            return rep
        # 服务器掉线 → 回退本地
    u = _load()["users"].get(name)
    if not u or u["pw"] != _hash(u["salt"], pw or ""):
        return False, "用户名或密码错误"
    db = _load()
    db["current"] = name
    _save(db)
    _mkdir_decks(name)
    _leave_guest()
    return True, ""


def logout():
    """退出登录 → 回到游客状态（游客本来就"不记东西"，所以不会丢数据）"""
    global _is_guest
    if _BACKEND == "server" and _REMOTE is not None:
        # 只清本地令牌，不占用服务器连接（同一连接还要用于对局中转）
        _drop_session()
        _is_guest = True
        return
    db = _load()
    db["current"] = None
    _save(db)
    _is_guest = True


def delete_account(name=None, server_data=False):
    """永久删除账号，返回 (ok, err_key)。

    err_key 是给界面层翻译的短标记（本模块不依赖 i18n）：
        "no_user"       没有登录 / 传了 GUEST
        "offline"       勾了「同时删除服务器数据」但当前没连服务器
        "server_failed" 服务器没删成功（超时/拒绝/账号不存在）

    ⚠ 勾选服务器删除时**先删服务器、再删本地**：服务器没删掉就直接
    返回失败并且本地一点不动 —— 否则用户以为"全删干净了"，服务器上
    还留着账号、战绩和云卡组，下次登录又全回来了。

    不勾选时只清本机：账号行、免密会话、货币/商店外观/每日任务、
    自组卡组目录；服务器账号仍可用原密码登录回来（远端保留）。
    """
    name = name or current()
    if not name or name == GUEST:
        return False, "no_user"
    # 只清本机时，账号必须真的在本机存在（服务器账号由服务器判定）
    if (not server_data and name not in _load()["users"]
            and current() != name):
        return False, "no_user"

    if server_data:
        if _BACKEND != "server" or _REMOTE is None or not _REMOTE.alive:
            return False, "offline"
        rep = _rpc({"m": "delete_account"}, key="delete_account", timeout=10.0)
        if not (isinstance(rep, dict) and rep.get("m") == "account_deleted"
                and rep.get("ok")):
            return False, "server_failed"

    _purge_local(name)
    return True, ""


def _purge_local(name):
    """清掉本机属于该账号的一切（删除账号专用，不要单独调用）。"""
    global _TOKEN, _is_guest

    # 先记住「被删的是不是当前登录的人」：删别人（或别的本地账号）
    # 不该把当前玩家一脚踢成游客。
    was_current = current() == name

    db = _load()
    db["users"].pop(name, None)
    if db.get("current") == name:
        db["current"] = None
    _save(db)

    # 免密会话：只清这个账号的那份，别把同一台机器上别的账号一起登出
    if _load_session().get("name") == name:
        _drop_session()
    if was_current:
        _TOKEN = None

    # 钱包：货币 / 商店外观 / 每日任务（本地与服务器两份都清）
    keys = wallet_keys(name)
    cur = _load_currency()
    hit = False
    for k in keys:
        if k in cur:
            cur.pop(k, None)
            hit = True
    if hit:
        _save_currency(cur)
    try:
        import kards_shop as _shop
        _shop.purge(name)
    except Exception:                        # noqa: BLE001 清理失败不该阻断删除
        pass
    try:
        import kards_quests as _quests
        _quests.purge(name)
    except Exception:                        # noqa: BLE001
        pass

    # 自组卡组目录（只删这个账号那一个，路径由 deck_dir 生成）
    d = deck_dir(name)
    if os.path.isdir(d):
        try:
            shutil.rmtree(d)
        except OSError:
            pass

    if was_current:
        _is_guest = True


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
        rep = _rpc({"m": "stats"}, key="stats")
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
        # 在线时战绩只记在服务器（本地那份不参与，避免两边不一致）
        if _rpc({"m": "stats_add", "result": result}, key="stats_add") is not None:
            return
    db = _load()
    u = db["users"].get(name)
    if not u:
        return
    st = u.setdefault("stats", {"win": 0, "lose": 0, "draw": 0})
    st[result] = st.get(result, 0) + 1
    _save(db)


# ---------------------------------------------------------------- 段位

def _local_rank(name):
    """本地段位状态（顺带做赛季结算）。"""
    db = _load()
    u = db["users"].get(name) or {}
    st = rank.normalize(u.get("rank") or rank.new_state())
    st2, rolled = rank.roll_season(st)
    if rolled and name in db["users"]:
        db["users"][name]["rank"] = st2
        _save(db)
    return st2


def get_rank(name=None):
    """当前段位状态；游客/未登录返回 None。

    在线优先问服务器（段位是服务器权威数据，换机器也一致）；
    连不上就退回本地副本，保证单机也能看到自己的段位。
    """
    name = name or current()
    if not name or name == GUEST:
        return None
    if _BACKEND == "server" and name:
        rep = _rpc({"m": "rank"}, key="rank")
        if isinstance(rep, dict) and isinstance(rep.get("rank"), dict):
            return rank.normalize(rep["rank"])
    return _local_rank(name)


def rank_add(name, result):
    """结算一场**联机**排位对局，返回 {"rank": 新状态, "change": 变化} 或 None。

    ⚠ 人机对局走 rank_add_ai()：那边每 2 胜才折算 1 星，且不吃连胜加成。
    """
    if not name or result not in ("win", "lose", "draw"):
        return None
    if _BACKEND == "server" and name:
        rep = _rpc({"m": "rank_add", "result": result}, key="rank_add",
                   timeout=8.0)
        if isinstance(rep, dict) and isinstance(rep.get("rank"), dict):
            return {"rank": rank.normalize(rep["rank"]),
                    "change": rep.get("change") or {}}
        # 服务器应答丢失（超时/断线）→ 不能本地再算一遍，否则会双记
        return None
    db = _load()
    u = db["users"].get(name)
    if not u:
        return None
    st, ch = rank.apply_result(u.get("rank") or rank.new_state(), result)
    u["rank"] = st
    _save(db)
    return {"rank": st, "change": ch}


def rank_add_ai(name, result):
    """结算一场**人机**对局：每 2 胜折算 1 星，负场不动段位。

    和 rank_add 一样以服务器为准（段位是服务器权威数据）；应答丢失时
    不本地补算，避免一局两记。
    """
    if not name or result not in ("win", "lose", "draw"):
        return None
    if _BACKEND == "server" and name:
        rep = _rpc({"m": "rank_add_ai", "result": result}, key="rank_add_ai",
                   timeout=8.0)
        if isinstance(rep, dict) and isinstance(rep.get("rank"), dict):
            return {"rank": rank.normalize(rep["rank"]),
                    "change": rep.get("change") or {}}
        return None
    db = _load()
    u = db["users"].get(name)
    if not u:
        return None
    st, ch = rank.apply_ai_result(u.get("rank") or rank.new_state(), result)
    u["rank"] = st
    _save(db)
    return {"rank": st, "change": ch}


def leaderboard(limit=50):
    """排行榜。

    返回 {"rows": 前 N 名, "total": 上榜人数, "me": 我的行|None,
          "online": 是否来自服务器, "season": "2026"}
    离线时只能用本地账号库拼一个"单机榜"，界面上要说明。
    """
    limit = max(1, int(limit or 50))
    if _BACKEND == "server" and _REMOTE is not None and getattr(_REMOTE, "alive", False):
        rep = _rpc({"m": "rank_board", "limit": limit}, key="rank_board",
                   timeout=8.0)
        if isinstance(rep, dict) and isinstance(rep.get("rows"), list):
            return {"rows": rep.get("rows") or [],
                    "total": int(rep.get("total") or 0),
                    "me": rep.get("me"), "online": True,
                    "season": str(rep.get("season") or rank.season_id())}
    db = _load()
    entries = []
    for n, u in db["users"].items():
        st, _ = rank.roll_season(rank.normalize(u.get("rank") or rank.new_state()))
        entries.append((n, st))
    full = rank.board_rows(entries, 0)
    cur = current()
    me = next((r for r in full if r["name"] == cur), None)
    return {"rows": full[:limit], "total": len(full), "me": me,
            "online": False, "season": rank.season_id()}


# ---------------------------------------------------------------- 货币 ----
# 金币 / 钻石。设计取向：
# - 只存本地（DATA_DIR/currency.json）：服务器还没有货币协议，硬塞进账号
#   结构会造成"在线时改不动"的死数据。等服务器支持后再迁移同步。
# - 游客也发币（按 guest 键存），但换账号/清档即没了 —— 引导注册。

CURRENCY_START = {"gold": 300, "diamonds": 10}   # 初次见面的见面礼

# 一场对局的奖励（与 stats_add 的 result 对齐）
CURRENCY_REWARDS = {
    "win":  {"gold": 100, "diamonds": 1},
    "lose": {"gold": 30,  "diamonds": 0},
    "draw": {"gold": 50,  "diamonds": 0},
}

_CURRENCY_FILE = os.path.join(DATA_DIR, "currency.json")


def _currency_key(name=None):
    """货币归谁：游客统一 guest；正式账号按 后端:名字，避免本地/服务器重名混账。

    ⚠ 判定顺序：**显式传入的名字优先**，其次当前登录账号；都没有、或明确
    处于游客态、或名字就是 GUEST 哨兵，才落 guest 键。不能只看 `_is_guest`：
    调用方可能拿着账号名来查，但进程里还没走过登录流程（`current()` 为 None
    且 `_is_guest` 为 False），这时按名字路由才不会把账记到别人头上。
    """
    name = name or current()
    if name is None or name == GUEST:
        return "guest"
    # ⚠ 显式传名优先于"当前是不是游客"：删号/登出后 `_is_guest` 为 True，
    # 但调用方完全可能在问"乙乙的钱包"（结算旧账号、测试、清理），
    # 这时必须读乙乙那一份，不能一律塞到 guest 池里（曾把别人的账读丢）。
    return f"{backend()}:{name}"


def wallet_key(name=None):
    """本地玩家数据的归属键（货币 / 商店外观 / 每日任务共用）。

    游客统一 "guest"；正式账号按 "后端:名字"，避免本地与服务器重名混账。
    """
    return _currency_key(name)


def wallet_keys(name):
    """该用户名**可能留下**的所有钱包键（本地 + 服务器各一份）。

    用途：删除账号时清账。玩家可能先在本地攒金币买外观，后来把账号
    迁到服务器又攒了一份；只清当前 backend() 那份会留下孤儿数据，
    换个后端登录同名账号就会"继承"上一任的钱和外观。
    """
    if not name or name == GUEST:
        return ["guest"]
    return [f"local:{name}", f"server:{name}"]


def _load_currency():
    try:
        with open(_CURRENCY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_currency(d):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_CURRENCY_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except OSError:
        pass            # 磁盘只读时钱丢了就丢了，别为它崩掉对局结算


def get_currency(name=None):
    """返回 {"gold": n, "diamonds": n}；从未记录过的账号给初始金额"""
    c = _load_currency().get(_currency_key(name)) or CURRENCY_START
    return {"gold": int(c.get("gold", 0)), "diamonds": int(c.get("diamonds", 0))}


def currency_add(gold=0, diamonds=0, name=None):
    """加（或减，传负数）货币，返回更新后的 {"gold": n, "diamonds": n}"""
    d = _load_currency()
    k = _currency_key(name)
    c = d.get(k) or dict(CURRENCY_START)
    c["gold"] = max(0, int(c.get("gold", 0)) + gold)
    c["diamonds"] = max(0, int(c.get("diamonds", 0)) + diamonds)
    d[k] = c
    _save_currency(d)
    return {"gold": c["gold"], "diamonds": c["diamonds"]}


def currency_reward(result, name=None):
    """按对局结果发放奖励，返回 {"gold": n, "diamonds": n}（增量）。

    name 不传时记到"当前玩家"头上（登录账号或 guest 池），与 App 结算处
    `account.get_currency(self.account)` 的口径一致。
    """
    r = CURRENCY_REWARDS.get(result) or {"gold": 0, "diamonds": 0}
    currency_add(gold=r["gold"], diamonds=r["diamonds"], name=name)
    return dict(r)
