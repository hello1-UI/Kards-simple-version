package com.kards.engine;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.function.Consumer;

/** 对局主体（对齐 kards_engine.Game，v1.6.3.12 规则）。
 *
 * 已对齐的核心规则：
 *  - 指挥点槽（开局 0 / 回合开始 +1 至 12 / 绝对上限 24，指挥点=槽数）
 *  - 反击简化：打单位必吃反击，唯一免法是进攻方[冲击]（攻击后消耗）
 *  - 动员：回合开始 +1/+1，受伤只失去关键词、加成保留，失去后不再成长
 *  - 攻击射程：战斗机/轰炸机/炮兵任意阵线；步兵/坦克只打相邻阵线
 *  - 前线占领：同一时刻只有一方控制前线（canTakeFrontline）
 *  - 总部血量 20，各国研发被动区分特色
 */
public final class Game {
    public final Player[] players = new Player[2];
    public final CardDb db;
    public int turnNum = 0;
    public Player current;
    public boolean over = false;
    public Player conceded = null;
    public boolean forceEnd = false;
    public final Random rng;
    private final Map<Player, Integer> hqHitTurn = new LinkedHashMap<>();
    private Consumer<String> logSink = s -> { };
    private Consumer<String> eventSink = s -> { };

    public Game(Player p1, Player p2, CardDb db, long seed) {
        players[0] = p1;
        players[1] = p2;
        this.db = db;
        current = p1;
        this.rng = new Random(seed);
    }

    public void setLogSink(Consumer<String> sink) { this.logSink = sink; }
    public void setEventSink(Consumer<String> sink) { this.eventSink = sink; }

    public void log(String msg) { logSink.accept(msg); }

    private void emit(String type, Object... kv) {
        StringBuilder sb = new StringBuilder(type);
        for (int i = 0; i + 1 < kv.length; i += 2) {
            sb.append('|').append(kv[i]).append('=').append(kv[i + 1]);
        }
        eventSink.accept(sb.toString());
    }

    public Player opponentOf(Player p) {
        return p == players[0] ? players[1] : players[0];
    }

    public Integer hqHitTurnOf(Player p) { return hqHitTurn.get(p); }

    public int playersIndex(Player p) { return p == players[0] ? 0 : 1; }

    // ---------------- 费用与研发 ----------------
    public int getCost(CardDef card, Player p) {
        int cost = card.cost;
        if (card.isUnit() && card.traits.containsKey("cost_free")
                && Boolean.TRUE.equals(card.traits.get("cost_free"))) {
            return 0;
        }
        String perk = p.hqCard.perk;
        if ("tank_discount".equals(perk) && card.isUnit() && "坦克".equals(card.unitType)) {
            cost = Math.max(1, cost - 1);
        }
        if ("support_discount".equals(perk) && (card.isOrder() || card.isCounter())) {
            cost = Math.max(1, cost - 1);
        }
        if (card.isUnit() && "德国".equals(card.nation)) {
            for (Unit u : p.board) {
                if (u.hasTrait("ger_hand_discount") && u.defense > 0) {
                    cost = Math.max(1, cost - 1);
                    break;
                }
            }
        }
        return cost;
    }

    public List<Integer> playableCards(Player p) {
        List<Integer> res = new ArrayList<>();
        for (int i = 0; i < p.hand.size(); i++) {
            CardDef c = p.hand.get(i);
            if (getCost(c, p) > p.kredits) continue;
            if (c.isUnit() && !canDeploy(p)) continue;
            if (c.isCounter() && p.counters.size() >= rules().counterSlots) continue;
            res.add(i);
        }
        return res;
    }

    public boolean canDeploy(Player p) {
        if (p.board.size() >= rules().boardSize) return false;
        int rear = 0;
        for (Unit u : p.board) if ("后方".equals(u.position)) rear++;
        return rear < rules().rearSlots;
    }

    public CardDb.Rules rules() { return db.rules; }

    // ---------------- 抽牌 ----------------
    public void drawCards(Player p, int n) {
        for (int i = 0; i < n; i++) {
            if (p.deck.isEmpty()) {
                // 士气伤害（旧称疲劳）：1起递增，与[协力]惩罚共用 p.morale
                p.morale++;
                damageHq(p, p.morale, null);
                log("  " + p.name + " 牌库已空，受到 " + p.morale + " 点士气伤害！");
                continue;
            }
            if (p.hand.size() >= rules().handLimit) {
                p.discard.add(p.deck.remove(p.deck.size() - 1));
                log("  " + p.name + " 手牌已满，1 张牌被烧毁。");
                continue;
            }
            p.hand.add(p.deck.remove(p.deck.size() - 1));
        }
    }

    // ---------------- 伤害结算 ----------------
    public void damageUnit(Unit unit, int amount, Unit source, boolean combat) {
        if (amount > 0) {
            int red = combat ? unit.armor() : 0;
            if (red > 0) {
                amount = Math.max(0, amount - red);
                log("  " + unit.name() + " 的[装甲]抵消了 " + red + " 点伤害。");
            }
            // [动员]：受到实际伤害只失去关键词，已获得的加成保留（v1.6.3.12）
            if (amount > 0 && unit.has("动员")) {
                unit.keywords.remove("动员");
                unit.mob = 0;
                log("  " + unit.name() + " 受到伤害，失去[动员]（已获得的加成保留）。");
            }
        }
        if (amount > 0) {
            unit.defense -= amount;
            emit("unit_damage", "unit", unit.name(), "amount", amount);
            if (unit.defense <= 0) {
                destroyUnit(unit);
                if (source != null && source.has("收缴")
                        && source.owner != unit.owner
                        && !unit.owner.board.contains(unit)) {
                    applyConfiscate(source, unit);
                }
            }
        }
    }

    public void damageHq(Player player, int amount, Unit source) {
        hqHitTurn.put(player, turnNum);
        if (amount <= 0 || player.hq <= 0) {
            if (amount > 0 && player.hq > 0) {
                player.hq = Math.max(0, player.hq - amount);
                emit("hq_damage", "player", player.name, "amount", amount);
            }
            checkGameOver();
            return;
        }
        // 西苏精神：反制转嫁
        CardDef c = checkCounter(player, "hq_damage", null);
        if (c != null) {
            log("  ⚡ " + player.name + " 的反制 [ " + c.name + " ] 触发！"
                    + amount + " 点伤害转嫁给敌方总部！");
            emit("counter", "card", c.name);
            damageHq(opponentOf(player), amount, source);
            return;
        }
        player.hq = Math.max(0, player.hq - amount);
        emit("hq_damage", "player", player.name, "amount", amount);
        for (Unit u : player.board) {
            if (u.hasTrait("hq_hurt_grow")) {
                u.attack += 1;
                log("  " + u.name() + " 因总部受伤获得 +1 攻击（" + u.attack + "）。");
            }
        }
        if (amount >= 3 && player.atsMark != 0) {
            Player marker = players[player.atsMark - 1];
            drawCards(marker, 1);
            log("  [本土防卫军] " + player.name + " 的总部受到 " + amount
                    + " 点伤害，" + marker.name + " 抽了 1 张牌。");
        }
        checkGameOver();
    }

    private void checkGameOver() {
        if (!over && (players[0].hq <= 0 || players[1].hq <= 0)) over = true;
    }

    public void applyConfiscate(Unit killer, Unit victim) {
        Player owner = killer.owner;
        CardDef c = victim.card;
        if (owner.hand.size() >= rules().handLimit) {
            log("  " + owner.name + " 手牌已满，无法收缴 " + victim.name() + "。");
            return;
        }
        CardDef token = c.confiscateCopy();
        owner.hand.add(token);
        log("  [收缴]：" + killer.name() + " 缴获 " + victim.name()
                + "！一张 1/1 副本（费用 " + token.cost + "）加入手牌。");
        emit("confiscate", "unit", killer.name());
    }

    public void destroyUnit(Unit unit) {
        if (!unit.owner.board.contains(unit)) return;
        unit.owner.board.remove(unit);
        unit.owner.discard.add(unit.card);
        emit("destroy", "unit", unit.name());
        log("  " + unit.name() + " 被消灭了。");
        Object watcher = unit.trait("deathwatch_owner");
        if (watcher instanceof Player) {
            drawCards((Player) watcher, 1);
            log("  [第738猎兵团] 标记的目标 " + unit.name() + " 被消灭，抽一张牌！");
        }
        Player killerSide = opponentOf(unit.owner);
        if (current == killerSide) {
            for (Unit x : new ArrayList<>(killerSide.board)) {
                if (x.hasTrait("kill_kredits") && x.defense > 0
                        && once(killerSide, "supply_" + System.identityHashCode(x))) {
                    killerSide.kredits += 2;
                    log("  " + x.name() + "：消灭敌军，获得 2 指挥点（共 "
                            + killerSide.kredits + "）。");
                }
            }
        }
        if (unit.dyingHq > 0) {
            Player foe = opponentOf(unit.owner);
            log("  [亡计] " + unit.name() + " 对敌方总部造成 " + unit.dyingHq + " 点伤害！");
            damageHq(foe, unit.dyingHq, unit);
        }
        for (Unit u : new ArrayList<>(opponentOf(unit.owner).board)) {
            if (u.hasTrait("kill_grow")) {
                u.attack += 2;
                log("  " + u.name() + " 因敌方单位被消灭获得 +2 攻击（" + u.attack + "）。");
            }
        }
        for (CardDef c : new ArrayList<>(unit.owner.counters)) {
            if ("friendly_death".equals(c.trigger)) {
                unit.owner.counters.remove(c);
                unit.owner.discard.add(c);
                log("  ⚡ " + unit.owner.name + " 的反制 [ " + c.name + " ] 触发！");
                emit("counter", "card", c.name);
                if (c.effectId != null) Effects.run(this, unit.owner, c);
            }
        }
    }

    // ---------------- 部署与位置 ----------------
    public Integer nextSlot(Player p) {
        List<Integer> used = new ArrayList<>();
        for (Unit u : p.board) if (u.slot != null) used.add(u.slot);
        for (int i = 0; i < rules().boardSize; i++) {
            if (!used.contains(i)) return i;
        }
        return null;
    }

    public Unit deployUnit(Player p, CardDef card) {
        if (p.board.size() >= rules().boardSize) return null;
        Unit u = new Unit(card, p);
        u.slot = nextSlot(p);
        if (!u.keywords.contains("闪击")) u.freshDeploy = true;
        p.board.add(u);
        emit("deploy", "unit", u.name(), "player", p.name);
        if (u.has("山地")) {
            int n = 0;
            for (Unit x : p.board) {
                if (x != u && x.has("山地") && x.defense > 0) n++;
            }
            if (n > 0) bump(u, n, n, n + " 个山地单位");
            for (Unit x : p.board) {
                if (x != u && x.hasTrait("mtn_grow") && x.defense > 0) {
                    bump(x, 1, 1, "山地单位加入");
                }
            }
        }
        for (Unit x : new ArrayList<>(p.board)) {
            if (x != u && x.hasTrait("self_destruct_on_deploy")) {
                log("  " + x.name() + " 主动让位（友军部署时消灭本单位）。");
                destroyUnit(x);
            }
        }
        if ("坦克".equals(u.unitType)) {
            for (Unit x : p.board) {
                if (x != u && "ally_tank_deploy".equals(x.strTrait("vet_when"))) {
                    vetUpgrade(x);
                }
            }
        }
        if (u.attack >= 4) {
            for (Unit x : p.board) {
                if (x != u && x.hasTrait("deploy_kredits4")
                        && once(p, "shizhongtang_" + System.identityHashCode(x))) {
                    p.kredits += 2;
                    log("  " + x.name() + "：部署强力单位，获得 2 指挥点（共 " + p.kredits + "）。");
                }
            }
        }
        for (Unit other : p.board) {
            if (other != u && other.hasTrait("inf_aura") && "步兵".equals(u.unitType)) {
                u.attack += 1;
                log("  " + other.name() + " 的光环使 " + u.name() + " +1 攻击（" + u.attack + "）。");
            }
        }
        return u;
    }

    public static Unit strongest(List<Unit> units) {
        List<Unit> live = new ArrayList<>();
        for (Unit u : units) if (!u.hasTrait("order_immune")) live.add(u);
        if (live.isEmpty()) live = units;
        Unit best = null;
        for (Unit u : live) {
            if (best == null || u.attack > best.attack
                    || (u.attack == best.attack && u.defense > best.defense)) best = u;
        }
        return best;
    }

    // ---------------- 前线机制 ----------------
    public Player frontlineOwner() {
        for (Player p : players) {
            for (Unit u : p.board) if ("前线".equals(u.position)) return p;
        }
        return null;
    }

    public boolean canTakeFrontline(Player p) {
        for (Unit u : opponentOf(p).board) {
            if ("前线".equals(u.position)) return false;
        }
        int n = 0;
        for (Unit u : p.board) if ("前线".equals(u.position)) n++;
        return n < rules().frontlineSlots;
    }

    // ---------------- 新词条钩子 ----------------
    public boolean once(Player p, String tag) {
        Integer used = p.onceTurn.get(tag);
        if (used != null && used == turnNum) return false;
        p.onceTurn.put(tag, turnNum);
        return true;
    }

    public void bump(Unit u, int atk, int hp, String why) {
        u.attack += atk;
        u.defense += hp;
        u.maxDefense += hp;
        String extra = why == null || why.isEmpty() ? "" : "（" + why + "）";
        log("  " + u.name() + " 获得 +" + atk + "/+" + hp + extra
                + "（" + u.attack + "/" + u.defense + "）。");
    }

    public void vetUpgrade(Unit u) {
        if (u.veteran || u.has("老兵")) return;
        u.veteran = true;
        u.keywords.add("老兵");
        Map<String, Object> vet = unitObjTrait(u, "vet");
        int atk = vet.containsKey("atk") ? MiniJson.getInt(vet, "atk") : u.attack;
        int hp = vet.containsKey("hp") ? MiniJson.getInt(vet, "hp") : u.defense;
        u.attack = atk;
        u.defense = hp;
        u.maxDefense = hp;
        for (Object kw : MiniJson.arr(vet.get("kw"))) {
            String k = String.valueOf(kw);
            if (!u.keywords.contains(k)) u.keywords.add(k);
        }
        log("  ⭐ " + u.name() + " 升级为老兵！（" + u.attack + "/" + u.defense + "）");
        emit("veteran", "unit", u.name());
        if ("kredits2".equals(vet.get("effect"))) {
            u.owner.kredits += 2;
            log("  升级奖励：获得 2 指挥点（共 " + u.owner.kredits + "）。");
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> unitObjTrait(Unit u, String key) {
        Object v = u.trait(key);
        return v instanceof Map ? (Map<String, Object>) v : new LinkedHashMap<>();
    }

    public void onArriveFrontline(Unit u) {
        if (!"前线".equals(u.position)) return;
        if (u.has("烟幕")) {
            u.keywords.remove("烟幕");
            log("  " + u.name() + " 进入前线，[烟幕]失效。");
        }
        if ("front_move".equals(u.strTrait("vet_when"))) vetUpgrade(u);
        if (u.hasTrait("front_gain_ambush") && !u.has("伏击")) {
            u.keywords.add("伏击");
            log("  " + u.name() + " 进军前线，获得[伏击]！");
        }
        if (u.hasTrait("front_hq3")) {
            Player foe = opponentOf(u.owner);
            log("  " + u.name() + " 进军前线，炮火延伸：敌方总部受 3 点伤害！");
            damageHq(foe, 3, u);
        }
        if (u.hasTrait("front_buff2")) {
            log("  " + u.name() + " 进军前线，前线所有单位攻击 +2（本回合）！");
            for (Player side : players) {
                for (Unit x : side.board) {
                    if ("前线".equals(x.position) && x.defense > 0) {
                        x.attack += 2;
                        side.tempBuffs.add(new Player.Buff(x, 2));
                    }
                }
            }
        }
        if (u.hasTrait("front_atk2") && !u.frontAtkActive) {
            u.frontAtkActive = true;
            u.attack += 2;
            log("  " + u.name() + " 在前线，攻击 +2（" + u.attack + "）。");
        }
        if ("德国".equals(u.card.nation)) {
            for (Unit x : u.owner.board) {
                if (x != u && x.hasTrait("moto_buff") && x.defense > 0) {
                    u.attack += 1;
                    u.operate = Math.max(0, u.operate - 1);
                    log("  " + x.name() + " 的联动：" + u.name() + " +1 攻击、行动费 -1"
                            + "（" + u.attack + "/⚡" + u.operate + "）。");
                }
            }
        }
    }

    public void onLeaveFrontline(Unit u) {
        if (u.hasTrait("front_atk2") && u.frontAtkActive) {
            u.frontAtkActive = false;
            u.attack -= 2;
            log("  " + u.name() + " 撤回后方，前线加成消失（" + u.attack + "）。");
        }
    }

    public void postAction(Unit u, int spent, boolean attack) {
        Player owner = u.owner;
        if (attack && u.has("烟幕")) {
            u.keywords.remove("烟幕");
            log("  " + u.name() + " 行动后失去[烟幕]。");
        }
        if ("acted".equals(u.strTrait("vet_when"))) vetUpgrade(u);
        if (attack && u.hasTrait("pincer_grow") && owner.board.contains(u)) {
            bump(u, 1, 1, "钳击");
        }
        if (attack && u.hasTrait("pincer_spread") && owner.board.contains(u)) {
            for (Unit x : owner.board) {
                if (x != u && x.has("钳击")) bump(x, 1, 1, "钳击协同");
            }
        }
        if ("德国".equals(u.card.nation)) {
            for (Unit x : owner.board) {
                if (x.hasTrait("act_minus")) {
                    x.operate = Math.max(0, x.operate - 1);
                    log("  " + x.name() + " 的行动费 -1（⚡" + x.operate + "）。");
                }
                if (x != u && x.hasTrait("ger_act_grow")) {
                    bump(x, 1, 1, u.name() + " 行动");
                }
            }
        }
        if (spent > 0) {
            for (Unit x : owner.board) {
                if (x.hasTrait("blue_legion")) {
                    bump(u, spent, spent, "蓝色军团（花费 " + spent + "）");
                    break;
                }
            }
        }
    }

    public boolean moveUnit(Unit unit, String dest) {
        if (unit.moved) {
            log("  " + unit.name() + " 本回合已经移动过了。");
            return false;
        }
        if (unit.freshDeploy) {
            log("  " + unit.name() + " 刚加入战场，需要[闪击]才能立即移动！");
            return false;
        }
        if ("步兵".equals(unit.unitType) && unit.attacksMade > 0
                && !unit.hasTrait("move_and_attack")) {
            log("  " + unit.name() + "（步兵）本回合已攻击过，不能再移动！");
            return false;
        }
        if ("前线".equals(dest)) {
            if ("前线".equals(unit.position)) return false;
            if (!canTakeFrontline(unit.owner)) {
                Player enemy = opponentOf(unit.owner);
                boolean occupied = false;
                for (Unit u : enemy.board) if ("前线".equals(u.position)) occupied = true;
                log(occupied ? "  前线被敌方占领！先清掉敌方前线单位才能上前线。"
                        : "  我方前线位已满（4 个）！");
                return false;
            }
        } else {
            if ("后方".equals(unit.position)) return false;
        }
        int spent = 0;
        if (unit.operate > 0) {
            if (unit.owner.kredits < unit.operate) {
                log("  " + unit.name() + " 移动需要 " + unit.operate + " 点行动费，指挥点不足！");
                return false;
            }
            unit.owner.kredits -= unit.operate;
            spent = unit.operate;
            log("  " + unit.name() + " 支付 " + unit.operate + " 点行动费进行移动（剩余 "
                    + unit.owner.kredits + "）。");
        }
        if ("前线".equals(dest)) {
            unit.position = "前线";
            log("  " + unit.name() + " 奔赴前线，占领前线！");
        } else {
            unit.position = "后方";
            log("  " + unit.name() + " 撤回了后方。");
        }
        unit.moved = true;
        if ("前线".equals(dest)) onArriveFrontline(unit);
        else onLeaveFrontline(unit);
        postAction(unit, spent, false);
        return true;
    }

    public boolean keywordMove(Unit unit, String dest, String source) {
        String tag = source == null || source.isEmpty() ? "" : "[" + source + "] ";
        String where = "前线".equals(dest) ? "前线" : "支援阵线";
        if (unit.position.equals(dest)) {
            log("  " + tag + unit.name() + " 已在" + where + "，效果落空。");
            return false;
        }
        if ("前线".equals(dest) && !canTakeFrontline(unit.owner)) {
            log("  " + tag + "前线被敌方占领或已满，" + unit.name() + " 无法进军。");
            return false;
        }
        unit.position = dest;
        log("  " + tag + unit.name() + ("前线".equals(dest) ? " 奔赴前线！" : " 移回了支援阵线。"));
        if ("前线".equals(dest)) onArriveFrontline(unit);
        else onLeaveFrontline(unit);
        emit("move", "unit", unit.name());
        return true;
    }

    // ---------------- 攻击 ----------------
    public List<Unit> attackTargets(Unit attacker) {
        Player enemy = opponentOf(attacker.owner);
        List<Unit> pool = new ArrayList<>();
        if (rules().rangedTypes.contains(attacker.unitType)) {
            pool.addAll(enemy.board);
        } else if ("前线".equals(attacker.position)) {
            pool.addAll(enemy.board);
        } else {
            for (Unit u : enemy.board) if ("前线".equals(u.position)) pool.add(u);
        }
        boolean smoked = false;
        for (Unit t : pool) if (t.has("烟幕")) { smoked = true; break; }
        if (smoked) {
            List<Unit> np = new ArrayList<>();
            for (Unit t : pool) if (!t.has("烟幕")) np.add(t);
            pool = np;
            if (pool.isEmpty()) return pool;
        }
        if (!"炮兵".equals(attacker.unitType) && !"轰炸机".equals(attacker.unitType)) {
            List<Unit> guarded = new ArrayList<>();
            for (Unit t : pool) if (isGuarded(t)) guarded.add(t);
            if (!guarded.isEmpty() && guarded.size() < pool.size()) {
                List<Unit> np = new ArrayList<>();
                for (Unit t : pool) if (!guarded.contains(t)) np.add(t);
                pool = np;
            } else if (!guarded.isEmpty()) {
                return new ArrayList<>();
            }
        }
        if ("轰炸机".equals(attacker.unitType)) {
            boolean hasF = false;
            for (Unit u : pool) if ("战斗机".equals(u.unitType)) hasF = true;
            if (hasF) {
                List<String> lines = new ArrayList<>();
                for (Unit u : pool) {
                    if ("战斗机".equals(u.unitType) && !lines.contains(u.position)) {
                        lines.add(u.position);
                    }
                }
                List<Unit> res = new ArrayList<>();
                for (Unit u : pool) {
                    if ("战斗机".equals(u.unitType) || !lines.contains(u.position)) res.add(u);
                }
                return res;
            }
        }
        if ("炮兵".equals(attacker.unitType) || "轰炸机".equals(attacker.unitType)) {
            return pool;
        }
        List<Unit> guards = new ArrayList<>();
        for (Unit u : pool) if (u.has("警卫")) guards.add(u);
        if (guards.isEmpty()) return pool;
        List<Unit> res = new ArrayList<>();
        for (Unit u : pool) {
            if (guards.contains(u)) { res.add(u); continue; }
            boolean protectedOk = false;
            for (Unit g : guards) {
                if (g != u && g.slot != null && u.slot != null
                        && Math.abs(g.slot - u.slot) == 1) { protectedOk = true; break; }
            }
            if (!protectedOk) res.add(u);
        }
        return res.isEmpty() ? pool : res;
    }

    public boolean isGuarded(Unit unit) {
        if (unit.has("守护")) return false;
        for (Unit g : unit.owner.board) {
            if (g.has("守护") && g.defense > 0 && g != unit
                    && g.slot != null && unit.slot != null
                    && Math.abs(g.slot - unit.slot) == 1) return true;
        }
        return false;
    }

    public boolean canHitHq(Unit attacker) {
        if (!"前线".equals(attacker.position)
                && !rules().rangedTypes.contains(attacker.unitType)) {
            return false;
        }
        Player enemy = opponentOf(attacker.owner);
        if (!"炮兵".equals(attacker.unitType) && !"轰炸机".equals(attacker.unitType)) {
            for (Unit u : enemy.board) {
                if (u.has("警卫") && u.slot != null && u.slot == 0) return false;
            }
        }
        return true;
    }

    public int hqDamage(Unit attacker) {
        return attacker.attack + ("轰炸机".equals(attacker.unitType) ? 2 : 0);
    }

    public boolean unitReady(Unit u) {
        if (!u.canAttack || u.attacksMade >= u.maxAttacks()) return false;
        if (u.freshDeploy) return false;
        if (u.operate > 0 && u.owner.kredits < u.operate) return false;
        if ("步兵".equals(u.unitType) && u.moved && !u.hasTrait("move_and_attack")) return false;
        if (u.attack >= 5) {
            for (Player pl : players) {
                for (Unit x : pl.board) if (x.hasTrait("lock5")) return false;
            }
        }
        return true;
    }

    public int combatDamage(Unit attacker, Unit target) {
        int dmg = attacker.attack;
        List<String> t2 = attacker.listTrait("dmg2");
        if (!t2.isEmpty()) {
            boolean hit = t2.contains(target.unitType)
                    || (("战斗机".equals(target.unitType) || "轰炸机".equals(target.unitType))
                    && t2.contains("空军"));
            if (hit) {
                dmg *= 2;
                log("  " + attacker.name() + " 对" + target.unitType + "造成双倍伤害！");
            }
        }
        if (attacker.hasTrait("katyusha")) {
            int extra = rng.nextInt(2);
            if (extra > 0) {
                dmg += extra;
                log("  喀秋莎的火箭弹造成 " + extra + " 点额外伤害！");
            }
        }
        if (attacker.hasTrait("anti_strong") && target.attack > attacker.attack) {
            dmg += 2;
            log("  " + attacker.name() + " 面对更强的敌人，攻击 +2！");
        }
        return dmg;
    }

    public Unit interceptor(Player defenderSide) {
        Unit best = null;
        for (Unit u : defenderSide.board) {
            if ("战斗机".equals(u.unitType) && u.defense > 0) {
                if (best == null || u.attack > best.attack
                        || (u.attack == best.attack && u.defense > best.defense)) best = u;
            }
        }
        return best;
    }

    public void doAttack(Unit attacker, Unit target) {
        if ("轰炸机".equals(attacker.unitType) && !"战斗机".equals(target.unitType)) {
            Unit fi = interceptor(target.owner);
            if (fi != null) {
                log("  ⚡ " + fi.name() + " 紧急升空拦截 " + attacker.name() + "！攻击被迫转向！");
                target = fi;
            }
        }
        log("  " + attacker.name() + " 攻击 " + target.name() + "！");
        int spent = 0;
        if (attacker.operate > 0) {
            if (attacker.owner.kredits < attacker.operate) {
                log("  " + attacker.name() + " 需要 " + attacker.operate
                        + " 点行动费，指挥点不足，攻击取消！");
                return;
            }
            attacker.owner.kredits -= attacker.operate;
            spent = attacker.operate;
            log("  " + attacker.name() + " 支付 " + attacker.operate + " 点行动费（剩余 "
                    + attacker.owner.kredits + "）。");
        }
        CardDef counter = checkCounter(target.owner, "attack", attacker);
        if (counter != null) {
            log("  ⚡ " + target.owner.name + " 的反制 [ " + counter.name
                    + " ] 触发！" + attacker.name() + " 被消灭！");
            emit("counter", "card", counter.name);
            destroyUnit(attacker);
            attacker.attacksMade++;
            return;
        }
        if (target.has("伏击")) {
            log("  " + target.name() + " 的[伏击]先发制人！");
            damageUnit(attacker, combatDamage(target, attacker), target, true);
            if (attacker.defense <= 0 || !attacker.owner.board.contains(attacker)) {
                log("  " + attacker.name() + " 在伏击中阵亡，攻击失败！");
                attacker.attacksMade++;
                return;
            }
        }
        if (attacker.hasTrait("barrage")) {
            Player foe = opponentOf(attacker.owner);
            boolean any = false;
            for (Unit u : foe.board) if (u.defense > 0) any = true;
            if (any) {
                log("  " + attacker.name() + " 的火力随机覆盖敌方阵地（3 点伤害）！");
                for (int i = 0; i < 3; i++) {
                    List<Unit> live = new ArrayList<>();
                    for (Unit u : foe.board) if (u.defense > 0) live.add(u);
                    if (live.isEmpty()) break;
                    damageUnit(live.get(rng.nextInt(live.size())), 1, attacker, true);
                }
            } else {
                log("  " + attacker.name() + " 对敌方总部造成 3 点伤害！");
                damageHq(foe, 3, attacker);
            }
        } else {
            int dmg = combatDamage(attacker, target);
            int preDef = target.defense;
            damageUnit(target, dmg, attacker, true);
            boolean died = !target.owner.board.contains(target) || target.defense <= 0;
            if (died) {
                int overflow = dmg - preDef;
                if (overflow > 0 && (attacker.hasTrait("overflow_hq") || attacker.overflowTurn)) {
                    log("  " + attacker.name() + " 的溢出 " + overflow + " 点伤害转移到敌方总部！");
                    damageHq(opponentOf(attacker.owner), overflow, attacker);
                }
            } else if (attacker.hasTrait("kill_damaged_tank")
                    && "坦克".equals(target.unitType)) {
                log("  " + attacker.name() + " 重创 " + target.name() + "，将其消灭！");
                destroyUnit(target);
            }
        }
        emit("attack", "attacker", attacker.name(), "target", target.name());
        boolean shocked = attacker.has("冲击");
        if (shocked) {
            attacker.keywords.remove("冲击");
            log("  " + attacker.name() + " 的[冲击]已消耗。");
        }
        if (target.owner.board.contains(target) && target.defense > 0) {
            if (shocked) {
                log("  [冲击]生效：" + attacker.name() + " 不受反击！");
            } else {
                log("  " + target.name() + " 反击！" + attacker.name() + " 受到 "
                        + target.attack + " 点伤害。");
                damageUnit(attacker, target.attack, target, true);
            }
        }
        attacker.attacksMade++;
        postAction(attacker, spent, true);
    }

    public void doHqAttack(Unit attacker) {
        Player enemy = opponentOf(attacker.owner);
        if ("轰炸机".equals(attacker.unitType)) {
            Unit fi = interceptor(enemy);
            if (fi != null) {
                log("  ⚡ " + fi.name() + " 紧急升空拦截 " + attacker.name() + " 的空袭！");
                doAttack(attacker, fi);
                return;
            }
        }
        CardDef counter = checkCounter(enemy, "attack", attacker);
        if (counter != null) {
            log("  ⚡ " + enemy.name + " 的反制 [ " + counter.name
                    + " ] 触发！" + attacker.name() + " 被消灭！");
            emit("counter", "card", counter.name);
            destroyUnit(attacker);
            attacker.attacksMade++;
            return;
        }
        int spent = 0;
        if (attacker.operate > 0) {
            if (attacker.owner.kredits < attacker.operate) {
                log("  " + attacker.name() + " 需要 " + attacker.operate
                        + " 点行动费，指挥点不足，攻击取消！");
                return;
            }
            attacker.owner.kredits -= attacker.operate;
            spent = attacker.operate;
        }
        int dmg = hqDamage(attacker);
        if (attacker.hasTrait("katyusha")) {
            int extra = rng.nextInt(2);
            if (extra > 0) dmg += extra;
        }
        damageHq(enemy, dmg, attacker);
        attacker.attacksMade++;
        log("  " + attacker.name() + " 直击敌方总部，造成 " + dmg + " 点伤害！"
                + ("轰炸机".equals(attacker.unitType) ? "（轰炸机 +2）" : ""));
        postAction(attacker, spent, true);
        if (attacker.hasTrait("stuka_hq") && !enemy.hand.isEmpty()) {
            CardDef lost = enemy.hand.remove(rng.nextInt(enemy.hand.size()));
            enemy.discard.add(lost);
            log("  " + attacker.name() + " 迫使 " + enemy.name + " 弃掉了一张手牌！");
            emit("discard", "player", enemy.name, "card", lost.name);
            if (lost.traits.containsKey("recycle_discard")) {
                for (int i = 0; i < enemy.deck.size(); i++) {
                    if (enemy.deck.get(i).name.equals(lost.name)) {
                        enemy.hand.add(enemy.deck.remove(i));
                        log("  [M4A1] " + lost.name + " 从卡组中被抽了回来！");
                        break;
                    }
                }
            }
        }
    }

    public CardDef checkCounter(Player player, String event, Unit ctx) {
        for (CardDef c : new ArrayList<>(player.counters)) {
            if (c.matches(event, ctx)) {
                player.counters.remove(c);
                player.discard.add(c);
                for (Unit u : player.board) {
                    if (u.hasTrait("counter_grow")) {
                        u.attack += 2;
                        u.defense += 2;
                        u.maxDefense += 2;
                        log("  " + u.name() + " 因反制触发获得 +2/+2（"
                                + u.attack + "/" + u.defense + "）。");
                    }
                }
                return c;
            }
        }
        return null;
    }

    // ---------------- 出牌 ----------------
    public boolean playCard(Player p, int idx) {
        if (idx < 0 || idx >= p.hand.size()) {
            log("  手牌编号无效！");
            return false;
        }
        CardDef card = p.hand.get(idx);
        int cost = getCost(card, p);
        if (cost > p.kredits) {
            log("  指挥点不足！");
            return false;
        }
        p.kredits -= cost;
        p.hand.remove(idx);
        if (card.isUnit()) {
            if (p.board.size() >= rules().boardSize) {
                log("  场上已满，无法部署！");
                p.hand.add(idx, card);
                p.kredits += cost;
                return false;
            }
            Unit unit = deployUnit(p, card);
            log("  " + p.name + " 部署了 " + unit);
            Effects.onDeploy(this, unit);
            // [协力]：回合开始时场上没有同国家友方单位 → 总部士气伤害
            // （判定用回合开始快照，与牌库抽空共用 p.morale 计数）
            if (unit.has("协力") && p.board.contains(unit)) {
                if (!p.turnStartNations.contains(card.nation)) {
                    p.morale += 1;
                    log("  [协力] " + p.name + " 回合开始时场上没有 " + card.nation + " 友军，"
                            + "总部受到 " + p.morale + " 点士气伤害！");
                    damageHq(p, p.morale, null);
                }
            }
            for (Unit x : p.board) {
                if (x.hasTrait("katzmann") && x.defense > 0) {
                    x.operate += 1;
                    x.katzAdded += 1;
                    log("  " + x.name() + " 的行动费 +1（本回合，⚡" + x.operate + "）。");
                }
            }
        } else if (card.isCounter()) {
            if (p.counters.size() >= rules().counterSlots) {
                log("  反制区已满（最多 " + rules().counterSlots + " 张）！");
                p.hand.add(idx, card);
                p.kredits += cost;
                return false;
            }
            p.counters.add(card);
            log("  " + p.name + " 暗中布置了一张反制卡……");
            emit("counter_set", "player", p.name);
        } else {
            CardDef counter = checkCounter(opponentOf(p), "order", null);
            if (counter != null) {
                log("  ⚡ " + p.name + " 打出指令 [ " + card.name + " ]——"
                        + "敌方反制 [ " + counter.name + " ] 触发，指令被无效化！");
                emit("counter", "card", counter.name);
                p.discard.add(card);
                return true;
            }
            log("  " + p.name + " 打出指令牌 [ " + card.name + " ]");
            emit("order", "card", card.name, "player", p.name);
            p.ordersPlayed++;
            for (Player pl : players) {
                for (Unit u : pl.board) {
                    if (u.hasTrait("order_pain")) {
                        log("  " + u.name() + " 的联动：" + p.name + " 的总部受到 1 点伤害！");
                        damageHq(p, 1, u);
                    }
                }
            }
            Effects.run(this, p, card);
            p.discard.add(card);
            for (Unit u : new ArrayList<>(p.board)) {
                if (u.hasTrait("order_draw_once") && u.defense > 0
                        && once(p, "mtn_camp_" + System.identityHashCode(u))) {
                    drawCards(p, 1);
                    log("  " + u.name() + "：友方使用指令，抽一张牌。");
                }
            }
        }
        return true;
    }

    // ---------------- 回合流程 ----------------
    public void startTurn() {
        if (over || current.hq <= 0) return;
        turnNum++;
        forceEnd = false;
        Player p = current;
        // [协力]：回合开始时场上友方单位的国家快照（本回合阵亡/新部署均不影响判定）
        p.turnStartNations.clear();
        for (Unit u0 : p.board) {
            if (u0.defense > 0) p.turnStartNations.add(u0.card.nation);
        }
        if (p.cpSlots < rules().cpSlotGrowthCap) p.cpSlots++;
        p.cpSlots = Math.min(p.cpSlots, rules().cpSlotMax);
        p.kredits = p.cpSlots;
        log("\n===== 第 " + turnNum + " 回合 | " + p.name + " (" + p.nation + ") =====");
        log("  指挥点: " + p.kredits + "/" + p.cpSlots + "（槽） | HQ: " + p.hq
                + " | 手牌 " + p.hand.size() + " 张");
        if ("regen".equals(p.hqCard.perk) && p.hq < p.hqCard.hp) {
            p.hq += 1;
            emit("hq_heal", "player", p.name, "amount", 1);
            log("  [研发] 纵深防御：总部恢复 1 点生命（" + p.hq + " HP）。");
        }
        drawCards(p, 1);
        p.ordersPlayed = 0;
        for (Unit u : p.board) {
            u.canAttack = true;
            u.attacksMade = 0;
            u.moved = false;
            u.freshDeploy = false;
            if (u.hasTrait("turn_kredits") && u.defense > 0) {
                p.kredits += 1;
                log("  " + u.name() + "：回合开始，获得 1 指挥点（共 " + p.kredits + "）。");
            }
            if (u.hasTrait("tank_line_grow") && u.defense > 0) {
                int n = 0;
                for (Unit x : p.board) {
                    if (x != u && "坦克".equals(x.unitType)
                            && x.position.equals(u.position) && x.defense > 0) n++;
                }
                if (n > 0) {
                    u.attack += n;
                    log("  " + u.name() + " 因同阵线 " + n + " 个坦克，攻击 +" + n
                            + "（" + u.attack + "）。");
                }
            }
            if ("turn_start_front".equals(u.strTrait("vet_when"))
                    && "前线".equals(u.position)) {
                vetUpgrade(u);
            }
            if (u.has("动员")) {
                u.attack += 1;
                u.defense += 1;
                u.maxDefense += 1;
                u.mob += 1;
                log("  [动员] " + u.name() + " 获得 +1/+1（" + u.attack + "/" + u.defense + "）。");
            }
        }
    }

    public void endTurn() {
        for (Unit u : current.board) {
            if (u.hasTrait("end_draw") && u.defense > 0) {
                boolean front = false;
                for (Unit x : current.board) {
                    if ("前线".equals(x.position) && x.defense > 0) { front = true; break; }
                }
                if (front) {
                    drawCards(current, 1);
                    log("  " + u.name() + "：回合结束，前线有友军，抽一张牌。");
                    break;
                }
            }
        }
        cleanupOwnTurn();
        if (players[0].hq <= 0 || players[1].hq <= 0) {
            over = true;
            return;
        }
        forceEnd = false;
        current = opponentOf(current);
    }

    private void cleanupOwnTurn() {
        for (Player.Buff b : current.tempBuffs) {
            if (current.board.contains(b.unit)) {
                b.unit.attack -= b.amount;
                log("  " + b.unit.name() + " 的本回合攻击加成消失（" + b.unit.attack + "）。");
            }
        }
        current.tempBuffs.clear();
        for (Unit u : current.board) {
            u.overflowTurn = false;
            if (u.katzAdded > 0) {
                u.operate = Math.max(0, u.operate - u.katzAdded);
                u.katzAdded = 0;
            }
        }
        opponentOf(current).atsMark = 0;
    }

    // ---------------- AI ----------------
    public int incomingDamage(Player foe) {
        int total = 0;
        for (Unit u : foe.board) {
            if (u.defense <= 0) continue;
            if (canHitHq(u)) {
                total += hqDamage(u) * Math.max(1, u.maxAttacks());
            }
        }
        return total;
    }

    public double aiPower(Player p) {
        double score = p.hq;
        for (Unit u : p.board) {
            score += u.attack + u.defense * 1.15;
            for (String k : u.keywords) {
                if ("警卫".equals(k) || "伏击".equals(k) || "亡计".equals(k)) score += 0.4;
            }
        }
        score += 2.0 * p.hand.size();
        score += p.deck.size() / 5.0;
        score += 1.5 * p.counters.size();
        return score;
    }

    public boolean aiShouldConcede(Player p) {
        Player foe = opponentOf(p);
        int incoming = incomingDamage(foe);
        double my = aiPower(p), his = aiPower(foe);
        for (Unit u : p.board) {
            if (unitReady(u) && !attackTargets(u).isEmpty()) return false;
        }
        if (p.hq <= 4 && incoming >= p.hq) {
            if (!playableCards(p).isEmpty() && p.hq > 2) return false;
            return true;
        }
        if (p.hq > 8) return false;
        if (!p.hand.isEmpty() && !playableCards(p).isEmpty()) return false;
        if (p.deck.size() > 3) return false;
        if (!p.hand.isEmpty()) return false;
        return his >= my * 3.0;
    }

    /** 一次性执行整个 AI 回合（CLI/演示用）。 */
    public void aiTurn() {
        Player p = current;
        if (over) return;
        if (aiShouldConcede(p)) {
            over = true;
            conceded = p;
            log("  [AI] " + p.name + " 判定无胜算，投降。");
            return;
        }
        boolean acted = true;
        java.util.Set<CardDef> skippedViolation =
                java.util.Collections.newSetFromMap(new java.util.IdentityHashMap<>());
        while (acted && !forceEnd) {
            acted = false;
            List<Integer> playable = playableCards(p);
            playable.sort((a, b) -> Integer.compare(
                    getCost(p.hand.get(b), p), getCost(p.hand.get(a), p)));
            // [协力]：回合开始没有同国友军时，有安全牌先出安全牌并记住放弃的
            // 协力卡；只有手里再无可出的安全牌、且本回合还没放弃过违约时，
            // 才肯吃一次士气伤害（避免白忍一场，也避免把卡攥死造成停滞）。
            List<Integer> viol = new ArrayList<>(), safe = new ArrayList<>();
            for (int idx : playable) {
                CardDef c = p.hand.get(idx);
                if (c.keywords.contains("协力") && !p.turnStartNations.contains(c.nation)) {
                    viol.add(idx);
                } else {
                    safe.add(idx);
                }
            }
            List<Integer> pool;
            if (!safe.isEmpty()) {
                pool = safe;
                for (int idx : viol) skippedViolation.add(p.hand.get(idx));
            } else if (skippedViolation.isEmpty()) {
                pool = playable;
            } else {
                pool = new ArrayList<>();
            }
            for (int idx : pool) {
                CardDef card = p.hand.get(idx);
                if (playCard(p, idx)) {
                    acted = true;
                    break;
                }
            }
            for (Player pl : players) {
                for (Unit u : new ArrayList<>(pl.board)) {
                    if (u.defense <= 0) destroyUnit(u);
                }
            }
        }
        if (forceEnd) return;
        for (Unit u : new ArrayList<>(p.board)) {
            if ("后方".equals(u.position) && !u.moved && !u.freshDeploy
                    && canTakeFrontline(p) && "坦克".equals(u.unitType)) {
                moveUnit(u, "前线");
            }
        }
        for (Unit u : new ArrayList<>(p.board)) {
            while (p.board.contains(u) && unitReady(u) && u.defense > 0) {
                List<Unit> targets = attackTargets(u);
                if (targets.isEmpty()) break;
                Player foe = opponentOf(p);
                if (canHitHq(u) && foe.hq <= hqDamage(u)) {
                    doHqAttack(u);
                    continue;
                }
                List<Unit> killable = new ArrayList<>();
                for (Unit t : targets) {
                    if (u.attack - t.armor() >= t.defense) killable.add(t);
                }
                Unit target;
                if (!killable.isEmpty() && rng.nextInt(10) < 7) {
                    target = killable.get(rng.nextInt(killable.size()));
                } else if (canHitHq(u) && rng.nextInt(10) < 5) {
                    doHqAttack(u);
                    continue;
                } else {
                    target = targets.get(0);
                    for (Unit t : targets) if (t.defense < target.defense) target = t;
                }
                doAttack(u, target);
            }
            for (Player pl : players) {
                for (Unit dead : new ArrayList<>(pl.board)) {
                    if (dead.defense <= 0) destroyUnit(dead);
                }
            }
        }
    }

    // ---------------- 对局主循环 ----------------
    public Player winnerOf() {
        Player p0 = players[0], p1 = players[1];
        if (p0.hq <= 0 && p1.hq <= 0) return null;
        if (conceded != null) return opponentOf(conceded);
        if (p0.hq <= 0) return p1;
        if (p1.hq <= 0) return p0;
        return null;
    }

    public void setup() {
        for (Player p : players) drawCards(p, rules().startHand);
        drawCards(players[1], 1);
    }

    public void runAiVsAi() {
        setup();
        while (!over) {
            startTurn();
            if (over || current.hq <= 0) break;
            aiTurn();
            if (conceded != null) break;
            endTurn();
        }
    }
}
