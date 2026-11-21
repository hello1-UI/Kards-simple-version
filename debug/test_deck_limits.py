# -*- coding: utf-8 -*-
"""单卡张数上限测试：按稀有度区分（普通 4 / 稀有 3 / 史诗 2 / 传说 1）。

对应原版 KARDS 的四档：Standard 4 / Limited 3 / Special 2 / Elite 1。
用法: python debug/test_deck_limits.py
"""
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
random.seed(7)

import kards_engine as K

PASS = []
FAIL = []

CAPS = {"普通": 4, "稀有": 3, "史诗": 2, "传说": 1}


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name
          + (f"  [{detail}]" if detail and not cond else ""))


def sample_cards(db, nation):
    """取该阵营可用的、每个稀有度各一张代表卡"""
    out = {}
    for c in K.allowed_cards(nation, db):
        out.setdefault(c.rarity, c)
    return out


def deck_with(db, nation, target, n, fill=K.DECK_SIZE):
    """造一副 fill 张的卡组：target 放 n 张，其余按各自上限补满"""
    counts = {target.name: n}
    total = n

    def ally_total():
        return sum(v for k, v in counts.items() if db[k].nation in K.ALLY_NATIONS)

    progress = True
    while total < fill and progress:
        progress = False
        for c in K.allowed_cards(nation, db):
            if c.name == target.name:
                continue
            have = counts.get(c.name, 0)
            if have >= K.max_copies(c):
                continue
            if c.nation in K.ALLY_NATIONS and ally_total() >= K.ALLY_LIMIT:
                continue
            counts[c.name] = have + 1
            total += 1
            progress = True
            if total >= fill:
                break

    deck = []
    for name, cnt in counts.items():
        deck += [db[name]] * cnt
    return deck


def main():
    db = K.card_database()
    nat = "德国"
    samples = sample_cards(db, nat)

    print("=== 1. 上限表 ===")
    check("RARITY_COPIES 四档取值", K.RARITY_COPIES == CAPS, str(K.RARITY_COPIES))
    check("MAX_COPIES 是四档里最宽的那个（4）", K.MAX_COPIES == 4, str(K.MAX_COPIES))
    for r, n in CAPS.items():
        check(f"{r} → {n} 张", K.max_copies(r) == n, str(K.max_copies(r)))
    for r, c in sorted(samples.items()):
        check(f"卡牌对象 {c.name}（{r}）→ {CAPS[r]} 张",
              K.max_copies(c) == CAPS[r], str(K.max_copies(c)))
    check("未知稀有度兜底 4 张", K.max_copies("神话") == 4, str(K.max_copies("神话")))
    check("缺省参数兜底 4 张", K.max_copies() == 4, str(K.max_copies()))
    check("不认 1~4 数字编号（历史两套编号相反，猜必错）",
          K.max_copies(1) == 4 and K.max_copies(4) == 4)

    print("\n=== 2. validate_deck 按稀有度卡上限 ===")
    for r, cap in CAPS.items():
        card = samples[r]
        ok, msg = K.validate_deck(deck_with(db, nat, card, cap), nat, db)
        check(f"{r}卡带满 {cap} 张 → 合法", ok, msg)
        ok, msg = K.validate_deck(deck_with(db, nat, card, cap + 1), nat, db)
        check(f"{r}卡带 {cap + 1} 张 → 拒绝", (not ok) and "最多" in msg, msg)

    print("\n=== 3. 推荐卡组 / 自动填充遵守上限 ===")
    for nation in K.MAIN_NATIONS:
        deck = K.build_deck(nation, db)
        counts = {}
        for c in deck:
            counts[c.name] = counts.get(c.name, 0) + 1
        over = {n: k for n, k in counts.items() if k > K.max_copies(db[n])}
        check(f"{nation} 推荐卡组没有超限卡", not over, str(over))
        ok, msg = K.validate_deck(deck, nation, db)
        check(f"{nation} 推荐卡组 39 张且合法", ok, msg)

    print("\n=== 4. 粘贴清单按稀有度截断 ===")
    legend = samples["传说"]
    common = samples["普通"]
    counts, _ = K.parse_deck_text(f"9 {legend.name}", db)
    check("写 9 张传说 → 截到 1 张", counts.get(legend.name) == 1, str(counts))
    counts, _ = K.parse_deck_text(f"9 {common.name}", db)
    check("写 9 张普通 → 截到 4 张", counts.get(common.name) == 4, str(counts))
    counts, _ = K.parse_deck_text(f"3 {legend.name}\n3 {legend.name}", db)
    check("两行各 3 张传说 → 合计仍 1 张", counts.get(legend.name) == 1, str(counts))
    counts, _ = K.parse_deck_text(f"3 {legend.name}", db, clamp=False)
    check("clamp=False 保留原始数字（载入旧档要靠它提示）",
          counts.get(legend.name) == 3, str(counts))

    print("\n=== 5. counts_to_deck / clamp_counts ===")
    deck = K.counts_to_deck({legend.name: 3, common.name: 6}, nat, db)
    got = {}
    for c in deck:
        got[c.name] = got.get(c.name, 0) + 1
    check("counts_to_deck 把 3 张传说裁成 1 张", got.get(legend.name) == 1, str(got))
    check("counts_to_deck 把 6 张普通裁成 4 张", got.get(common.name) == 4, str(got))
    check("counts_to_deck 仍然补满 39 张", len(deck) == K.DECK_SIZE, str(len(deck)))

    kept, changes = K.clamp_counts({legend.name: 3, common.name: 2}, db)
    check("clamp_counts 下调传说", kept.get(legend.name) == 1, str(kept))
    check("clamp_counts 报出改动明细", (legend.name, 3, 1) in changes, str(changes))
    check("未超限的卡不动、也不进明细",
          kept.get(common.name) == 2 and all(c[0] != common.name for c in changes))
    kept, changes = K.clamp_counts({legend.name: 1}, db)
    check("本来合法 → 无改动", changes == [] and kept.get(legend.name) == 1, str(changes))
    kept, changes = K.clamp_counts({"不存在的卡": 2}, db)
    check("未知卡名剔除并记录",
          "不存在的卡" not in kept and changes == [("不存在的卡", 2, 0)], str(changes))

    print("\n=== 6. 旧存档读回（不应被静默改小） ===")
    old_dir = K.DECKS_DIR
    K.DECKS_DIR = tempfile.mkdtemp(prefix="kards_decks_")
    try:
        K.save_deck_text("旧卡组", {legend.name: 3, common.name: 5}, nat)
        counts, saved_nation = K.load_deck_counts("旧卡组", db)
        check("save/load 国家标记正确", saved_nation == nat, saved_nation)
        check("读回时保留原始张数（3 张传说）",
              counts.get(legend.name) == 3, str(counts))
    finally:
        K.DECKS_DIR = old_dir

    print("\n=== 7. 卡池容量仍然够组 39 张 ===")
    for nation in K.MAIN_NATIONS:
        pool = K.allowed_cards(nation, db)
        own = [c for c in pool if c.nation == nation]
        ally = [c for c in pool if c.nation in K.ALLY_NATIONS]
        check(f"{nation} 本国卡容量 ≥ 39", sum(K.max_copies(c) for c in own) >= K.DECK_SIZE,
              str(sum(K.max_copies(c) for c in own)))
        check(f"{nation} 盟国卡容量 ≥ 盟国上限 20",
              sum(K.max_copies(c) for c in ally) >= K.ALLY_LIMIT,
              str(sum(K.max_copies(c) for c in ally)))

    print("\n=== 8. 卡池分布（供核对）===")
    dist = {}
    for c in db.values():
        dist.setdefault(c.rarity, []).append(c)
    for r in ("普通", "稀有", "史诗", "传说"):
        n = len(dist.get(r, []))
        print(f"  {r}: {n} 种 × 上限 {CAPS[r]} = 单刷最多 {n * CAPS[r]} 张")

    print(f"\n=== 结果: {len(PASS)} 通过 / {len(FAIL)} 失败 ===")
    if FAIL:
        print("失败用例:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
