# -*- coding: utf-8 -*-
"""把 kards_engine.card_database() 导出为 JSON，供 Java 版（Android）数据驱动建卡。

用法:
    python debug/export_cards_json.py            # 默认输出 android/app/src/main/assets/cards.json
    python debug/export_cards_json.py <输出路径>

效果函数映射:
    effect_xxx  -> id "xxx"
    mk_xxx(...) 闭包 -> id "xxx"，参数从闭包单元取
输出 schema 见 ROOT["meta"]["schema"]。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kards_engine as K  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(ROOT, "android", "app", "src", "main", "assets", "cards.json")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MK_PARAMS = {
    # mk_ 工厂 qualname 前缀 -> (效果 id, [参数名])
    "mk_deal_hq": ("deal_hq", ["amount"]),
    "mk_deal_all": ("deal_all", ["amount"]),
    "mk_draw": ("draw", ["n"]),
    "mk_advance_ally": ("advance_ally", []),
    "mk_rally_ally": ("rally_ally", []),
    "mk_destroy_random": ("destroy_random", []),
    "mk_destroy_damaged": ("destroy_damaged", []),
    "mk_destroy_cost_le": ("destroy_cost_le", ["cost"]),
}


def effect_spec(fn):
    """把 Python 效果函数转成 {id, params}。"""
    if fn is None:
        return None
    qual = getattr(fn, "__qualname__", "")
    name = getattr(fn, "__name__", "")
    if name.startswith("effect_"):
        return {"id": name[len("effect_"):], "params": {}}
    factory = qual.split(".<locals>")[0] if ".<locals>" in qual else name
    if factory in MK_PARAMS:
        eid, pnames = MK_PARAMS[factory]
        cells = {v: c.cell_contents
                 for v, c in zip(fn.__code__.co_freevars, fn.__closure__ or ())}
        params = {}
        for pn in pnames:
            v = cells.get(pn)
            if isinstance(v, tuple):
                v = list(v)
            params[pn] = v
        return {"id": eid, "params": params}
    raise SystemExit(f"未知效果函数: name={name!r} qualname={qual!r}")


def clean_traits(traits):
    """traits 一般是 JSON 兼容标量/列表/字典；vet 里嵌 dict 也兼容。"""
    out = {}
    for k, v in (traits or {}).items():
        if isinstance(v, tuple):
            v = list(v)
        out[k] = v
    return out


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    db = K.card_database()
    cards = []
    for name in sorted(db):
        c = db[name]
        entry = {"kind": c.kind, "name": c.name, "nation": c.nation,
                 "cost": c.cost, "rarity": c.rarity}
        if c.kind == "unit":
            entry.update({
                "attack": c.attack, "defense": c.defense,
                "keywords": list(c.keywords), "unitType": c.unit_type,
                "operate": int(getattr(c, "operate", 0)),
                "traits": clean_traits(c.traits),
            })
        elif c.kind == "order":
            entry.update({"desc": c.desc, "effect": effect_spec(c.effect)})
        else:  # counter
            entry.update({"desc": c.desc, "trigger": c.trigger,
                          "effect": effect_spec(c.effect)})
        cards.append(entry)

    hqs = [{"nation": n, "name": c.name, "hp": c.hp,
            "perk": c.perk, "perkDesc": c.perk_desc}
           for n, c in K.HQ_CARDS.items()]

    data = {
        "meta": {
            "schema": 1,
            "source": "kards_engine.card_database() @ v1.6.3.12",
            "counts": {"cards": len(cards), "hqs": len(hqs)},
            "rules": {
                "deckSize": K.DECK_SIZE, "handLimit": K.HAND_LIMIT,
                "startHand": K.START_HP, "boardSize": K.BOARD_SIZE,
                "rearSlots": K.REAR_SLOTS, "frontlineSlots": K.FRONTLINE_SLOTS,
                "counterSlots": K.COUNTER_SLOTS,
                "cpSlotGrowthCap": K.CP_SLOT_GROWTH_CAP,
                "cpSlotMax": K.CP_SLOT_MAX,
                "allyLimit": K.ALLY_LIMIT,
                "mainNations": list(K.MAIN_NATIONS),
                "allyNations": list(K.ALLY_NATIONS),
                "rarityCopies": K.RARITY_COPIES,
                "rangedTypes": list(K.RANGED_TYPES),
                "hqHp": K.HQ_HP,
            },
        },
        "hqs": hqs,
        "cards": cards,
        "keywords": K.KEYWORD_DESC,
        "keywordsI18n": {k: v for k, v in K.KEYWORD_I18N.items()},
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=False)
    print(f"导出 {len(cards)} 张卡 / {len(hqs)} 个总部 -> {out_path}")
    kinds = {}
    for c in cards:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    print("构成:", kinds)


if __name__ == "__main__":
    main()
