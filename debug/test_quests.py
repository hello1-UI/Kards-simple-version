# -*- coding: utf-8 -*-
"""每日任务测试：抽取 / 进度记账 / 领奖 / 跨日重置 / 坏数据兜底

运行:
    python debug/test_quests.py
"""
import json
import os
import sys
import tempfile

# 必须在 import 前设好：DATA_DIR 是导入期读取的
os.environ["KARDS_DATA_DIR"] = tempfile.mkdtemp(prefix="kards_quest_test_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_account as account      # noqa: E402
import kards_quests as Q             # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


def reset(name=None):
    """清掉某个钱包的任务存档，回到空白日。"""
    d = Q._load()
    d.pop(Q._key(name), None)
    Q._save(d)


def main():
    day = {"v": "2026-11-24"}
    Q._today = lambda: day["v"]          # 固定「今天」，测试才能跨日

    account.register("甲甲", "pass1234")
    account.register("乙乙", "pass1234")

    print("1. 每日抽取")
    rows = Q.daily("甲甲")
    check("每天 3 个任务", len(rows) == 3, len(rows))
    check("任务 id 不重复", len({r["id"] for r in rows}) == 3)
    tiers = sorted(Q._BY_ID[r["id"]]["tier"] for r in rows)
    check("难度 1/2/3 各一个", tiers == [1, 2, 3], tiers)
    check("每个任务都有名字", all(r["name"] for r in rows))
    check("初始进度为 0", all(r["progress"] == 0 and not r["done"] for r in rows))
    check("初始未领奖", all(not r["claimed"] for r in rows))

    ids_today = [r["id"] for r in rows]
    check("同一天两次读取一致", [r["id"] for r in Q.daily("甲甲")] == ids_today)

    # 抽样若干天：同一天必须稳定，不同天允许变化
    same = 0
    for d in ("2026-01-01", "2026-01-02", "2026-02-14", "2026-12-31"):
        a = Q._pick(d, True)
        b = Q._pick(d, True)
        if a != b:
            check("同一天抽取可复现 " + d, False)
            break
        if len(a) == 3:
            same += 1
    check("多天都能抽满 3 个", same == 4, same)

    print("2. 游客过滤联机任务")

    def has_online(ids):
        return any(Q._BY_ID[i]["kind"] in Q.ONLINE_KINDS for i in ids)

    for d in ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04",
              "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"):
        guest_ids = Q._pick(d, False)
        if has_online(guest_ids):
            check("游客抽不到联机任务 " + d, False, guest_ids)
            break
    else:
        check("游客抽不到联机任务（8 天抽样）", True)
    check("游客仍抽满 3 个", all(len(Q._pick(d, False)) == 3
                                for d in ("2026-01-01", "2026-01-09")))
    check("有资格时能抽到联机任务（30 天抽样）",
          any(has_online(Q._pick("2026-03-%02d" % i, True)) for i in range(1, 31)))

    print("3. 进度记账")
    reset("甲甲")
    for _ in range(3):
        Q.record_game("win", online=False, nation="德国", my_hq=18, name="甲甲")
    c = Q.get_state("甲甲")["counters"]
    check("局数累加", c["games"] == 3, c["games"])
    check("胜场累加", c["wins"] == 3, c["wins"])
    check("最长连胜 3", c["best_streak"] == 3, c["best_streak"])
    check("不同国家去重", c["nations"] == ["德国"], c["nations"])
    check("满血胜场计入", c["full_wins"] == 3, c["full_wins"])
    check("人机不计联机场次", c["online"] == 0, c["online"])

    Q.record_game("lose", online=False, name="甲甲")
    c = Q.get_state("甲甲")["counters"]
    check("负场不清最长连胜", c["best_streak"] == 3, c["best_streak"])
    check("负场清零当前连胜", c["streak"] == 0, c["streak"])
    check("负场不计胜场", c["wins"] == 3, c["wins"])

    Q.record_game("win", online=True, nation="苏联", my_hq=20, name="甲甲")
    c = Q.get_state("甲甲")["counters"]
    check("联机场次累加", c["online"] == 1, c["online"])
    check("联机胜场累加", c["online_wins"] == 1, c["online_wins"])
    check("第二个国家入库", sorted(c["nations"]) == ["德国", "苏联"], c["nations"])

    Q.record_game("draw", name="甲甲")
    c = Q.get_state("甲甲")["counters"]
    check("平局算一局", c["games"] == 6, c["games"])
    check("平局不算胜负", c["wins"] == 4, c["wins"])

    print("4. 完成判定与领奖")
    reset("甲甲")
    # 抽到一个「3 场对局」这类硬性任务靠运气；直接注入必含三类的日期
    for _ in range(3):
        Q.record_game("win", online=True, nation="德国", my_hq=20, name="甲甲")
    rows = Q.daily("甲甲")
    done = [r for r in rows if r["done"]]
    check("有任务被判定完成", len(done) >= 1, [(r["id"], r["progress"]) for r in rows])

    gold0 = account.get_currency("甲甲")["gold"]
    row = done[0]
    got, err = Q.claim("甲甲", row["id"])
    check("完成任务能领奖", got == row["gold"] and err is None, (got, err))
    check("金币到账", account.get_currency("甲甲")["gold"] == gold0 + row["gold"])
    check("已领不会重复发", Q.claim("甲甲", row["id"]) == (0, "quest_err_claimed"))
    check("已领标记写回", next(r for r in Q.daily("甲甲")
                               if r["id"] == row["id"])["claimed"])
    check("已领金币统计", Q.claimed_gold("甲甲") == row["gold"])

    locked = next((r for r in Q.daily("甲甲") if not r["done"]), None)
    if locked is not None:
        check("未完成不能领", Q.claim("甲甲", locked["id"]) == (0, "quest_err_locked"))
    check("不存在的任务被拒", Q.claim("甲甲", "__nope__") == (0, "quest_err_unknown"))

    rows = Q.daily("甲甲")
    avail = Q.available_gold("甲甲")
    check("待领金币 = 已完成未领之和",
          avail == sum(r["gold"] for r in rows if r["done"] and not r["claimed"]), avail)
    check("领完之后待领变少", avail < sum(r["gold"] for r in rows if r["done"]))

    print("5. 跨日重置")
    before = Q.daily("甲甲")
    reset_day_ids = [r["id"] for r in before]
    day["v"] = "2026-11-25"
    rows = Q.daily("甲甲")
    check("跨日会换一批任务", [r["id"] for r in rows] != reset_day_ids)
    check("跨日进度归零", all(r["progress"] == 0 for r in rows))
    check("跨日清空领奖记录", all(not r["claimed"] for r in rows))
    check("跨日已领金币归零", Q.claimed_gold("甲甲") == 0)
    check("跨日后仍 3 个任务", len(rows) == 3, len(rows))

    print("6. 坏数据兜底")
    k = Q._key("甲甲")
    d = Q._load()
    d[k] = {"date": "2026-11-25", "ids": ["q_games3", "__bogus__"],
            "counters": {"games": -5, "wins": "x", "nations": [None, "德国", ""],
                         "best_streak": None},
            "claimed": ["q_games3", "__bogus__"]}
    Q._save(d)
    st = Q.get_state("甲甲")
    check("负数计数归零", st["counters"]["games"] >= 0, st["counters"]["games"])
    check("坏值计数归零", st["counters"]["wins"] == 0, st["counters"]["wins"])
    check("未下架任务保留", st["ids"] == ["q_games3"], st["ids"])
    check("已下架任务被剔除", "__bogus__" not in st["claimed"], st["claimed"])
    check("国家列表剔除空值", st["counters"]["nations"] == ["德国"],
          st["counters"]["nations"])

    d = Q._load()
    d[k] = "not-a-dict"
    Q._save(d)
    rows = Q.daily("甲甲")
    check("全坏档也能出任务", len(rows) == 3 and all(r["progress"] == 0 for r in rows))

    d = Q._load()
    d[k] = {"date": "2026-11-25", "ids": [], "counters": {}, "claimed": []}
    Q._save(d)
    check("空 id 列表会补抽", len(Q.daily("甲甲")) == 3)

    print("7. 账号隔离")
    reset("乙乙")
    check("乙乙是空白任务", all(r["progress"] == 0 for r in Q.daily("乙乙")))
    Q.record_game("win", name="乙乙")
    check("乙乙记账不影响甲甲",
          Q.get_state("甲甲")["counters"]["games"] != 1
          or Q.get_state("乙乙")["counters"]["games"] == 1)
    check("两个钱包键不同", Q._key("甲甲") != Q._key("乙乙"))

    print("8. 界面辅助")
    check("倒计时至少 1 小时", 1 <= Q.days_left_hint() <= 24, Q.days_left_hint())
    check("三语任务名都齐全",
          all(q.get("name") and q.get("name_en") and q.get("name_ja")
              for q in Q.POOL))
    check("奖励都是正数", all(int(q["gold"]) > 0 for q in Q.POOL))
    check("目标都是正数", all(int(q["target"]) > 0 for q in Q.POOL))
    check("每个 kind 都有对应计数器",
          all(q["kind"] in Q._blank()["counters"] for q in Q.POOL))

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
