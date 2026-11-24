# -*- coding: utf-8 -*-
"""商店逻辑测试：目录 / 库存轮换 / 购买 / 装备 / 坏数据兜底

运行:
    python debug/test_shop.py
"""
import json
import os
import sys
import tempfile

# 必须在 import 前设好：DATA_DIR 是导入期读取的
os.environ["KARDS_DATA_DIR"] = tempfile.mkdtemp(prefix="kards_shop_test_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_account as account      # noqa: E402
import kards_shop as shop            # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


def main():
    account.register("甲甲", "pass1234")
    account.currency_add(gold=5000, diamonds=50, name="甲甲")

    print("1. 商品目录")
    check("三类商品都有货", all(shop.items_in(c) for c in shop.CATEGORIES))
    ids = [it["id"] for it in shop.CATALOG]
    check("商品 id 不重复", len(ids) == len(set(ids)))
    for it in shop.CATALOG:
        if it["cat"] == "avatar" and not shop.emblem_polygons(it["emblem"]):
            check("头像都有徽记 " + it["id"], False)
            break
        if it["cat"] == "table" and not all(
                k in it for k in ("bg", "row", "edge", "mid", "accent")):
            check("桌饰五色齐备 " + it["id"], False)
            break
        if it["cat"] == "hq" and not all(
                k in it for k in ("fill", "edge", "accent")):
            check("总部三色齐备 " + it["id"], False)
            break
    else:
        check("每件商品的字段齐备（头像/桌饰/总部）", True)
    check("未知徽记退回默认形状", bool(shop.emblem_polygons("__nope__")))
    check("未知商品返回 None", shop.item("__nope__") is None)
    check("价格都是正数", all(shop.price_text(it) > 0 for it in shop.CATALOG))

    print("2. 当日库存")
    st = shop.get_state("甲甲")
    check("库存 6 件（每类 2 件）", len(st["stock"]["ids"]) == 6, st["stock"])
    by_cat = {}
    for i in st["stock"]["ids"]:
        by_cat.setdefault(shop.item(i)["cat"], []).append(i)
    check("每类恰好 2 件", all(len(v) == 2 for v in by_cat.values()), by_cat)
    check("同一批不重复", len(set(st["stock"]["ids"])) == 6)
    again = shop.get_state("甲甲")
    check("同一天读两遍库存不变", again["stock"]["ids"] == st["stock"]["ids"])
    check("免费刷新次数 = 1", shop.free_rerolls_left("甲甲") == 1)

    print("3. 购买与装备")
    target = next(it for it in shop.stock("甲甲")
                  if not shop.is_diamond(it) and shop.price_text(it) <= 5000)
    gold0 = account.get_currency("甲甲")["gold"]
    ok, err = shop.buy(target["id"], "甲甲")
    check("买得起 → 成功", ok, err)
    check("扣了钱", account.get_currency("甲甲")["gold"] == gold0 - shop.price_text(target))
    check("买完自动装备", shop.equipped_id(target["cat"], "甲甲") == target["id"])
    ok, err = shop.buy(target["id"], "甲甲")
    check("重复购买被拒", not ok and err == "shop_err_owned", err)
    ok, err = shop.buy("__nope__", "甲甲")
    check("未知商品被拒", not ok and err == "shop_err_item", err)
    off_stock = next(it for it in shop.CATALOG if it["id"] not in st["stock"]["ids"])
    ok, err = shop.buy(off_stock["id"], "甲甲")
    check("不在货架上的买不了", not ok and err == "shop_err_not_in_stock", err)

    other = next(it for it in shop.stock("甲甲") if it["cat"] == target["cat"]
                 and it["id"] != target["id"])
    field = "diamonds" if shop.is_diamond(other) else "gold"
    if shop.price_text(other) <= account.get_currency("甲甲")[field]:
        ok, err = shop.buy(other["id"], "甲甲")
        check("同类第二件也能买", ok, err)
        ok, err = shop.equip(other["id"], "甲甲")
        check("换装成功", ok and shop.equipped_id(other["cat"], "甲甲") == other["id"])
        ok, err = shop.equip(target["id"], "甲甲")
        check("已购商品可来回换装", ok)

    ok, err = shop.equip("__nope__", "甲甲")
    check("装备未知商品被拒", not ok and err == "shop_err_item", err)
    ok, err = shop.equip("")
    check("空串 = 卸下全部", ok and all(v == "" for v in
                                       shop.get_state()["equipped"].values()))
    ok, err = shop.equip(target["id"], "甲甲")
    check("重新装备回来", ok)

    print("4. 钱不够")
    acct = account.get_currency("甲甲")
    account.currency_add(gold=-acct["gold"], diamonds=-acct["diamonds"],
                         name="甲甲")
    victim = next((it for it in shop.stock("甲甲")
                   if not shop.is_diamond(it)
                   and it["id"] not in shop.get_state("甲甲")["owned"][it["cat"]]),
                  None)
    if victim:
        ok, err = shop.buy(victim["id"], "甲甲")
        check("没钱买提示金币不足", not ok and err == "shop_no_gold", err)
    else:
        check("没钱买提示金币不足（货架全是已购，跳过）", True)
    account.currency_add(gold=3000, diamonds=10, name="甲甲")

    print("5. 刷新（重摇）")
    ok, err, cost = shop.reroll("甲甲")
    check("当天首次刷新免费", ok and err is None and cost == 0, (ok, err, cost))
    check("免费次数用完", shop.free_rerolls_left("甲甲") == 0)
    ids1 = [i["id"] for i in shop.stock("甲甲")]
    g0 = account.get_currency("甲甲")["gold"]
    ok, err, cost = shop.reroll("甲甲")
    check("第二次刷新收 80 金", ok and cost == shop.REROLL_COST, (ok, err, cost))
    check("刷新扣钱", account.get_currency("甲甲")["gold"] == g0 - shop.REROLL_COST)
    ids2 = [i["id"] for i in shop.stock("甲甲")]
    check("刷新后换了货架", ids1 != ids2, (ids1, ids2))
    # 钱不够 → 拒绝且货架不变
    acct = account.get_currency("甲甲")
    account.currency_add(gold=-acct["gold"], name="甲甲")
    ids_before = [i["id"] for i in shop.stock("甲甲")]
    ok, err, cost = shop.reroll("甲甲")
    check("没钱刷新被拒", not ok and err == "shop_no_gold", err)
    check("拒绝时不改货架", [i["id"] for i in shop.stock("甲甲")] == ids_before)

    print("6. 坏数据兜底")
    raw = shop._load()
    raw["guest"] = {"owned": {"avatar": ["__bad__", "av_star"], "table": None},
                    "equipped": {"avatar": "av_star", "hq": "hq_steel"},
                    "stock": {"date": "bad", "seed": "x", "ids": ["__bad__"],
                              "rerolls": -5}}
    shop._save(raw)
    st = shop.normalize(raw["guest"])
    check("坏 owned 被清洗", st["owned"]["avatar"] == ["av_star"], st["owned"])
    check("未拥有的装备位清空", st["equipped"]["hq"] == "", st["equipped"])
    check("rerolls 负数归零", st["stock"]["rerolls"] == 0)
    st2 = shop.normalize("垃圾数据")
    check("非 dict 存档也能修", st2["owned"]["avatar"] == [])
    shop._save({"guest": "不是字典"})
    st3 = shop.get_state(None)
    check("全坏档不炸", isinstance(st3["owned"], dict), st3["owned"])

    print("7. 账号隔离")
    account.register("乙乙", "pass1234")
    check("乙是空白商店", shop.get_state("乙乙")["owned"]["avatar"] == [])
    check("乙看不到甲的装备", shop.equipped_id("avatar", "乙乙") == "")

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
