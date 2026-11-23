# -*- coding: utf-8 -*-
"""段位 / 赛季 / 排行榜规则测试（纯逻辑，不碰网络与 GUI）

覆盖用户 2026-11-23 给定的全部规则：
  · 25 段起始、2~25 段 5 星升段
  · 胜 +1、连胜 3 场起 +2
  · 21~25 负不扣星；1~20 负 -1
  · 0 星连输 3 场掉段；21~25 不掉段
  · 保护段位 20/15/10/5/1
  · 每月 1 日结算 -25 星（自然月为 1 赛季）
  · 1 段进排行榜，胜 +3 / 负 -2

运行:
    python debug/test_rank.py
"""
import copy
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_rank as R      # noqa: E402

PASS, FAIL = [], []


def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [!!] ") + label + (f"  {extra}" if extra else ""))


def play(st, results, year="2026-11"):
    """连续打若干场，返回 (最终状态, 每场的 change)"""
    chs = []
    for r in results:
        st, ch = R.apply_result(st, r, year)
        chs.append(ch)
    return st, chs


def set_rank(st, tier, stars, best=None, streak=0):
    st = R.normalize(st)
    st["tier"] = tier
    st["stars"] = stars
    st["best"] = tier if best is None else best
    st["streak"] = streak
    return st


def main():
    print("1. 基础换算：总星数 ↔ (段位, 星)")
    st = R.new_state("2026-11")
    check("初始 25 段 0 星", st["tier"] == 25 and st["stars"] == 0, st)
    check("初始总星 0", R.total_stars(st) == 0)
    ok = True
    for total in range(0, 126):
        t, s = R.split_total(total)
        if R.total_stars({"tier": t, "stars": s}) != total:
            ok = False
            print("     roundtrip fail", total, t, s)
    check("0~125 总星全部可逆", ok)
    check("1 段 0 星 = 120", R.split_total(120) == (1, 0))
    check("1 段 5 星 = 125（封顶）", R.split_total(125) == (1, 5))
    check("超界不越界", R.split_total(999) == (1, 5) and R.split_total(-5) == (25, 0))

    print("2. 保护段位映射")
    cases = {1: 1, 2: 5, 4: 5, 5: 5, 6: 10, 9: 10, 10: 10,
             11: 15, 14: 15, 15: 15, 16: 20, 19: 20, 20: 20,
             21: 25, 25: 25}
    check("20/15/10/5/1 逐档收紧", all(R.floor_for(k) == v for k, v in cases.items()),
          {k: R.floor_for(k) for k in cases})

    print("3. 胜场与连胜")
    st = R.new_state("2026-11")
    st, chs = play(st, ["win", "win"])
    check("前两胜各 +1 星", [c["stars"] for c in chs] == [1, 1], chs)
    st, ch = R.apply_result(st, "win", "2026-11")
    check("第 3 胜（连胜 3）+2 星", ch["stars"] == 2, ch)
    check("连胜计数 = 3", st["streak"] == 3)
    st, ch = R.apply_result(st, "win", "2026-11")
    check("第 4 胜仍 +2 星", ch["stars"] == 2, ch)
    st, ch = R.apply_result(st, "lose", "2026-11")
    check("一败连胜清零", st["streak"] == 0)
    st, ch = R.apply_result(st, "win", "2026-11")
    check("断连胜后回到 +1 星", ch["stars"] == 1, ch)

    print("4. 升段")
    st = set_rank(R.new_state("2026-11"), 25, 4, streak=0)
    st, ch = R.apply_result(st, "win", "2026-11")
    check("4 星 +1 → 晋级 24 段 0 星", ch["to"] == (24, 0) and ch["promoted"], ch)
    st = set_rank(R.new_state("2026-11"), 25, 4, streak=5)
    st, ch = R.apply_result(st, "win", "2026-11")
    check("4 星 +2（连胜）→ 24 段 1 星", ch["to"] == (24, 1), ch)
    st = set_rank(R.new_state("2026-11"), 2, 3, streak=5)
    st, ch = R.apply_result(st, "win", "2026-11")
    check("2 段 3 星 +2 → 1 段 0 星", ch["to"] == (1, 0), ch)
    st = set_rank(R.new_state("2026-11"), 1, 5, streak=9)
    st, ch = R.apply_result(st, "win", "2026-11")
    check("1 段封顶：星数不超过 5", st["stars"] == 5, st)
    check("1 段封顶：总星不变", ch["stars"] == 0, ch)

    print("5. 负场：21~25 段不扣星、不掉段")
    st = R.new_state("2026-11")
    st, chs = play(st, ["lose"] * 10)
    check("25 段连输 10 场仍 0 星", st["stars"] == 0 and st["tier"] == 25)
    check("25 段连输不掉段", st["tier"] == 25)
    st = set_rank(R.new_state("2026-11"), 22, 3)
    st, ch = R.apply_result(st, "lose", "2026-11")
    check("22 段 3 星负 → 星数不变", st["stars"] == 3 and ch["stars"] == 0, ch)
    st = set_rank(R.new_state("2026-11"), 21, 0)
    st, chs = play(st, ["lose"] * 8)
    check("21 段 0 星连输 8 场不掉段", st["tier"] == 21, st)

    print("6. 负场：1~20 段扣星与掉段")
    st = set_rank(R.new_state("2026-11"), 20, 2)
    st, ch = R.apply_result(st, "lose", "2026-11")
    check("20 段 2 星 → 1 星", ch["stars"] == -1 and st["stars"] == 1, ch)
    st = set_rank(R.new_state("2026-11"), 18, 1)
    st, ch1 = R.apply_result(st, "lose", "2026-11")
    check("1 星负 → 0 星", st["stars"] == 0 and not ch1["demoted"], ch1)
    st, ch2 = R.apply_result(st, "lose", "2026-11")
    st, ch3 = R.apply_result(st, "lose", "2026-11")
    check("0 星第 1、2 败不掉段",
          not ch2["demoted"] and not ch3["demoted"] and st["tier"] == 18, [ch2, ch3])
    st, ch4 = R.apply_result(st, "lose", "2026-11")
    check("0 星第 3 败掉 1 段", ch4["demoted"] and st["tier"] == 19, ch4)
    check("掉段后星归 0", st["stars"] == 0)
    st, ch = R.apply_result(st, "win", "2026-11")
    check("掉段后一胜回到 1 星", st["stars"] == 1, ch)
    # 保护段位本身就是 10 —— 站在 10 段的人不可能再掉到 11。
    # 掉段只发生在两档保护位之间（13 段的保护位是 15）。
    st = set_rank(R.new_state("2026-11"), 13, 0, best=13)
    st, chs = play(st, ["lose"] * 12)
    check("两次掉段后停在保护位：13 → 15", st["tier"] == 15, st["tier"])

    print("7. 保护段位（赛季进行中不掉到更低）")
    st = set_rank(R.new_state("2026-11"), 16, 0, best=15)
    st, chs = play(st, ["lose"] * 30)
    check("到过 15 段后最多掉到 15", st["tier"] == 15, st["tier"])
    check("保护触发被标记", any(c["protected"] for c in chs))
    st = set_rank(R.new_state("2026-11"), 20, 0, best=15)
    st, chs = play(st, ["lose"] * 30)
    check("到过 15 段的人不会再掉到 20", st["tier"] == 15, st["tier"])
    st = set_rank(R.new_state("2026-11"), 1, 0, best=1)
    st, chs = play(st, ["lose"] * 40)
    check("1 段连输 40 场仍在 1 段", st["tier"] == 1, st["tier"])
    st = set_rank(R.new_state("2026-11"), 7, 0, best=5)
    st, chs = play(st, ["lose"] * 30)
    check("到过 5 段后最多掉到 5", st["tier"] == 5, st["tier"])
    st = set_rank(R.new_state("2026-11"), 21, 0, best=21)
    st, chs = play(st, ["lose"] * 30)
    check("从没到过 20 → 停在 21~25 不再上浮", st["tier"] == 21, st["tier"])

    print("8. 赛季结算（自然月）")
    st = set_rank(R.new_state("2026-11"), 1, 0)
    st2, rolled = R.roll_season(st, "2026-12")
    check("跨月触发结算", rolled)
    check("1 段 0 星 -25 → 6 段 0 星", (st2["tier"], st2["stars"]) == (6, 0),
          (st2["tier"], st2["stars"]))
    check("结算后连胜清零", st2["streak"] == 0)
    check("结算后保护位重算为 10 段", R.floor_tier(st2) == 10, R.floor_tier(st2))
    st = set_rank(R.new_state("2026-11"), 15, 3)
    st2, _ = R.roll_season(st, "2026-12")
    # 15 段 3 星 = 53 总星，-25 = 28 → 20 段 3 星
    check("15 段 3 星 -25 → 20 段 3 星", (st2["tier"], st2["stars"]) == (20, 3),
          (st2["tier"], st2["stars"]))
    st = R.new_state("2026-11")
    st2, _ = R.roll_season(st, "2026-12")
    check("25 段 0 星结算后仍是 25 段", st2["tier"] == 25 and st2["stars"] == 0)
    st = set_rank(R.new_state("2026-08"), 1, 0)
    st3, _ = R.roll_season(st, "2026-11")
    check("缺席 3 个月扣 3 次：1 段 → 16 段", st3["tier"] == 16, st3["tier"])
    st = set_rank(R.new_state("2026-12"), 1, 0)
    st4, _ = R.roll_season(st, "2027-01")
    check("跨年（12 月 → 1 月）只扣 1 次", st4["tier"] == 6, st4["tier"])
    st = set_rank(R.new_state("2026-11"), 12, 2)
    same, rolled = R.roll_season(st, "2026-11")
    check("同赛季不结算", not rolled and same["tier"] == 12)
    check("账本上的赛季号 = 当前月", same["season"] == "2026-11")
    check("赛季号格式 YYYY-MM", len(R.season_id()) == 7
          and R.season_id()[4] == "-", R.season_id())

    print("9. 排行榜")
    st = set_rank(R.new_state("2026-11"), 2, 4, streak=5)
    st, ch = R.apply_result(st, "win", "2026-11")
    check("升上 1 段 → 上榜", st["lb_active"] and ch["entered"], ch)
    check("升段那场不计分", st["lb_pts"] == 0 and ch["lb"] == 0)
    st, ch = R.apply_result(st, "win", "2026-11")
    check("上榜后胜 +3 分", st["lb_pts"] == 3 and ch["lb"] == 3, ch)
    check("上榜胜场 +1", st["lb_win"] == 1)
    st, ch = R.apply_result(st, "lose", "2026-11")
    check("上榜后负 -2 分", st["lb_pts"] == 1 and ch["lb"] == -2, ch)
    check("上榜负场 +1", st["lb_lose"] == 1)
    st, chs = play(st, ["lose"] * 3)
    check("分数可为负", st["lb_pts"] == -5, st["lb_pts"])
    check("1 段连败不掉段（保护）", st["tier"] == 1)

    rows = R.board_rows([
        ("甲", {"tier": 1, "lb_active": True, "lb_pts": 10, "lb_win": 4, "lb_lose": 1}),
        ("乙", {"tier": 1, "lb_active": True, "lb_pts": 16, "lb_win": 6, "lb_lose": 2}),
        ("丙", {"tier": 1, "lb_active": True, "lb_pts": 10, "lb_win": 5, "lb_lose": 2}),
        ("丁", {"tier": 3, "lb_active": False, "lb_pts": 99, "lb_win": 30}),
    ], 0)
    check("按分数降序", [r["name"] for r in rows][:2] == ["乙", "丙"], rows)
    check("同分比胜场", [r["name"] for r in rows] == ["乙", "丙", "甲"], rows)
    check("未上榜的人不进榜", all(r["name"] != "丁" for r in rows))
    check("名次连续", [r["pos"] for r in rows] == [1, 2, 3])
    check("limit 生效", len(R.board_rows([(str(i), {"lb_active": True, "lb_pts": i})
                                          for i in range(9)], 5)) == 5)
    check("找不到自己返回 None", R.my_position(rows, "无名") is None)
    check("能找到自己", (R.my_position(rows, "甲") or {}).get("pos") == 3)

    print("10. 平局与健壮性")
    st = set_rank(R.new_state("2026-11"), 12, 3, streak=2)
    before = copy.deepcopy(st)
    st2, ch = R.apply_result(st, "draw", "2026-11")
    check("draw 完全不动", st2["stars"] == 3 and st2["streak"] == 2 and ch["stars"] == 0)
    check("不修改传入的字典", st == before)
    for bad in (None, {}, {"tier": "x"}, {"tier": 99, "stars": 99},
                {"tier": -5, "stars": -5}, {"tier": 1, "stars": 9}):
        n = R.normalize(bad)
        ok = (1 <= n["tier"] <= 25 and 0 <= n["stars"] <= 5
              and n["best"] <= n["tier"] and isinstance(n["season"], str))
        check(f"坏数据被规范化 {bad!r}", ok, n)
    st = R.normalize({"tier": 18, "stars": 2, "best": 10})
    check("best 不会比当前段位更差", st["best"] <= st["tier"], st["best"])
    st = set_rank(R.new_state("2026-11"), 18, 2, best=10)
    check("保护位把越界段位拉回", R.normalize({"tier": 18, "best": 10})["tier"] == 10)
    st = set_rank(R.new_state("2026-11"), 8, 3)
    txt = json.dumps(st)
    check("状态可 JSON 往返", R.normalize(json.loads(txt)) == st)
    check("距结算天数在 1~31", 1 <= R.season_days_left() <= 31,
          R.season_days_left())
    check("每月 1 日当天已属新赛季",
          R.season_id(time.mktime((2027, 1, 1, 0, 0, 0, 0, 0, -1))) == "2027-01")
    check("12 月 31 日属 12 月赛季",
          R.season_id(time.mktime((2026, 12, 31, 23, 0, 0, 0, 0, -1))) == "2026-12")

    print("11. 文案生成")
    tr = lambda k, **kw: k + "|" + ",".join(f"{a}={b}" for a, b in sorted(kw.items()))
    st = set_rank(R.new_state("2026-11"), 25, 4)
    _, ch = R.apply_result(st, "win", "2026-11")
    check("晋级文案", R.describe(ch, tr).startswith("rank_promoted"), R.describe(ch, tr))
    st = set_rank(R.new_state("2026-11"), 13, 0, best=13)
    st, _ = play(st, ["lose", "lose"])            # 0 星连败 2 场：还没掉
    st, ch = R.apply_result(st, "lose", "2026-11")   # 第 3 场才掉段
    check("掉段文案", R.describe(ch, tr).startswith("rank_demoted"), R.describe(ch, tr))
    _, ch = R.apply_result(st, "win", "2026-11")
    check("加星文案带 +n", "n=1" in R.describe(ch, tr), R.describe(ch, tr))
    _, ch = R.apply_result(set_rank(R.new_state("2026-11"), 15, 2), "lose", "2026-11")
    check("扣星文案带 n=1", "n=1" in R.describe(ch, tr), R.describe(ch, tr))
    st = set_rank(R.new_state("2026-11"), 15, 0, best=15)
    _, ch = R.apply_result(set_rank(st, 15, 0, best=15), "lose", "2026-11")
    check("draw 文案不为空", bool(R.describe({"result": "draw", "to": (15, 0),
                                              "stars": 0}, tr)))
    check("无变化也能描述", bool(R.describe(ch, tr)))

    # ------------------------------------------------------------------
    print("12. 人机对局：每 2 胜折算 1 星（2026-11-24 新规则）")
    st = R.new_state("2026-11")
    st, ch = R.apply_ai_result(st, "win", "2026-11")
    check("人机第 1 胜不涨星", st["stars"] == 0 and ch["stars"] == 0, st["stars"])
    check("第 1 胜标为还差 1 胜", ch["ai_pending"] and ch["ai_win"] == 1, ch)
    check("第 1 胜文案提示再赢 1 场",
          R.describe(ch, tr).startswith("rank_ai_pending")
          and "left=1" in R.describe(ch, tr), R.describe(ch, tr))

    st, ch = R.apply_ai_result(st, "win", "2026-11")
    check("人机第 2 胜 +1 星", ch["stars"] == 1 and st["stars"] == 1, st["stars"])
    check("第 2 胜后计数清零", st["ai_wins"] == 0, st["ai_wins"])
    check("第 2 胜文案是加星", R.describe(ch, tr).startswith("rank_ai_gain"),
          R.describe(ch, tr))

    # 负场：星、连胜、连败、榜单全都不动
    st0 = copy.deepcopy(st)
    st, ch = R.apply_ai_result(st, "lose", "2026-11")
    check("人机负场不改段位", (st["tier"], st["stars"]) == (st0["tier"], st0["stars"]))
    check("人机负场不计连败/连胜",
          st["zero_losses"] == 0 and st["streak"] == 0, st["zero_losses"])
    check("人机负场不产文案", R.describe(ch, tr) == "")
    st, ch = R.apply_ai_result(st, "draw", "2026-11")
    check("人机平局完全空操作", st["ai_wins"] == st0["ai_wins"] and ch["stars"] == 0)

    # 不必连续：胜-负-胜 也能凑够 2 胜
    st = set_rank(R.new_state("2026-11"), 20, 0, best=20)
    for r in ("win", "lose", "win"):
        st, ch = R.apply_ai_result(st, r, "2026-11")
    check("人机 2 胜可隔场累计", st["stars"] == 1, st["stars"])

    # 不吃连胜加成：连赢 6 场 = 3 星（联机是 +1/+1/+2/+2/+2/+2 = 10 星）
    st = set_rank(R.new_state("2026-11"), 20, 0, best=20)
    base = R.total_stars(st)
    for _ in range(6):
        st, ch = R.apply_ai_result(st, "win", "2026-11")
    check("人机连胜没有 +2 星加成", R.total_stars(st) - base == 3,
          R.total_stars(st) - base)
    check("人机不累加连胜计数", st["streak"] == 0, st["streak"])

    # 满 5 星照样升段
    st = set_rank(R.new_state("2026-11"), 20, 4, best=20)
    st, ch = R.apply_ai_result(st, "win", "2026-11")     # 第 1 胜
    st, ch = R.apply_ai_result(st, "win", "2026-11")     # 第 2 胜 → 升段
    check("人机也能晋级", st["tier"] == 19 and st["stars"] == 0,
          (st["tier"], st["stars"]))
    check("人机晋级文案", R.describe(ch, tr).startswith("rank_ai_promoted"),
          R.describe(ch, tr))

    # 不进排行榜：5 段刷满也不会拿到榜分
    st = set_rank(R.new_state("2026-11"), 5, 0, best=5)
    for _ in range(20):
        st, ch = R.apply_ai_result(st, "win", "2026-11")
    check("人机不产生排行榜分", st["lb_pts"] == 0 and st["lb_win"] == 0,
          (st["lb_pts"], st["lb_win"]))
    check("人机不写榜单胜负场", st["lb_lose"] == 0)

    # 1 段满星：赢了也没星可给，且不把计数攒成 2
    st = set_rank(R.new_state("2026-11"), 1, 5, best=1)
    st, ch = R.apply_ai_result(st, "win", "2026-11")
    check("1 段满星人机不产出", R.total_stars(st) == R.total_stars(
        set_rank(R.new_state("2026-11"), 1, 5, best=1)), R.total_stars(st))
    check("1 段满星不记人机胜场", st["ai_wins"] == 0, st["ai_wins"])
    check("1 段满星不产文案", R.describe(ch, tr) == "")

    # 跨赛季：人机结算也要先补 -25 星
    st = set_rank(R.new_state("2026-11"), 20, 0, best=20)
    st, ch = R.apply_ai_result(st, "win", "2026-12")
    check("人机结算先补赛季扣星", ch["season_rolled"] and st["season"] == "2026-12")
    check("赛季扣星后人不机涨星（第 1 胜）", st["stars"] == 0, st["stars"])

    # 坏数据兜底
    st = R.normalize({"tier": 20, "stars": 2, "ai_wins": 7})
    check("ai_wins 坏值被折成 0/1", st["ai_wins"] in (0, 1), st["ai_wins"])
    check("归一化默认带 ai_wins", "ai_wins" in R.new_state("2026-11"))

    print()
    print("=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  -", f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
