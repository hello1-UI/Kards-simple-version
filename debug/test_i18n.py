# -*- coding: utf-8 -*-
"""i18n 一致性测试：三套语言键集合 / 占位符 / 缺失回退

防止以后加文案时只改中文、忘了 en/ja（会静默回退成中文）。
这类问题不会崩，但英文/日文玩家会看到中文界面，必须用测试锁住。

用法: python debug/test_i18n.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kards_i18n as i18n  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name
          + (f"  {detail}" if detail else ""))


def main():
    L = i18n.LANGS
    ks = {lang: set(pack) for lang, pack in L.items()}
    allk = set().union(*ks.values())

    print("\n=== 1. 三套语言键集合一致 ===")
    missing = [(k, [l for l in L if k not in ks[l]])
               for k in sorted(allk) if any(k not in ks[l] for l in L)]
    check("无缺键（每种语言都有全部键）", not missing,
          f"缺 {len(missing)} 个: {missing[:5]}" if missing else "")
    check("语言数量为 3", len(L) == 3, str(list(L)))
    counts = {l: len(ks[l]) for l in L}
    check("各语言键数相同", len(set(counts.values())) == 1, str(counts))
    check("键数 > 100（防止误清空）", len(allk) > 100, f"共 {len(allk)} 键")

    print("\n=== 2. f-string 占位符一致 ===")
    ph = lambda s: set(re.findall(r"\{(\w+)\}", s))
    diffs = []
    for k in sorted(allk):
        if k not in ks["zh"]:
            continue
        base = ph(L["zh"][k])
        for lang in L:
            if lang == "zh" or k not in ks[lang]:
                continue
            if ph(L[lang][k]) != base:
                diffs.append((k, lang, sorted(ph(L[lang][k]) ^ base)))
    check("占位符三语言一致", not diffs, str(diffs[:5]))

    print("\n=== 3. 文案非空 / 类型正确 ===")
    empties = [(l, k) for l in L for k in ks[l] if not isinstance(L[l][k], str)]
    check("所有值都是字符串", not empties, str(empties[:5]))
    blanks = [(l, k) for l in L for k in ks[l] if not L[l][k].strip()]
    check("无空文案", not blanks, str(blanks[:5]))

    print("\n=== 4. t() 的缺键回退行为 ===")
    old = i18n._current["lang"]
    try:
        i18n._current["lang"] = "en"
        check("缺键回退到中文（不崩）",
              i18n.t("__not_a_real_key__") == "__not_a_real_key__")
        i18n._current["lang"] = "zh"
        check("中文键可正常取用",
              i18n.t("ai_concede_log").startswith("  🏳"))
        i18n._current["lang"] = "en"
        v = i18n.t("ai_concede_log")
        check("英文键已翻译（不是中文回退）", "AI" in v and "🏳" in v, v[:40])
        i18n._current["lang"] = "ja"
        v = i18n.t("ai_concede_reason", reason="テスト")
        check("日文带参格式化正常", "テスト" in v, v[:40])
    finally:
        i18n._current["lang"] = old

    print("\n=== 5. settings_language 三语言齐备（历史缺键） ===")
    for lang in L:
        check(f"{lang} 有 settings_language",
              "settings_language" in ks[lang],
              L[lang].get("settings_language", "<缺失>"))

    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
