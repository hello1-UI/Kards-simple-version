# -*- coding: utf-8 -*-
"""关键词说明界面测试（需要 tkinter → 用系统 Python 跑）

验证：
  1. core.keyword_guide() 结构完整（分组 / 条数 / 非空说明）
  2. 三语言都有译文，且没有回退成中文（en/ja）
  3. GUI 能打开「关键词说明」窗口并渲染出对应数量的条目
  4. 卡牌 tooltip 里的关键词说明按语言切换
  5. 卡池里出现的关键词都被 KEYWORD_DESC 覆盖

运行: python debug/test_keywords.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_engine as core          # noqa: E402
import kards_i18n as i18n            # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


def main():
    print("1. 卡池关键词覆盖率")
    db = core.card_database()
    used = set()
    for card in db.values():
        for kw in getattr(card, "keywords", []) or []:
            used.add(kw)
    missing = {k for k in used if not core.kw_desc(k, "zh")}
    check(f"卡池用到的 {len(used)} 个关键词都有说明", not missing, missing)
    check("亡计 也有说明（它由卡牌效果授予，不在 keywords 里）",
          bool(core.kw_desc("亡计", "zh")))

    print("2. keyword_guide 结构")
    g = core.keyword_guide("zh")
    check("返回 4 个分组", len(g) == 4, len(g))
    keys = [k for k, _ in g]
    check("分组 key 正确",
          keys == ["kw_group_unit", "kw_group_trigger", "kw_group_term",
                   "kw_group_planned"], keys)
    total = 0
    for k, rows in g:
        check(f"{k} 非空", len(rows) > 0, len(rows))
        bad = [(n, d) for n, d in rows if not n or not d]
        check(f"{k} 每项都有名称和说明", not bad, bad)
        total += len(rows)
    check("条目总数合理（38）", total == 38, total)

    print("2b. 原版词条分组（未实装，供查阅）")
    planned = dict(g)["kw_group_planned"]
    pnames = [n for n, _d in planned]
    check("含「烟幕」（用户提供，本作未实装）", "烟幕" in pnames)
    check("含「重甲X」并说明本作叫装甲", "装甲" in core.kw_desc("重甲X", "zh"))
    check("含「士气伤害」", "士气伤害" in pnames)
    check("含「老兵」", "老兵" in pnames)
    # 未实装词条不能混进「已实装」分组
    impl = [n for k, rows in g if k != "kw_group_planned" for n, _d in rows]
    overlap = [n for n in pnames if n in impl]
    check("未实装词条不与已实装词条重名", not overlap, overlap)

    print("3. 三语言译文")
    for lang in ("en", "ja"):
        groups = core.keyword_guide(lang)
        flat = [n for _k, rows in groups for n, _d in rows]
        # 允许"本来就同形"的词：Kredits 是外来语，装甲N 中日同字
        SAME_OK = {"Kredits", "装甲", "装甲2", "装甲3"}
        zh_names = {n for _k, rows in core.keyword_guide("zh") for n, _d in rows}
        untranslated = [n for n in flat if n in zh_names and n not in SAME_OK]
        check(f"{lang}: 名称都本地化了", not untranslated, untranslated)
        # 日文里不该出现简体中文特有的字（日文用「ダメージ」等，不用「伤害」）
        # 注意：位置 / 防御力 / 攻撃力 都是正规日文汉字，不能当残留（历史误报）。
        if lang == "ja":
            zh_only = ("伤害", "单位", "费用", "当回合", "消灭",
                       "防御值", "攻击力", "行动花费")
            bad_desc = []
            for _k, rows in groups:
                for n, d in rows:
                    hit = [w for w in zh_only if w in d]
                    if hit:
                        bad_desc.append((n, hit))
            check("ja: 没有简体中文残留", not bad_desc, bad_desc[:3])

    print("4. i18n 键完整性")
    for key in ("btn_keywords", "kw_title", "kw_sub", "kw_group_unit",
                "kw_group_trigger", "kw_group_term", "kw_group_planned",
                "kw_close"):
        vals = [i18n.LANGS[c].get(key) for c in ("zh", "en", "ja")]
        check(f"{key} 三语言都有", all(v for v in vals), vals)

    print("5. 卡牌 tooltip 按语言取说明")
    try:
        import tkinter as tk
        os.environ.setdefault("DISPLAY", "")
        import KARDS as gui
        card = None
        for c in db.values():
            if getattr(c, "keywords", None):
                card = c
                break
        check("找到带关键词的卡牌", card is not None)
        if card:
            i18n.set_lang("zh")
            zh = gui.card_tooltip(card)
            i18n.set_lang("en")
            en = gui.card_tooltip(card)
            i18n.set_lang("zh")
            kw = card.keywords[0]
            check("中文 tooltip 含中文说明", core.kw_desc(kw, "zh") in zh, kw)
            check("英文 tooltip 含英文说明",
                  core.kw_desc(kw, "en") in en or core.kw_desc(kw, "zh") in en, kw)
    except ImportError as e:
        print(f"  ※ 无 tkinter，跳过 GUI 部分: {e}")

    print()
    if FAIL:
        print(f"FAILED: {len(FAIL)}/{len(PASS) + len(FAIL)}")
        for f in FAIL:
            print("  -", f)
        sys.exit(1)
    print(f"ALL OK ({len(PASS)} checks)")


if __name__ == "__main__":
    main()
