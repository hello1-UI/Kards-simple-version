# -*- coding: utf-8 -*-
"""把卡牌效果对齐原版 KARDS：引擎机制扩展 + 卡池重写 + GUI/AI 适配。
用法: python debug/patch_original.py
"""
import ast
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rep(src, old, new, tag, expect=1):
    n = src.count(old)
    if n != expect:
        raise SystemExit(f"[{tag}] 期望 {expect} 处，实际 {n} 处")
    print(f"  ok: {tag}")
    return src.replace(old, new)


# ============================================================ kards.py
p = os.path.join(ROOT, "kards.py")
src = io.open(p, encoding="utf-8").read()

# ---- R1 关键词说明 ----
src = rep(src, '''KEYWORD_DESC = {
    "闪击": "部署当回合即可攻击",
    "装甲": "受到的伤害减少 1",
    "警卫": "保护相邻位置的单位；位于#0位（紧邻总部）时还保护总部",
    "冲击": "攻击单位免反击，攻击后消耗",
    "收缴": "消灭敌方单位时，将一张 1/1 副本（费用至多 3）加入手牌",
}''', '''KEYWORD_DESC = {
    "闪击": "部署当回合即可攻击",
    "装甲": "战斗伤害减少 1（指令等效果伤害不减）",
    "装甲2": "战斗伤害减少 2（指令等效果伤害不减）",
    "警卫": "保护相邻位置的单位；位于#0位（紧邻总部）时还保护总部",
    "冲击": "攻击单位免反击，攻击后消耗",
    "伏击": "被攻击时先出手打击攻击者；攻击者若阵亡则攻击无效",
    "奋战": "每回合可攻击两次",
    "动员": "你的回合开始时 +1/+1，直到它受到伤害为止",
    "收缴": "消灭敌方单位时，将一张 1/1 副本（费用至多 3）加入手牌",
}''', "R1 KEYWORD_DESC")

# ---- R2 UnitCard ----
src = rep(src, '''    def __init__(self, name, nation, cost, attack, defense, keywords=None, unit_type="步兵"):
        self.name = name
        self.nation = nation
        self.cost = cost
        self.attack = attack
        self.defense = defense
        self.keywords = keywords or []
        self.unit_type = unit_type
        self.rarity = auto_rarity(cost, keywords)''', '''    def __init__(self, name, nation, cost, attack, defense, keywords=None, unit_type="步兵",
                 traits=None, rarity=None):
        self.name = name
        self.nation = nation
        self.cost = cost
        self.attack = attack
        self.defense = defense
        self.keywords = keywords or []
        self.unit_type = unit_type
        self.traits = traits or {}      # 原版效果标记（部署/亡计/双倍伤害等）
        self.rarity = rarity or auto_rarity(cost, keywords)''', "R2 UnitCard")

# ---- R3 OrderCard ----
src = rep(src, '''    def __init__(self, name, nation, cost, effect, desc):
        self.name = name
        self.nation = nation
        self.cost = cost
        self.effect = effect  # callable(game, caster)
        self.desc = desc
        self.rarity = auto_rarity(cost)''', '''    def __init__(self, name, nation, cost, effect, desc, rarity=None):
        self.name = name
        self.nation = nation
        self.cost = cost
        self.effect = effect  # callable(game, caster)
        self.desc = desc
        self.rarity = rarity or auto_rarity(cost)''', "R3 OrderCard")

# ---- R4 CounterCard ----
src = rep(src, '''    def __init__(self, name, nation, cost, trigger, desc):
        self.name = name
        self.nation = nation
        self.cost = cost
        self.trigger = trigger  # attack_tank | attack_air | attack_inf | attack_any | order
        self.desc = desc
        self.rarity = auto_rarity(cost)''', '''    def __init__(self, name, nation, cost, trigger, desc, effect=None, rarity=None):
        self.name = name
        self.nation = nation
        self.cost = cost
        self.trigger = trigger  # attack_tank | attack_air | attack_inf | attack_any | order | friendly_death
        self.desc = desc
        self.effect = effect    # 自定义触发效果 callable(game, owner)；None 走默认（消灭攻击者）
        self.rarity = rarity or auto_rarity(cost)''', "R4 CounterCard")

# ---- R5 Unit.__init__ ----
src = rep(src, '''        self.can_attack = "闪击" in self.keywords  # 无闪击则下回合才能攻击
        self.attacks_made = 0''', '''        self.can_attack = "闪击" in self.keywords  # 无闪击则下回合才能攻击
        self.attacks_made = 0
        self.traits = dict(getattr(card, "traits", None) or {})  # 原版效果标记
        self.mob = 0                # [动员]当前加成（受伤时移除）
        self.dying_hq = int((getattr(card, "traits", None) or {}).get("dying_hq", 0))
        self.overflow_turn = False  # 本回合溢出伤害转移敌方总部（呜啦！）''', "R5 Unit fields")

# ---- R6 Unit: max_attacks / armor ----
src = rep(src, '''    def has(self, kw):
        return kw in self.keywords

    def __str__(self):''', '''    def has(self, kw):
        return kw in self.keywords

    @property
    def max_attacks(self):
        """[奋战]每回合可攻击两次"""
        return 2 if "奋战" in self.keywords else 1

    @property
    def armor(self):
        """战斗伤害减免（仅战斗，效果伤害不减免）"""
        if "装甲2" in self.keywords:
            return 2
        if "装甲" in self.keywords:
            return 1
        return 0

    def __str__(self):''', "R6 Unit props")

# ---- R7 Game.__init__ force_end ----
src = rep(src, '''        self.over = False
        self.event_hook = None  # GUI 动画钩子: fn(event: dict)''', '''        self.over = False
        self.force_end = False  # 万岁冲锋等强制结束回合标记
        self.event_hook = None  # GUI 动画钩子: fn(event: dict)''', "R7 force_end")

# ---- R8 Player fields ----
src = rep(src, '''        self.hq = self.hq_card.hp
        self.kredits = 0
        self.fatigue = 0''', '''        self.hq = self.hq_card.hp
        self.kredits = 0
        self.fatigue = 0
        self.temp_buffs = []    # 本回合临时攻击增益 [(unit, amount)]，回合结束还原
        self.orders_played = 0  # 本回合已使用指令数（廓尔喀联动）
        self.ats_mark = 0       # 本土防卫军标记（1/2=标记方索引+1，0=无）''', "R8 Player fields")

# ---- R9 fatigue -> damage_hq ----
src = rep(src, '''            if not p.deck:
                p.fatigue += 1
                p.hq -= p.fatigue
                self.log(f"  {p.name} 牌库已空，受到 {p.fatigue} 点疲劳伤害！")
                continue''', '''            if not p.deck:
                p.fatigue += 1
                self.damage_hq(p, p.fatigue)
                self.log(f"  {p.name} 牌库已空，受到 {p.fatigue} 点疲劳伤害！")
                continue''', "R9 fatigue")

# ---- R10 damage_unit + damage_hq ----
src = rep(src, '''    # ---------------- 伤害结算 ----------------
    def damage_unit(self, unit, amount, source=None):
        if unit.has("装甲") and amount > 0:
            self.log(f"  {unit.name} 的[装甲]抵消了 1 点伤害。")
            amount -= 1
        if amount > 0:''', '''    # ---------------- 伤害结算 ----------------
    def damage_unit(self, unit, amount, source=None, combat=False):
        """combat=True 表示战斗伤害（攻击/反击/伏击），只有战斗伤害受[装甲]减免"""
        if amount > 0:
            red = unit.armor if combat else 0
            if red:
                amount = max(0, amount - red)
                self.log(f"  {unit.name} 的[装甲]抵消了 {red} 点伤害。")
            if unit.mob:      # [动员]加成在受伤时移除
                self.log(f"  {unit.name} 的[动员]加成因受伤而消失。")
                unit.attack -= unit.mob
                unit.defense -= unit.mob
                unit.max_defense -= unit.mob
                unit.mob = 0
        if amount > 0:''', "R10a damage_unit")

src = rep(src, '''            if unit.defense <= 0:
                self.destroy_unit(unit)
                if source is not None and source.has("收缴") \\
                        and unit not in unit.owner.board:
                    self.apply_confiscate(source, unit)

    def apply_confiscate(self, killer, victim):''', '''            if unit.defense <= 0:
                self.destroy_unit(unit)
                if source is not None and source.has("收缴") \\
                        and unit not in unit.owner.board:
                    self.apply_confiscate(source, unit)

    def damage_hq(self, player, amount, source=None):
        """统一的总部伤害入口：处理近卫步兵成长 / 本土防卫军抽牌联动"""
        if amount <= 0 or player.hq <= 0:
            player.hq -= max(0, amount)
            if amount > 0:
                self.emit({"type": "hq_damage", "player": player, "amount": amount})
            return
        player.hq -= amount
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

    def apply_confiscate(self, killer, victim):''', "R10b damage_hq")

# ---- R12 destroy_unit hooks ----
src = rep(src, '''    def destroy_unit(self, unit):
        if unit in unit.owner.board:
            unit.owner.board.remove(unit)
            unit.owner.discard.append(unit.card)
            self.emit({"type": "destroy", "unit": unit})
            self.log(f"  {unit.name} 被消灭了。")''', '''    def destroy_unit(self, unit):
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
                        c.effect(self, unit.owner)''', "R12 destroy_unit")

# ---- R13 check_counter + counter_grow ----
src = rep(src, '''        for c in player.counters:
            if c.matches(event, ctx):
                player.counters.remove(c)
                player.discard.append(c)
                return c
        return None''', '''        for c in player.counters:
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
        return None''', "R13 check_counter")

# ---- R14 hq_damage 后加 unit_ready / combat_damage ----
src = rep(src, '''    def hq_damage(self, attacker):
        return attacker.attack + (2 if attacker.unit_type == "轰炸机" else 0)''', '''    def hq_damage(self, attacker):
        return attacker.attack + (2 if attacker.unit_type == "轰炸机" else 0)

    def unit_ready(self, u):
        """单位本回合是否还能攻击（含[奋战]两次、特种空勤团封锁）"""
        if not u.can_attack or u.attacks_made >= u.max_attacks:
            return False
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
        return dmg''', "R14 helpers")

# ---- R15 do_attack ----
src = rep(src, '''    def do_attack(self, attacker, target):
        self.log(f"  {attacker.name} 攻击 {target.name}！")
        # 反制触发
        counter = self.check_counter(target.owner, "attack", attacker)
        if counter:
            self.log(f"  ⚡ {target.owner.name} 的反制 [ {counter.name} ] 触发！{attacker.name} 被消灭！")
            self.emit({"type": "counter", "card": counter})
            self.destroy_unit(attacker)
            attacker.attacks_made += 1
            attacker.can_attack = False
            return
        self.damage_unit(target, attacker.attack, source=attacker)
        self.emit({"type": "attack", "attacker": attacker, "target": target})
        # 冲击：攻击单位免反击，攻击后消耗
        shocked = attacker.has("冲击")
        if shocked:
            attacker.keywords.remove("冲击")
            self.log(f"  {attacker.name} 的[冲击]已消耗。")
        # 反击规则：目标未死亡才会反击；冲击单位免反击
        if target in target.owner.board and target.defense > 0:
            if shocked:
                self.log(f"  [冲击]生效：{attacker.name} 不受反击！")
            else:
                self.log(f"  {target.name} 反击！{attacker.name} 受到 {target.attack} 点伤害。")
                self.damage_unit(attacker, target.attack, source=target)
        attacker.attacks_made += 1
        attacker.can_attack = False''', '''    def do_attack(self, attacker, target):
        self.log(f"  {attacker.name} 攻击 {target.name}！")
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
        # 反击规则：目标未死亡才会反击；冲击免反击；[伏击]目标已先出手不再反击
        if target in target.owner.board and target.defense > 0:
            if shocked:
                self.log(f"  [冲击]生效：{attacker.name} 不受反击！")
            elif target.has("伏击"):
                pass
            else:
                self.log(f"  {target.name} 反击！{attacker.name} 受到 {target.attack} 点伤害。")
                self.damage_unit(attacker, target.attack, source=target, combat=True)
        attacker.attacks_made += 1''', "R15 do_attack")

# ---- R16 do_hq_attack ----
src = rep(src, '''    def do_hq_attack(self, attacker):
        enemy = self.opponent_of(attacker.owner)
        counter = self.check_counter(enemy, "attack", attacker)
        if counter:
            self.log(f"  ⚡ {enemy.name} 的反制 [ {counter.name} ] 触发！{attacker.name} 被消灭！")
            self.emit({"type": "counter", "card": counter})
            self.destroy_unit(attacker)
            attacker.attacks_made += 1
            attacker.can_attack = False
            return
        dmg = self.hq_damage(attacker)
        bonus = "（轰炸机 +2）" if attacker.unit_type == "轰炸机" else ""
        enemy.hq -= dmg
        self.emit({"type": "hq_damage", "player": enemy, "amount": dmg})
        attacker.attacks_made += 1
        attacker.can_attack = False
        self.log(f"  {attacker.name} 直击敌方总部，造成 {dmg} 点伤害{bonus}！")''', '''    def do_hq_attack(self, attacker):
        enemy = self.opponent_of(attacker.owner)
        counter = self.check_counter(enemy, "attack", attacker)
        if counter:
            self.log(f"  ⚡ {enemy.name} 的反制 [ {counter.name} ] 触发！{attacker.name} 被消灭！")
            self.emit({"type": "counter", "card": counter})
            self.destroy_unit(attacker)
            attacker.attacks_made += 1
            return
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
                        break''', "R16 do_hq_attack")

# ---- R17 play_card unit branch -> on_deploy ----
src = rep(src, '''            unit = self.deploy_unit(p, card)
            self.log(f"  {p.name} 部署了 {unit}")''', '''            unit = self.deploy_unit(p, card)
            self.log(f"  {p.name} 部署了 {unit}")
            self.on_deploy(unit)''', "R17 on_deploy call")

# ---- R18 play_card order branch ----
src = rep(src, '''            self.log(f"  {p.name} 打出指令牌 [ {card.name} ]")
            self.emit({"type": "order", "card": card, "player": p})
            card.effect(self, p)
            p.discard.append(card)
        return True''', '''            self.log(f"  {p.name} 打出指令牌 [ {card.name} ]")
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
        return True''', "R18 order branch")

# ---- R19 deploy_unit 九七式光环 + on_deploy ----
src = rep(src, '''        u = Unit(card, p)
        u.slot = self.next_slot(p)
        p.board.append(u)
        self.emit({"type": "deploy", "unit": u, "player": p})
        return u''', '''        u = Unit(card, p)
        u.slot = self.next_slot(p)
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
            self.log(f"  [部署] {unit.name} 抽了 1 张牌。")''', "R19 on_deploy")

# ---- R20 start_turn ----
src = rep(src, '''    def start_turn(self):
        self.turn_num += 1
        p = self.current''', '''    def start_turn(self):
        self.turn_num += 1
        self.force_end = False
        p = self.current''', "R20a force_end reset")

src = rep(src, '''        self.draw_cards(p, 1)
        for u in p.board:
            u.can_attack = True
            u.attacks_made = 0
            u.moved = False''', '''        self.draw_cards(p, 1)
        p.orders_played = 0
        for u in p.board:
            u.can_attack = True
            u.attacks_made = 0
            u.moved = False
            # [动员]：回合开始 +1/+1，直到受伤
            if "动员" in u.keywords:
                u.attack += 1
                u.defense += 1
                u.max_defense += 1
                u.mob += 1
                self.log(f"  [动员] {u.name} 获得 +1/+1（{u.attack}/{u.defense}）。")''', "R20b mobilize")

# ---- R21 end_turn ----
src = rep(src, '''    def end_turn(self):
        if self.current.hq <= 0:
            self.over = True
            return
        self.current = self.opponent_of(self.current)''', '''    def end_turn(self):
        if self.current.hq <= 0:
            self.over = True
            return
        # 还原本回合临时攻击增益（闪电战 / 呜啦！）
        for u, amount in self.current.temp_buffs:
            if u in self.current.board:
                u.attack -= amount
                self.log(f"  {u.name} 的本回合攻击加成消失（{u.attack}）。")
        self.current.temp_buffs = []
        for u in self.current.board:
            u.overflow_turn = False
        self.opponent_of(self.current).ats_mark = 0
        self.force_end = False
        self.current = self.opponent_of(self.current)''', "R21 end_turn")

# ---- R22 human_turn: unit_ready + force_end + 帮助文本 ----
src = rep(src, '''                    attacker = p.board[mi]
                    if not attacker.can_attack:
                        print("  该单位本回合无法攻击（需要闪击关键词）")
                        continue
                    if attacker.attacks_made >= 1:
                        print("  该单位已攻击过")
                        continue''', '''                    attacker = p.board[mi]
                    if not self.unit_ready(attacker):
                        print("  该单位本回合无法攻击（需要[闪击]，或已用完攻击次数/被封锁）")
                        continue''', "R22a human attack gate")

src = rep(src, '''            else:
                print("  未知指令，输入 h 查看帮助")
            for pl in self.players:
                for u in list(pl.board):
                    if u.defense <= 0:
                        self.destroy_unit(u)

    # ---------------- AI ----------------''', '''            else:
                print("  未知指令，输入 h 查看帮助")
            for pl in self.players:
                for u in list(pl.board):
                    if u.defense <= 0:
                        self.destroy_unit(u)
            if self.force_end:
                print("  万岁冲锋！回合被迫结束。")
                break

    # ---------------- AI ----------------''', "R22b force_end human")

src = rep(src, '''                      "  打单位必吃反击（目标未死时）；[冲击]打单位免反击但消耗；轰炸机打总部+2\\n"
                      "  [收缴]消灭敌方单位时，一张 1/1 副本（费用至多3）加入手牌\\n"''', '''                      "  打单位必吃反击（目标未死时）；[冲击]打单位免反击但消耗；轰炸机打总部+2\\n"
                      "  [伏击]被攻击时先出手；[奋战]每回合攻击两次；[装甲]战斗伤害-1（[装甲2]-2）\\n"
                      "  [动员]回合开始+1/+1直至受伤；[亡计]被消灭时对敌方总部造成伤害\\n"
                      "  [收缴]消灭敌方单位时，一张 1/1 副本（费用至多3）加入手牌\\n"''', "R22c help text")

# ---- R23 ai_steps ----
src = rep(src, '''        p = self.current
        acted = True
        while acted:
            acted = False
            for idx in sorted(self.playable_cards(p),
                              key=lambda i: -self.get_cost(p.hand[i], p)):''', '''        p = self.current
        acted = True
        while acted:
            acted = False
            if self.force_end:
                break
            for idx in sorted(self.playable_cards(p),
                              key=lambda i: -self.get_cost(p.hand[i], p)):''', "R23a ai play gate")

src = rep(src, '''        # 机动：前线可占时，优先把突击力量调往前线''', '''        if self.force_end:
            yield {"type": "end"}
            return
        # 机动：前线可占时，优先把突击力量调往前线''', "R23b ai skip phases")

src = rep(src, '''            while u in p.board and u.can_attack and u.attacks_made < 1 and u.defense > 0:''', '''            while u in p.board and self.unit_ready(u) and u.defense > 0:''', "R23c ai attack loop")

io.open(p, "w", encoding="utf-8", newline="").write(src)
print("kards.py 阶段1 完成")

# ============================================================ kards.py 阶段2: 效果函数 + 卡池
src = io.open(p, encoding="utf-8").read()

# ---- effect_lightning -> effect_blitzkrieg ----
src = rep(src, '''def effect_lightning(game, caster):
    """闪电战: 对敌方总部造成 3 点伤害"""
    enemy = game.opponent_of(caster)
    enemy.hq -= 3
    game.emit({"type": "hq_damage", "player": enemy, "amount": 3})
    game.log("  闪电战对敌方总部造成 3 点伤害！")''', '''def effect_blitzkrieg(game, caster):
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
        game.log("  （前线没有友方单位，闪电战落空）")''', "E1 blitzkrieg")

# ---- effect_for_motherland -> effect_ura ----
src = rep(src, '''def effect_for_motherland(game, caster):
    """为了祖国: 一个随机友方单位 +1/+1"""
    if not caster.board:
        game.log("  没有友方单位，为了祖国落空。")
        return
    u = random.choice(caster.board)
    u.attack += 1
    u.defense += 1
    u.max_defense += 1
    game.log(f"  {u.name} 获得 +1/+1。")''', '''def effect_ura(game, caster):
    """呜啦!: 本回合所有苏联单位 +3 攻击，溢出伤害转移到敌方总部"""
    n = 0
    for u in caster.board:
        if u.card.nation == "苏联":
            u.attack += 3
            caster.temp_buffs.append((u, 3))
            u.overflow_turn = True
            n += 1
    game.log(f"  呜啦！{n} 个苏联单位本回合 +3 攻击，溢出伤害将转移至敌方总部！")''', "E2 ura")

# ---- effect_us_reinforce -> effect_fresh_recruits ----
src = rep(src, '''def effect_us_reinforce(game, caster):
    """步兵增援: 部署一个 2/2 步兵"""
    if len(caster.board) >= BOARD_SIZE:
        game.log("  场上已满，增援无法登陆。")
        return
    game.deploy_unit(caster, _token_card("增援步兵", 2, 2))
    game.log("  增援步兵（2/2）加入了战场！")''', '''def effect_fresh_recruits(game, caster):
    """新兵入伍(反制): 友方单位被消灭时，随机友方单位 +2/+3"""
    if not caster.board:
        game.log("  没有友方单位，新兵入伍落空。")
        return
    u = random.choice(caster.board)
    u.attack += 2
    u.defense += 3
    u.max_defense += 3
    game.log(f"  {u.name} 获得 +2/+3（{u.attack}/{u.defense}）。")''', "E3 fresh_recruits")

# ---- effect_medic -> effect_cup_of_tea ----
src = rep(src, '''def effect_medic(game, caster):
    """战地医疗: 己方总部恢复 5 点生命"""
    max_hp = caster.hq_card.hp
    caster.hq = min(max_hp, caster.hq + 5)
    game.emit({"type": "hq_heal", "player": caster, "amount": 5})
    game.log(f"  己方总部恢复 5 点生命，当前 {caster.hq} HP。")''', '''def effect_cup_of_tea(game, caster):
    """一杯茶: 你的所有英军单位 +2 防御"""
    n = 0
    for u in caster.board:
        if u.card.nation == "英国":
            u.defense += 2
            u.max_defense += 2
            n += 1
    game.log(f"  一杯茶：{n} 个英军单位 +2 防御，士气大振！")''', "E4 cup_of_tea")

# ---- effect_mobilization -> effect_double_strength ----
src = rep(src, '''def effect_mobilization(game, caster):
    """总动员: 抽 2 张牌，己方所有单位 +1/+1"""
    game.draw_cards(caster, 2)
    for u in caster.board:
        u.attack += 1
        u.defense += 1
        u.max_defense += 1
    game.log("  己方所有单位获得 +1/+1，并抽了 2 张牌。")''', '''def effect_double_strength(game, caster):
    """双倍力量: 随机复制一张手中的指令牌，洗入卡组"""
    orders = [c for c in caster.hand if c.kind == "order"]
    if not orders:
        game.log("  手中没有指令牌，双倍力量落空。")
        return
    c = random.choice(orders)
    caster.deck.insert(random.randrange(len(caster.deck) + 1), c)
    game.log(f"  双倍力量：复制了一张 [ {c.name} ] 洗入卡组。")''', "E5 double_strength")

# ---- effect_banzai ----
src = rep(src, '''def effect_banzai(game, caster):
    """万岁冲锋: 一个随机友方单位 +2/+0"""
    if not caster.board:
        game.log("  没有友方单位，万岁冲锋落空。")
        return
    u = random.choice(caster.board)
    u.attack += 2
    game.log(f"  {u.name} 获得 +2 攻击！")''', '''def effect_banzai(game, caster):
    """万岁冲锋: 消灭所有攻击力≤4 的陆军单位（双方），然后结束你的回合"""
    for pl in game.players:
        for u in list(pl.board):
            if u.unit_type in ("步兵", "坦克") and u.attack <= 4:
                game.log(f"  万岁冲锋吞没了 {u.name}！")
                game.destroy_unit(u)
    game.log("  万岁冲锋！你的回合就此结束。")
    game.force_end = True''', "E6 banzai")

# ---- effect_naval_support（炮火准备沿用）----
src = rep(src, '''def effect_naval_support(game, caster):
    """舰炮支援: 对一个随机敌方单位造成 2 点伤害"""
    targets = game.opponent_of(caster).board
    if targets:
        t = random.choice(targets)
        game.log(f"  舰炮支援命中 {t.name}，造成 2 点伤害！")
        game.damage_unit(t, 2)
    else:
        enemy = game.opponent_of(caster)
        enemy.hq -= 2
        game.emit({"type": "hq_damage", "player": enemy, "amount": 2})
        game.log("  场上没有目标，舰炮支援轰击敌方总部，造成 2 点伤害！")''', '''def effect_naval_support(game, caster):
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
        game.log("  场上没有目标，炮火准备轰击敌方总部，造成 2 点伤害！")''', "E7 naval_support")

# ---- effect_winter_war ----
src = rep(src, '''def effect_winter_war(game, caster):
    """冬季战争: 对敌方总部造成 2 点伤害，抽 1 张牌"""
    enemy = game.opponent_of(caster)
    enemy.hq -= 2
    game.emit({"type": "hq_damage", "player": enemy, "amount": 2})
    game.draw_cards(caster, 1)
    game.log("  冬季战争：敌方总部受到 2 点伤害，你抽了 1 张牌。")''', '''def effect_winter_war(game, caster):
    """冬季战争: 对敌方总部造成 2 点伤害，抽 1 张牌"""
    enemy = game.opponent_of(caster)
    game.damage_hq(enemy, 2)
    game.draw_cards(caster, 1)
    game.log("  冬季战争：敌方总部受到 2 点伤害，你抽了 1 张牌。")''', "E8 winter_war")

# ---- effect_hussars ----
src = rep(src, '''def effect_hussars(game, caster):
    """翼骑兵冲锋: 部署一个 2/2 步兵"""
    if not game.can_deploy(caster):
        game.log("  支援阵线已满，冲锋未能展开。")
        return
    game.deploy_unit(caster, _token_card("翼骑兵", 2, 2))
    game.log("  翼骑兵（2/2）发起冲锋！")''', '''def effect_hussars(game, caster):
    """冲锋在前(近似原版军团机制): 随机一个友方单位 +1/+1，并部署一个 1/1 军团"""
    if caster.board:
        u = random.choice(caster.board)
        u.attack += 1
        u.defense += 1
        u.max_defense += 1
        game.log(f"  {u.name} 获得 +1/+1。")
    if game.can_deploy(caster):
        game.deploy_unit(caster, _token_card("军团", 1, 1))
        game.log("  军团（1/1）加入了支援阵线！")''', "E9 hussars")

# ---- 新增效果函数（插在卡池分隔注释前）----
src = rep(src, '''# ---------------------------------------------------------------- 卡池''', '''def effect_naval_support_uk(game, caster):
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
    """大和号: 你的所有日军单位获得 亡计：对敌方总部造成 2 点伤害"""
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


# ---------------------------------------------------------------- 卡池''', "E10 new effects")

io.open(p, "w", encoding="utf-8", newline="").write(src)
print("kards.py 阶段2 完成")

# ============================================================ kards.py 阶段3: 卡池重写
src = io.open(p, encoding="utf-8").read()

OLD_DB_START = 'def card_database():\n    db = [\n        # ---- 德国（主国）----\n'
i = src.index(OLD_DB_START)
j = src.index('    return {c.name: c for c in db}\n', i)
j_end = j + len('    return {c.name: c for c in db}\n')
new_db = '''def card_database():
    """卡池：61 张卡对齐原版 KARDS 数据（费用/攻防/关键词/效果/稀有度），
    效果描述为自拟简洁中文；个别无法映射的原版机制用近似实现并注明。"""
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
                  "你的所有日军单位获得「亡计：对敌方总部造成 2 点伤害」", rarity="传说"),
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
    return {c.name: c for c in db}
'''
src = src[:i] + new_db + src[j_end:]
io.open(p, "w", encoding="utf-8", newline="").write(src)
print("kards.py 卡池重写完成")
ast.parse(io.open(p, encoding="utf-8").read())
print("kards.py 语法 OK")

# ============================================================ kards_gui.py
p2 = os.path.join(ROOT, "kards_gui.py")
gsrc = io.open(p2, encoding="utf-8").read()

gsrc = rep(gsrc, '''        ready = u.can_attack and u.attacks_made < 1''',
           '''        ready = self.game.unit_ready(u) if self.game else u.can_attack''',
           "G1 my_card ready")

gsrc = rep(gsrc, '''        if not attacker.can_attack or attacker.attacks_made >= 1:''',
           '''        if not g.unit_ready(attacker):''',
           "G2 attack gates", expect=2)

gsrc = rep(gsrc, '''            if g.play_card(me, idx) and self.mp_link is not None:
                self._mp_send_act({"k": "play", "i": idx})
            self.cleanup_dead()
            self.check_over()
            if self.game:
                self.refresh()
            return''', '''            if g.play_card(me, idx) and self.mp_link is not None:
                self._mp_send_act({"k": "play", "i": idx})
            self.cleanup_dead()
            self.check_over()
            if self.game:
                self.refresh()
            # 万岁冲锋：强制结束回合
            if self.game and self.game.force_end and not self.game.over:
                self.after(400, self.on_end_turn)
            return''', "G3 force_end after play")

io.open(p2, "w", encoding="utf-8", newline="").write(gsrc)
ast.parse(io.open(p2, encoding="utf-8").read())
print("kards_gui.py 语法 OK")
print("全部补丁应用成功")
