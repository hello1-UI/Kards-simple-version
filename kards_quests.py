# -*- coding: utf-8 -*-
"""每日任务：每天 3 个，完成领金币（纯逻辑 + 本地存档，无 GUI）

设计
--------------------------------------------------------------------------
· 按自然日刷新（本地时间 00:00），任务清单当天固定，跨日自动换。
· 清单用日期做种子抽 3 个；**游客不会抽到联机任务**（游客打不了联机，
  抽到就等于当天白给一个做不完的任务）。
· 进度只在「对局结束」时记账：局数、胜场、联机场次、当日最长连胜、
  用几个不同国家赢过、满血（HQ ≥ 15）获胜。
· 中途退出判负也会记一局（记负），和真实对局口径一致。
· 金币走 kards_account.currency_add，和商店/对局奖励同一个钱包。
"""
import json
import os
import random
import time

import kards_account as account

_FILE = os.path.join(account.DATA_DIR, "quests.json")
DAILY_COUNT = 3
FULL_HP = 15                     # 「满血获胜」的门槛（总部满血 20）

# kind → 计数器的哪一种。name 三语内嵌（任务文案是数据）
POOL = [
    {"id": "q_games3", "tier": 1, "kind": "games", "target": 3, "gold": 80,
     "name": "完成 3 场对局", "name_en": "Play 3 matches",
     "name_ja": "3 戦プレイ"},
    {"id": "q_games5", "tier": 2, "kind": "games", "target": 5, "gold": 120,
     "name": "完成 5 场对局", "name_en": "Play 5 matches",
     "name_ja": "5 戦プレイ"},
    {"id": "q_wins2", "tier": 2, "kind": "wins", "target": 2, "gold": 120,
     "name": "赢下 2 场对局", "name_en": "Win 2 matches",
     "name_ja": "2 勝する"},
    {"id": "q_wins3", "tier": 3, "kind": "wins", "target": 3, "gold": 180,
     "name": "赢下 3 场对局", "name_en": "Win 3 matches",
     "name_ja": "3 勝する"},
    {"id": "q_streak2", "tier": 2, "kind": "best_streak", "target": 2, "gold": 100,
     "name": "取得 2 连胜", "name_en": "Win 2 in a row",
     "name_ja": "2 連勝"},
    {"id": "q_streak3", "tier": 3, "kind": "best_streak", "target": 3, "gold": 160,
     "name": "取得 3 连胜", "name_en": "Win 3 in a row",
     "name_ja": "3 連勝"},
    {"id": "q_nations2", "tier": 2, "kind": "nations", "target": 2, "gold": 120,
     "name": "用 2 个不同国家获胜", "name_en": "Win with 2 nations",
     "name_ja": "2 か国で勝利"},
    {"id": "q_full1", "tier": 1, "kind": "full_wins", "target": 1, "gold": 100,
     "name": "总部满血以上赢 1 场", "name_en": "Win with HQ at 15+",
     "name_ja": "HQ15以上で1勝"},
    # ---- 联机专属（游客不会抽到） ----
    {"id": "q_online1", "tier": 2, "kind": "online", "target": 1, "gold": 100,
     "name": "完成 1 场联机对局", "name_en": "Play 1 online match",
     "name_ja": "オンライン1戦"},
    {"id": "q_online_win1", "tier": 3, "kind": "online_wins", "target": 1, "gold": 150,
     "name": "赢下 1 场联机对局", "name_en": "Win 1 online match",
     "name_ja": "オンライン1勝"},
]
ONLINE_KINDS = ("online", "online_wins")

_BY_ID = {q["id"]: q for q in POOL}


def name_of(q):
    try:
        import kards_i18n as i18n
        lang = i18n.get_lang()
    except Exception:                       # noqa: BLE001
        lang = "zh"
    if lang == "en":
        return q.get("name_en") or q["name"]
    if lang == "ja":
        return q.get("name_ja") or q["name"]
    return q["name"]


# ---------------------------------------------------------------- 存档
def _key(name=None):
    return account.wallet_key(name)


def _today():
    return time.strftime("%Y-%m-%d", time.localtime())


def _blank(date=None):
    return {"date": date or _today(), "ids": [],
            "counters": {"games": 0, "wins": 0, "online": 0, "online_wins": 0,
                         "best_streak": 0, "streak": 0, "nations": [],
                         "full_wins": 0},
            "claimed": []}


def _load():
    try:
        with open(_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _save(d):
    try:
        os.makedirs(account.DATA_DIR, exist_ok=True)
        with open(_FILE, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
    except OSError:
        pass


def normalize(raw, date=None):
    """修坏档：缺字段补齐、剔除已下架任务、计数夹到非负。"""
    out = _blank(date)
    if not isinstance(raw, dict):
        return out
    out["date"] = str(raw.get("date") or out["date"])
    ids = raw.get("ids") if isinstance(raw.get("ids"), list) else []
    out["ids"] = [i for i in ids if i in _BY_ID][:DAILY_COUNT]
    c = raw.get("counters") if isinstance(raw.get("counters"), dict) else {}
    for k in ("games", "wins", "online", "online_wins", "best_streak",
              "streak", "full_wins"):
        try:
            out["counters"][k] = max(0, int(c.get(k) or 0))
        except (TypeError, ValueError):
            out["counters"][k] = 0
    nat = c.get("nations") if isinstance(c.get("nations"), list) else []
    out["counters"]["nations"] = [str(n) for n in nat if n][:32]
    cl = raw.get("claimed") if isinstance(raw.get("claimed"), list) else []
    out["claimed"] = [i for i in cl if i in _BY_ID]
    return out


def _pick(date, online_ok):
    """抽当天 3 个任务：难度分 1/2/3 各取一个，尽量不撞同一类计数器。

    「各取一个难度」是为了别让一整天的任务都是「赢 3 场 + 连胜 3 场」这种
    同质硬活；游客会把联机任务过滤掉（打不了就等于白给一个做不完的）。
    """
    pool = [q for q in POOL if online_ok or q["kind"] not in ONLINE_KINDS]
    rng = random.Random("quests|" + date)
    picked, kinds = [], set()
    for tier in (1, 2, 3):
        cand = [q for q in pool
                if int(q.get("tier") or 0) == tier and q["kind"] not in kinds]
        if not cand:                      # 该类都撞了 → 允许重复类型
            cand = [q for q in pool if int(q.get("tier") or 0) == tier]
        if not cand:                      # 该难度没有适合游客的 → 跳过
            continue
        q = cand[rng.randrange(len(cand))]
        picked.append(q)
        kinds.add(q["kind"])
    return [q["id"] for q in picked]


def _ensure(name=None, online_ok=None):
    """取当天状态（跨日重置）。返回 (state, full_db)。"""
    d = _load()
    k = _key(name)
    st = normalize(d.get(k))
    today = _today()
    changed = False
    if st["date"] != today or not st["ids"]:
        if online_ok is None:
            try:
                online_ok = bool(account.can_play_online())
            except Exception:               # noqa: BLE001
                online_ok = False
        st = _blank(today)
        st["ids"] = _pick(today, online_ok)
        d[k] = st
        changed = True
    elif k not in d:
        d[k] = st
        changed = True
    if changed:
        _save(d)
    return st, d


def get_state(name=None):
    return _ensure(name)[0]


def purge(name):
    """删除账号时清掉该玩家的每日任务档（本地/服务器两个钱包键都清）。"""
    d = _load()
    hit = False
    for k in account.wallet_keys(name):
        if k in d:
            d.pop(k, None)
            hit = True
    if hit:
        _save(d)


def daily(name=None):
    """今天的任务列表：每项带进度、是否完成、是否已领。"""
    st = get_state(name)
    rows = []
    for qid in st["ids"]:
        q = _BY_ID.get(qid)
        if q is None:
            continue
        kind = q["kind"]
        raw = st["counters"].get(kind, 0)
        if kind == "nations":
            prog = len(st["counters"].get("nations") or [])
        else:
            prog = int(raw or 0)
        target = int(q["target"])
        rows.append({"id": qid, "kind": kind, "target": target,
                     "gold": int(q["gold"]), "name": name_of(q),
                     "progress": min(prog, target), "raw": prog,
                     "done": prog >= target,
                     "claimed": qid in st["claimed"]})
    return rows


def claim(name, qid):
    """领一个任务的奖励。返回 (gold, err_key)。"""
    row = next((r for r in daily(name) if r["id"] == qid), None)
    if row is None:
        return 0, "quest_err_unknown"
    if row["claimed"]:
        return 0, "quest_err_claimed"
    if not row["done"]:
        return 0, "quest_err_locked"

    d = _load()
    k = _key(name)
    st = normalize(d.get(k))
    if qid in st["claimed"]:
        return 0, "quest_err_claimed"
    st["claimed"].append(qid)
    d[k] = st
    _save(d)
    account.currency_add(gold=row["gold"], name=name)
    return row["gold"], None


def record_game(result, online=False, nation="", my_hq=0, name=None):
    """一局结束记账（含中途退出判负）。返回更新后的 counters。

    result: "win" / "lose" / "draw"。draw 只算一局，不算胜也不算负。
    """
    st, d = _ensure(name)
    c = st["counters"]
    c["games"] = int(c.get("games") or 0) + 1
    if online:
        c["online"] = int(c.get("online") or 0) + 1
    if result == "win":
        c["wins"] = int(c.get("wins") or 0) + 1
        c["streak"] = int(c.get("streak") or 0) + 1
        c["best_streak"] = max(int(c.get("best_streak") or 0), c["streak"])
        if online:
            c["online_wins"] = int(c.get("online_wins") or 0) + 1
        if nation:
            nat = list(c.get("nations") or [])
            if nation not in nat:
                nat.append(nation)
            c["nations"] = nat[:32]
        if int(my_hq or 0) >= FULL_HP:
            c["full_wins"] = int(c.get("full_wins") or 0) + 1
    elif result == "lose":
        c["streak"] = 0
    d[_key(name)] = st
    _save(d)
    return c


def claimed_gold(name=None):
    """今天已领到多少金币（界面用）。"""
    st = get_state(name)
    return sum(int(_BY_ID[i]["gold"]) for i in st["claimed"] if i in _BY_ID)


def available_gold(name=None):
    """今天还没领、且已完成的奖励总额（红点/提示用）。"""
    return sum(r["gold"] for r in daily(name) if r["done"] and not r["claimed"])


def days_left_hint():
    """距离 0 点还有多少小时（界面文案用，向上取整）。"""
    t = time.localtime()
    secs = 24 * 3600 - (t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec)
    return max(1, int((secs + 3599) // 3600))
