# -*- coding: utf-8 -*-
"""段位 / 赛季 / 排行榜 —— 纯规则模块（无 I/O、无 tkinter、无网络）

规则（用户 2026-11-23 指定）
--------------------------------------------------------------------------
段位
  · 共 25 段。25 段为初始段，数字越小越高，1 段最高。
  · 2~25 段每段 5 星，满 5 星升 1 段。
  · 胜 +1 星；连胜 ≥3 场时该场 +2 星（连胜含本场）。
  · 负：21~25 段扣 0 星；1~20 段 -1 星。
  · 0 星时连输 3 场掉 1 段（掉段后星数归 0）；21~25 段不掉段。
  · 保护段位 20 / 15 / 10 / 5 / 1：本赛季到达过，就不会再掉到更低的段位。

赛季
  · 自然月为 1 个赛季，每月 1 日结算。
  · 结算：每人 -25 星（按总星数折算，掉到 0 为止）。
  · ⚠ 「赛季结束前不会降至更低」的保护**不**作用于结算本身：
    否则 1 段玩家永远停在 1 段，赛季软重置就永远不发生。保护只在
    「赛季进行中的掉段」生效，结算后进入新赛季，保护段位按新段位重算。

排行榜
  · 进入 1 段即上榜，记录「升上 1 段之后」的场次。
  · 胜 +3 分，负 -2 分；分高者靠前。
  · 同分依次比胜场多、名字（保证顺序稳定）。
  · 榜单按赛季重置（结算后没人还能留在 1 段，见上）。

总星数
  用「总星数」做唯一真值：total = (25 - tier) * 5 + stars。
  升段/掉段/赛季扣星都先折算成 total 再拆回 (tier, stars)，
  避免在各处手写边界。
"""
import time

TIERS = 25                # 段位总数
START_TIER = 25           # 初始段
STARS_PER_TIER = 5        # 2~25 段升段所需星数
DEMOTE_LOSSES = 3         # 0 星连输几场掉段
SEASON_DECAY = 25         # 赛季结算每人扣多少星
LB_WIN, LB_LOSE = 3, -2   # 排行榜计分

# 保护段位：到达过就不再往下掉（数字是段位号）
FLOOR_CHECKPOINTS = (20, 15, 10, 5, 1)

_MAX_TOTAL = (TIERS - 1) * STARS_PER_TIER + STARS_PER_TIER   # 1 段 5 星 = 125


# ---------------------------------------------------------------- 基础换算

def season_id(ts=None):
    """当前赛季标识（自然月），如 "2026-11"。每月 1 日进入新赛季。"""
    t = time.localtime(ts)
    return f"{t.tm_year:04d}-{t.tm_mon:02d}"


def season_index(sid):
    """赛季号 → 连续月序号（用于算跨了几个月）。

    兼容老数据：只有年份的（"2026"）当作该年 1 月；
    完全无法解析返回 None，调用方按「跨 1 个赛季」处理。
    """
    s = str(sid or "").strip()
    try:
        if "-" in s:
            y, m = s.split("-", 1)
            return int(y) * 12 + int(m) - 1
        return int(s) * 12
    except (TypeError, ValueError):
        return None


def season_end_ts(ts=None):
    """本赛季结算时刻（下个月 1 日 00:00 本地时间）。"""
    t = time.localtime(ts)
    if t.tm_mon == 12:
        y, m = t.tm_year + 1, 1
    else:
        y, m = t.tm_year, t.tm_mon + 1
    return time.mktime((y, m, 1, 0, 0, 0, 0, 0, -1))


def season_days_left(ts=None):
    """距离赛季结算还有几天（向上取整，最后一天返回 1）。"""
    now = time.time() if ts is None else ts
    left = season_end_ts(now) - now
    return max(0, int((left + 86399) // 86400))


def total_stars(st):
    return (TIERS - int(st["tier"])) * STARS_PER_TIER + int(st["stars"])


def split_total(total):
    """总星数 → (tier, stars)"""
    total = max(0, min(int(total), _MAX_TOTAL))
    tier = TIERS - total // STARS_PER_TIER
    stars = total % STARS_PER_TIER
    if tier < 1:
        tier, stars = 1, STARS_PER_TIER
    return tier, stars


def floor_for(best_tier):
    """本赛季到达过 best_tier（数字最小）→ 对应的保护段位。

    best=17 → 20（没到 15，只能保护在 20）
    best=15 → 15
    best=25 → 25（21~25 本来就不掉段，等价于无额外保护）
    """
    best = max(1, min(int(best_tier), TIERS))
    # ⚠ 必须从「最好的保护位」往上找（1 → 5 → 10 → 15 → 20）：
    # 反过来写的话 first-match 会命中 20，1 段玩家的保护位变成 20，
    # 一路掉到 20 段才停（实测踩过）。
    for c in sorted(FLOOR_CHECKPOINTS):
        if best <= c:
            return c
    return TIERS


# ---------------------------------------------------------------- 状态

def new_state(season=None):
    return {
        "tier": START_TIER,
        "stars": 0,
        "best": START_TIER,          # 本赛季到达过的最好段位（数字最小）
        "streak": 0,                 # 当前连胜
        "zero_losses": 0,            # 0 星下的连续败场
        "season": season or season_id(),
        "lb_pts": 0,                 # 排行榜积分
        "lb_win": 0,
        "lb_lose": 0,
        "lb_active": False,          # 是否已进入排行榜
    }


def _i(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def normalize(st):
    """把任意（旧版/损坏/缺字段）状态修成合法状态。"""
    if not isinstance(st, dict):
        st = {}
    out = new_state(str(st.get("season") or season_id()))
    out["tier"] = max(1, min(_i(st.get("tier"), START_TIER), TIERS))
    out["stars"] = max(0, min(_i(st.get("stars"), 0), STARS_PER_TIER))
    out["best"] = max(1, min(_i(st.get("best"), out["tier"]), TIERS))
    out["streak"] = max(0, _i(st.get("streak"), 0))
    out["zero_losses"] = max(0, _i(st.get("zero_losses"), 0))
    out["lb_pts"] = _i(st.get("lb_pts"), 0)
    out["lb_win"] = max(0, _i(st.get("lb_win"), 0))
    out["lb_lose"] = max(0, _i(st.get("lb_lose"), 0))
    out["lb_active"] = bool(st.get("lb_active")) or out["tier"] == 1
    # 不变式：best 不能比当前段位差（数字更大），floor 也不会低于当前段位
    out["best"] = min(out["best"], out["tier"])
    out["tier"] = min(out["tier"], floor_for(out["best"]))
    if out["tier"] == 1:
        out["stars"] = min(out["stars"], STARS_PER_TIER)
    return out


def floor_tier(st):
    """当前生效的保护段位（= 不会再掉到的段位号）。"""
    return floor_for(normalize(st)["best"])


def is_top(st):
    return normalize(st)["tier"] == 1


# ---------------------------------------------------------------- 赛季

def _decay_once(st):
    """一次赛季结算：扣 25 星，保护段位不参与（软重置）。"""
    total = max(0, total_stars(st) - SEASON_DECAY)
    st["tier"], st["stars"] = split_total(total)
    return st


def roll_season(st, year=None):
    """跨赛季则结算。返回 (state, 是否发生了结算)。

    · 一次跨多个赛季就扣多次（一年一次，缺席几年就掉几年）。
    · 结算后进入新赛季：连胜、0 星连败、排行榜积分清零，
      保护段位按新段位重算。
    """
    year = str(year or season_id())
    st = normalize(st)
    if st["season"] == year:
        return st, False
    cur_i, old_i = season_index(year), season_index(st["season"])
    try:
        n = max(1, cur_i - old_i) if (cur_i is not None and old_i is not None) else 1
    except TypeError:                # 老数据/坏数据
        n = 1
    # 缺席很多个月时最多补 50 次（掉到 25 段 0 星也早就到底了）
    for _ in range(min(n, 50)):
        st = _decay_once(st)
    st["season"] = year
    st["best"] = st["tier"]
    st["streak"] = 0
    st["zero_losses"] = 0
    st["lb_pts"] = 0
    st["lb_win"] = 0
    st["lb_lose"] = 0
    st["lb_active"] = st["tier"] == 1
    return st, True


# ---------------------------------------------------------------- 对局

def apply_result(st, result, year=None):
    """结算一场排位对局。

    返回 (new_state, change)
    change = {
        "result": "win"/"lose"/"draw",
        "stars":  ±星数（折算总星数之差，升段也照实反映）,
        "from":   (tier, stars) 对局前,
        "to":     (tier, stars) 对局后,
        "promoted"/"demoted": bool,
        "protected": bool   # 本该掉段但被保护段位挡住
        "entered":  bool    # 本场升上 1 段、首次上榜（本场不计分）
        "lb":       排行榜分数变化,
        "season_rolled": bool,
    }

    「无平局情况」：draw 视为空操作（星、连胜、连败计数都不动），
    免得联机异常结算把玩家的段位打花。
    """
    st, rolled = roll_season(st, year)
    before = (st["tier"], st["stars"])
    before_total = total_stars(st)
    was_top = st["tier"] == 1
    change = {"result": result, "stars": 0, "from": before, "to": before,
              "promoted": False, "demoted": False, "protected": False,
              "entered": False, "lb": 0, "season_rolled": rolled}

    if result == "win":
        st["streak"] += 1
        st["zero_losses"] = 0
        gain = 2 if st["streak"] >= 3 else 1
        st["stars"] += gain
        while st["stars"] >= STARS_PER_TIER and st["tier"] > 1:
            st["stars"] -= STARS_PER_TIER
            st["tier"] -= 1
        if st["tier"] == 1:
            # 1 段封顶：星数不再往上堆，避免出现「1 段 9 星」这种怪值
            st["stars"] = min(st["stars"], STARS_PER_TIER)
        st["best"] = min(st["best"], st["tier"])
    elif result == "lose":
        st["streak"] = 0
        if st["tier"] >= 21:
            # 新手保护：21~25 段负场不扣星、也不掉段
            st["zero_losses"] = 0
        elif st["stars"] > 0:
            st["stars"] -= 1
            st["zero_losses"] = 0
        else:
            st["zero_losses"] += 1
            if st["zero_losses"] >= DEMOTE_LOSSES:
                floor = floor_for(st["best"])
                if st["tier"] + 1 <= floor and st["tier"] < TIERS:
                    st["tier"] += 1
                    st["stars"] = 0
                    change["demoted"] = True
                else:
                    change["protected"] = True
                # 无论掉没掉段，计数都归零：掉了重新积累，被保护则
                # 再连输 3 场才会再次触发判定（避免每输一场都判一次）
                st["zero_losses"] = 0
    # draw / 其它未知结果：完全不动

    # ---- 排行榜 ----
    # 只在「对局开始前已经是 1 段」时计分：升上 1 段的那一场算入场，不计分。
    if was_top:
        st["lb_active"] = True
        if result == "win":
            st["lb_pts"] += LB_WIN
            st["lb_win"] += 1
            change["lb"] = LB_WIN
        elif result == "lose":
            st["lb_pts"] += LB_LOSE
            st["lb_lose"] += 1
            change["lb"] = LB_LOSE
    elif st["tier"] == 1:
        st["lb_active"] = True
        change["entered"] = True

    change["stars"] = total_stars(st) - before_total
    change["promoted"] = st["tier"] < before[0]
    change["to"] = (st["tier"], st["stars"])
    return st, change


def describe(change, tr):
    """把 change 翻成一行人类可读文字。

    tr 传 `kards_i18n.t`，这样本模块不依赖 i18n（便于纯逻辑测试）。
    """
    if not change:
        return ""
    if change.get("season_rolled"):
        pass                     # 赛季结算提示由调用方单独显示
    tier, stars = change["to"]
    d = change.get("stars", 0)
    if change.get("result") == "draw" or d == 0 and not change.get("demoted"):
        if change.get("protected"):
            return tr("rank_protected", tier=tier)
        return tr("rank_unchanged", tier=tier, stars=stars)
    if change.get("demoted"):
        return tr("rank_demoted", tier=tier, stars=stars)
    if change.get("promoted"):
        return tr("rank_promoted", tier=tier, stars=stars)
    if d > 0:
        return tr("rank_gain", n=d, tier=tier, stars=stars)
    return tr("rank_loss", n=-d, tier=tier, stars=stars)


# ---------------------------------------------------------------- 排行榜

def board_rows(entries, limit=50):
    """entries: [(name, state)] → 排序后的榜单行。

    只收已上榜（lb_active）的人；分高者靠前，同分比胜场，再按名字。
    """
    rows = []
    for name, st in entries:
        st = normalize(st)
        if not st.get("lb_active"):
            continue
        rows.append({"name": name, "tier": st["tier"], "stars": st["stars"],
                     "pts": st["lb_pts"], "win": st["lb_win"],
                     "lose": st["lb_lose"]})
    rows.sort(key=lambda r: (-r["pts"], -r["win"], r["lose"], r["name"]))
    for i, r in enumerate(rows, 1):
        r["pos"] = i
    if limit:
        return rows[:int(limit)]
    return rows


def my_position(rows, name):
    """在完整榜单里找自己的名次（rows 需是完整列表）。"""
    for r in rows:
        if r["name"] == name:
            return r
    return None
