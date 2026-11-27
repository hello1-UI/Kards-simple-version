package com.kards.engine;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** 指令 / 反制 / 部署效果的 Java 实现（对齐 kards_engine effect_* / on_deploy）。 */
public final class Effects {
    private Effects() { }

    /** 中立衍生牌：军团（1/1 衍生单位，hussars 用）。 */
    public static CardDef tokenLegion() {
        return token("军团", 1, 1);
    }

    /** 中立衍生牌：生产（获得 1 指挥点，production_to_hand 用）。 */
    public static CardDef tokenProduction() {
        CardDef c = token("生产", 0, 0);
        Map<String, Object> m = new java.util.LinkedHashMap<>();
        m.put("kind", "order"); m.put("name", "生产"); m.put("nation", "中立");
        m.put("cost", 0.0); m.put("rarity", "普通");
        m.put("desc", "获得 1 指挥点。");
        m.put("effect", paramsMap("production"));
        return new CardDef(m);
    }

    private static CardDef token(String name, int atk, int def) {
        Map<String, Object> m = new java.util.LinkedHashMap<>();
        m.put("kind", "unit"); m.put("name", name); m.put("nation", "中立");
        m.put("cost", 1.0); m.put("rarity", "普通");
        m.put("attack", (double) atk); m.put("defense", (double) def);
        m.put("keywords", new ArrayList<Object>());
        m.put("unitType", "步兵"); m.put("operate", 0.0);
        m.put("traits", new java.util.LinkedHashMap<String, Object>());
        return new CardDef(m);
    }

    private static Map<String, Object> paramsMap(String id) {
        Map<String, Object> em = new java.util.LinkedHashMap<>();
        em.put("id", id);
        em.put("params", new java.util.LinkedHashMap<String, Object>());
        return em;
    }

    private static int p(CardDef card, String key, int dflt) {
        Object v = card.effectParams.get(key);
        if (v instanceof Double) return (int) Math.round((Double) v);
        if (v instanceof Number) return ((Number) v).intValue();
        return dflt;
    }

    // ---------------- 部署效果 ----------------
    public static void onDeploy(Game g, Unit unit) {
        String d = unit.strTrait("deploy");
        if (d == null) return;
        Player p = unit.owner;
        Player foe = g.opponentOf(p);
        switch (d) {
            case "retreat": {
                List<Unit> cands = new ArrayList<>();
                for (Unit u : foe.board) if ("前线".equals(u.position)) cands.add(u);
                Unit t = Game.strongest(cands);
                if (t != null) g.keywordMove(t, "后方", "召集");
                else g.log("  [部署] 敌方没有前线单位，[召集] 效果落空。");
                break;
            }
            case "rally_ally": {
                Unit t = null;
                for (Unit u : p.board) {
                    if ("前线".equals(u.position)
                            && (t == null || u.defense < t.defense
                            || (u.defense == t.defense && u.attack < t.attack))) t = u;
                }
                if (t != null) g.keywordMove(t, "后方", "召集");
                else g.log("  [部署] 我方没有前线单位，[召集] 效果落空。");
                break;
            }
            case "advance_ally": {
                List<Unit> cands = new ArrayList<>();
                for (Unit u : p.board) if ("后方".equals(u.position)) cands.add(u);
                Unit t = Game.strongest(cands);
                if (t != null) g.keywordMove(t, "前线", "进军");
                else g.log("  [部署] 我方没有支援阵线单位，[进军] 效果落空。");
                break;
            }
            case "per_enemy": {
                int n = foe.board.size();
                if (n > 0) {
                    unit.attack += n;
                    unit.defense += n;
                    unit.maxDefense += n;
                    g.log("  [部署] " + unit.name() + " 因敌方 " + n + " 个单位获得 +"
                            + n + "/+" + n + "（" + unit.attack + "/" + unit.defense + "）。");
                }
                break;
            }
            case "us_draw2": {
                boolean ok = false;
                for (Unit u : p.board) {
                    if ("前线".equals(u.position) && "美国".equals(u.card.nation)) ok = true;
                }
                if (ok) {
                    g.drawCards(p, 2);
                    g.log("  [部署] " + unit.name() + "：前线有美军单位，抽了 2 张牌！");
                }
                break;
            }
            case "air4": {
                List<Unit> air = new ArrayList<>();
                for (Unit u : foe.board) {
                    if ("战斗机".equals(u.unitType) || "轰炸机".equals(u.unitType)) air.add(u);
                }
                if (!air.isEmpty()) {
                    Unit t = air.get(g.rng.nextInt(air.size()));
                    g.log("  [部署] " + unit.name() + " 对 " + t.name() + " 造成 4 点伤害！");
                    g.damageUnit(t, 4, unit, false);
                } else {
                    g.log("  [部署] 敌方没有空军单位。");
                }
                break;
            }
            case "nuke3": {
                List<Unit> live = new ArrayList<>();
                for (Unit u : foe.board) if (u.defense > 0) live.add(u);
                Unit t = Game.strongest(live);
                if (t != null) {
                    g.log("  [部署] " + unit.name() + " 对 " + t.name() + " 造成 3 点伤害！");
                    g.damageUnit(t, 3, unit, false);
                }
                break;
            }
            case "bomb1": {
                List<Unit> live = new ArrayList<>();
                for (Unit u : foe.board) if (u.defense > 0) live.add(u);
                if (!live.isEmpty()) {
                    Unit t = live.get(g.rng.nextInt(live.size()));
                    g.log("  [部署] " + unit.name() + " 对 " + t.name() + " 造成 1 点伤害。");
                    g.damageUnit(t, 1, unit, false);
                } else {
                    g.log("  [部署] " + unit.name() + " 对敌方总部造成 1 点伤害。");
                    g.damageHq(foe, 1, unit);
                }
                break;
            }
            case "snipe2": {
                List<Unit> cands = new ArrayList<>();
                for (Unit u : foe.board) if (u.defense > 0 && u.attack <= 2) cands.add(u);
                Unit t = Game.strongest(cands);
                if (t != null) {
                    g.log("  [部署] " + unit.name() + " 偷袭并消灭了 " + t.name() + "！");
                    g.destroyUnit(t);
                } else {
                    g.log("  [部署] 没有攻击力≤2 的敌方单位可供消灭。");
                }
                break;
            }
            case "gurkha": {
                int n = p.ordersPlayed;
                if (n > 0) {
                    unit.attack += n;
                    g.log("  [部署] " + unit.name() + " 因本回合使用过 " + n
                            + " 个指令获得 +" + n + " 攻击（" + unit.attack + "）。");
                }
                break;
            }
            case "yokosuka": {
                int n = 0;
                for (Unit u : p.board) if (u != unit && u.card.cost == 0) n++;
                if (n > 0) {
                    unit.attack += n;
                    unit.defense += n;
                    unit.maxDefense += n;
                    g.log("  [部署] " + unit.name() + " 因 " + n + " 个 0 费单位获得 +"
                            + n + "/+" + n + "（" + unit.attack + "/" + unit.defense + "）。");
                }
                break;
            }
            case "m1340": {
                if (p.board.size() > foe.board.size()) {
                    unit.keywords.add("闪击");
                    unit.keywords.add("奋战");
                    unit.canAttack = true;
                    g.log("  [部署] " + unit.name() + " 获得了 [闪击] 和 [奋战]！");
                } else {
                    unit.keywords.add("警卫");
                    g.log("  [部署] " + unit.name() + " 获得了 [警卫]。");
                }
                break;
            }
            case "foe_hand": {
                int n = foe.hand.size();
                if (n > 0) {
                    unit.attack += n;
                    unit.defense += n;
                    unit.maxDefense += n;
                    g.log("  [部署] " + unit.name() + " 因对手的 " + n + " 张手牌获得 +"
                            + n + "/+" + n + "（" + unit.attack + "/" + unit.defense + "）。");
                }
                break;
            }
            case "draw1":
                g.drawCards(p, 1);
                g.log("  [部署] " + unit.name() + " 抽了 1 张牌。");
                break;
            case "front_army_def": {
                int n = 0;
                for (Unit x : p.board) {
                    if ("前线".equals(x.position)
                            && ("步兵".equals(x.unitType) || "坦克".equals(x.unitType))
                            && x.defense > 0) {
                        x.defense += 1;
                        x.maxDefense += 1;
                        n++;
                    }
                }
                g.log(n > 0 ? "  [部署] " + unit.name() + "：前线 " + n + " 个友方陆军防御 +1。"
                        : "  [部署] 前线没有友方陆军，效果落空。");
                break;
            }
            case "self_advance":
                g.keywordMove(unit, "前线", "进军");
                break;
            case "ger_tank_minus": {
                boolean ok = false;
                for (Unit x : p.board) {
                    if ("坦克".equals(x.unitType) && x.defense > 0) ok = true;
                }
                if (ok) {
                    unit.operate = Math.max(0, unit.operate - 1);
                    g.log("  [部署] " + unit.name() + "：有友方坦克，行动费 -1（⚡" + unit.operate + "）。");
                }
                break;
            }
            case "guard_if_blitz": {
                boolean ok = false;
                for (Unit x : foe.board) if (x.has("闪击")) ok = true;
                if (ok) {
                    unit.keywords.add("守护");
                    unit.defense += 2;
                    unit.maxDefense += 2;
                    g.log("  [部署] " + unit.name() + "：敌方有闪击单位，获得[守护]与 +2 防御（"
                            + unit.defense + "）。");
                }
                break;
            }
            case "counter_develop": {
                CardDef found = null;
                for (CardDef c : p.deck) {
                    if (c.isCounter() && "德国".equals(c.nation)) { found = c; break; }
                }
                if (found != null && p.counters.size() < g.rules().counterSlots) {
                    p.deck.remove(found);
                    p.counters.add(found);
                    g.log("  [部署] " + unit.name() + "：开发反制 [ " + found.name + " ]！");
                } else {
                    g.log("  [部署] 卡组里没有可开发的德国反制（或反制区已满）。");
                }
                break;
            }
            case "counter_from_hand": {
                CardDef found = null;
                for (CardDef c : p.hand) {
                    if (c.isCounter()) { found = c; break; }
                }
                if (found != null && p.counters.size() < g.rules().counterSlots) {
                    p.hand.remove(found);
                    p.counters.add(found);
                    g.log("  [部署] " + unit.name() + "：将手中的 [ " + found.name
                            + " ] 激活布置到反制区！");
                } else {
                    g.log("  [部署] 手中没有反制（或反制区已满）。");
                }
                break;
            }
            case "deathmark": {
                List<Unit> live = new ArrayList<>();
                for (Unit x : foe.board) if (x.defense > 0) live.add(x);
                Unit t = Game.strongest(live);
                if (t != null) {
                    t.traits().put("deathwatch_owner", p);
                    g.log("  [部署] " + unit.name() + " 标记 " + t.name()
                            + "：其被消灭时抽一张牌。");
                }
                break;
            }
            case "bounce_ally": {
                Unit t = null;
                for (Unit x : p.board) {
                    if (x != unit && (t == null || x.attack < t.attack
                            || (x.attack == t.attack && x.defense < t.defense))) t = x;
                }
                if (t != null) {
                    p.board.remove(t);
                    p.hand.add(t.card);
                    unit.attack += 1;
                    unit.defense += 1;
                    unit.maxDefense += 1;
                    g.log("  [部署] " + unit.name() + "：" + t.name() + " 返回手牌，自身 +1/+1"
                            + "（" + unit.attack + "/" + unit.defense + "）。");
                } else {
                    g.log("  [部署] 没有其他友方单位，效果落空。");
                }
                break;
            }
            case "ally_minus_operate": {
                List<Unit> cands = new ArrayList<>();
                for (Unit x : p.board) if (x != unit && x.operate > 0) cands.add(x);
                Unit t = Game.strongest(cands);
                if (t != null) {
                    t.operate -= 1;
                    g.log("  [部署] " + unit.name() + "：" + t.name() + " 行动费 -1（⚡" + t.operate + "）。");
                } else {
                    g.log("  [部署] 没有可减费的友方单位。");
                }
                break;
            }
            case "unique_buff": {
                boolean alone = true;
                for (Unit x : p.board) if (x != unit) alone = false;
                if (alone) {
                    unit.attack += 2;
                    unit.defense += 2;
                    unit.maxDefense += 2;
                    g.log("  [部署] " + unit.name() + "：唯一友军，获得 +2/+2（"
                            + unit.attack + "/" + unit.defense + "）。");
                }
                break;
            }
            case "hq_hit_check": {
                Integer hit = g.hqHitTurnOf(foe);
                if (hit != null && hit == g.turnNum) {
                    unit.attack += 2;
                    unit.defense += 2;
                    unit.maxDefense += 2;
                    g.log("  [部署] " + unit.name() + "：敌方总部本回合受过伤，+2/+2（"
                            + unit.attack + "/" + unit.defense + "）。");
                } else {
                    g.log("  [部署] 本回合敌方总部还未受伤，效果落空。");
                }
                break;
            }
            case "ally_tank_atk2": {
                int n = 0;
                for (Unit x : p.board) {
                    if (x != unit && "坦克".equals(x.unitType) && x.defense > 0) {
                        x.attack += 2;
                        n++;
                    }
                }
                g.log(n > 0 ? "  [部署] " + unit.name() + "：" + n + " 个友方坦克攻击 +2。"
                        : "  [部署] 没有友方坦克，效果落空。");
                break;
            }
            case "swap_position": {
                List<Unit> front = new ArrayList<>();
                for (Unit x : p.board) {
                    if (x != unit && "前线".equals(x.position) && x.defense > 0) front.add(x);
                }
                List<Unit> others = front;
                if (others.isEmpty()) {
                    others = new ArrayList<>();
                    for (Unit x : p.board) if (x != unit && x.defense > 0) others.add(x);
                }
                if (!others.isEmpty()) {
                    Unit t = others.get(0);
                    Integer s = unit.slot;
                    unit.slot = t.slot;
                    t.slot = s;
                    String pos = unit.position;
                    unit.position = t.position;
                    t.position = pos;
                    for (Unit x : new Unit[]{unit, t}) {
                        if ("前线".equals(x.position)) g.onArriveFrontline(x);
                        else g.onLeaveFrontline(x);
                    }
                    g.log("  [部署] " + unit.name() + " 与 " + t.name() + " 交换了位置。");
                } else {
                    g.log("  [部署] 没有可交换的友方单位。");
                }
                break;
            }
            case "free_unit2": {
                CardDef pick = null;
                for (CardDef c : p.hand) {
                    if (c.isUnit() && c.cost <= 2 && !c.traits.containsKey("cost_free")) {
                        if (pick == null || c.cost < pick.cost) pick = c;
                    }
                }
                if (pick != null) {
                    CardDef c2 = pick.copy();
                    Map<String, Object> t = new java.util.LinkedHashMap<>(c2.traits);
                    t.put("cost_free", Boolean.TRUE);
                    CardDef replaced = new CardDef(copyWithTraits(c2, t));
                    p.hand.set(p.hand.indexOf(pick), replaced);
                    g.log("  [部署] " + unit.name() + "：" + pick.name + " 的费用变为 0！");
                } else {
                    g.log("  [部署] 手中没有费用≤2的单位，效果落空。");
                }
                break;
            }
            case "production_to_hand":
                p.hand.add(tokenProduction());
                g.log("  [部署] " + unit.name() + "：一张 [生产] 加入手牌。");
                break;
            default:
                g.log("  [部署] 未知部署效果: " + d);
        }
    }

    private static Map<String, Object> copyWithTraits(CardDef c, Map<String, Object> traits) {
        Map<String, Object> m = new java.util.LinkedHashMap<>();
        m.put("kind", c.kind); m.put("name", c.name); m.put("nation", c.nation);
        m.put("cost", (double) c.cost); m.put("rarity", c.rarity);
        m.put("attack", (double) c.attack); m.put("defense", (double) c.defense);
        m.put("keywords", new ArrayList<Object>(c.keywords));
        m.put("unitType", c.unitType); m.put("operate", (double) c.operate);
        m.put("traits", traits); m.put("desc", c.desc); m.put("trigger", c.trigger);
        return m;
    }

    // ---------------- 指令 / 反制效果 ----------------
    public static void run(Game g, Player caster, CardDef card) {
        String id = card.effectId;
        if (id == null) return;
        Player foe = g.opponentOf(caster);
        switch (id) {
            case "blitzkrieg": {
                int n = 0;
                for (Unit u : caster.board) {
                    if ("前线".equals(u.position)) {
                        u.attack += 3;
                        caster.tempBuffs.add(new Player.Buff(u, 3));
                        n++;
                    }
                }
                g.log(n > 0 ? "  闪电战！前线 " + n + " 个友方单位本回合 +3 攻击。"
                        : "  （前线没有友方单位，闪电战落空）");
                break;
            }
            case "ura": {
                int n = 0;
                for (Unit u : caster.board) {
                    if ("苏联".equals(u.card.nation)) {
                        u.attack += 3;
                        caster.tempBuffs.add(new Player.Buff(u, 3));
                        u.overflowTurn = true;
                        n++;
                    }
                }
                g.log("  呜啦！" + n + " 个苏联单位本回合 +3 攻击，溢出伤害将转移至敌方总部！");
                break;
            }
            case "fresh_recruits": {
                if (caster.board.isEmpty()) {
                    g.log("  没有友方单位，新兵入伍落空。");
                    break;
                }
                Unit u = caster.board.get(g.rng.nextInt(caster.board.size()));
                u.attack += 2;
                u.defense += 3;
                u.maxDefense += 3;
                g.log("  " + u.name() + " 获得 +2/+3（" + u.attack + "/" + u.defense + "）。");
                break;
            }
            case "cup_of_tea": {
                int n = 0;
                for (Unit u : caster.board) {
                    if ("英国".equals(u.card.nation)) {
                        u.defense += 2;
                        u.maxDefense += 2;
                        n++;
                    }
                }
                g.log("  一杯茶：" + n + " 个英军单位 +2 防御，士气大振！");
                break;
            }
            case "double_strength": {
                List<CardDef> orders = new ArrayList<>();
                for (CardDef c : caster.hand) if (c.isOrder()) orders.add(c);
                if (orders.isEmpty()) {
                    g.log("  手中没有指令牌，双倍力量落空。");
                    break;
                }
                CardDef c = orders.get(g.rng.nextInt(orders.size()));
                caster.deck.add(g.rng.nextInt(caster.deck.size() + 1), c.copy());
                g.log("  双倍力量：复制了一张 [ " + c.name + " ] 洗入卡组。");
                break;
            }
            case "banzai": {
                for (Player pl : g.players) {
                    for (Unit u : new ArrayList<>(pl.board)) {
                        if (("步兵".equals(u.unitType) || "坦克".equals(u.unitType))
                                && u.attack <= 4) {
                            g.log("  万岁冲锋吞没了 " + u.name() + "！");
                            g.destroyUnit(u);
                        }
                    }
                }
                g.log("  万岁冲锋！你的回合就此结束。");
                g.forceEnd = true;
                break;
            }
            case "naval_support": {
                List<Unit> targets = new ArrayList<>();
                for (Unit u : foe.board) {
                    if (u.defense > 0 && !u.hasTrait("untargetable")) targets.add(u);
                }
                if (!targets.isEmpty()) {
                    Unit t = targets.get(g.rng.nextInt(targets.size()));
                    g.log("  炮火准备命中 " + t.name() + "，造成 2 点伤害！");
                    g.damageUnit(t, 2, null, false);
                } else {
                    g.damageHq(foe, 2, null);
                    g.log("  场上没有目标，炮火准备轰击敌方总部，造成 2 点伤害！");
                }
                break;
            }
            case "resistance":
                g.drawCards(caster, 1);
                caster.hq = Math.min(caster.hqCard.hp, caster.hq + 1);
                g.log("  抽了 1 张牌，总部恢复 1 点生命。");
                break;
            case "winter_war":
                g.damageHq(foe, 2, null);
                g.drawCards(caster, 1);
                g.log("  冬季战争：敌方总部受到 2 点伤害，你抽了 1 张牌。");
                break;
            case "hussars": {
                if (!caster.board.isEmpty()) {
                    Unit u = caster.board.get(g.rng.nextInt(caster.board.size()));
                    u.attack += 1;
                    u.defense += 1;
                    u.maxDefense += 1;
                    g.log("  " + u.name() + " 获得 +1/+1。");
                }
                if (g.canDeploy(caster)) {
                    g.deployUnit(caster, tokenLegion());
                    g.log("  军团（1/1）加入了支援阵线！");
                }
                break;
            }
            case "anzac_storm": {
                if (caster.board.isEmpty()) {
                    g.log("  没有友方单位，澳新风暴落空。");
                    break;
                }
                for (Unit u : caster.board) {
                    u.attack += 1;
                    if (!u.has("冲击")) u.keywords.add("冲击");
                }
                g.log("  己方所有单位 +1 攻击并获得 [冲击]！");
                break;
            }
            case "lotta": {
                if (caster.board.isEmpty()) {
                    g.log("  没有友方单位，洛塔组织落空。");
                    break;
                }
                for (Unit u : caster.board) {
                    u.defense += 1;
                    u.maxDefense += 1;
                }
                g.log("  洛塔组织：己方所有单位 +1 防御！");
                break;
            }
            case "anzac_spirit": {
                for (Unit u : new ArrayList<>(foe.board)) g.damageUnit(u, 2, null, false);
                g.drawCards(caster, 2);
                g.log("  澳新军团精神：所有敌方单位受到 2 点伤害，你抽了 2 张牌。");
                break;
            }
            case "naval_support_uk": {
                if (caster.board.isEmpty()) {
                    g.log("  没有友方单位，海军支援落空。");
                    break;
                }
                Unit best = caster.board.get(0);
                for (Unit u : caster.board) {
                    if (u.defense > best.defense
                            || (u.defense == best.defense && u.attack > best.attack)) best = u;
                }
                int before = best.attack;
                best.attack = best.defense;
                g.log("  海军支援：" + best.name() + " 的攻击力 " + before + " → "
                        + best.attack + "（等同于防御力）。");
                break;
            }
            case "ats": {
                foe.atsMark = g.playersIndex(caster) + 1;
                g.log("  本土防卫军监视敌方总部：本回合其受到 3 点或以上伤害时，你抽一张牌。");
                break;
            }
            case "yamato": {
                int n = 0;
                for (Unit u : caster.board) {
                    if ("日本".equals(u.card.nation)) {
                        u.dyingHq = 2;
                        n++;
                    }
                }
                g.log("  大和号坐镇！" + n + " 个日军单位获得 [亡计：对敌方总部 2 伤]。");
                break;
            }
            case "bombing_raid": {
                List<Unit> live = new ArrayList<>();
                for (Unit u : foe.board) {
                    if (u.defense > 0 && !u.hasTrait("untargetable")) live.add(u);
                }
                if (live.isEmpty()) {
                    g.damageHq(foe, 3, null);
                    break;
                }
                Unit t = live.get(g.rng.nextInt(live.size()));
                g.log("  轰炸突袭：" + t.name() + " 受到 3 点伤害！");
                g.damageUnit(t, 3, null, false);
                for (Unit u : new ArrayList<>(foe.board)) {
                    if (u == t || u.defense <= 0) continue;
                    if (u.slot != null && t.slot != null && Math.abs(u.slot - t.slot) == 1) {
                        g.log("  波及伤害：" + u.name() + " 受到 2 点伤害。");
                        g.damageUnit(u, 2, null, false);
                    }
                }
                break;
            }
            case "conscripts":
                g.log("  征召令：新兵列队完毕。（无其他效果）");
                break;
            case "deal_hq": {
                int amount = p(card, "amount", 1);
                g.log("  精准打击：敌方总部受到 " + amount + " 点伤害！");
                g.damageHq(foe, amount, null);
                break;
            }
            case "deal_all": {
                int amount = p(card, "amount", 1);
                g.log("  火力覆盖：所有敌方单位受到 " + amount + " 点伤害！");
                for (Unit u : new ArrayList<>(foe.board)) {
                    if (u.defense > 0) g.damageUnit(u, amount, null, false);
                }
                break;
            }
            case "draw": {
                int n = p(card, "n", 1);
                g.drawCards(caster, n);
                g.log("  抽了 " + n + " 张牌。");
                break;
            }
            case "advance_ally": {
                List<Unit> cands = new ArrayList<>();
                for (Unit u : caster.board) if ("后方".equals(u.position)) cands.add(u);
                Unit t = Game.strongest(cands);
                if (t != null) g.keywordMove(t, "前线", "进军");
                else g.log("  [进军] 我方没有支援阵线单位，效果落空。");
                break;
            }
            case "rally_ally": {
                List<Unit> cands = new ArrayList<>();
                for (Unit u : caster.board) if ("前线".equals(u.position)) cands.add(u);
                if (cands.isEmpty()) {
                    g.log("  [召集] 我方没有前线单位，效果落空。");
                    break;
                }
                Unit t = cands.get(0);
                for (Unit u : cands) {
                    if (u.defense < t.defense
                            || (u.defense == t.defense && u.attack < t.attack)) t = u;
                }
                g.keywordMove(t, "后方", "召集");
                break;
            }
            case "destroy_random": {
                List<Unit> live = new ArrayList<>();
                for (Unit u : foe.board) {
                    if (u.defense > 0 && !u.hasTrait("untargetable")) live.add(u);
                }
                if (!live.isEmpty()) {
                    Unit t = live.get(g.rng.nextInt(live.size()));
                    g.log("  精确清除：" + t.name() + " 被消灭！");
                    g.destroyUnit(t);
                } else {
                    g.log("  场上没有目标，效果落空。");
                }
                break;
            }
            case "destroy_damaged": {
                Unit t = pickDestroy(g, foe, u -> u.defense < u.maxDefense);
                if (t != null) {
                    g.log("  重点摧毁：" + t.name() + " 被消灭！");
                    g.destroyUnit(t);
                } else {
                    g.log("  没有符合条件的敌方单位，效果落空。");
                }
                break;
            }
            case "destroy_cost_le": {
                int cost = p(card, "cost", 99);
                List<Unit> cands = new ArrayList<>();
                for (Unit u : foe.board) {
                    if (u.defense > 0 && !u.hasTrait("untargetable") && u.card.cost <= cost) {
                        cands.add(u);
                    }
                }
                Unit t = Game.strongest(cands);
                if (t != null) {
                    g.log("  低费清除（费用≤" + cost + "）：" + t.name() + " 被消灭！");
                    g.destroyUnit(t);
                } else {
                    g.log("  没有符合条件的敌方单位，效果落空。");
                }
                break;
            }
            case "production":
                caster.kredits += 1;
                g.log("  [生产] " + caster.name + " 获得 1 指挥点（共 " + caster.kredits + "）。");
                break;
            case "demolition": {
                List<Unit> live = new ArrayList<>();
                for (Unit u : foe.board) {
                    if (u.defense > 0 && !u.hasTrait("order_immune")) live.add(u);
                }
                if (!live.isEmpty()) {
                    Unit t = live.get(0);
                    for (Unit u : live) {
                        if (u.defense < t.defense
                                || (u.defense == t.defense && u.attack < t.attack)) t = u;
                    }
                    g.log("  [爆破] 对 " + t.name() + " 造成 1 点伤害。");
                    g.damageUnit(t, 1, null, false);
                } else {
                    g.log("  [爆破] 没有可指定的敌方单位，效果落空。");
                }
                break;
            }
            case "plan":
                g.drawCards(caster, 1);
                g.log("  [计划] 抽了一张牌。");
                break;
            default:
                g.log("  [效果未实现: " + id + "，已跳过]");
        }
    }

    private interface UnitFilter { boolean ok(Unit u); }

    private static Unit pickDestroy(Game g, Player foe, UnitFilter filt) {
        List<Unit> live = new ArrayList<>();
        for (Unit u : foe.board) {
            if (u.defense > 0 && !u.hasTrait("untargetable") && filt.ok(u)) live.add(u);
        }
        return Game.strongest(live);
    }
}
