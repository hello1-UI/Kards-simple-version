# -*- coding: utf-8 -*-
"""从原版 CSV 挖掘新卡扩充卡池到 200+：
- 单位卡：费用/攻防/关键词/稀有度全用原版数据（旗标仅限可映射的 7 种，其余跳过）
- 指令卡：只选文本可映射到通用效果工厂的原版卡
- 名称用原版简体中文（缺省用英文），全局去重
生成的代码注入 kards.py（EXTRA_CARDS + 效果工厂）。
"""
import ast
import csv
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CSV_PATH = "debug/all_cards_original.csv"
SRC = "kards.py"

FLAG_KW = {
    "blitz": "闪击",
    "guard": "警卫",
    "ambush": "伏击",
    "mobilize": "动员",
    "fury": "奋战",
    "heavyArmor1": "装甲",
    "heavyArmor2": "装甲2",
}
OTHER_FLAGS = {"smokescreen", "pincer", "alpine", "intel2", "intel3"}
TYPE_MAP = {"infantry": "步兵", "tank": "坦克", "fighter": "战斗机",
            "bomber": "轰炸机", "artillery": "炮兵"}
NATION_MAP = {"Germany": "德国", "Soviet": "苏联", "USA": "美国",
              "Britain": "英国", "Japan": "日本", "Italy": "意大利",
              "France": "法国", "Poland": "波兰"}
RARITY_MAP = {"Standard": "普通", "Limited": "稀有", "Special": "史诗",
              "Elite": "传说"}

UNIT_QUOTA = {"德国": 24, "苏联": 24, "美国": 20, "英国": 20, "日本": 20,
              "意大利": 4, "法国": 4, "波兰": 4}
ORDER_QUOTA = {"德国": 5, "苏联": 5, "美国": 4, "英国": 5, "日本": 4,
               "意大利": 2, "法国": 2, "波兰": 2}

ORDER_PATTERNS = [
    (re.compile(r"^Draw (\d+) cards?\.?$"),
     lambda m: ("mk_draw(%s)" % m.group(1), "抽 %s 张牌" % m.group(1))),
    (re.compile(r"^Draw a card\.?$"),
     lambda m: ("mk_draw(1)", "抽 1 张牌")),
    (re.compile(r"^Deal (\d+) damage to (the )?target HQ\.?$"),
     lambda m: ("mk_deal_hq(%s)" % m.group(1), "对敌方总部造成 %s 点伤害" % m.group(1))),
    (re.compile(r"^Deal (\d+) damage to all enemies\.?$|^Deal (\d+) damage to all\.?$"),
     lambda m: ("mk_deal_all(%s)" % (m.group(1) or m.group(2)),
                "对所有敌方单位造成 %s 点伤害" % (m.group(1) or m.group(2)))),
    (re.compile(r"^Destroy a random enemy unit\.?$"),
     lambda m: ("mk_destroy_random()", "消灭一个随机敌方单位")),
    (re.compile(r"^Destroy a damaged unit\.?$"),
     lambda m: ("mk_destroy_damaged()", "消灭一个已受损的敌方单位（攻击力最高者优先）")),
    (re.compile(r"^Destroy a unit that costs (\d+) kredits? or less\.?$"),
     lambda m: ("mk_destroy_cost_le(%s)" % m.group(1),
                "消灭一个费用不大于 %s 的敌方单位（攻击力最高者优先）" % m.group(1))),
]


def truthy(v):
    return str(v).strip().lower() in ("1", "true", "yes", "y")


def clean_name(r):
    zh = (r["title zh-Hans"] or "").strip()
    name = zh.split("/")[0].strip() if zh else ""
    return name or r["title en-EN"].strip()


def main():
    # 已实现卡的英文标题（从匹配报告提取）
    used_en = set()
    for line in io.open("debug/original_match2.txt", encoding="utf-8"):
        m = re.match(r"^### .*? -> (.+?) \| ", line)
        if m:
            seg = re.sub(r"^\d+\.\s*", "", m.group(1).strip())
            used_en.add(seg.upper())
    if len(used_en) < 50:
        print("警告：匹配报告只解析到", len(used_en), "个英文标题")

    rows = list(csv.DictReader(io.open(CSV_PATH, encoding="utf-8"), delimiter=";"))
    existing = set()
    import kards
    existing |= set(kards.card_database().keys())

    # ---- 单位卡筛选 ----
    unit_cands = {}
    for r in rows:
        if r["type"] not in TYPE_MAP or r["faction"] not in NATION_MAP:
            continue
        if r["title en-EN"].strip().upper() in used_en:
            continue
        flags = {c for c in FLAG_KW if truthy(r.get(c, ""))}
        if {c for c in OTHER_FLAGS if truthy(r.get(c, ""))}:
            continue
        try:
            cost, atk, dfn = int(r["kredits"]), int(r["attack"]), int(r["defense"])
        except (ValueError, KeyError):
            continue
        if not (0 <= cost <= 10 and 0 <= atk <= 12 and 1 <= dfn <= 12):
            continue
        name = clean_name(r)
        if name in existing:
            continue
        nat = NATION_MAP[r["faction"]]
        kw = [FLAG_KW[c] for c in ("blitz", "guard", "ambush", "mobilize",
                                   "fury", "heavyArmor1", "heavyArmor2")
              if c in flags]
        unit_cands.setdefault(nat, []).append({
            "name": name, "cost": cost, "atk": atk, "dfn": dfn,
            "kw": kw, "type": TYPE_MAP[r["type"]],
            "rarity": RARITY_MAP.get(r["rarity"]),
            "dying": "Destruction: Deal 2 damage to the enemy HQ" in r["text en-EN"],
        })

    def spread(cands, quota):
        """按费用排序后均匀抽样，保证费用段分布"""
        cands = sorted(cands, key=lambda c: (c["cost"], c["name"]))
        if len(cands) <= quota:
            return cands
        step = len(cands) / quota
        return [cands[min(int(i * step), len(cands) - 1)] for i in range(quota)]

    picked_units = []
    for nat, quota in UNIT_QUOTA.items():
        for c in spread(unit_cands.get(nat, []), quota):
            c["nation"] = nat
            existing.add(c["name"])
            picked_units.append(c)

    # ---- 指令卡筛选 ----
    picked_orders = []
    order_count = {}
    for r in rows:
        if r["type"] != "order" or r["faction"] not in NATION_MAP:
            continue
        if r["title en-EN"].strip().upper() in used_en:
            continue
        nat = NATION_MAP[r["faction"]]
        if order_count.get(nat, 0) >= ORDER_QUOTA.get(nat, 0):
            continue
        text = r["text en-EN"].strip()
        for pat, mk in ORDER_PATTERNS:
            m = pat.match(text)
            if m:
                fname, desc = mk(m)
                name = clean_name(r)
                if name in existing:
                    break
                try:
                    cost = int(r["kredits"])
                except ValueError:
                    break
                picked_orders.append({
                    "name": name, "nation": nat, "cost": cost,
                    "factory": fname, "desc": desc,
                    "rarity": RARITY_MAP.get(r["rarity"]),
                })
                existing.add(name)
                order_count[nat] = order_count.get(nat, 0) + 1
                break

    total_new = len(picked_units) + len(picked_orders)
    print(f"新卡: 单位 {len(picked_units)} + 指令 {len(picked_orders)} = {total_new}")
    print("各指令:", order_count)
    assert total_new + 76 > 200, "总数不足 200"

    # ---- 生成代码 ----
    lines = []
    for c in picked_units:
        kw = ", ".join(f'"{k}"' for k in c["kw"])
        args = f'UnitCard("{c["name"]}", "{c["nation"]}", {c["cost"]}, {c["atk"]}, {c["dfn"]}, [{kw}], "{c["type"]}"'
        traits = []
        if c["dying"]:
            traits.append('"dying_hq": 2')
        if traits:
            args += f", traits={{{', '.join(traits)}}}"
        if c["rarity"]:
            args += f', rarity="{c["rarity"]}"'
        lines.append("        " + args + "),")
    for c in picked_orders:
        args = (f'OrderCard("{c["name"]}", "{c["nation"]}", {c["cost"]}, '
                f'{c["factory"]}, "{c["desc"]}"')
        if c["rarity"]:
            args += f', rarity="{c["rarity"]}"'
        lines.append("        " + args + "),")

    extra_block = (
        "\n\n# ---------------------------------------------------------------- 扩充卡池（数据取自原版 CSV，效果用通用机制近似）\n"
        "EXTRA_CARDS = [\n"
        "    # ---- 单位 ----\n    " + "\n    ".join(lines[:len(picked_units)]) +
        "\n    # ---- 指令 ----\n    " + "\n    ".join(lines[len(picked_units):]) +
        "\n]\n"
    )

    factories = '''

def mk_deal_hq(amount):
    """通用指令: 对敌方总部造成 X 点伤害"""
    def eff(game, caster):
        game.log(f"  精准打击：敌方总部受到 {amount} 点伤害！")
        game.damage_hq(game.opponent_of(caster), amount)
    return eff


def mk_deal_all(amount):
    """通用指令: 对所有敌方单位造成 X 点伤害"""
    def eff(game, caster):
        game.log(f"  火力覆盖：所有敌方单位受到 {amount} 点伤害！")
        for u in list(game.opponent_of(caster).board):
            if u.defense > 0:
                game.damage_unit(u, amount)
    return eff


def mk_draw(n):
    """通用指令: 抽 N 张牌"""
    def eff(game, caster):
        game.draw_cards(caster, n)
        game.log(f"  抽了 {n} 张牌。")
    return eff


def mk_destroy_random():
    """通用指令: 消灭一个随机敌方单位"""
    def eff(game, caster):
        foe = game.opponent_of(caster)
        live = [u for u in foe.board
                if u.defense > 0 and not u.traits.get("untargetable")]
        if live:
            t = random.choice(live)
            game.log(f"  精确清除：{t.name} 被消灭！")
            game.destroy_unit(t)
        else:
            game.log("  场上没有目标，效果落空。")
    return eff


def _destroy_pick(game, caster, filt, desc):
    foe = game.opponent_of(caster)
    live = [u for u in foe.board
            if u.defense > 0 and not u.traits.get("untargetable") and filt(u)]
    if live:
        t = max(live, key=lambda x: (x.attack, x.defense))
        game.log(f"  {desc}：{t.name} 被消灭！")
        game.destroy_unit(t)
    else:
        game.log(f"  没有符合条件的敌方单位，效果落空。")


def mk_destroy_damaged():
    """通用指令: 消灭一个已受损的敌方单位"""
    def eff(game, caster):
        _destroy_pick(game, caster, lambda u: u.defense < u.max_defense,
                      "重点摧毁")
    return eff


def mk_destroy_cost_le(cost):
    """通用指令: 消灭费用不大于 X 的敌方单位"""
    def eff(game, caster):
        _destroy_pick(game, caster, lambda u: u.card.cost <= cost,
                      f"低费清除（费用≤{cost}）")
    return eff

'''

    src = io.open(SRC, encoding="utf-8").read()
    if "EXTRA_CARDS" in src:
        raise SystemExit("kards.py 已包含 EXTRA_CARDS，请勿重复注入")
    n1 = src.count("\ndef card_database():")
    if n1 != 1:
        raise SystemExit(f"card_database 锚点 {n1} 处")
    src = src.replace("\ndef card_database():", factories + extra_block + "\ndef card_database():")
    old_ret = "    ]\n    return {c.name: c for c in db}"
    n2 = src.count(old_ret)
    if n2 != 1:
        raise SystemExit(f"return 锚点 {n2} 处")
    src = src.replace(old_ret, "    ]\n    db.extend(EXTRA_CARDS)\n    return {c.name: c for c in db}")
    old_doc = '''    """卡池：61 张卡对齐原版 KARDS 数据（费用/攻防/关键词/效果/稀有度），
    效果描述为自拟简洁中文；个别无法映射的原版机制用近似实现并注明。"""'''
    if old_doc in src:
        src = src.replace(old_doc, '''    """卡池：核心 61 张对齐原版 KARDS 数据（费用/攻防/关键词/效果/稀有度），
    EXTRA_CARDS 为扩充卡（数据同样取自原版 CSV；效果用通用机制近似实现）。"""''')

    ast.parse(src)
    io.open(SRC, "w", encoding="utf-8", newline="").write(src)
    print("注入完成")

    # ---- 验证 ----
    import importlib
    importlib.reload(kards)
    db = kards.card_database()
    print("新总卡数:", len(db))
    from collections import Counter
    print(Counter(c.nation for c in db.values()))
    print(Counter(c.kind for c in db.values()))
    print(Counter(c.rarity for c in db.values()))


if __name__ == "__main__":
    main()
