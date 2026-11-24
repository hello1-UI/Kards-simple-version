# -*- coding: utf-8 -*-
"""生成随包分发的内置 UI 模板（models/*.json）

为什么用脚本而不是手写 12 份 JSON：
  * 21 个颜色键 × 12 套，手抄必错（少一个键就被 normalize 回落成预设色，
    表现是"某个地方颜色不对"，很难查）；
  * 统一在这里跑一遍对比度自检（正文/次要文字在底色上要看得清），
    生成的模板直接可用，不需要人眼一套套验。

产物格式与 settings → 外观 →「导出」出来的 JSON 完全一致，
所以玩家也能把这些文件直接「导入」到自己的模板里。

用法: python debug/gen_models.py [--check]
      --check 只校验不写盘（CI/回归用）
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "models")
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_theme as theme  # noqa: E402

# 21 个键的骨架，顺序即落盘顺序（与 BASE_KEYS 一致，diff 友好）
K = theme.BASE_KEYS

MODELS = [
    # ---------------------------------------------------------------- 暗色
    dict(
        slug="nordic-night",
        name="北境夜航", name_en="Nordic Night", name_ja="北極夜航",
        base="frontline", light=False,
        accent="#6fb3d2",
        bg="#101820", bg_alt="#0b1218", panel="#16222c", panel_alt="#1d2c38",
        card="#22333f", card_dim="#1a2833",
        text="#e4eef4", dim="#9db0bd", mute="#6d818f",
        border="#2a3c49", border_hi="#3d5464",
        red="#d96a6a", green="#6fbf9a", gold="#dcb463",
        btn="#33454f",
        row_bg="#131e26", row_edge="#22323d", mid_bg="#121c24",
        log_bg="#0a1116", hand_area="#16222c",
    ),
    dict(
        slug="desert-fox",
        name="沙漠之狐", name_en="Desert Fox", name_ja="砂漠の狐",
        base="desert", light=False,
        accent="#d8a14e",
        bg="#1f1a13", bg_alt="#17130e", panel="#2a241a", panel_alt="#372e21",
        card="#413626", card_dim="#322a1e",
        text="#f2e9d8", dim="#c0ad90", mute="#8d7c62",
        border="#4a3d2a", border_hi="#655239",
        red="#d76a4c", green="#94ad72", gold="#e3bd63",
        btn="#55462f",
        row_bg="#241e16", row_edge="#3b3223", mid_bg="#221c14",
        log_bg="#15110c", hand_area="#2a241a",
    ),
    dict(
        slug="blood-iron",
        name="血与铁", name_en="Blood & Iron", name_ja="血と鉄",
        base="frontline", light=False,
        accent="#c2453f",
        bg="#14100f", bg_alt="#0d0a09", panel="#1e1817", panel_alt="#2a2220",
        card="#332a27", card_dim="#251e1c",
        text="#ece1db", dim="#b3a09a", mute="#806c66",
        border="#3a2d2a", border_hi="#523f3a",
        red="#e05555", green="#6fae78", gold="#d6a75a",
        btn="#43332e",
        row_bg="#1a1413", row_edge="#2c2220", mid_bg="#181210",
        log_bg="#0c0908", hand_area="#1e1817",
    ),
    dict(
        slug="pacific-dawn",
        name="太平洋黎明", name_en="Pacific Dawn", name_ja="太平洋の夜明け",
        base="steel", light=False,
        accent="#e08a5a",
        bg="#0e1b1d", bg_alt="#091415", panel="#152629", panel_alt="#1d3336",
        card="#254044", card_dim="#1b3134",
        text="#e2eef0", dim="#9ab2b4", mute="#6b8587",
        border="#284345", border_hi="#3a5f61",
        red="#dd6b62", green="#5fb39a", gold="#e0b96a",
        btn="#2d4a4c",
        row_bg="#112021", row_edge="#234042", mid_bg="#101d1e",
        log_bg="#081112", hand_area="#152629",
    ),
    dict(
        slug="radio-silence",
        name="无线电静默", name_en="Radio Silence", name_ja="無線封止",
        base="olive", light=False,
        accent="#7fc48a",
        bg="#0f1410", bg_alt="#090d09", panel="#172017", panel_alt="#1f2b1f",
        card="#283628", card_dim="#1e2a1e",
        text="#dfe9d8", dim="#a3b49a", mute="#72856b",
        border="#2b3a29", border_hi="#405441",
        red="#cf6055", green="#86c46a", gold="#d2b45c",
        btn="#3a4a36",
        row_bg="#121a12", row_edge="#263424", mid_bg="#111711",
        log_bg="#080c08", hand_area="#172017",
    ),
    dict(
        slug="snowfield",
        name="雪原白狼", name_en="Snowfield", name_ja="雪原の白狼",
        base="arctic", light=False,
        accent="#9fb8d6",
        bg="#171b21", bg_alt="#10141a", panel="#1f252c", panel_alt="#283039",
        card="#323b47", card_dim="#262e38",
        text="#eaf0f6", dim="#a9b6c4", mute="#798695",
        border="#313b47", border_hi="#47535f",
        red="#d57373", green="#7cbc9a", gold="#dcc17c",
        btn="#3b4550",
        row_bg="#1a1f26", row_edge="#2c3541", mid_bg="#181d24",
        log_bg="#0e1218", hand_area="#1f252c",
    ),
    dict(
        slug="violet-hq",
        name="紫罗兰司令部", name_en="Violet HQ", name_ja="紫の司令部",
        base="midnight", light=False,
        accent="#a98ada",
        bg="#17131f", bg_alt="#100d17", panel="#201a2b", panel_alt="#2a2238",
        card="#352b45", card_dim="#292136",
        text="#ece5f5", dim="#b6a8c9", mute="#857596",
        border="#362b47", border_hi="#4d3d63",
        red="#d96a7e", green="#74b891", gold="#dcb768",
        btn="#423455",
        row_bg="#191420", row_edge="#2c2340", mid_bg="#171220",
        log_bg="#0c0913", hand_area="#201a2b",
    ),
    dict(
        slug="sakura-front",
        name="樱花前线", name_en="Sakura Front", name_ja="桜前線",
        base="frontline", light=False,
        accent="#e08aa8",
        bg="#1b1418", bg_alt="#140f12", panel="#251b20", panel_alt="#31232a",
        card="#3d2c34", card_dim="#2f2328",
        text="#f2e4e9", dim="#c5aab4", mute="#94777f",
        border="#3f2c34", border_hi="#5a4049",
        red="#dd6577", green="#7cb992", gold="#ddb868",
        btn="#4a3840",
        row_bg="#1e161a", row_edge="#34262c", mid_bg="#1c1518",
        log_bg="#100c0e", hand_area="#251b20",
    ),
    # ---------------------------------------------------------------- 亮色
    dict(
        slug="wartime-archive",
        name="战时档案", name_en="Wartime Archive", name_ja="戦時档案",
        base="paper", light=True,
        accent="#8a6a3a",
        bg="#ede6d6", bg_alt="#e2d9c6", panel="#faf6ec", panel_alt="#f2ecdf",
        card="#fffdf7", card_dim="#e8e0cf",
        text="#2b2416", dim="#5d5342", mute="#8a7f6b",
        border="#d2c8b2", border_hi="#b3a68c",
        red="#a83b2e", green="#3f6f3a", gold="#8a6a1e",
        btn="#ddd3bf",
        row_bg="#f4eee0", row_edge="#d2c8b2", mid_bg="#ece5d5",
        log_bg="#fbf8f0", hand_area="#faf6ec",
    ),
    dict(
        slug="snow-map",
        name="雪地地图", name_en="Snow Map", name_ja="雪原の地図",
        base="paper", light=True,
        accent="#3f6f9f",
        bg="#eef3f7", bg_alt="#e2eaf1", panel="#ffffff", panel_alt="#f5f9fc",
        card="#ffffff", card_dim="#e6edf3",
        text="#1f2a35", dim="#52616f", mute="#7f8d9a",
        border="#cdd9e3", border_hi="#adbecd",
        red="#b3403f", green="#2f7450", gold="#9a6f1c",
        btn="#dde7ef",
        row_bg="#f4f8fb", row_edge="#cdd9e3", mid_bg="#eaf1f7",
        log_bg="#fbfdff", hand_area="#ffffff",
    ),
    dict(
        slug="frontline-briefing",
        name="前线简报", name_en="Frontline Briefing", name_ja="前線ブリーフィング",
        base="paper", light=True,
        accent="#5f7a4a",
        bg="#e9e7de", bg_alt="#dedbd0", panel="#f8f7f1", panel_alt="#efeee5",
        card="#fffefa", card_dim="#e6e3d7",
        text="#26271f", dim="#55584a", mute="#828575",
        border="#cbc8b8", border_hi="#a9a795",
        red="#a63f35", green="#3c6b39", gold="#8c6a22",
        btn="#d9d6c6",
        row_bg="#f1efe6", row_edge="#cbc8b8", mid_bg="#e7e4d9",
        log_bg="#faf9f3", hand_area="#f8f7f1",
    ),
    dict(
        slug="dusk-gazette",
        name="黄昏报摊", name_en="Dusk Gazette", name_ja="夕暮れの新聞台",
        base="paper", light=True,
        accent="#a85a3a",
        bg="#f2e6dc", bg_alt="#e8d8cb", panel="#fdf6ef", panel_alt="#f6ebe0",
        card="#fffaf5", card_dim="#eddfd2",
        text="#2f231c", dim="#5f4e43", mute="#8e7b6d",
        border="#dbc7b6", border_hi="#c0a894",
        red="#a83a32", green="#3f6f43", gold="#95681f",
        btn="#e6d3c2",
        row_bg="#f7ece1", row_edge="#dbc7b6", mid_bg="#f0e3d7",
        log_bg="#fdf8f2", hand_area="#fdf6ef",
    ),
]


def build_payload(m):
    colors = {k: m[k].lower() for k in K}
    return {
        "version": 1,
        "name": m["name"],
        "name_en": m["name_en"],
        "name_ja": m["name_ja"],
        "base": m["base"] if m["base"] in theme.PRESETS else theme.DEFAULT_PRESET,
        "light": bool(m["light"]),
        "colors": colors,
    }


def check_payload(slug, payload):
    """对比度自检：模板不能出现"看不清的字"，否则玩家一眼就觉得坏了。"""
    problems = []
    p = theme.normalize_preset(payload)
    pal = theme._finalize(p, None)
    for fg_key, bg_key, minimum in (("text", "bg", 7.0),
                                    ("dim", "bg", 4.5),
                                    ("mute", "bg", 2.6),
                                    ("text", "panel", 7.0),
                                    ("dim", "panel", 4.5),
                                    ("text", "card", 7.0),
                                    ("dim", "card", 4.5),
                                    ("text", "row_bg", 7.0)):
        ratio = theme.contrast(pal[fg_key], pal[bg_key])
        if ratio < minimum:
            problems.append("%s/%s %.2f < %.1f" % (fg_key, bg_key, ratio, minimum))
    light = bool(payload["light"])
    if light and theme.luminance(pal["bg"]) < 0.55:
        problems.append("标记为亮色但底色偏暗（%s）" % pal["bg"])
    if (not light) and theme.luminance(pal["bg"]) > 0.35:
        problems.append("标记为暗色但底色偏亮（%s）" % pal["bg"])
    if problems:
        print("  [!!] %-20s %s" % (slug, "; ".join(problems)))
    return problems


def main():
    only_check = "--check" in sys.argv
    slugs = set()
    bad = 0
    for m in MODELS:
        missing = [k for k in K if k not in m]
        if missing:
            print("  [!!] %s 缺键: %s" % (m["slug"], missing))
            bad += 1
            continue
        if m["slug"] in slugs:
            print("  [!!] 重复 slug: %s" % m["slug"])
            bad += 1
        slugs.add(m["slug"])
        payload = build_payload(m)
        bad += len(check_payload(m["slug"], payload))
        if only_check:
            continue
        os.makedirs(OUT_DIR, exist_ok=True)
        path = os.path.join(OUT_DIR, m["slug"] + ".json")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    print("模板 %d 套，检查失败 %d 项 → %s" %
          (len(MODELS), bad, "只校验" if only_check else OUT_DIR))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
