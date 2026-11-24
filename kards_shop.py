# -*- coding: utf-8 -*-
"""商店：头像 / 桌饰 / 总部皮肤（纯数据 + 本地存档，无 GUI）

设计要点
--------------------------------------------------------------------------
· 只卖**外观**，不卖战力 —— 付费/攒币不影响对局平衡。
· 库存按自然日轮换：同一天所有人看到同一批（种子 = 日期），
  每天 2 头像 + 2 桌饰 + 2 总部；当天首次刷新免费，之后 80 金重摇。
· 存档按玩家隔离（游客统一 guest），与货币同一套 wallet key，
  换账号/换后端不会串档。
· 外观数据全部是**颜色 + 多边形**：tkinter（Canvas）与 pygame 共用一份，
  不依赖美术资源（项目里本来也没有卡图/总部图，全是过程式绘制）。
· 装备即生效：cosmetics() 返回已装备的商品，渲染层每帧/每次重绘时读它。
"""
import json
import math
import os
import random
import time

import kards_account as account

CATEGORIES = ("avatar", "table", "hq")

_STOCK_PER_CAT = 2              # 每天每类上架几件
REROLL_COST = 80                # 当天第二次起的重摇价格（金）
FREE_REROLLS = 1                # 每天免费刷新次数

_FILE = os.path.join(account.DATA_DIR, "shop.json")


# ---------------------------------------------------------------- 徽记形状
# 全部用 0~1 单位坐标描述，渲染层按画布尺寸缩放即可。
# 这样同一份形状既能在 tkinter Canvas 上画，也能在 pygame 的 polygon 上画。
def _star_pts(cx=0.5, cy=0.5, ro=0.46, ri=0.19, n=5):
    pts = []
    for i in range(n * 2):
        ang = -math.pi / 2 + i * math.pi / n
        r = ro if i % 2 == 0 else ri
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


EMBLEMS = {
    "star": [_star_pts()],
    "bolt": [[(0.56, 0.04), (0.24, 0.56), (0.46, 0.56), (0.36, 0.96),
              (0.74, 0.40), (0.52, 0.40)]],
    "shield": [[(0.50, 0.05), (0.90, 0.20), (0.85, 0.60), (0.50, 0.95),
                (0.15, 0.60), (0.10, 0.20)]],
    "wing": [[(0.46, 0.30), (0.92, 0.16), (0.92, 0.40), (0.46, 0.50)],
             [(0.46, 0.50), (0.86, 0.46), (0.86, 0.66), (0.46, 0.70)],
             [(0.46, 0.70), (0.78, 0.68), (0.74, 0.86), (0.46, 0.88)]],
    "crown": [[(0.10, 0.78), (0.14, 0.28), (0.31, 0.52), (0.50, 0.20),
               (0.69, 0.52), (0.86, 0.28), (0.90, 0.78)]],
    "anchor": [[(0.42, 0.16), (0.58, 0.16), (0.58, 0.54), (0.88, 0.54),
                (0.88, 0.68), (0.60, 0.68), (0.60, 0.88), (0.40, 0.88),
                (0.40, 0.68), (0.12, 0.68), (0.12, 0.54), (0.42, 0.54)]],
    "cross": [[(0.40, 0.08), (0.60, 0.08), (0.60, 0.40), (0.92, 0.40),
               (0.92, 0.60), (0.60, 0.60), (0.60, 0.92), (0.40, 0.92),
               (0.40, 0.60), (0.08, 0.60), (0.08, 0.40), (0.40, 0.40)]],
    "hex": [[(0.50, 0.06), (0.88, 0.28), (0.88, 0.72), (0.50, 0.94),
             (0.12, 0.72), (0.12, 0.28)]],
}


def emblem_polygons(kind):
    """徽记形状（单位坐标多边形列表）；未知类型退回菱形，绝不返回空。"""
    polys = EMBLEMS.get(kind)
    if polys:
        return polys
    return [[(0.50, 0.10), (0.90, 0.50), (0.50, 0.90), (0.10, 0.50)]]


# ---------------------------------------------------------------- 商品目录
# name 直接内嵌三语（商品名是数据，不是界面文案；省得 i18n 里塞 60 条键）
CATALOG = [
    # ---- 头像：环色 + 填充色 + 徽记 ----
    {"id": "av_star", "cat": "avatar", "price": 400, "cur": "gold",
     "ring": "#e8c164", "fill": "#3a2f18", "emblem": "star",
     "name": "星徽", "name_en": "Star Crest", "name_ja": "星の紋章"},
    {"id": "av_bolt", "cat": "avatar", "price": 500, "cur": "gold",
     "ring": "#7fc4ff", "fill": "#16283a", "emblem": "bolt",
     "name": "雷霆", "name_en": "Thunderbolt", "name_ja": "雷光"},
    {"id": "av_shield", "cat": "avatar", "price": 500, "cur": "gold",
     "ring": "#9fb3c8", "fill": "#1c2430", "emblem": "shield",
     "name": "铁盾", "name_en": "Iron Shield", "name_ja": "鉄の盾"},
    {"id": "av_wing", "cat": "avatar", "price": 700, "cur": "gold",
     "ring": "#e0d3a8", "fill": "#2b2618", "emblem": "wing",
     "name": "双翼", "name_en": "Wings", "name_ja": "双翼"},
    {"id": "av_crown", "cat": "avatar", "price": 8, "cur": "diamonds",
     "ring": "#f0d060", "fill": "#3a2c10", "emblem": "crown",
     "name": "王冠", "name_en": "Crown", "name_ja": "王冠"},
    {"id": "av_anchor", "cat": "avatar", "price": 6, "cur": "diamonds",
     "ring": "#8fd6c0", "fill": "#142a26", "emblem": "anchor",
     "name": "铁锚", "name_en": "Anchor", "name_ja": "錨"},
    {"id": "av_cross", "cat": "avatar", "price": 600, "cur": "gold",
     "ring": "#d8d8d8", "fill": "#2a2a2a", "emblem": "cross",
     "name": "白十字", "name_en": "White Cross", "name_ja": "白十字"},
    {"id": "av_hex", "cat": "avatar", "price": 10, "cur": "diamonds",
     "ring": "#c08bff", "fill": "#241832", "emblem": "hex",
     "name": "棱光", "name_en": "Prism", "name_ja": "プリズム"},

    # ---- 桌饰：棋盘行的底色 / 边线 / 中线 ----
    {"id": "tb_forest", "cat": "table", "price": 600, "cur": "gold",
     "bg": "#16241b", "row": "#1d3226", "edge": "#2f5a3d",
     "mid": "#203a2a", "accent": "#4f9e6a",
     "name": "森林绿", "name_en": "Forest", "name_ja": "森林"},
    {"id": "tb_desert", "cat": "table", "price": 600, "cur": "gold",
     "bg": "#241d13", "row": "#332c1c", "edge": "#6b5638",
     "mid": "#3a3220", "accent": "#c9a227",
     "name": "沙漠黄", "name_en": "Desert", "name_ja": "砂漠"},
    {"id": "tb_night", "cat": "table", "price": 750, "cur": "gold",
     "bg": "#101725", "row": "#1a2338", "edge": "#2f4468",
     "mid": "#1f2a42", "accent": "#4a7bd0",
     "name": "夜战蓝", "name_en": "Night Ops", "name_ja": "夜戦"},
    {"id": "tb_snow", "cat": "table", "price": 750, "cur": "gold",
     "bg": "#1a2126", "row": "#27303a", "edge": "#4a5a66",
     "mid": "#2c3844", "accent": "#9fc7e0",
     "name": "雪原白", "name_en": "Snowfield", "name_ja": "雪原"},
    {"id": "tb_urban", "cat": "table", "price": 5, "cur": "diamonds",
     "bg": "#1b1b20", "row": "#2a2a30", "edge": "#4a4a52",
     "mid": "#303038", "accent": "#8b8b98",
     "name": "城市灰", "name_en": "Urban Gray", "name_ja": "市街戦"},
    {"id": "tb_blood", "cat": "table", "price": 5, "cur": "diamonds",
     "bg": "#241212", "row": "#351c1c", "edge": "#6b2a2a",
     "mid": "#3d2020", "accent": "#c0392b",
     "name": "血土红", "name_en": "Blood Soil", "name_ja": "血染め"},

    # ---- 总部：只改我方总部卡（对手那边各看各的） ----
    {"id": "hq_steel", "cat": "hq", "price": 700, "cur": "gold",
     "fill": "#232c33", "edge": "#5a6b78", "accent": "#9fc0d8",
     "name": "钢铁指挥所", "name_en": "Steel Command", "name_ja": "鋼の司令部"},
    {"id": "hq_gold", "cat": "hq", "price": 1200, "cur": "gold",
     "fill": "#2e2716", "edge": "#c9a227", "accent": "#f0d060",
     "name": "黄金总部", "name_en": "Golden HQ", "name_ja": "黄金本部"},
    {"id": "hq_ember", "cat": "hq", "price": 900, "cur": "gold",
     "fill": "#2b1c14", "edge": "#8a4a24", "accent": "#e0763a",
     "name": "余烬要塞", "name_en": "Ember Fort", "name_ja": "残り火要塞"},
    {"id": "hq_ice", "cat": "hq", "price": 900, "cur": "gold",
     "fill": "#1a2733", "edge": "#4a7fb0", "accent": "#a8daf5",
     "name": "极地堡垒", "name_en": "Polar Keep", "name_ja": "極地要塞"},
    {"id": "hq_shadow", "cat": "hq", "price": 7, "cur": "diamonds",
     "fill": "#1b1622", "edge": "#5a3f7a", "accent": "#b48ce0",
     "name": "暗影地堡", "name_en": "Shadow Bunker", "name_ja": "影の壕"},
    {"id": "hq_victory", "cat": "hq", "price": 12, "cur": "diamonds",
     "fill": "#26221a", "edge": "#d8c070", "accent": "#ffe9a0",
     "name": "胜利丰碑", "name_en": "Victory Monument", "name_ja": "勝利の碑"},
]

_BY_ID = {it["id"]: it for it in CATALOG}


def item(item_id):
    """按 id 取商品（未知 id 返回 None，渲染层要能容忍）。"""
    return _BY_ID.get(item_id)


def items_in(cat):
    return [it for it in CATALOG if it["cat"] == cat]


def name_of(it):
    """商品名的当前语言版本。"""
    try:
        import kards_i18n as i18n
        lang = i18n.get_lang()
    except Exception:                       # noqa: BLE001
        lang = "zh"
    if lang == "en":
        return it.get("name_en") or it["name"]
    if lang == "ja":
        return it.get("name_ja") or it["name"]
    return it["name"]


def is_diamond(it):
    return it.get("cur") == "diamonds"


def price_text(it):
    """价格文案的数字部分（单位由界面按语言补，避免这里依赖 i18n 表）。"""
    return int(it.get("price") or 0)


# ---------------------------------------------------------------- 存档
def _key(name=None):
    return account.wallet_key(name)


def _blank():
    return {"owned": {c: [] for c in CATEGORIES},
            "equipped": {c: "" for c in CATEGORIES},
            "stock": {"date": "", "seed": 0, "ids": [], "rerolls": 0}}


def _load():
    try:
        with open(_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _save(d):
    try:
        os.makedirs(account.DATA_DIR, exist_ok=True)
        with open(_FILE, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
    except OSError:
        pass


def _today():
    return time.strftime("%Y-%m-%d", time.localtime())


def _i(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def normalize(raw):
    """把损坏/旧版存档修成合法结构（缺字段补齐、剔除已下架商品）。"""
    out = _blank()
    if not isinstance(raw, dict):
        return out
    owned = raw.get("owned") if isinstance(raw.get("owned"), dict) else {}
    for c in CATEGORIES:
        ids = owned.get(c) if isinstance(owned.get(c), list) else []
        out["owned"][c] = [i for i in ids if i in _BY_ID and _BY_ID[i]["cat"] == c]
    eq = raw.get("equipped") if isinstance(raw.get("equipped"), dict) else {}
    for c in CATEGORIES:
        i = str(eq.get(c) or "")
        out["equipped"][c] = i if i in out["owned"][c] else ""
    st = raw.get("stock") if isinstance(raw.get("stock"), dict) else {}
    out["stock"]["date"] = str(st.get("date") or "")
    out["stock"]["seed"] = _i(st.get("seed"))
    ids = st.get("ids") if isinstance(st.get("ids"), list) else []
    out["stock"]["ids"] = [i for i in ids if i in _BY_ID]
    out["stock"]["rerolls"] = max(0, _i(st.get("rerolls")))
    return out


def _roll(date, seed, n_per_cat=_STOCK_PER_CAT):
    """按 (日期, 种子) 抽当日库存：每类固定 n 件，永不重复同类同款。"""
    rng = random.Random(f"{date}|{seed}")
    ids = []
    for c in CATEGORIES:
        pool = list(items_in(c))
        rng.shuffle(pool)
        ids.extend(it["id"] for it in pool[:max(0, int(n_per_cat))])
    return ids


def get_state(name=None):
    """读当前玩家的商店状态（跨日自动换一批，不动已购/已装备）。"""
    d = _load()
    k = _key(name)
    st = normalize(d.get(k))
    today = _today()
    if st["stock"]["date"] != today:
        st["stock"] = {"date": today, "seed": 0,
                       "ids": _roll(today, 0), "rerolls": 0}
        d[k] = st
        _save(d)
    return st


def stock(name=None):
    """当日货架（商品 dict 列表，顺序 = 页面展示顺序）。"""
    st = get_state(name)
    out = [item(i) for i in st["stock"]["ids"]]
    return [it for it in out if it is not None]


def free_rerolls_left(name=None):
    st = get_state(name)
    return max(0, FREE_REROLLS - int(st["stock"]["rerolls"]))


def reroll(name=None):
    """重摇当日货架。返回 (ok, err_key, cost)。

    当天首次免费；之后每次 REROLL_COST 金。钱不够就什么都不改。
    """
    st = get_state(name)
    used = int(st["stock"]["rerolls"])
    free = used < FREE_REROLLS
    cost = 0 if free else REROLL_COST
    if cost:
        cur = account.get_currency(name)
        if cur["gold"] < cost:
            return False, "shop_no_gold", cost
        account.currency_add(gold=-cost, name=name)
    st["stock"]["rerolls"] = used + 1
    # 种子只用「第几次重摇」不够随机：再掺一点时间，让连点几次也不撞车
    seed = used + 1 + int(time.time() * 1000) % 9973
    st["stock"]["seed"] = seed
    st["stock"]["ids"] = _roll(st["stock"]["date"], seed)
    d = _load()
    d[_key(name)] = st
    _save(d)
    return True, None, cost


def _mutate(name, fn):
    d = _load()
    k = _key(name)
    st = normalize(d.get(k))
    res = fn(st)
    d[k] = st
    _save(d)
    return res


def owns(item_id, name=None):
    it = item(item_id)
    if it is None:
        return False
    return item_id in get_state(name)["owned"][it["cat"]]


def buy(item_id, name=None):
    """买一件。返回 (ok, err_key)。买完自动装备（外观类本来就该立刻看到）。"""
    it = item(item_id)
    if it is None:
        return False, "shop_err_item"
    st = get_state(name)
    if item_id in st["owned"][it["cat"]]:
        return False, "shop_err_owned"
    if item_id not in st["stock"]["ids"]:
        return False, "shop_err_not_in_stock"
    cur = account.get_currency(name)
    field = "diamonds" if is_diamond(it) else "gold"
    if cur[field] < int(it["price"]):
        return False, ("shop_no_diamond" if field == "diamonds" else "shop_no_gold")

    def apply(s):
        s["owned"][it["cat"]].append(item_id)
        s["equipped"][it["cat"]] = item_id
        return True

    account.currency_add(gold=(-int(it["price"]) if field == "gold" else 0),
                         diamonds=(-int(it["price"]) if field == "diamonds" else 0),
                         name=name)
    _mutate(name, apply)
    return True, None


def equip(item_id, name=None):
    """装备已购商品。传空串 = 卸下全部（回到默认外观）。"""
    if not item_id:
        def clear(s):
            for c in CATEGORIES:
                s["equipped"][c] = ""
            return True, None

        _mutate(name, clear)
        return True, None
    it = item(item_id)
    if it is None:
        return False, "shop_err_item"
    st = get_state(name)
    if item_id not in st["owned"][it["cat"]]:
        return False, "shop_err_not_owned"

    def apply(s):
        s["equipped"][it["cat"]] = item_id
        return True

    _mutate(name, apply)
    return True, None


def cosmetics(name=None):
    """当前装备的外观：{"avatar": item|None, "table": ..., "hq": ...}

    渲染层只读这个函数的结果，不直接碰存档结构。
    """
    st = get_state(name)
    out = {}
    for c in CATEGORIES:
        out[c] = item(st["equipped"][c])
    return out


def equipped_id(cat, name=None):
    return get_state(name)["equipped"].get(cat) or ""
