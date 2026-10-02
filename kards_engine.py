# -*- coding: utf-8 -*-
"""
KARDS 简化版 —— 二战卡牌对战游戏

规则说明:
- 双方各有总部(HQ)，将敌方总部血量降到 0 即获胜。
- 每回合获得 Kredits（资源）= 当前回合数（上限 12），用于打出卡牌。
- 场上每方最多 5 个单位，每个单位占据一个编号位置(0-4)。
- 卡组：40 张 = 1 张总部卡 + 39 张单位/指令/反制，单卡上限 3 张，盟国卡上限 20 张。\n稀有度：对齐原版的卡为固定评定，其余按费用+关键词自动评定 普通/稀有/史诗/传说（★~★★★）。
- 主国: 德国/苏联/美国/英国/日本；盟国: 意大利/法国/芬兰/波兰/澳新军团。
- 总部卡自带「研发」被动（各主国不同）。
- 单位关键词（对齐原版 KARDS）:
    闪击  - 部署当回合就可攻击
    装甲  - 战斗伤害减少 1（指令等效果伤害不减）
    装甲2 - 战斗伤害减少 2（指令等效果伤害不减）
    装甲3 - 战斗伤害减少 3（指令等效果伤害不减）
    警卫  - 保护相邻位置的单位；#0位（紧邻总部）的警卫还保护总部
    冲击  - 攻击敌方单位时不受反击，攻击后移除
    伏击  - 被攻击时先出手打击攻击者；攻击者若阵亡则攻击无效
    奋战  - 每回合可攻击两次
    动员  - 你的回合开始时 +1/+1，直到它受到伤害为止
    收缴  - 消灭敌方单位时，将一张 1/1 副本（费用至多 3）加入手牌（仅日本/芬兰有）
    亡计  - 被消灭时对敌方总部造成伤害（如隼式/大和号授予）
- 反制：暗置在反制区（上限 3 张），满足条件时自动触发。日本与苏联没有反制卡。
- 每回合开始抽 1 张牌，牌库抽空则受到 1 点疲劳伤害且疲劳+1。

运行方式:
    python kards.py          # 人机对战（可选自组卡组/导入清单）
    python kards.py --demo   # AI vs AI 自动演示
"""

import copy
import os
import random
import re
import sys
import time

MAX_KREDITS = 12
HQ_HP = 20             # 总部血量：各国统一 20（实际取值见下方 HQ_CARDS）
BOARD_SIZE = 9         # 一方场上总上限（前线5 + 支援线4；总部不算单位）
REAR_SLOTS = 4         # 支援阵线（后方）最多 4 个单位
FRONTLINE_SLOTS = 5    # 前线最多 5 个单位（占领方）
RANGED_TYPES = ("炮兵", "战斗机", "轰炸机")   # 无需上前线即可攻击的兵种
NO_COUNTER_DEAL = ("轰炸机",)                 # 不进行反击的兵种（打它不吃反击）
HAND_LIMIT = 10
START_HP = 3        # 起始手牌数
COUNTER_SLOTS = 3    # 反制区上限
DECK_SIZE = 39       # 卡组张数：39 张单位/指令/反制 + 1 张总部卡 = 40 张
MAX_COPIES = 3       # 单卡上限
ALLY_LIMIT = 20      # 盟国卡上限（约卡组的 1/3）

# ---- AI 自动投降 ----
# 设计原则：宁可多打一会儿，也不要早退。只有"确实已经输了"才投降。
# 阈值按总部血量 HQ_HP 标定：HQ=20 时，HP2 取 8（40% 血线）。
AI_AUTO_CONCEDE = True     # 总开关：AI 觉得没胜算时主动投降
AI_CONCEDE_HP = 4          # 濒死线：总部血 ≤ 此值 + 对方场攻够 → 投
AI_CONCEDE_HP2 = 8         # 资源枯竭判定的血线：血高于此值一律不投
AI_CONCEDE_RATIO = 3.0     # 对方场面强度 ≥ 我方此倍数才算被碾压
AI_CONCEDE_DECK_LEFT = 3   # 牌库剩余 ≤ 此值才算"资源枯竭"
AI_CONCEDE_IGNORE_HAND = False  # True=忽略"手里还攒着牌"这一保留条件

MAIN_NATIONS = ["德国", "苏联", "美国", "英国", "日本"]
ALLY_NATIONS = ["意大利", "法国", "芬兰", "波兰", "澳新军团"]

KEYWORD_DESC = {
    "闪击": "部署当回合即可移动和攻击",
    "装甲": "战斗伤害减少 1（指令等效果伤害不减）",
    "装甲2": "战斗伤害减少 2（指令等效果伤害不减）",
    "装甲3": "战斗伤害减少 3（指令等效果伤害不减）",
    "警卫": "保护相邻位置的单位；#0位警卫保护总部（炮兵/轰炸机无视警卫）",
    "冲击": "攻击单位免反击，攻击后消耗",
    "伏击": "被攻击时先出手打击攻击者；攻击者若阵亡则攻击无效",
    "奋战": "每回合可攻击两次",
    "动员": "你的回合开始时 +1/+1，直到它受到伤害为止",
    "收缴": "消灭敌方单位时，将一张 1/1 副本（费用至多 3）加入手牌",
}

RULES_TEXT = [
    "部署: 新单位进入支援线; 移动与攻击都消耗行动费(⚡)",
    "无[闪击]的单位部署当回合不能移动或攻击",
    "步兵每回合移动/攻击二选一; 坦克可以移动并攻击",
    "空军(战斗机/轰炸机)与炮兵在支援线即可攻击(仅限敌方前线单位与总部)",
    "炮兵/轰炸机无视[警卫]; 轰炸机必须优先攻击敌方战斗机, 且会被战斗机拦截",
    "炮兵/轰炸机攻击不吃反击; 轰炸机不反击(打它不吃反击); 轰炸机打总部+2",
    "[伏击]被攻击时先出手；[奋战]每回合攻击两次；[装甲]战斗伤害-1（[装甲2]-2、[装甲3]-3）",
    "[动员]回合开始+1/+1直至受伤；[亡计]被消灭时对敌方总部造成伤害",
    "[收缴]消灭敌方单位时，一张 1/1 副本（费用至多3）加入手牌",
    "[警卫]保护相邻位置的单位；位于#0位（紧邻总部）的警卫还保护总部",
]


# ---- 稀有度 -----------------------------------------------------------------
RARITY_LEVELS = ["普通", "稀有", "史诗", "传说"]
RARITY_COLORS = {"普通": "#9aa2ad", "稀有": "#4a8fd4", "史诗": "#a05ad4", "传说": "#d4af37"}
RARITY_STARS = {"普通": "", "稀有": " ★", "史诗": " ★★", "传说": " ★★★"}


def auto_rarity(cost, keywords=()):
    """按费用与关键词强度自动评定稀有度（规则透明，全卡池一致）"""
    score = cost
    kw = set(keywords or ())
    if "收缴" in kw:
        score += 3
    if "警卫" in kw:
        score += 2
    if "装甲" in kw:
        score += 2
    if "冲击" in kw:
        score += 1
    if "闪击" in kw:
        score += 1
    if score >= 9:
        return "传说"
    if score >= 6:
        return "史诗"
    if score >= 4:
        return "稀有"
    return "普通"


# ---------------------------------------------------------------- 卡牌定义

class UnitCard:
    kind = "unit"

    def __init__(self, name, nation, cost, attack, defense, keywords=None, unit_type="步兵",
                 traits=None, rarity=None, operate=0):
        self.name = name
        self.nation = nation
        self.cost = cost
        self.attack = attack
        self.defense = defense
        self.keywords = keywords or []
        self.unit_type = unit_type
        self.traits = traits or {}      # 原版效果标记（部署/亡计/双倍伤害等）
        self.rarity = rarity or auto_rarity(cost, keywords)
        self.operate = int(operate)     # 行动费：每次攻击额外消耗的 Kredits（原版机制）


class OrderCard:
    kind = "order"

    def __init__(self, name, nation, cost, effect, desc, rarity=None):
        self.name = name
        self.nation = nation
        self.cost = cost
        self.effect = effect  # callable(game, caster)
        self.desc = desc
        self.rarity = rarity or auto_rarity(cost)


class CounterCard:
    """反制卡：暗置在反制区，满足条件时自动触发"""
    kind = "counter"

    def __init__(self, name, nation, cost, trigger, desc, effect=None, rarity=None):
        self.name = name
        self.nation = nation
        self.cost = cost
        self.trigger = trigger  # attack_tank | attack_air | attack_inf | attack_any | order | friendly_death | hq_damage
        self.desc = desc
        self.effect = effect    # 自定义触发效果 callable(game, owner)；None 走默认（消灭攻击者）
        self.rarity = rarity or auto_rarity(cost)

    def matches(self, event, ctx):
        if self.trigger == "attack_tank":
            return event == "attack" and ctx.unit_type == "坦克"
        if self.trigger == "attack_air":
            return event == "attack" and ctx.unit_type in ("战斗机", "轰炸机")
        if self.trigger == "attack_inf":
            return event == "attack" and ctx.unit_type == "步兵"
        if self.trigger == "attack_any":
            return event == "attack"
        if self.trigger == "order":
            return event == "order"
        if self.trigger == "hq_damage":
            return event == "hq_damage"
        return False


class HQCard:
    """总部卡：不进入抽牌库，卡组 40 张中的第 1 张；自带研发被动"""
    kind = "hq"

    def __init__(self, nation, name, hp, perk, perk_desc):
        self.nation = nation
        self.name = name
        self.hp = hp
        self.perk = perk          # tank_discount | regen | air_attack | support_discount | inf_attack
        self.perk_desc = perk_desc


# 总部血量统一为 20：各国只靠"研发被动"区分特色，血量不再造成额外强弱差
HQ_CARDS = {
    "德国": HQCard("德国", "德国国防军总部", 20, "tank_discount",
                   "研发·闪电战术: 你的坦克费用 -1"),
    "苏联": HQCard("苏联", "苏联最高统帅部", 20, "regen",
                   "研发·纵深防御: 每回合开始总部恢复 1 点生命"),
    "美国": HQCard("美国", "盟军远征军总部", 20, "air_attack",
                   "研发·航空引擎: 你的战斗机与轰炸机攻击 +1"),
    "英国": HQCard("英国", "英国皇家司令部", 20, "support_discount",
                   "研发·情报部门: 你的指令与反制费用 -1"),
    "日本": HQCard("日本", "大日本帝国大本营", 20, "inf_attack",
                   "研发·精神注入: 你的步兵攻击 +1"),
}

# 一致性校验：所有国家的总部血量必须相同（统一 20）。
# 曾经各国血量不同（25/27/24/24/24），等于偷偷给某些国家加/减上限，
# 强弱不在同一基准线上。这里显式断言，防止以后改单张卡时又飘掉。
assert len({c.hp for c in HQ_CARDS.values()}) == 1, \
    "各国总部血量必须一致，当前: " + \
    ", ".join(f"{n}={c.hp}" for n, c in HQ_CARDS.items())
assert next(iter(HQ_CARDS.values())).hp == HQ_HP, \
    f"总部血量应为 {HQ_HP}，当前 {next(iter(HQ_CARDS.values())).hp}"


class Unit:
    """场上的单位实例"""

    def __init__(self, card, owner):
        self.card = card
        self.owner = owner
        self.attack = card.attack
        self.defense = card.defense
        self.max_defense = card.defense
        self.keywords = list(card.keywords)
        self.unit_type = card.unit_type
        self.position = "后方"      # "后方" 或 "前线"
        self.slot = None            # 场上位置编号 0-4（警卫相邻判定用）
        self.moved = False          # 本回合是否已移动过
        self.can_attack = "闪击" in self.keywords  # 无闪击则下回合才能攻击
        self.attacks_made = 0
        self.traits = dict(getattr(card, "traits", None) or {})  # 原版效果标记
        self.mob = 0                # [动员]当前加成（受伤时移除）
        self.fresh_deploy = False   # 本回合刚部署（无[闪击]不能立即移动/攻击）
        self.operate = int(getattr(card, "operate", 0))  # 行动费：每次攻击消耗
        self.dying_hq = int((getattr(card, "traits", None) or {}).get("dying_hq", 0))
        self.overflow_turn = False  # 本回合溢出伤害转移敌方总部（呜啦！）
        # 总部研发被动
        perk = owner.hq_card.perk
        if perk == "air_attack" and card.unit_type in ("战斗机", "轰炸机"):
            self.attack += 1
        if perk == "inf_attack" and card.unit_type == "步兵":
            self.attack += 1

    @property
    def name(self):
        return self.card.name

    def has(self, kw):
        return kw in self.keywords

    @property
    def max_attacks(self):
        """[奋战]每回合可攻击两次"""
        return 2 if "奋战" in self.keywords else 1

    @property
    def armor(self):
        """战斗伤害减免（仅战斗，效果伤害不减免）：装甲=1 / 装甲2=2 / 装甲3=3"""
        if "装甲3" in self.keywords:
            return 3
        if "装甲2" in self.keywords:
            return 2
        if "装甲" in self.keywords:
            return 1
        return 0

    def __str__(self):
        kws = ("/" + "".join(f"[{k}]" for k in self.keywords)) if self.keywords else ""
        op = f"⚡{self.operate}" if self.operate else ""
        return f"{self.name} {self.attack}/{self.defense}({self.unit_type}@{self.position}#{self.slot}){op}{kws}"


# ---------------------------------------------------------------- 指令效果

def _token_card(name, attack, defense, unit_type="步兵"):
    return UnitCard(name, "中立", 0, attack, defense, [], unit_type)


def effect_blitzkrieg(game, caster):
    """闪电战: 本回合前线友方单位 +3 攻击（回合结束还原）"""
    n = 0
    for u in caster.board:
        if u.position == "前线":
            u.attack += 3
            caster.temp_buffs.append((u, 3))
            n += 1
    if n:
        game.log(f"  闪电战！前线 {n} 个友方单位本回合 +3 攻击。")
    else:
        game.log("  （前线没有友方单位，闪电战落空）")


def effect_ura(game, caster):
    """呜啦!: 本回合所有苏联单位 +3 攻击，溢出伤害转移到敌方总部"""
    n = 0
    for u in caster.board:
        if u.card.nation == "苏联":
            u.attack += 3
            caster.temp_buffs.append((u, 3))
            u.overflow_turn = True
            n += 1
    game.log(f"  呜啦！{n} 个苏联单位本回合 +3 攻击，溢出伤害将转移至敌方总部！")


def effect_fresh_recruits(game, caster):
    """新兵入伍(反制): 友方单位被消灭时，随机友方单位 +2/+3"""
    if not caster.board:
        game.log("  没有友方单位，新兵入伍落空。")
        return
    u = random.choice(caster.board)
    u.attack += 2
    u.defense += 3
    u.max_defense += 3
    game.log(f"  {u.name} 获得 +2/+3（{u.attack}/{u.defense}）。")


def effect_cup_of_tea(game, caster):
    """一杯茶: 你的所有英军单位 +2 防御"""
    n = 0
    for u in caster.board:
        if u.card.nation == "英国":
            u.defense += 2
            u.max_defense += 2
            n += 1
    game.log(f"  一杯茶：{n} 个英军单位 +2 防御，士气大振！")


def effect_double_strength(game, caster):
    """双倍力量: 随机复制一张手中的指令牌，洗入卡组"""
    orders = [c for c in caster.hand if c.kind == "order"]
    if not orders:
        game.log("  手中没有指令牌，双倍力量落空。")
        return
    c = random.choice(orders)
    caster.deck.insert(random.randrange(len(caster.deck) + 1), copy.deepcopy(c))
    game.log(f"  双倍力量：复制了一张 [ {c.name} ] 洗入卡组。")


def effect_banzai(game, caster):
    """万岁冲锋: 消灭所有攻击力≤4 的陆军单位（双方），然后结束你的回合"""
    for pl in game.players:
        for u in list(pl.board):
            if u.unit_type in ("步兵", "坦克") and u.attack <= 4:
                game.log(f"  万岁冲锋吞没了 {u.name}！")
                game.destroy_unit(u)
    game.log("  万岁冲锋！你的回合就此结束。")
    game.force_end = True


def effect_naval_support(game, caster):
    """炮火准备: 对一个随机敌方单位造成 2 点伤害（无法选中"不可被指令指定"的单位）"""
    targets = [u for u in game.opponent_of(caster).board
               if u.defense > 0 and not u.traits.get("untargetable")]
    if targets:
        t = random.choice(targets)
        game.log(f"  炮火准备命中 {t.name}，造成 2 点伤害！")
        game.damage_unit(t, 2)
    else:
        enemy = game.opponent_of(caster)
        game.damage_hq(enemy, 2)
        game.log("  场上没有目标，炮火准备轰击敌方总部，造成 2 点伤害！")


def effect_resistance(game, caster):
    """抵抗网络: 抽 1 张牌，总部恢复 1 点生命"""
    game.draw_cards(caster, 1)
    max_hp = caster.hq_card.hp
    caster.hq = min(max_hp, caster.hq + 1)
    game.log("  抽了 1 张牌，总部恢复 1 点生命。")


def effect_winter_war(game, caster):
    """冬季战争: 对敌方总部造成 2 点伤害，抽 1 张牌"""
    enemy = game.opponent_of(caster)
    game.damage_hq(enemy, 2)
    game.draw_cards(caster, 1)
    game.log("  冬季战争：敌方总部受到 2 点伤害，你抽了 1 张牌。")


def effect_hussars(game, caster):
    """冲锋在前(近似原版军团机制): 随机一个友方单位 +1/+1，并部署一个 1/1 军团"""
    if caster.board:
        u = random.choice(caster.board)
        u.attack += 1
        u.defense += 1
        u.max_defense += 1
        game.log(f"  {u.name} 获得 +1/+1。")
    if game.can_deploy(caster):
        game.deploy_unit(caster, _token_card("军团", 1, 1))
        game.log("  军团（1/1）加入了支援阵线！")


def effect_anzac_storm(game, caster):
    """澳新风暴: 己方所有单位 +1 攻击，并获得 [冲击]（尚未拥有时）"""
    if not caster.board:
        game.log("  没有友方单位，澳新风暴落空。")
        return
    for u in caster.board:
        u.attack += 1
        if not u.has("冲击"):
            u.keywords.append("冲击")
    game.log("  己方所有单位 +1 攻击并获得 [冲击]！")


def effect_lotta(game, caster):
    """洛塔组织: 己方所有单位 +1 防御（原版另有减行动费，简化版无行动费加成项）"""
    if not caster.board:
        game.log("  没有友方单位，洛塔组织落空。")
        return
    for u in caster.board:
        u.defense += 1
        u.max_defense += 1
    game.log("  洛塔组织：己方所有单位 +1 防御！")


def effect_anzac_spirit(game, caster):
    """澳新军团精神: 对所有敌方单位造成 2 点伤害，抽 2 张牌"""
    enemy = game.opponent_of(caster)
    for u in list(enemy.board):
        game.damage_unit(u, 2)
    game.draw_cards(caster, 2)
    game.log("  澳新军团精神：所有敌方单位受到 2 点伤害，你抽了 2 张牌。")


def effect_naval_support_uk(game, caster):
    """海军支援: 一个（防御最高的）友方单位攻击力变为等同于其防御力"""
    if not caster.board:
        game.log("  没有友方单位，海军支援落空。")
        return
    u = max(caster.board, key=lambda x: (x.defense, x.attack))
    before = u.attack
    u.attack = u.defense
    game.log(f"  海军支援：{u.name} 的攻击力 {before} → {u.attack}（等同于防御力）。")


def effect_ats(game, caster):
    """本土防卫军: 本回合敌方总部受到 3 点或以上伤害时，你抽一张牌"""
    foe = game.opponent_of(caster)
    foe.ats_mark = game.players.index(caster) + 1
    game.log("  本土防卫军监视敌方总部：本回合其受到 3 点或以上伤害时，你抽一张牌。")


def effect_yamato(game, caster):
    """大和号: 当前所有日军单位获得 亡计：对敌方总部造成 2 点伤害（之后部署的不含）"""
    n = 0
    for u in caster.board:
        if u.card.nation == "日本":
            u.dying_hq = 2
            n += 1
    game.log(f"  大和号坐镇！{n} 个日军单位获得 [亡计：对敌方总部 2 伤]。")


def effect_bombing_raid(game, caster):
    """轰炸突袭: 对一个随机敌方目标 3 伤，其相邻目标 2 伤"""
    foe = game.opponent_of(caster)
    live = [u for u in foe.board
            if u.defense > 0 and not u.traits.get("untargetable")]
    if not live:
        game.log("  轰炸突袭：敌方总部受到 3 点伤害！")
        game.damage_hq(foe, 3)
        return
    t = random.choice(live)
    game.log(f"  轰炸突袭：{t.name} 受到 3 点伤害！")
    game.damage_unit(t, 3)
    for u in list(foe.board):
        if u is t or u.defense <= 0:
            continue
        if u.slot is not None and t.slot is not None and abs(u.slot - t.slot) == 1:
            game.log(f"  波及伤害：{u.name} 受到 2 点伤害。")
            game.damage_unit(u, 2)


def effect_conscripts(game, caster):
    """征召令: 无其他效果（用于触发指令联动）"""
    game.log("  征召令：新兵列队完毕。（无其他效果）")


# ---------------------------------------------------------------- 卡池


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



# ---------------------------------------------------------------- 扩充卡池（数据取自原版 CSV，效果用通用机制近似）
EXTRA_CARDS = [
    # ---- 单位 ----
            UnitCard("Pak36反坦克炮", "德国", 1, 1, 1, [], "炮兵", rarity="普通"),
            UnitCard("二号坦克 C 型", "德国", 1, 1, 3, [], "坦克", rarity="普通"),
            UnitCard("第 4 先锋营", "德国", 1, 1, 3, [], "步兵", rarity="普通"),
            UnitCard("35(t)指挥车", "德国", 2, 2, 2, [], "坦克", rarity="史诗"),
            UnitCard("亨舍尔 Hs 123", "德国", 2, 1, 3, ["奋战"], "轰炸机", rarity="史诗"),
            UnitCard("第 104 装甲掷弹兵团", "德国", 2, 3, 3, [], "步兵", rarity="稀有"),
            UnitCard("第 3 空降猎兵团", "德国", 2, 2, 2, [], "步兵", rarity="稀有"),
            UnitCard("第 8 空降猎兵团", "德国", 2, 3, 2, ["闪击", "奋战"], "步兵", rarity="传说"),
            UnitCard("150毫米榴弹炮", "德国", 3, 3, 2, [], "炮兵", rarity="传说"),
            UnitCard("Fw 200 秃鹰", "德国", 3, 3, 3, ["闪击"], "轰炸机", rarity="史诗"),
            UnitCard("三号坦克 G 型", "德国", 3, 3, 4, ["闪击"], "坦克", rarity="稀有"),
            UnitCard("三号突击炮 G 型", "德国", 3, 3, 3, [], "坦克", rarity="普通"),
            UnitCard("四号突击炮", "德国", 3, 3, 4, ["奋战"], "坦克", rarity="稀有"),
            UnitCard("第 980 国民掷弹兵团", "德国", 3, 3, 6, [], "步兵", rarity="普通"),
            UnitCard("BF 109E-7 热带型", "德国", 4, 3, 3, [], "战斗机", rarity="普通"),
            UnitCard("三号坦克 H 型", "德国", 4, 2, 4, [], "坦克", rarity="史诗"),
            UnitCard("斯图卡 B2", "德国", 4, 3, 2, [], "轰炸机", rarity="稀有"),
            UnitCard("第 81 步兵团", "德国", 4, 3, 7, [], "步兵", rarity="普通"),
            UnitCard("105毫米轻型榴弹炮", "德国", 5, 2, 3, [], "炮兵", rarity="普通"),
            UnitCard("容克 Ju 88 A", "德国", 5, 4, 5, [], "轰炸机", rarity="稀有"),
            UnitCard("豹式坦克 G 型", "德国", 5, 6, 5, ["装甲"], "坦克", rarity="史诗"),
            UnitCard("Fw 190A 百舌鸟", "德国", 6, 5, 5, [], "战斗机", rarity="普通"),
            UnitCard("Me 410 大黄蜂", "德国", 7, 3, 4, [], "战斗机", rarity="传说"),
            UnitCard("BP-42 装甲列车", "德国", 9, 5, 9, ["装甲"], "坦克", rarity="传说"),
            UnitCard("步兵第 554 团", "苏联", 0, 1, 1, ["闪击"], "步兵", rarity="普通"),
            UnitCard("步兵第 89 团", "苏联", 1, 1, 3, ["警卫"], "步兵", rarity="普通"),
            UnitCard("海军步兵第 6 旅", "苏联", 1, 3, 1, [], "步兵", rarity="稀有"),
            UnitCard("T-70", "苏联", 2, 3, 2, ["警卫"], "坦克", rarity="普通"),
            UnitCard("伊-15 海鸥", "苏联", 2, 1, 2, [], "战斗机", rarity="史诗"),
            UnitCard("步兵第 456 团", "苏联", 2, 1, 3, [], "步兵", rarity="普通"),
            UnitCard("海军陆战队第 2 营", "苏联", 2, 2, 4, ["闪击"], "步兵", rarity="普通"),
            UnitCard("雅克-7", "苏联", 2, 2, 2, [], "战斗机", rarity="传说"),
            UnitCard("佩-2", "苏联", 3, 4, 4, [], "轰炸机", rarity="史诗"),
            UnitCard("摩托化步兵第 15 团", "苏联", 3, 1, 5, ["警卫"], "步兵", rarity="史诗"),
            UnitCard("步兵第 35 团", "苏联", 3, 3, 4, [], "步兵", rarity="史诗"),
            UnitCard("步兵第 84 团", "苏联", 3, 1, 8, ["警卫"], "步兵", rarity="普通"),
            UnitCard("T-60", "苏联", 4, 2, 4, ["警卫"], "坦克", rarity="稀有"),
            UnitCard("步兵第 1005 团", "苏联", 4, 5, 3, ["伏击"], "步兵", rarity="普通"),
            UnitCard("近卫步兵第 1 团", "苏联", 4, 3, 5, ["警卫"], "步兵", rarity="传说"),
            UnitCard("雅克-3", "苏联", 4, 3, 5, ["伏击"], "战斗机", rarity="稀有"),
            UnitCard("BP-43 装甲列车", "苏联", 5, 3, 7, ["警卫", "装甲"], "坦克", rarity="传说"),
            UnitCard("日托米尔第 71 团", "苏联", 5, 3, 5, ["伏击"], "步兵", rarity="史诗"),
            UnitCard("步兵第 461 团", "苏联", 5, 5, 3, ["伏击"], "步兵", rarity="普通"),
            UnitCard("米格-3", "苏联", 5, 4, 5, [], "战斗机", rarity="稀有"),
            UnitCard("KV-1 1939", "苏联", 6, 4, 6, ["警卫", "装甲"], "坦克", rarity="史诗"),
            UnitCard("海军步兵第 83 旅", "苏联", 6, 4, 4, ["警卫", "伏击"], "步兵", rarity="传说"),
            UnitCard("ISU-152", "苏联", 7, 4, 6, ["装甲2"], "坦克", rarity="传说"),
            UnitCard("步兵第 756 团", "苏联", 7, 7, 7, [], "步兵", rarity="稀有"),
            UnitCard("M8 灰狗", "美国", 1, 1, 3, ["闪击"], "坦克", rarity="普通"),
            UnitCard("第 32 步兵团", "美国", 1, 2, 1, [], "步兵", rarity="普通"),
            UnitCard("F4F-3 野猫", "美国", 2, 2, 3, [], "战斗机", rarity="普通"),
            UnitCard("T19 榴弹炮", "美国", 2, 1, 3, [], "炮兵", rarity="普通"),
            UnitCard("第 99 步兵营", "美国", 2, 2, 3, [], "步兵", rarity="史诗"),
            UnitCard("A-20 浩劫", "美国", 3, 2, 2, [], "轰炸机", rarity="普通"),
            UnitCard("M18 地狱猫", "美国", 3, 4, 2, ["闪击"], "坦克", rarity="史诗"),
            UnitCard("M7 牧师", "美国", 3, 1, 2, [], "炮兵", rarity="稀有"),
            UnitCard("德州第 1 步兵团", "美国", 3, 1, 1, [], "步兵", rarity="稀有"),
            UnitCard("第 332 工兵团", "美国", 3, 2, 2, [], "步兵", rarity="稀有"),
            UnitCard("A-24 女妖", "美国", 4, 3, 4, ["装甲"], "轰炸机", rarity="稀有"),
            UnitCard("P-38 闪电", "美国", 4, 3, 5, [], "战斗机", rarity="稀有"),
            UnitCard("第 106 军需连", "美国", 4, 2, 5, [], "步兵", rarity="史诗"),
            UnitCard("第 7 步兵团", "美国", 4, 3, 6, [], "步兵", rarity="普通"),
            UnitCard("A-26 入侵者", "美国", 5, 4, 4, [], "轰炸机", rarity="普通"),
            UnitCard("F4U-1C 海盗", "美国", 5, 4, 6, [], "战斗机", rarity="普通"),
            UnitCard("P-61 黑寡妇", "美国", 5, 4, 5, [], "战斗机", rarity="传说"),
            UnitCard("A-36 阿帕齐", "美国", 6, 4, 4, [], "战斗机", rarity="稀有"),
            UnitCard("加州第 2 步兵团", "美国", 6, 7, 4, [], "步兵", rarity="普通"),
            UnitCard("TBF-1 复仇者", "美国", 8, 4, 4, [], "轰炸机", rarity="史诗"),
            UnitCard("第 5 伞兵旅", "英国", 0, 1, 1, ["动员"], "步兵", rarity="普通"),
            UnitCard("剑鱼 Mk I", "英国", 1, 1, 3, [], "轰炸机", rarity="稀有"),
            UnitCard("2 磅炮", "英国", 2, 1, 2, [], "炮兵", rarity="普通"),
            UnitCard("水牛 Mk I", "英国", 2, 2, 3, [], "战斗机", rarity="稀有"),
            UnitCard("青花鱼 Mk I", "英国", 2, 1, 2, [], "轰炸机", rarity="史诗"),
            UnitCard("P-40 小鹰", "英国", 3, 2, 3, [], "战斗机", rarity="传说"),
            UnitCard("冷溪近卫团", "英国", 3, 1, 4, ["警卫"], "步兵", rarity="稀有"),
            UnitCard("瓦伦丁 Mk III", "英国", 3, 2, 4, ["奋战"], "坦克", rarity="普通"),
            UnitCard("阿盖尔郡高地人团", "英国", 3, 1, 6, [], "步兵", rarity="稀有"),
            UnitCard("25 磅炮", "英国", 4, 2, 3, [], "炮兵", rarity="普通"),
            UnitCard("台风 Mk IB", "英国", 4, 5, 4, [], "战斗机", rarity="史诗"),
            UnitCard("喷火 Mk II", "英国", 4, 3, 5, [], "战斗机", rarity="稀有"),
            UnitCard("第 22 卫队旅", "英国", 4, 2, 5, ["警卫"], "步兵", rarity="稀有"),
            UnitCard("M4 萤火虫", "英国", 5, 8, 5, [], "坦克", rarity="传说"),
            UnitCard("因尼斯基林燧发枪团", "英国", 5, 4, 6, [], "步兵", rarity="史诗"),
            UnitCard("皇家西肯特郡团", "英国", 5, 2, 5, [], "步兵", rarity="稀有"),
            UnitCard("A34 彗星", "英国", 6, 6, 6, ["装甲"], "坦克", rarity="传说"),
            UnitCard("斯特林 Mk I S3", "英国", 6, 6, 4, [], "轰炸机", rarity="史诗"),
            UnitCard("9.2英寸岸防炮", "英国", 7, 4, 4, [], "炮兵", rarity="稀有"),
            UnitCard("暴风 Mk V", "英国", 7, 3, 7, ["伏击"], "战斗机", rarity="稀有"),
            UnitCard("九三式装甲车", "日本", 1, 1, 1, [], "坦克", rarity="稀有"),
            UnitCard("姬路联队", "日本", 1, 3, 1, [], "步兵", rarity="普通"),
            UnitCard("福山自行车联队", "日本", 1, 1, 1, ["闪击", "奋战"], "步兵", rarity="史诗"),
            UnitCard("静冈联队", "日本", 1, 2, 2, [], "步兵", rarity="普通"),
            UnitCard("D3A1 九九舰爆", "日本", 2, 2, 1, [], "轰炸机", rarity="史诗"),
            UnitCard("Ki-51 九九轻爆", "日本", 2, 1, 2, [], "轰炸机", rarity="史诗"),
            UnitCard("八八式高射炮", "日本", 2, 1, 3, [], "炮兵", rarity="普通"),
            UnitCard("秋田联队", "日本", 2, 2, 1, ["闪击"], "步兵", rarity="普通"),
            UnitCard("D4Y 彗星舰爆", "日本", 3, 2, 1, [], "轰炸机", rarity="普通"),
            UnitCard("九七式改中战车", "日本", 3, 3, 3, ["闪击"], "坦克", rarity="稀有"),
            UnitCard("水户联队", "日本", 3, 2, 3, ["闪击"], "步兵", traits={"dying_hq": 2}, rarity="普通"),
            UnitCard("鹿儿岛联队", "日本", 3, 5, 3, ["伏击"], "步兵", rarity="史诗"),
            UnitCard("Ki-21 九七重爆", "日本", 4, 5, 2, [], "轰炸机", rarity="稀有"),
            UnitCard("M6A1 晴岚特攻", "日本", 4, 1, 4, [], "轰炸机", rarity="史诗"),
            UnitCard("九零式野战炮", "日本", 4, 3, 2, [], "炮兵", rarity="稀有"),
            UnitCard("B6N 天山舰攻", "日本", 5, 3, 3, [], "轰炸机", rarity="稀有"),
            UnitCard("Ki-61 三式战 飞燕", "日本", 5, 5, 4, ["闪击"], "战斗机", rarity="普通"),
            UnitCard("三式中战车", "日本", 5, 4, 5, [], "坦克", rarity="稀有"),
            UnitCard("大阪联队", "日本", 5, 4, 7, ["警卫"], "步兵", rarity="普通"),
            UnitCard("Ki-61 三式战改 飞燕", "日本", 6, 5, 4, ["闪击"], "战斗机", rarity="稀有"),
            UnitCard("菲亚特 C.R.42", "意大利", 0, 1, 2, [], "战斗机", rarity="普通"),
            UnitCard("萨伏依骑兵团", "意大利", 1, 1, 1, ["闪击"], "步兵", rarity="普通"),
            UnitCard("马基 C.202", "意大利", 2, 2, 4, [], "战斗机", rarity="普通"),
            UnitCard("SM.79 食雀鹰", "意大利", 4, 5, 3, [], "轰炸机", rarity="稀有"),
            UnitCard("第 73 步兵团", "法国", 1, 0, 1, ["动员"], "步兵", rarity="普通"),
            UnitCard("75毫米野战炮", "法国", 3, 1, 1, ["动员"], "炮兵", rarity="普通"),
            UnitCard("莫拉纳 M.S.406", "法国", 3, 3, 3, [], "战斗机", rarity="普通"),
            UnitCard("第 2 旅", "法国", 4, 2, 6, ["警卫", "动员"], "步兵", rarity="史诗"),
            UnitCard("PZL P.7", "波兰", 1, 1, 2, ["闪击"], "战斗机", rarity="普通"),
            UnitCard("西里西亚第 74 步兵团", "波兰", 2, 2, 2, [], "步兵", rarity="普通"),
            UnitCard("飓风 PL", "波兰", 3, 3, 3, [], "战斗机", rarity="普通"),
            UnitCard("伊尔-2M PL", "波兰", 4, 3, 3, ["装甲"], "轰炸机", rarity="稀有"),
    # ---- 指令 ----
            OrderCard("冬季战争", "苏联", 1, mk_deal_all(1), "对所有敌方单位造成 1 点伤害", rarity="稀有"),
            OrderCard("总参二局", "波兰", 2, mk_draw(1), "抽 1 张牌", rarity="普通"),
            OrderCard("突然袭击", "德国", 2, mk_destroy_cost_le(2), "消灭一个费用不大于 2 的敌方单位（攻击力最高者优先）", rarity="稀有"),
            OrderCard("虎！虎！虎！", "日本", 2, mk_deal_all(1), "对所有敌方单位造成 1 点伤害", rarity="普通"),
            OrderCard("空中闪击", "德国", 3, mk_deal_hq(3), "对敌方总部造成 3 点伤害", rarity="稀有"),
            OrderCard("HX 175 护航队", "英国", 3, mk_draw(2), "抽 2 张牌", rarity="普通"),
            OrderCard("致命一击", "苏联", 4, mk_destroy_damaged(), "消灭一个已受损的敌方单位（攻击力最高者优先）", rarity="稀有"),
            OrderCard("死神降临", "美国", 4, mk_destroy_random(), "消灭一个随机敌方单位", rarity="稀有"),
            OrderCard("动员", "美国", 5, mk_draw(3), "抽 3 张牌", rarity="史诗"),
            OrderCard("租借法案", "英国", 7, mk_draw(4), "抽 4 张牌", rarity="稀有"),
            OrderCard("冬季攻势", "苏联", 8, mk_deal_all(4), "对所有敌方单位造成 4 点伤害", rarity="传说"),
            OrderCard("俾斯麦号", "德国", 10, mk_deal_hq(7), "对敌方总部造成 7 点伤害", rarity="传说"),
]

# ---- 芬兰（盟国，冬季战争扩展）----------------------------------------------
FINLAND_CARDS = [
    # I. STRIDSGRUPPEN: 2费 1/4，行动费2，[收缴]，对攻击力更高的单位 +2 攻击
    UnitCard("第1战斗群", "芬兰", 2, 1, 4, ["收缴"], "步兵",
             traits={"anti_strong": True}, operate=2, rarity="稀有"),
    # INFANTRY REGIMENT 13: 5费 2/4，行动费1，[警卫]，部署时每有一个敌方单位 +1/+1
    UnitCard("第13步兵团", "芬兰", 5, 2, 4, ["警卫"], "步兵",
             traits={"deploy": "per_enemy"}, operate=1, rarity="普通"),
    # LOTTA SVÄRD: 2费指令，己方所有单位 +1 防御
    OrderCard("洛塔组织", "芬兰", 2, effect_lotta,
              "己方所有单位 +1 防御", rarity="稀有"),
    # SISU: 3费反制，总部受到的伤害转嫁给敌方总部
    CounterCard("西苏精神", "芬兰", 3, "hq_damage",
                "暗置：你的总部即将受到伤害时，改为敌方总部承受", rarity="稀有"),
]


def card_database():
    """卡池：核心 61 张对齐原版 KARDS 数据（费用/攻防/关键词/效果/稀有度），
    EXTRA_CARDS 为扩充卡（数据同样取自原版 CSV；效果用通用机制近似实现）。"""
    db = [
        # ---- 德国（主国）----
        UnitCard("步兵班", "德国", 2, 2, 2, [], "步兵",
                 traits={"counter_grow": True}, rarity="普通"),
        UnitCard("装甲掷弹兵", "德国", 2, 2, 2, ["奋战"], "步兵", rarity="普通"),
        UnitCard("山地猎兵", "德国", 3, 4, 3, [], "步兵", rarity="普通"),
        UnitCard("Bf-109战斗机", "德国", 3, 3, 4, [], "战斗机", rarity="普通"),
        UnitCard("四号坦克", "德国", 6, 5, 5, [], "坦克",
                 traits={"deploy": "retreat"}, rarity="稀有"),
        UnitCard("88毫米炮", "德国", 6, 3, 4, ["伏击"], "炮兵",
                 traits={"dmg2": ["空军", "坦克"]}, rarity="稀有"),
        UnitCard("三号突击炮", "德国", 2, 2, 3, [], "坦克",
                 traits={"dmg2": ["坦克"]}, rarity="普通"),
        UnitCard("追猎者坦克歼击车", "德国", 5, 5, 3, ["装甲"], "坦克"),
        UnitCard("斯图卡俯冲轰炸机", "德国", 4, 3, 2, [], "轰炸机",
                 traits={"stuka_hq": True}, rarity="普通"),
        UnitCard("虎式坦克", "德国", 8, 8, 8, ["装甲2"], "坦克", rarity="史诗"),
        OrderCard("闪电战", "德国", 3, effect_blitzkrieg,
                  "本回合前线友方单位 +3 攻击（回合结束还原）", rarity="稀有"),
        CounterCard("反坦克炮", "德国", 2, "attack_tank", "暗置：当敌方坦克攻击时，将其消灭"),
        # ---- 苏联（主国，无反制）----
        OrderCard("动员兵", "苏联", 2, effect_conscripts,
                  "无其他效果的指令（可触发指令联动）", rarity="普通"),
        UnitCard("波波沙冲锋队", "苏联", 2, 3, 1, ["冲击"], "步兵"),
        UnitCard("近卫步兵", "苏联", 1, 1, 1, ["闪击"], "步兵",
                 traits={"hq_hurt_grow": True}, rarity="普通"),
        UnitCard("拉-7战斗机", "苏联", 4, 4, 4, [], "战斗机", rarity="稀有"),
        UnitCard("T-34坦克", "苏联", 5, 5, 5, ["闪击"], "坦克", rarity="普通"),
        UnitCard("惩戒营", "苏联", 3, 4, 2, ["冲击"], "步兵"),
        UnitCard("SU-85坦克歼击车", "苏联", 4, 5, 3, [], "坦克",
                 traits={"dmg2": ["坦克"]}, rarity="普通"),
        UnitCard("伊尔-2攻击机", "苏联", 4, 4, 3, ["装甲"], "轰炸机",
                 traits={"overflow_hq": True}, rarity="普通"),
        UnitCard("喀秋莎", "苏联", 2, 1, 2, ["闪击"], "炮兵",
                 traits={"katyusha": True}, rarity="稀有"),
        UnitCard("IS-2重型坦克", "苏联", 10, 8, 8, ["装甲2"], "坦克", rarity="传说"),
        OrderCard("为了祖国", "苏联", 3, effect_ura,
                  "本回合所有苏联单位 +3 攻击，溢出伤害转移到敌方总部", rarity="史诗"),
        # ---- 美国（主国）----
        UnitCard("游骑兵", "美国", 5, 4, 6, [], "步兵", rarity="普通"),
        UnitCard("伞兵连", "美国", 1, 2, 2, [], "步兵", rarity="普通"),
        UnitCard("海军陆战队", "美国", 3, 3, 4, ["闪击"], "步兵", rarity="稀有"),
        UnitCard("谢尔曼坦克", "美国", 4, 4, 4, [], "坦克",
                 traits={"deploy": "us_draw2"}, rarity="普通"),
        UnitCard("P-51野马", "美国", 6, 6, 4, [], "战斗机",
                 traits={"deploy": "air4"}, rarity="稀有"),
        UnitCard("M10狼獾", "美国", 2, 3, 2, [], "坦克",
                 traits={"kill_damaged_tank": True}, rarity="史诗"),
        UnitCard("远程榴弹炮", "美国", 5, 2, 4, [], "炮兵",
                 traits={"barrage": True}, rarity="传说"),
        UnitCard("M4A3E8", "美国", 4, 4, 5, [], "坦克",
                 traits={"untargetable": True, "recycle_discard": True}, rarity="史诗"),
        UnitCard("B-17空中堡垒", "美国", 10, 6, 6, ["闪击", "装甲"], "轰炸机",
                 traits={"untargetable": True}, rarity="传说"),
        CounterCard("步兵增援", "美国", 2, "friendly_death",
                    "暗置：友方单位被消灭时，随机友方单位 +2/+3",
                    effect=effect_fresh_recruits, rarity="普通"),
        CounterCard("防空火力", "美国", 2, "attack_air", "暗置：当敌方战斗机或轰炸机攻击时，将其消灭"),
        # ---- 英国（主国）----
        OrderCard("本土防卫军", "英国", 4, effect_ats,
                  "本回合敌方总部受到 3 点或以上伤害时，你抽一张牌", rarity="传说"),
        UnitCard("特种空勤团", "英国", 3, 3, 3, [], "步兵",
                 traits={"lock5": True}, rarity="史诗"),
        UnitCard("廓尔喀步枪团", "英国", 2, 1, 4, ["奋战"], "步兵",
                 traits={"deploy": "gurkha"}, rarity="史诗"),
        UnitCard("喷火战斗机", "英国", 5, 5, 5, [], "战斗机", rarity="普通"),
        UnitCard("克伦威尔坦克", "英国", 4, 3, 6, ["装甲"], "坦克",
                 traits={"kill_grow": True}, rarity="史诗"),
        UnitCard("德哈维兰蚊式", "英国", 6, 4, 4, [], "战斗机",
                 traits={"deploy": "nuke3"}, rarity="传说"),
        UnitCard("丘吉尔坦克", "英国", 5, 2, 6, ["警卫", "装甲"], "坦克", rarity="普通"),
        UnitCard("兰开斯特轰炸机", "英国", 9, 7, 4, ["闪击"], "轰炸机", rarity="稀有"),
        OrderCard("战地医疗", "英国", 1, effect_cup_of_tea,
                  "你的所有英军单位 +2 防御", rarity="普通"),
        OrderCard("皇家海军炮击", "英国", 2, effect_naval_support_uk,
                  "一个（防御最高的）友方单位攻击力变为等同于其防御力", rarity="普通"),
        OrderCard("总动员", "英国", 1, effect_double_strength,
                  "随机复制一张手中的指令牌，洗入卡组", rarity="史诗"),
        CounterCard("战术欺骗", "英国", 3, "order", "暗置：当敌方打出指令牌时，使其无效"),
        # ---- 日本（主国，无反制）----
        UnitCard("步兵联队", "日本", 2, 2, 2, ["奋战"], "步兵", rarity="普通"),
        UnitCard("九五式轻战车", "日本", 2, 2, 2, [], "坦克",
                 traits={"order_pain": True}, rarity="普通"),
        UnitCard("丛林渗透队", "日本", 3, 2, 2, ["闪击"], "步兵",
                 traits={"deploy": "snipe2"}, rarity="传说"),
        UnitCard("零式战斗机", "日本", 5, 4, 4, ["伏击"], "战斗机",
                 traits={"deploy": "bomb1"}, rarity="普通"),
        UnitCard("海军特别陆战队", "日本", 2, 1, 3, ["闪击", "奋战"], "步兵",
                 traits={"deploy": "yokosuka"}, rarity="传说"),
        UnitCard("隼式战斗机", "日本", 4, 3, 3, [], "战斗机",
                 traits={"dying_hq": 2}, rarity="普通"),
        UnitCard("九七式坦克", "日本", 3, 3, 3, [], "坦克",
                 traits={"inf_aura": True}, rarity="普通"),
        UnitCard("神风特攻队", "日本", 4, 5, 2, ["闪击"], "战斗机"),
        OrderCard("大和号战列舰", "日本", 4, effect_yamato,
                  "你的日军单位获得「亡计：对敌方总部造成 2 点伤害」（仅当前场上的单位）", rarity="传说"),
        OrderCard("万岁冲锋", "日本", 7, effect_banzai,
                  "消灭所有攻击力≤4 的陆军单位（双方），并结束你的回合", rarity="传说"),
        OrderCard("舰炮支援", "日本", 4, effect_bombing_raid,
                  "对一个随机敌方目标 3 伤，其相邻目标 2 伤", rarity="传说"),
        # ---- 意大利（盟国）----
        UnitCard("黑衫军", "意大利", 1, 2, 1, [], "步兵"),
        UnitCard("M13/40坦克", "意大利", 3, 3, 4, [], "坦克",
                 traits={"deploy": "m1340"}, rarity="稀有"),
        UnitCard("意大利炮兵团", "意大利", 3, 1, 2, [], "炮兵", rarity="史诗"),
        OrderCard("炮火准备", "意大利", 2, effect_naval_support,
                  "对一个随机敌方单位造成 2 点伤害"),
        CounterCard("山地伏击", "意大利", 4, "attack_any", "暗置：当敌方单位攻击时，将其消灭"),
        # ---- 法国（盟国）----
        UnitCard("殖民步兵", "法国", 5, 1, 1, ["闪击", "动员"], "步兵",
                 traits={"deploy": "foe_hand"}, rarity="稀有"),
        UnitCard("索玛S35", "法国", 4, 4, 4, [], "坦克"),
        OrderCard("抵抗网络", "法国", 2, effect_resistance, "抽 1 张牌，总部恢复 1 点生命"),
        CounterCard("地下抵抗", "法国", 2, "attack_inf", "暗置：当敌方步兵攻击时，将其消灭"),
        # ---- 波兰（盟国）----
        UnitCard("波兰枪骑兵", "波兰", 2, 3, 1, ["闪击"], "步兵"),
        UnitCard("华沙守军", "波兰", 5, 4, 7, [], "步兵",
                 traits={"deploy": "draw1"}, rarity="史诗"),
        OrderCard("翼骑兵冲锋", "波兰", 2, effect_hussars,
                  "随机友方单位 +1/+1，并部署一个 1/1 军团", rarity="稀有"),
        CounterCard("华沙战士", "波兰", 3, "attack_inf", "暗置：当敌方步兵攻击时，将其消灭"),
        # ---- 澳新军团（盟国）----
        UnitCard("长程沙漠群", "澳新军团", 2, 2, 2, ["闪击"], "步兵"),
        UnitCard("第25澳新营", "澳新军团", 2, 1, 5, ["警卫"], "步兵", rarity="普通"),
        UnitCard("RAAF飓风", "澳新军团", 3, 3, 2, ["闪击"], "战斗机", rarity="普通"),
        OrderCard("澳新风暴", "澳新军团", 3, effect_anzac_storm,
                  "己方所有单位 +1 攻击并获得 [冲击]"),
        OrderCard("澳新军团精神", "澳新军团", 5, effect_anzac_spirit,
                  "对所有敌方单位造成 2 点伤害，抽 2 张牌"),
        CounterCard("滩头阵地", "澳新军团", 2, "attack_air", "暗置：当敌方战斗机或轰炸机攻击时，将其消灭"),
    ]
    db.extend(EXTRA_CARDS)
    db.extend(FINLAND_CARDS)
    return {c.name: c for c in db}


# ---------------------------------------------------------------- 卡组

def allowed_cards(nation, db):
    """组卡可用卡牌：主国本国卡 + 全部盟国卡"""
    return sorted((c for c in db.values()
                   if c.nation == nation or c.nation in ALLY_NATIONS),
                  key=lambda c: (c.cost, c.name))


def validate_deck(deck, nation, db):
    """校验自定义卡组，合法返回 (True, "")，否则 (False, 错误信息)"""
    if len(deck) != DECK_SIZE:
        return False, f"卡组必须恰好 {DECK_SIZE} 张（当前 {len(deck)} 张）"
    counts = {}
    for c in deck:
        counts[c.name] = counts.get(c.name, 0) + 1
    ally_n = 0
    for name, n in counts.items():
        if n > MAX_COPIES:
            return False, f"[{name}] 超过单卡 {MAX_COPIES} 张上限"
        card = db.get(name)
        if card is None:
            return False, f"未知卡牌: {name}"
        if card.nation != nation and card.nation not in ALLY_NATIONS:
            return False, f"[{name}] 不属于 {nation} 或盟国阵营"
        if card.nation in ALLY_NATIONS:
            ally_n += n
    if ally_n > ALLY_LIMIT:
        return False, f"盟国卡超过 {ALLY_LIMIT} 张上限（当前 {ally_n} 张）"
    return True, ""


COST_WEIGHT = {1: 3, 2: 3, 3: 3, 4: 2, 5: 2, 6: 1, 7: 1}


def build_deck(nation, db, size=DECK_SIZE):
    """随机推荐卡组：主国+盟国卡池，低费加权，遵守单卡/盟国上限"""
    pool = allowed_cards(nation, db)
    weights = [COST_WEIGHT.get(c.cost, 1) for c in pool]
    counts = {}
    ally_n = 0
    deck = []
    guard = 0
    while len(deck) < size and guard < 200000:
        guard += 1
        c = random.choices(pool, weights=weights, k=1)[0]
        if counts.get(c.name, 0) >= MAX_COPIES:
            continue
        if c.nation in ALLY_NATIONS and ally_n >= ALLY_LIMIT:
            continue
        counts[c.name] = counts.get(c.name, 0) + 1
        if c.nation in ALLY_NATIONS:
            ally_n += 1
        deck.append(c)
    random.shuffle(deck)
    return deck


# ---- 原版卡组导入 ----------------------------------------------------------

# 常见原版英文名 -> 本游戏卡名（能对上多少算多少，其余行会提示）
ALIAS = {
    "infantry squad": "步兵班", "panzergrenadiers": "装甲掷弹兵",
    "panzer iv": "四号坦克", "tiger": "虎式坦克", "88mm flak": "88毫米炮",
    "stuka": "斯图卡俯冲轰炸机", "conscript": "动员兵",
    "guards infantry": "近卫步兵", "t-34": "T-34坦克", "il-2": "伊尔-2攻击机",
    "katyusha": "喀秋莎", "is-2": "IS-2重型坦克", "rangers": "游骑兵",
    "paratroopers": "伞兵连", "sherman": "谢尔曼坦克", "p-51": "P-51野马",
    "m4a3e8": "M4A3E8", "home guard": "本土防卫军", "sas": "特种空勤团",
    "spitfire": "喷火战斗机", "churchill": "丘吉尔坦克",
    "lancaster": "兰开斯特轰炸机", "zero": "零式战斗机",
    "type 97": "九七式坦克", "kamikaze": "神风特攻队", "yamato": "大和号战列舰",
    "blackshirts": "黑衫军", "m13/40": "M13/40坦克", "somua s35": "索玛S35",
    "s35": "索玛S35", "long range desert group": "长程沙漠群",
    "25th anzac battalion": "第25澳新营", "raaf hurricane": "RAAF飓风",
}


# ---- 用户数据目录 -------------------------------------------------------------
# 打包运行时: 用户数据(日志/卡组)统一存到 %USERPROFILE%\AppData\Kards-Simple-Version
if getattr(sys, "frozen", False):
    DATA_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Kards-Simple-Version")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except OSError:
        DATA_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(DATA_DIR, "logs")
_log_fh = None


def _game_log_file():
    global _log_fh
    if _log_fh is None:
        os.makedirs(LOGS_DIR, exist_ok=True)
        _log_fh = open(os.path.join(LOGS_DIR, "log.log"), "a", encoding="utf-8")
    return _log_fh


def write_game_log(msg):
    """把一条对局日志写入 logs/log.log（带时间戳，静默失败不影响游戏）"""
    try:
        fh = _game_log_file()
        fh.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        fh.flush()
    except OSError:
        pass


def setup_error_log():
    """错误输出保存到 logs/error.log：未捕获异常 + stderr 双写（控制台仍显示）"""
    os.makedirs(LOGS_DIR, exist_ok=True)

    class _Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, s):
            for st in self.streams:
                try:
                    st.write(s)
                except Exception:
                    pass
            return len(s)

        def flush(self):
            for st in self.streams:
                try:
                    st.flush()
                except Exception:
                    pass

    try:
        err_fh = open(os.path.join(LOGS_DIR, "error.log"), "a", encoding="utf-8")
        orig_err = sys.stderr

        def _hook(tp, val, tb):
            import traceback
            # 只打原始 stderr（避免 error.log 因 Tee 双写而重复）
            traceback.print_exception(tp, val, tb, file=orig_err)
            try:
                err_fh.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
                traceback.print_exception(tp, val, tb, file=err_fh)
                err_fh.flush()
            except Exception:
                pass

        sys.excepthook = _hook
        sys.stderr = _Tee(orig_err, err_fh)
    except OSError:
        pass


# ---- 卡组保存 / 载入 --------------------------------------------------------
DECKS_DIR = os.path.join(DATA_DIR, "decks")


def set_decks_dir(path):
    """账号系统：切换自组卡组目录（None 还原默认）"""
    global DECKS_DIR
    DECKS_DIR = path or os.path.join(DATA_DIR, "decks")


def save_deck_text(name, counts, nation):
    """把 {卡名:数量} 保存到 decks/<名字>.txt，返回保存路径"""
    os.makedirs(DECKS_DIR, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', "_", str(name)).strip() or "我的卡组"
    lines = [f"#国家:{nation}"]
    lines += [f"{n} {cname}" for cname, n in counts.items() if n > 0]
    path = os.path.join(DECKS_DIR, safe + ".txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def list_saved_decks(nation=None):
    """列出已保存卡组名（nation 给定时只列该国家的）"""
    if not os.path.isdir(DECKS_DIR):
        return []
    out = []
    for fn in os.listdir(DECKS_DIR):
        if not fn.endswith(".txt"):
            continue
        if nation is not None:
            try:
                with open(os.path.join(DECKS_DIR, fn), encoding="utf-8") as f:
                    head = f.readline().strip()
            except OSError:
                continue
            if head != f"#国家:{nation}":
                continue
        out.append(fn[:-4])
    return sorted(out)


def load_deck_counts(name, db):
    """读取已保存卡组，返回 (counts{卡名:数量}, 国家)；文件不存在返回 (None, "")"""
    path = os.path.join(DECKS_DIR, str(name) + ".txt")
    if not os.path.isfile(path):
        return None, ""
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip("\n") for ln in f]
    nation, body = "", []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#国家:"):
            nation = s[4:]
        elif not s.startswith("#"):
            body.append(ln)
    counts, _ = parse_deck_text("\n".join(body), db)
    return counts, nation


def parse_deck_text(text, db):
    """解析粘贴的卡组清单，返回 (counts{卡名:数量}, unmatched[原始行])

    支持每行: "3 谢尔曼坦克" / "谢尔曼坦克 x3" / "3x Sherman Tank" / "谢尔曼坦克"
    """
    counts = {}
    unmatched = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\s*[xX×]?\s+(.+)$", line)
        if m:
            n, name = int(m.group(1)), m.group(2).strip()
        else:
            m = re.match(r"^(.+?)\s+[xX×]\s*(\d+)$", line)
            if m:
                name, n = m.group(1).strip(), int(m.group(2))
            else:
                name, n = line, 1
        n = max(1, min(n, MAX_COPIES))
        card_name = _resolve_card_name(name, db)
        if card_name is None:
            unmatched.append(line)
        else:
            counts[card_name] = min(MAX_COPIES, counts.get(card_name, 0) + n)
    return counts, unmatched


def _resolve_card_name(name, db):
    if name in db:
        return name
    low = name.lower()
    if low in ALIAS and ALIAS[low] in db:
        return ALIAS[low]
    # 模糊包含（中英都可）
    for key, target in ALIAS.items():
        if key in low or low in key:
            if target in db:
                return target
    for cn in db:
        if low in cn.lower() or cn.lower() in low:
            return cn
    return None


def counts_to_deck(counts, nation, db, autofill=True):
    """把 {卡名:数量} 变成合法卡组：裁掉超限，不足则按推荐逻辑补满"""
    deck, ally_n = [], 0
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        c = db.get(name)
        if c is None:
            continue
        n = min(n, MAX_COPIES)
        if c.nation in ALLY_NATIONS:
            n = min(n, max(0, ALLY_LIMIT - ally_n))
            ally_n += n
        deck += [c] * n
    if len(deck) > DECK_SIZE:
        deck = deck[:DECK_SIZE]
    if autofill and len(deck) < DECK_SIZE:
        pool = allowed_cards(nation, db)
        weights = [COST_WEIGHT.get(c.cost, 1) for c in pool]
        extra_counts = {}
        for c in deck:
            extra_counts[c.name] = extra_counts.get(c.name, 0) + 1
        ally_n = sum(1 for c in deck if c.nation in ALLY_NATIONS)
        guard = 0
        while len(deck) < DECK_SIZE and guard < 200000:
            guard += 1
            c = random.choices(pool, weights=weights, k=1)[0]
            if extra_counts.get(c.name, 0) >= MAX_COPIES:
                continue
            if c.nation in ALLY_NATIONS and ally_n >= ALLY_LIMIT:
                continue
            extra_counts[c.name] = extra_counts.get(c.name, 0) + 1
            if c.nation in ALLY_NATIONS:
                ally_n += 1
            deck.append(c)
    random.shuffle(deck)
    return deck


# ---------------------------------------------------------------- 玩家

class Player:
    def __init__(self, name, nation, deck):
        self.name = name
        self.nation = nation
        self.hq_card = HQ_CARDS[nation]
        self.deck = deck
        self.hand = []
        self.board = []
        self.discard = []
        self.counters = []      # 暗置的反制卡
        self.hq = self.hq_card.hp
        self.kredits = 0
        self.fatigue = 0
        self.temp_buffs = []    # 本回合临时攻击增益 [(unit, amount)]，回合结束还原
        self.orders_played = 0  # 本回合已使用指令数（廓尔喀联动）
        self.ats_mark = 0       # 本土防卫军标记（1/2=标记方索引+1，0=无）

    def alive_units(self):
        return [u for u in self.board if u.defense > 0]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------- 游戏主体

class Game:
    def __init__(self, p1, p2, interactive=True):
        self.players = [p1, p2]
        self.turn_num = 0
        self.current = p1
        self.interactive = interactive
        self.over = False
        self.conceded = None    # 投降方（Player）；None = 正常打到总部倒下
        self.force_end = False  # 万岁冲锋等强制结束回合标记
        self.event_hook = None  # GUI 动画钩子: fn(event: dict)
        write_game_log(f"===== 新对局: {p1.name}({p1.nation}) vs "
                        f"{p2.name}({p2.nation}) =====")

    def log(self, msg):
        try:
            print(msg)
        except Exception:
            pass    # 控制台句柄失效（窗口被关闭/管道断开）时不再崩溃
        try:
            write_game_log(msg)
        except Exception:
            pass

    def emit(self, ev):
        """向界面发出动画事件（无钩子时忽略）"""
        if self.event_hook:
            try:
                self.event_hook(ev)
            except Exception:
                pass

    def opponent_of(self, p):
        return self.players[1] if p is self.players[0] else self.players[0]

    # ---------------- 费用与研发 ----------------
    def get_cost(self, card, p):
        """按总部研发计算实际费用"""
        cost = card.cost
        perk = p.hq_card.perk
        if perk == "tank_discount" and card.kind == "unit" and card.unit_type == "坦克":
            cost = max(1, cost - 1)
        if perk == "support_discount" and card.kind in ("order", "counter"):
            cost = max(1, cost - 1)
        return cost

    def playable_cards(self, p):
        """返回当前可打出的手牌下标列表"""
        res = []
        for i, c in enumerate(p.hand):
            if self.get_cost(c, p) > p.kredits:
                continue
            if c.kind == "unit" and not self.can_deploy(p):
                continue
            if c.kind == "counter" and len(p.counters) >= COUNTER_SLOTS:
                continue
            res.append(i)
        return res

    def can_deploy(self, p):
        """能否部署新单位：总场上限 9（前线5+支援线4），新单位进入支援线，须未满 4"""
        if len(p.board) >= BOARD_SIZE:
            return False
        rear = sum(1 for u in p.board if u.position == "后方")
        return rear < REAR_SLOTS

    # ---------------- 抽牌 ----------------
    def draw_cards(self, p, n=1):
        for _ in range(n):
            if not p.deck:
                p.fatigue += 1
                self.damage_hq(p, p.fatigue)
                self.log(f"  {p.name} 牌库已空，受到 {p.fatigue} 点疲劳伤害！")
                continue
            if len(p.hand) >= HAND_LIMIT:
                p.discard.append(p.deck.pop())
                self.log(f"  {p.name} 手牌已满，1 张牌被烧毁。")
                continue
            p.hand.append(p.deck.pop())

    # ---------------- 伤害结算 ----------------
    def damage_unit(self, unit, amount, source=None, combat=False):
        """combat=True 表示战斗伤害（攻击/反击/伏击），只有战斗伤害受[装甲]减免"""
        if amount > 0:
            red = unit.armor if combat else 0
            if red:
                amount = max(0, amount - red)
                self.log(f"  {unit.name} 的[装甲]抵消了 {red} 点伤害。")
            if amount > 0 and unit.mob:   # [动员]加成只在受到实际伤害时移除（被装甲完全抵消则保留）
                self.log(f"  {unit.name} 的[动员]加成因受伤而消失。")
                unit.attack -= unit.mob
                unit.defense -= unit.mob
                unit.max_defense -= unit.mob
                unit.mob = 0
        if amount > 0:
            unit.defense -= amount
            self.emit({"type": "unit_damage", "unit": unit, "amount": amount})
            if unit.defense <= 0:
                self.destroy_unit(unit)
                # [收缴] 只能缴获"敌人的"单位：不校验阵营的话，全场/随机
                # 清除类效果打到自己人身上也会触发缴获。
                if (source is not None and source.has("收缴")
                        and source.owner is not unit.owner
                        and unit not in unit.owner.board):
                    self.apply_confiscate(source, unit)

    def damage_hq(self, player, amount, source=None):
        """统一的总部伤害入口：处理近卫步兵成长 / 本土防卫军抽牌联动"""
        if amount <= 0 or player.hq <= 0:
            # 总部已经倒下：不再继续扣血（否则血量会一路变负，污染 ai_power 等
            # 按血量算分的逻辑）。至少保证有下限 0。
            if amount > 0 and player.hq > 0:
                player.hq = max(0, player.hq - amount)
                self.emit({"type": "hq_damage", "player": player, "amount": amount})
            self._check_game_over()
            return
        # 西苏精神: 总部即将受到伤害时，转嫁给敌方总部（反制消耗）
        c = self.check_counter(player, "hq_damage", None)
        if c:
            self.log(f"  ⚡ {player.name} 的反制 [ {c.name} ] 触发！{amount} 点伤害转嫁给敌方总部！")
            self.emit({"type": "counter", "card": c})
            self.damage_hq(self.opponent_of(player), amount, source=source)
            return
        player.hq = max(0, player.hq - amount)
        self.emit({"type": "hq_damage", "player": player, "amount": amount})
        # 近卫步兵: 你的总部受到伤害时 +1 攻击
        for u in player.board:
            if u.traits.get("hq_hurt_grow"):
                u.attack += 1
                self.log(f"  {u.name} 因总部受伤获得 +1 攻击（{u.attack}）。")
        # 本土防卫军: 本回合总部受到 3 点或以上伤害时，标记方抽一张牌
        if amount >= 3 and player.ats_mark:
            marker = self.players[player.ats_mark - 1]
            self.draw_cards(marker, 1)
            self.log(f"  [本土防卫军] {player.name} 的总部受到 {amount} 点伤害，{marker.name} 抽了 1 张牌。")
        self._check_game_over()

    def _check_game_over(self):
        """血 ≤ 0 就结束对局。

        统一收口：所有扣血路径最后都过这里，就不会出现「有人死了但 over
        还是 False」的中间态（之前只在 end_turn 里判当前方，对手死了不管）。
        """
        if not self.over and any(p.hq <= 0 for p in self.players):
            self.over = True


    def apply_confiscate(self, killer, victim):
        """[收缴]：消灭单位时把一张 1/1 副本（费用至多 3）加入手牌"""
        owner = killer.owner
        c = victim.card
        if len(owner.hand) >= HAND_LIMIT:
            self.log(f"  {owner.name} 手牌已满，无法收缴 {victim.name}。")
            return
        token = UnitCard(c.name, c.nation, min(c.cost, 3), 1, 1, [], c.unit_type)
        owner.hand.append(token)
        self.log(f"  [收缴]：{killer.name} 缴获 {victim.name}！"
                 f"一张 1/1 副本（费用 {min(c.cost, 3)}）加入手牌。")
        self.emit({"type": "confiscate", "unit": killer, "card": token})

    def destroy_unit(self, unit):
        if unit in unit.owner.board:
            unit.owner.board.remove(unit)
            unit.owner.discard.append(unit.card)
            self.emit({"type": "destroy", "unit": unit})
            self.log(f"  {unit.name} 被消灭了。")
            # [亡计]：被消灭时对敌方总部造成伤害
            if unit.dying_hq:
                foe = self.opponent_of(unit.owner)
                self.log(f"  [亡计] {unit.name} 对敌方总部造成 {unit.dying_hq} 点伤害！")
                self.damage_hq(foe, unit.dying_hq, source=unit)
            # 克伦威尔: 敌方单位被消灭时 +2 攻击
            for u in self.opponent_of(unit.owner).board:
                if u.traits.get("kill_grow"):
                    u.attack += 2
                    self.log(f"  {u.name} 因敌方单位被消灭获得 +2 攻击（{u.attack}）。")
            # 步兵增援等反制：友方单位被消灭时触发
            for c in list(unit.owner.counters):
                if c.trigger == "friendly_death":
                    unit.owner.counters.remove(c)
                    unit.owner.discard.append(c)
                    self.log(f"  ⚡ {unit.owner.name} 的反制 [ {c.name} ] 触发！")
                    self.emit({"type": "counter", "card": c})
                    if c.effect:
                        c.effect(self, unit.owner)

    # ---------------- 部署与位置 ----------------
    def next_slot(self, p):
        used = {u.slot for u in p.board if u.slot is not None}
        for i in range(BOARD_SIZE):
            if i not in used:
                return i
        return None

    def deploy_unit(self, p, card):
        """部署一个单位（含位置编号分配），返回单位或 None"""
        if len(p.board) >= BOARD_SIZE:
            return None
        u = Unit(card, p)
        u.slot = self.next_slot(p)
        if "闪击" not in u.keywords:
            u.fresh_deploy = True   # 无[闪击]的单位部署当回合不能移动/攻击
        p.board.append(u)
        self.emit({"type": "deploy", "unit": u, "player": p})
        # 九七式坦克光环：友方步兵部署时 +1 攻击
        for other in p.board:
            if other is not u and other.traits.get("inf_aura") and u.unit_type == "步兵":
                u.attack += 1
                self.log(f"  {other.name} 的光环使 {u.name} +1 攻击（{u.attack}）。")
        return u

    # ---------------- 部署效果（原版"部署："） ----------------
    @staticmethod
    def _strongest(units):
        return max(units, key=lambda u: (u.attack, u.defense)) if units else None

    def on_deploy(self, unit):
        """结算从手牌打出单位时的"部署"效果（自动选目标）"""
        d = unit.traits.get("deploy")
        if not d:
            return
        p = unit.owner
        foe = self.opponent_of(p)
        if d == "retreat":      # 四号坦克: 使一个（攻击力最高的）前线敌方单位撤回后方
            t = self._strongest([u for u in foe.board if u.position == "前线"])
            if t:
                t.position = "后方"
                self.log(f"  [部署] {unit.name} 迫使 {t.name} 撤回了后方。")
                self.emit({"type": "move", "unit": t})
            else:
                self.log("  [部署] 敌方没有前线单位，撤退效果落空。")
        elif d == "per_enemy":  # 第13步兵团: 每有一个敌方单位，+1/+1
            n = len(foe.board)
            if n:
                unit.attack += n
                unit.defense += n
                unit.max_defense += n
                self.log(f"  [部署] {unit.name} 因敌方 {n} 个单位获得 +{n}/+{n}（{unit.attack}/{unit.defense}）。")
        elif d == "us_draw2":   # 谢尔曼: 前线有美军单位则抽 2 张牌
            if any(u.position == "前线" and u.card.nation == "美国" for u in p.board):
                self.draw_cards(p, 2)
                self.log(f"  [部署] {unit.name}：前线有美军单位，抽了 2 张牌！")
        elif d == "air4":       # P-51: 随机对一个敌方空军造成 4 点伤害
            air = [u for u in foe.board if u.unit_type in ("战斗机", "轰炸机")]
            if air:
                t = random.choice(air)
                self.log(f"  [部署] {unit.name} 对 {t.name} 造成 4 点伤害！")
                self.damage_unit(t, 4, source=unit)
            else:
                self.log("  [部署] 敌方没有空军单位。")
        elif d == "nuke3":      # 蚊式: 对一个（攻击力最高的）敌方单位造成 3 点伤害
            t = self._strongest([u for u in foe.board if u.defense > 0])
            if t:
                self.log(f"  [部署] {unit.name} 对 {t.name} 造成 3 点伤害！")
                self.damage_unit(t, 3, source=unit)
        elif d == "bomb1":      # 零战: 造成 1 点伤害（随机敌方单位，无则打总部）
            live = [u for u in foe.board if u.defense > 0]
            if live:
                t = random.choice(live)
                self.log(f"  [部署] {unit.name} 对 {t.name} 造成 1 点伤害。")
                self.damage_unit(t, 1, source=unit)
            else:
                self.log(f"  [部署] {unit.name} 对敌方总部造成 1 点伤害。")
                self.damage_hq(foe, 1, source=unit)
        elif d == "snipe2":     # 丛林渗透队: 消灭一个攻击力≤2 的（攻击力最高的）敌方单位
            t = self._strongest([u for u in foe.board
                                 if u.defense > 0 and u.attack <= 2])
            if t:
                self.log(f"  [部署] {unit.name} 偷袭并消灭了 {t.name}！")
                self.destroy_unit(t)
            else:
                self.log("  [部署] 没有攻击力≤2 的敌方单位可供消灭。")
        elif d == "gurkha":     # 廓尔喀: 本回合每使用过 1 个指令 +1 攻击
            n = p.orders_played
            if n:
                unit.attack += n
                self.log(f"  [部署] {unit.name} 因本回合使用过 {n} 个指令获得 +{n} 攻击（{unit.attack}）。")
        elif d == "yokosuka":   # 横须贺: 每控制一个 0 费单位 +1/+1
            n = sum(1 for u in p.board if u is not unit and u.card.cost == 0)
            if n:
                unit.attack += n
                unit.defense += n
                unit.max_defense += n
                self.log(f"  [部署] {unit.name} 因 {n} 个 0 费单位获得 +{n}/+{n}（{unit.attack}/{unit.defense}）。")
        elif d == "m1340":      # M13/40: 单位数多于对手→闪击+奋战，否则→警卫
            if len(p.board) > len(foe.board):
                unit.keywords += ["闪击", "奋战"]
                unit.can_attack = True
                self.log(f"  [部署] {unit.name} 获得了 [闪击] 和 [奋战]！")
            else:
                unit.keywords.append("警卫")
                self.log(f"  [部署] {unit.name} 获得了 [警卫]。")
        elif d == "foe_hand":   # 殖民步兵: 对手每有一张手牌 +1/+1
            n = len(foe.hand)
            if n:
                unit.attack += n
                unit.defense += n
                unit.max_defense += n
                self.log(f"  [部署] {unit.name} 因对手的 {n} 张手牌获得 +{n}/+{n}（{unit.attack}/{unit.defense}）。")
        elif d == "draw1":      # 华沙守军(近似原版情报联动): 抽一张牌
            self.draw_cards(p, 1)
            self.log(f"  [部署] {unit.name} 抽了 1 张牌。")

    # ---------------- 前线机制 ----------------
    def frontline_used(self):
        return sum(1 for p in self.players for u in p.board if u.position == "前线")

    def frontline_owner(self):
        """当前占领前线的一方（None 表示无人占领，可抢占）"""
        for p in self.players:
            if any(u.position == "前线" for u in p.board):
                return p
        return None

    def frontline_status(self):
        """命令行界面用：描述前线占领状态（以当前行动方视角）"""
        owner = self.frontline_owner()
        if owner is None:
            return "无人占领（可抢占）"
        n = sum(1 for u in owner.board if u.position == "前线")
        side = "我方" if owner is self.current else "敌方"
        return f"{side}占领 {n}/{FRONTLINE_SLOTS}"

    def can_take_frontline(self, p):
        """前线同一时刻只能被一方占领：敌方占线时无法上前线"""
        if any(u.position == "前线" for u in self.opponent_of(p).board):
            return False
        return sum(1 for u in p.board if u.position == "前线") < FRONTLINE_SLOTS

    def move_unit(self, unit, dest):
        """移动单位到 前线/后方：消耗行动费，每单位每回合一次。
        规则：无[闪击]部署当回合不能移动；步兵移动与攻击二选一。"""
        if unit.moved:
            self.log(f"  {unit.name} 本回合已经移动过了。")
            return False
        if unit.fresh_deploy:
            self.log(f"  {unit.name} 刚加入战场，需要[闪击]才能立即移动！")
            return False
        if unit.unit_type == "步兵" and unit.attacks_made > 0:
            self.log(f"  {unit.name}（步兵）本回合已攻击过，不能再移动！")
            return False
        if dest == "前线":
            if unit.position == "前线":
                return False
            if not self.can_take_frontline(unit.owner):
                enemy = self.opponent_of(unit.owner)
                if any(u.position == "前线" for u in enemy.board):
                    self.log("  前线被敌方占领！先清掉敌方前线单位才能上前线。")
                else:
                    self.log("  我方前线位已满（4 个）！")
                return False
        else:
            if unit.position == "后方":
                return False
        # 行动费：移动同样消耗（不足则失败）
        if unit.operate:
            if unit.owner.kredits < unit.operate:
                self.log(f"  {unit.name} 移动需要 {unit.operate} 点行动费，Kredits 不足！")
                return False
            unit.owner.kredits -= unit.operate
            self.log(f"  {unit.name} 支付 {unit.operate} 点行动费进行移动（剩余 {unit.owner.kredits}）。")
        if dest == "前线":
            unit.position = "前线"
            self.log(f"  {unit.name} 奔赴前线，占领前线！")
        else:
            unit.position = "后方"
            self.log(f"  {unit.name} 撤回了后方。")
        unit.moved = True
        return True

    # ---------------- 攻击 ----------------
    def attack_targets(self, attacker):
        """可攻击的敌方单位。
        - 前线单位可攻击敌方全场；后方只有空军/炮兵能攻击（仅限敌方前线单位）
        - 炮兵/轰炸机无视[警卫]
        - 轰炸机：敌方前线有战斗机时必须优先攻击战斗机"""
        enemy = self.opponent_of(attacker.owner)
        if attacker.position == "前线":
            pool = list(enemy.board)
        else:
            if attacker.unit_type not in RANGED_TYPES:
                return []
            pool = [u for u in enemy.board if u.position == "前线"]
        if attacker.unit_type == "轰炸机":
            fighters = [u for u in pool if u.unit_type == "战斗机"]
            if fighters:
                return fighters          # 必须优先打战斗机
        if attacker.unit_type in ("炮兵", "轰炸机"):
            return pool                  # 无视警卫
        guards = [u for u in pool if u.has("警卫")]
        if not guards:
            return pool
        res = []
        for u in pool:
            if u in guards:
                res.append(u)
                continue
            protected = any(g is not u and g.slot is not None and u.slot is not None
                            and abs(g.slot - u.slot) == 1 for g in guards)
            if not protected:
                res.append(u)
        return res or pool

    def can_hit_hq(self, attacker):
        """前线单位（或支援线的空军/炮兵）能直击敌方总部；
        敌方#0位警卫保护总部，但炮兵/轰炸机无视警卫"""
        if attacker.position != "前线" and attacker.unit_type not in RANGED_TYPES:
            return False, "只有前线单位能攻击敌方总部！（空军/炮兵在支援线也可以）"
        enemy = self.opponent_of(attacker.owner)
        if attacker.unit_type not in ("炮兵", "轰炸机"):
            if any(u.has("警卫") and u.slot == 0 for u in enemy.board):
                return False, "敌方#0位（紧邻总部）有警卫，总部受到保护！"
        return True, ""

    def hq_damage(self, attacker):
        return attacker.attack + (2 if attacker.unit_type == "轰炸机" else 0)

    def unit_ready(self, u):
        """单位本回合是否还能攻击（含[奋战]两次、特种空勤团封锁、行动费、步兵限制）"""
        if not u.can_attack or u.attacks_made >= u.max_attacks:
            return False
        if u.fresh_deploy:
            return False            # 无[闪击]部署当回合不能攻击
        if u.operate and u.owner.kredits < u.operate:
            return False            # 行动费不足
        if u.unit_type == "步兵" and u.moved:
            return False            # 步兵：移动与攻击每回合二选一
        if u.attack >= 5 and any(x.traits.get("lock5")
                                 for pl in self.players for x in pl.board):
            return False
        return True

    def combat_damage(self, attacker, target):
        """攻击者对目标的战斗伤害：含双倍伤害特性与喀秋莎随机加成"""
        dmg = attacker.attack
        t2 = attacker.traits.get("dmg2")
        if t2 and (target.unit_type in t2
                   or (target.unit_type in ("战斗机", "轰炸机") and "空军" in t2)):
            dmg *= 2
            self.log(f"  {attacker.name} 对{target.unit_type}造成双倍伤害！")
        if attacker.traits.get("katyusha"):
            extra = random.randint(0, 1)
            if extra:
                dmg += extra
                self.log(f"  喀秋莎的火箭弹造成 {extra} 点额外伤害！")
        if attacker.traits.get("anti_strong") and target.attack > attacker.attack:
            dmg += 2
            self.log(f"  {attacker.name} 面对更强的敌人，攻击 +2！")
        return dmg

    def _interceptor(self, defender_side):
        """拦截者：防守方攻击力最高的存活战斗机（轰炸机攻击非战斗机目标时触发）"""
        fs = [u for u in defender_side.board
              if u.unit_type == "战斗机" and u.defense > 0]
        return max(fs, key=lambda u: (u.attack, u.defense)) if fs else None

    def do_attack(self, attacker, target):
        # 战斗机拦截：轰炸机攻击非战斗机目标时，敌方战斗机紧急升空
        if attacker.unit_type == "轰炸机" and target.unit_type != "战斗机":
            fi = self._interceptor(target.owner)
            if fi is not None:
                self.log(f"  ⚡ {fi.name} 紧急升空拦截 {attacker.name}！攻击被迫转向！")
                target = fi
        self.log(f"  {attacker.name} 攻击 {target.name}！")
        # 行动费：攻击前支付（不足则取消攻击）
        if attacker.operate:
            if attacker.owner.kredits < attacker.operate:
                self.log(f"  {attacker.name} 需要 {attacker.operate} 点行动费，Kredits 不足，攻击取消！")
                return
            attacker.owner.kredits -= attacker.operate
            self.log(f"  {attacker.name} 支付 {attacker.operate} 点行动费（剩余 {attacker.owner.kredits}）。")
        # 反制触发
        counter = self.check_counter(target.owner, "attack", attacker)
        if counter:
            self.log(f"  ⚡ {target.owner.name} 的反制 [ {counter.name} ] 触发！{attacker.name} 被消灭！")
            self.emit({"type": "counter", "card": counter})
            self.destroy_unit(attacker)
            attacker.attacks_made += 1
            return
        # [伏击]：防守方先出手；攻击者若阵亡则攻击不生效
        if target.has("伏击"):
            self.log(f"  {target.name} 的[伏击]先发制人！")
            self.damage_unit(attacker, self.combat_damage(target, attacker),
                             source=target, combat=True)
            if attacker.defense <= 0 or attacker not in attacker.owner.board:
                self.log(f"  {attacker.name} 在伏击中阵亡，攻击失败！")
                attacker.attacks_made += 1
                return
        # 远程榴弹炮：攻击改为 3 点伤害随机分配至敌方所有目标
        if attacker.traits.get("barrage"):
            foe = self.opponent_of(attacker.owner)
            if any(u.defense > 0 for u in foe.board):
                self.log(f"  {attacker.name} 的火力随机覆盖敌方阵地（3 点伤害）！")
                for _ in range(3):
                    live = [u for u in foe.board if u.defense > 0]
                    if not live:
                        break
                    self.damage_unit(random.choice(live), 1, source=attacker, combat=True)
            else:
                self.log(f"  {attacker.name} 对敌方总部造成 3 点伤害！")
                self.damage_hq(foe, 3, source=attacker)
        else:
            dmg = self.combat_damage(attacker, target)
            pre_def = target.defense
            self.damage_unit(target, dmg, source=attacker, combat=True)
            died = target not in target.owner.board or target.defense <= 0
            if died:
                overflow = dmg - pre_def
                if overflow > 0 and (attacker.traits.get("overflow_hq")
                                     or attacker.overflow_turn):
                    self.log(f"  {attacker.name} 的溢出 {overflow} 点伤害转移到敌方总部！")
                    self.damage_hq(self.opponent_of(attacker.owner), overflow,
                                   source=attacker)
            elif attacker.traits.get("kill_damaged_tank") and target.unit_type == "坦克":
                self.log(f"  {attacker.name} 重创 {target.name}，将其消灭！")
                self.destroy_unit(target)
        self.emit({"type": "attack", "attacker": attacker, "target": target})
        # 冲击：攻击单位免反击，攻击后消耗
        shocked = attacker.has("冲击")
        if shocked:
            attacker.keywords.remove("冲击")
            self.log(f"  {attacker.name} 的[冲击]已消耗。")
        # 反击规则：目标未死亡才会反击；冲击免反击；[伏击]目标已先出手不再反击；
        # 轰炸机不反击（打它不吃反击）；炮兵攻击永远不吃反击；
        # 轰炸机只在攻击战斗机时吃反击（高空投弹躲开地面火力）
        if target in target.owner.board and target.defense > 0:
            if shocked:
                self.log(f"  [冲击]生效：{attacker.name} 不受反击！")
            elif target.has("伏击"):
                pass
            elif target.unit_type in NO_COUNTER_DEAL:
                self.log(f"  {target.name}（轰炸机）不进行反击。")
            elif attacker.unit_type == "炮兵":
                self.log(f"  {attacker.name}（炮兵）远处开火，不受反击！")
            elif attacker.unit_type == "轰炸机" and target.unit_type != "战斗机":
                self.log(f"  {attacker.name}（轰炸机）高空投弹，不受反击！")
            else:
                self.log(f"  {target.name} 反击！{attacker.name} 受到 {target.attack} 点伤害。")
                self.damage_unit(attacker, target.attack, source=target, combat=True)
        attacker.attacks_made += 1

    def do_hq_attack(self, attacker):
        enemy = self.opponent_of(attacker.owner)
        # 战斗机拦截轰炸机对总部的空袭
        if attacker.unit_type == "轰炸机":
            fi = self._interceptor(enemy)
            if fi is not None:
                self.log(f"  ⚡ {fi.name} 紧急升空拦截 {attacker.name} 的空袭！")
                self.do_attack(attacker, fi)
                return
        counter = self.check_counter(enemy, "attack", attacker)
        if counter:
            self.log(f"  ⚡ {enemy.name} 的反制 [ {counter.name} ] 触发！{attacker.name} 被消灭！")
            self.emit({"type": "counter", "card": counter})
            self.destroy_unit(attacker)
            attacker.attacks_made += 1
            return
        # 行动费：攻击总部同样需要支付
        if attacker.operate:
            if attacker.owner.kredits < attacker.operate:
                self.log(f"  {attacker.name} 需要 {attacker.operate} 点行动费，Kredits 不足，攻击取消！")
                return
            attacker.owner.kredits -= attacker.operate
            self.log(f"  {attacker.name} 支付 {attacker.operate} 点行动费（剩余 {attacker.owner.kredits}）。")
        dmg = self.hq_damage(attacker)
        bonus = "（轰炸机 +2）" if attacker.unit_type == "轰炸机" else ""
        if attacker.traits.get("katyusha"):
            extra = random.randint(0, 1)
            if extra:
                dmg += extra
                bonus += f"，喀秋莎额外 +{extra}"
        self.damage_hq(enemy, dmg, source=attacker)
        attacker.attacks_made += 1
        self.log(f"  {attacker.name} 直击敌方总部，造成 {dmg} 点伤害{bonus}！")
        # 斯图卡：对敌方总部造成伤害时，弃掉对手一张手牌
        if attacker.traits.get("stuka_hq") and enemy.hand:
            lost = enemy.hand.pop(random.randrange(len(enemy.hand)))
            enemy.discard.append(lost)
            self.log(f"  {attacker.name} 迫使 {enemy.name} 弃掉了一张手牌！")
            self.emit({"type": "discard", "player": enemy, "card": lost})
            # M4A1: 被对手效果弃掉时，从卡组中抽回此单位
            if getattr(lost, "traits", None) and lost.traits.get("recycle_discard"):
                for i, dc in enumerate(enemy.deck):
                    if dc.name == lost.name:
                        enemy.hand.append(enemy.deck.pop(i))
                        self.log(f"  [M4A1] {lost.name} 从卡组中被抽了回来！")
                        break

    def check_counter(self, player, event, ctx):
        """检查并触发玩家的反制卡，触发则返回该卡"""
        for c in player.counters:
            if c.matches(event, ctx):
                player.counters.remove(c)
                player.discard.append(c)
                # 步兵班: 你的反制被触发时，此单位 +2/+2
                for u in player.board:
                    if u.traits.get("counter_grow"):
                        u.attack += 2
                        u.defense += 2
                        u.max_defense += 2
                        self.log(f"  {u.name} 因反制触发获得 +2/+2（{u.attack}/{u.defense}）。")
                return c
        return None

    # ---------------- 出牌 ----------------
    def play_card(self, p, idx):
        # 边界校验：负索引在 Python 里是合法的（-1 取最后一张），网络/插件
        # 传来的 idx 只挡了正向越界，负数会静默打出错误的手牌。
        if not isinstance(idx, int) or not (0 <= idx < len(p.hand)):
            self.log("  手牌编号无效！")
            return False
        card = p.hand[idx]
        cost = self.get_cost(card, p)
        if cost > p.kredits:
            self.log("  Kredits 不足！")
            return False
        p.kredits -= cost
        p.hand.pop(idx)
        if card.kind == "unit":
            if len(p.board) >= BOARD_SIZE:
                self.log("  场上已满，无法部署！")
                p.hand.insert(idx, card)
                p.kredits += cost
                return False
            unit = self.deploy_unit(p, card)
            self.log(f"  {p.name} 部署了 {unit}")
            self.on_deploy(unit)
        elif card.kind == "counter":
            if len(p.counters) >= COUNTER_SLOTS:
                self.log(f"  反制区已满（最多 {COUNTER_SLOTS} 张）！")
                p.hand.insert(idx, card)
                p.kredits += cost
                return False
            p.counters.append(card)
            self.log(f"  {p.name} 暗中布置了一张反制卡……")
            self.emit({"type": "counter_set", "player": p})
        else:
            # 指令牌可能被敌方的反制（如战术欺骗）无效化
            counter = self.check_counter(self.opponent_of(p), "order", card)
            if counter:
                self.log(f"  ⚡ {p.name} 打出指令 [ {card.name} ]——"
                         f"敌方反制 [ {counter.name} ] 触发，指令被无效化！")
                self.emit({"type": "counter", "card": counter})
                p.discard.append(card)
                return True
            self.log(f"  {p.name} 打出指令牌 [ {card.name} ]")
            self.emit({"type": "order", "card": card, "player": p})
            p.orders_played += 1
            # 九五式轻战车：双方每次使用指令，其总部受 1 点伤害
            for pl in self.players:
                for u in pl.board:
                    if u.traits.get("order_pain"):
                        self.log(f"  {u.name} 的联动：{p.name} 的总部受到 1 点伤害！")
                        self.damage_hq(p, 1, source=u)
            card.effect(self, p)
            p.discard.append(card)
        return True

    # ---------------- 回合流程 ----------------
    def start_turn(self):
        # 对局已结束（有人总部倒下 / 投降）就不要再推进回合了。
        # GUI 有多处会无条件调用 start_turn，缺这道守卫时死掉的玩家
        # 还会继续抽牌、拿 Kredits、结算动员。
        if self.over or self.current.hq <= 0:
            return
        self.turn_num += 1
        self.force_end = False
        p = self.current
        p.kredits = min(MAX_KREDITS, self.turn_num // 2 + 1)
        self.log(f"\n===== 第 {self.turn_num} 回合 | {p.name} ({p.nation}) =====")
        self.log(f"  Kredits: {p.kredits} | HQ: {p.hq} | 手牌 {len(p.hand)} 张")
        if p.hq_card.perk == "regen" and p.hq < p.hq_card.hp:
            p.hq += 1
            self.emit({"type": "hq_heal", "player": p, "amount": 1})
            self.log(f"  [研发] 纵深防御：总部恢复 1 点生命（{p.hq} HP）。")
        self.draw_cards(p, 1)
        p.orders_played = 0
        for u in p.board:
            u.can_attack = True
            u.attacks_made = 0
            u.moved = False
            u.fresh_deploy = False
            # [动员]：回合开始 +1/+1，直到受伤
            if "动员" in u.keywords:
                u.attack += 1
                u.defense += 1
                u.max_defense += 1
                u.mob += 1
                self.log(f"  [动员] {u.name} 获得 +1/+1（{u.attack}/{u.defense}）。")

    def end_turn(self):
        # 临时增益必须在任何早退之前还原，否则「闪电战 / 呜啦！」的加攻
        # 会在对局结束的那一刻永久留在场上（temp_buffs 再没机会清空）。
        self._cleanup_own_turn()
        if any(p.hq <= 0 for p in self.players):
            # 任一方总部倒下就结束。只看 self.current 会漏掉「对手已死但
            # 还没轮到我方结算」的情形，导致死人继续抽牌拿 Kredits。
            self.over = True
            return
        self.force_end = False
        self.current = self.opponent_of(self.current)

    def _cleanup_own_turn(self):
        """回合结束时的收尾：还原临时攻击增益与各类临时标记"""
        for u, amount in self.current.temp_buffs:
            if u in self.current.board:
                u.attack -= amount
                self.log(f"  {u.name} 的本回合攻击加成消失（{u.attack}）。")
        self.current.temp_buffs = []
        for u in self.current.board:
            u.overflow_turn = False
        self.opponent_of(self.current).ats_mark = 0

    # ---------------- 界面（命令行）----------------
    def show_board(self):
        me, foe = self.current, self.opponent_of(self.current)
        print("\n--- 敌方 ---")
        print(f"  [{foe.name}] {foe.hq_card.name} HQ: {foe.hq} HP | 手牌 {len(foe.hand)} 张 | "
              f"Kredits: {foe.kredits} | 反制 ❓×{len(foe.counters)}")
        for i, u in enumerate(foe.board):
            print(f"    E{i}: {u}")
        print(f"  --- 前线: {self.frontline_status()} ---")
        print("--- 我方 ---")
        for i, u in enumerate(me.board):
            print(f"    M{i}: {u}")
        print(f"  [{me.name}] {me.hq_card.name} HQ: {me.hq} HP | Kredits: {me.kredits} | "
              f"研发: {me.hq_card.perk_desc}")
        if me.counters:
            print("  反制区: " + " | ".join(c.name for c in me.counters))
        print("--- 手牌 ---")
        for i, c in enumerate(me.hand):
            cost = self.get_cost(c, me)
            tag = "" if cost <= me.kredits else " (资源不足)"
            if c.kind == "unit":
                kws = "".join(f"[{k}]" for k in c.keywords)
                op = f" ⚡行动{c.operate}" if getattr(c, "operate", 0) else ""
                print(f"    {i}: {c.name} 费{cost}{op} {c.unit_type} {c.attack}/{c.defense} {kws}{tag}")
            elif c.kind == "counter":
                print(f"    {i}: [反制] {c.name} 费{cost} - {c.desc}{tag}")
            else:
                print(f"    {i}: [指令] {c.name} 费{cost} - {c.desc}{tag}")

    # ---------------- 玩家操作 ----------------
    def human_turn(self):
        p = self.current
        while True:
            self.show_board()
            if p.hq <= 0:
                return
            cmd = input("\n指令 (h=帮助, a N=攻击, p N=出牌, f N=上前线, b N=撤后方, e=结束回合): ").strip().lower()
            if cmd == "e":
                break
            elif cmd == "h":
                print("  p N   打出手牌第 N 张\n  a X Y 用我方 M 攻击敌方 E(或 h 打总部)\n"
                      "  f N   将我方单位 N 调往前线（耗行动费, 每回合一次; 前线同一时刻只能被一方占领, 占领方最多5个单位）\n"
                      "  b N   将我方单位 N 撤回后方（耗行动费）")
                for line in RULES_TEXT:
                    print("  " + line)
                print("  e     结束回合")
            elif cmd.startswith("p"):
                try:
                    idx = int(cmd.split()[1])
                    self.play_card(p, idx)
                except (IndexError, ValueError):
                    print("  格式: p <手牌编号>")
            elif cmd.startswith("f"):
                try:
                    mi = int(cmd.split()[1].replace("m", ""))
                    self.move_unit(p.board[mi], "前线")
                except (IndexError, ValueError):
                    print("  格式: f <我方编号>")
            elif cmd.startswith("b"):
                try:
                    mi = int(cmd.split()[1].replace("m", ""))
                    self.move_unit(p.board[mi], "后方")
                except (IndexError, ValueError):
                    print("  格式: b <我方编号>")
            elif cmd.startswith("a"):
                try:
                    mi, ti = cmd.split()[1], cmd.split()[2]
                    mi = int(mi.replace("m", ""))
                    if mi >= len(p.board):
                        print("  编号无效")
                        continue
                    attacker = p.board[mi]
                    if not self.unit_ready(attacker):
                        print("  该单位本回合无法攻击（部署当回合需[闪击]；步兵移动过不能攻击；或行动费不足/攻击次数用完）")
                        continue
                    targets = self.attack_targets(attacker)
                    if ti == "h":
                        ok, msg = self.can_hit_hq(attacker)
                        if not ok:
                            print(f"  {msg}")
                            continue
                        self.do_hq_attack(attacker)
                    else:
                        ti = int(ti.replace("e", ""))
                        if ti >= len(self.opponent_of(p).board):
                            print("  编号无效")
                            continue
                        target = self.opponent_of(p).board[ti]
                        if target not in targets:
                            if attacker.position == "后方":
                                print("  后方单位只能攻击敌方前线单位！")
                            else:
                                print("  该单位被相邻的警卫保护，必须先攻击警卫！")
                            continue
                        self.do_attack(attacker, target)
                except (IndexError, ValueError):
                    print("  格式: a <我方编号> <敌方编号|h>")
            else:
                print("  未知指令，输入 h 查看帮助")
            for pl in self.players:
                for u in list(pl.board):
                    if u.defense <= 0:
                        self.destroy_unit(u)
            if self.force_end:
                print("  万岁冲锋！回合被迫结束。")
                break

    # ---------------- AI ----------------
    def ai_turn(self):
        """一次性执行完整个 AI 回合（命令行/演示模式用）"""
        for _ in self.ai_steps():
            pass

    # ---------------- AI 投降判定 ----------------

    def ai_power(self, p):
        """估算一方当前的"场面强度"：总部血 + 场上单位的攻防 + 手牌/牌库资源。

        单位按 攻击+防御 计（防御权重略高，因为站得住才有输出），
        手牌按 每张 2 点、牌库按 每 5 张 1 点折算成等效血量。
        结果只用于比较双方强弱，绝对值没有意义。
        """
        score = p.hq * 1.0
        for u in p.board:
            score += u.attack + u.defense * 1.15
            # 关键特性（警卫/亡计等）略微加分
            score += 0.4 * len([k for k in u.keywords if k in ("警卫", "伏击", "重甲", "亡计")])
        score += 2.0 * len(p.hand)
        score += 1.0 * len(p.deck) / 5.0
        score += 1.5 * len(p.counters)          # 暗置反制 = 潜在收益
        return score

    def ai_concede_reason(self, p):
        """给投降补一句人话理由（写进战斗日志）"""
        foe = self.opponent_of(p)
        return (f"总部 {p.hq} vs {foe.hq}，"
                f"场面 {len(p.board)} 单位 vs {len(foe.board)} 单位")

    def ai_should_concede(self, p):
        """AI 判断自己已经彻底没胜算 → 投降。

        判定分两种情形（都要求"确实已经输了"，宁可多打一会儿也不早退）：

          1. **濒死必死**：总部血 ≤ AI_CONCEDE_HP，且对方场上现有单位
             一轮能打出的伤害就足以打死我，而我没有任何即时保命手段
             （血量再少也不救——救不回来就是白送）

          2. **资源枯竭 + 场面碾压**：总部血量已经低于 AI_CONCEDE_HP2
             （不是"还健康"），牌库抽干、手里也没有能打出的牌，
             同时对方场面强度是我方 AI_CONCEDE_RATIO 倍以上。
             三个条件同时成立才算——只满足"打不出牌"是后期常态，不能投。

        两种情形都额外要求"本回合已经没有攻击可打"：如果场上还有 ready
        的单位能出手，就应该先打完这一轮再谈投降（手里攒着一次攻击却
        直接认输，看起来像 AI 在摆烂）。

        返回 True 表示该投降。真人玩家不受影响（只在 ai_steps 里调用）。
        """
        if not AI_AUTO_CONCEDE:
            return False
        g = self
        foe = g.opponent_of(p)

        incoming = self.incoming_damage(foe)
        my, his = self.ai_power(p), self.ai_power(foe)

        # --- 情形 0：还有能出手的单位就先打完，不打完不许投 ---
        if any(self.unit_ready(u) and self.attack_targets(u) for u in p.board):
            return False

        # --- 情形 1：濒死必死 ---
        if p.hq <= AI_CONCEDE_HP and incoming >= p.hq:
            # 手里有牌也可能翻盘（治疗/清场/斩杀对面总部），再给自己一次机会
            if self.playable_cards(p) and p.hq > 2:
                return False
            return True

        # --- 情形 2：资源枯竭 + 场面碾压 + 血线已低 ---
        if p.hq > AI_CONCEDE_HP2:
            return False                        # 血还很健康，谈不上没胜算
        if p.hand and self.playable_cards(p):
            return False                        # 还有牌可打，别投
        if len(p.deck) > AI_CONCEDE_DECK_LEFT:
            return False                        # 牌库还有货，后面能抽到东西
        if p.hand and not AI_CONCEDE_IGNORE_HAND:
            return False                        # 手里还攒着牌（只是暂时打不出）
        return his >= my * AI_CONCEDE_RATIO

    def incoming_damage(self, foe):
        """对方场上所有单位一轮内能打出的**总部**伤害（含轰炸机 +2）。

        只统计真的打得到总部的单位。曾经把打不到总部的单位按 0.5 折算
        进来，结果一个后方步兵 9 攻也能凑出 4.5 点"斩杀伤害"，
        濒死判定（incoming >= hq）被误判，AI 会在其实安全时投降。
        """
        total = 0
        for u in foe.board:
            if u.defense <= 0:
                continue
            if self.can_hit_hq(u)[0]:
                total += self.hq_damage(u) * max(1, u.max_attacks)   # 奋战可打两次
        return total

    def ai_steps(self):
        """AI 回合的分步执行器：每完成一个动作 yield 一次，供 GUI 逐步播放动画"""
        p = self.current
        # 对局已结束就别再动了（GUI 可能在结算后又推进了一次）
        if self.over:
            return
        # 开局先判断有没有胜算，没有就直接投降（省得陪打到最后一滴血）
        if self.ai_should_concede(p):
            self.over = True
            self.conceded = p
            yield {"type": "concede", "player": p, "reason": self.ai_concede_reason(p)}
            return
        acted = True
        while acted:
            acted = False
            if self.force_end:
                break
            for idx in sorted(self.playable_cards(p),
                              key=lambda i: -self.get_cost(p.hand[i], p)):
                card = p.hand[idx]
                if self.play_card(p, idx):
                    acted = True
                    yield {"type": "play", "card": card}
                    break
            for pl in self.players:
                for u in list(pl.board):
                    if u.defense <= 0:
                        self.destroy_unit(u)
        if self.force_end:
            yield {"type": "end"}
            return
        # 机动：前线可占时优先把坦克调往前线（坦克移动后仍可攻击；
        # 空军/炮兵在支援线即可攻击无需上前线，步兵移动后当回合无法攻击）
        for u in list(p.board):
            if (u.position == "后方" and not u.moved and not u.fresh_deploy
                    and self.can_take_frontline(p)):
                if u.unit_type == "坦克":
                    if self.move_unit(u, "前线"):
                        yield {"type": "move", "unit": u}
        # 攻击
        for u in p.board:
            while u in p.board and self.unit_ready(u) and u.defense > 0:
                targets = self.attack_targets(u)
                if not targets:
                    break
                foe = self.opponent_of(p)
                ok, _ = self.can_hit_hq(u)
                if ok and foe.hq <= self.hq_damage(u):
                    self.do_hq_attack(u)
                    yield {"type": "hq_attack", "unit": u}
                else:
                    killable = [t for t in targets if u.attack - t.armor >= t.defense]
                    if killable and random.random() < 0.7:
                        target = random.choice(killable)
                    elif ok and random.random() < 0.5:
                        self.do_hq_attack(u)
                        yield {"type": "hq_attack", "unit": u}
                        continue
                    else:
                        target = min(targets, key=lambda t: t.defense)
                    self.do_attack(u, target)
                    yield {"type": "attack", "unit": u, "target": target}
                for pl in self.players:
                    for dead in list(pl.board):
                        if dead.defense <= 0:
                            self.destroy_unit(dead)
        yield {"type": "end"}

    def winner_of(self):
        """判定胜者（None = 平局）。

        三种结束方式，必须分开处理：
          - 双方总部同时倒下 → 平局
          - 一方总部倒下 → 另一方获胜
          - 投降（self.conceded）→ 投降方的对手获胜

        之前只靠"谁的 hq > 0"来猜，把"投降"和"被打死"混为一谈，
        而且双死时会因为 players[0].hq > 0 为假而错判给 players[1]。
        """
        p0, p1 = self.players
        if p0.hq <= 0 and p1.hq <= 0:
            return None
        if self.conceded is not None:
            return self.opponent_of(self.conceded)
        if p0.hq <= 0:
            return p1
        if p1.hq <= 0:
            return p0
        return None

    def run(self):
        for p in self.players:
            self.draw_cards(p, START_HP)
        self.draw_cards(self.players[1], 1)  # 后手多抽一张
        while not self.over:
            self.start_turn()
            if self.over or self.current.hq <= 0:
                break
            if self.interactive and self.current.name == "你":
                self.human_turn()
            else:
                self.log("  [AI 行动中]")
                self.ai_turn()
            if self.conceded is not None:
                # AI 判定无胜算投降：不结算回合，直接结束
                self.log(f"  🏳 {self.current.name} 认为已无胜算，选择投降！")
                break
            self.end_turn()
        winner = self.winner_of()
        print(f"\n{'='*40}")
        if winner is None:
            print("  战斗结束！双方总部同时陷落——平局！")
        else:
            print(f"  战斗结束！{winner.name} 获胜！")
        print(f"{'='*40}")
        return winner


# ---------------------------------------------------------------- 入口

def cli_build_deck(nation, db):
    """命令行组卡器：a N=加入, d N=移除, done=完成"""
    allowed = allowed_cards(nation, db)
    counts = {}
    ally_n = 0
    while True:
        total = sum(counts.values())
        print("\n" + "=" * 50)
        print(f"  组卡中: {total}/{DECK_SIZE} (单卡≤{MAX_COPIES}, 盟国卡 {ally_n}/{ALLY_LIMIT})")
        for i, c in enumerate(allowed):
            n = counts.get(c.name, 0)
            if c.kind == "unit":
                kws = "".join(f"[{k}]" for k in c.keywords)
                info = f"{c.unit_type} {c.attack}/{c.defense} {kws}"
            else:
                tag = "反制" if c.kind == "counter" else "指令"
                info = f"[{tag}] {c.desc}"
            print(f"  {i:>2}: ◆{c.cost} {c.name} {info}  ×{n}")
        cmd = input("指令 (a N=加入, d N=移除, done=完成): ").strip().lower()
        if cmd == "done":
            if total != DECK_SIZE:
                print(f"  卡组必须恰好 {DECK_SIZE} 张，当前 {total} 张！")
                continue
            break
        try:
            op, idx = cmd.split()[0], int(cmd.split()[1])
            card = allowed[idx]
            if op == "a":
                if counts.get(card.name, 0) >= MAX_COPIES:
                    print(f"  {card.name} 已达 {MAX_COPIES} 张上限！")
                elif total >= DECK_SIZE:
                    print("  卡组已满！")
                elif card.nation in ALLY_NATIONS and ally_n >= ALLY_LIMIT:
                    print(f"  盟国卡已达 {ALLY_LIMIT} 张上限！")
                else:
                    counts[card.name] = counts.get(card.name, 0) + 1
                    if card.nation in ALLY_NATIONS:
                        ally_n += 1
            elif op == "d":
                if counts.get(card.name, 0) > 0:
                    counts[card.name] -= 1
                    if card.nation in ALLY_NATIONS:
                        ally_n -= 1
                else:
                    print("  该卡不在卡组中。")
            else:
                print("  未知指令")
        except (IndexError, ValueError, KeyError):
            print("  格式: a <编号> / d <编号> / done")
    deck = []
    for name, n in counts.items():
        deck += [db[name]] * n
    random.shuffle(deck)
    return deck


def cli_import_deck(nation, db):
    """命令行导入：粘贴原版卡牌清单，自动补满剩余张数"""
    print("粘贴卡组清单（每行: '3 谢尔曼坦克' / 'Sherman Tank x3'，支持英文名），输入 END 结束：")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip().upper() == "END":
            break
        lines.append(line)
    counts, unmatched = parse_deck_text("\n".join(lines), db)
    if unmatched:
        print("  未识别（已忽略）: " + "；".join(unmatched[:8]))
    deck = counts_to_deck(counts, nation, db, autofill=True)
    print(f"  已导入 {sum(counts.values())} 张，自动补满至 {DECK_SIZE} 张。")
    return deck


def main():
    setup_error_log()
    demo = "--demo" in sys.argv
    db = card_database()
    if demo:
        random.seed()
        nations = random.choices(MAIN_NATIONS, k=2)  # 可能内战
        p1 = Player("AI-红军", nations[0], build_deck(nations[0], db))
        p2 = Player("AI-蓝军", nations[1], build_deck(nations[1], db))
        print(f"演示模式: {p1.nation} vs {p2.nation}")
        Game(p1, p2, interactive=False).run()
        return

    print("=" * 40)
    print("       KARDS 简化版 - 二战卡牌对战")
    print("=" * 40)
    print("可选主国: 1)德国  2)苏联  3)美国  4)英国  5)日本")
    nations = {"1": "德国", "2": "苏联", "3": "美国", "4": "英国", "5": "日本"}
    nation = None
    while nation is None:
        choice = input("选择你的阵营 (1-5, 回车=随机): ").strip()
        if not choice:
            nation = random.choice(MAIN_NATIONS)
            print(f"  已随机选择: {nation}")
        elif choice in nations:
            nation = nations[choice]
        elif choice in nations.values():
            nation = choice
        else:
            print("  无效输入，请输入 1-5 或阵营名称！")
    hq = HQ_CARDS[nation]
    print(f"总部卡: {hq.name}（{hq.hp} HP） | {hq.perk_desc}")
    custom = input("卡组 (y=自组 / i=导入清单 / 回车=随机推荐): ").strip().lower()
    if custom == "y":
        deck = cli_build_deck(nation, db)
    elif custom == "i":
        deck = cli_import_deck(nation, db)
    else:
        deck = build_deck(nation, db)
    ai_nation = random.choice(MAIN_NATIONS)  # 随机匹配，可能内战
    p_you = Player("你", nation, deck)
    p_ai = Player("AI", ai_nation, build_deck(ai_nation, db))
    first = random.choice(["你", "AI"])
    if first == "AI":
        p1, p2 = p_ai, p_you      # AI 先手：让 AI 成为 p1（游戏从 p1 开始，后手补偿自动给 p2）
    else:
        p1, p2 = p_you, p_ai
    print(f"\n你选择了 {nation}，对手是 {ai_nation} 阵营。本轮先手: {first}。")
    print("祝你好运，指挥官！输入 h 可查看指令帮助。\n")
    Game(p1, p2, interactive=True).run()


if __name__ == "__main__":
    main()
