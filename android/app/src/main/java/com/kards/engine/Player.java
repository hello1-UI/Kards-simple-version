package com.kards.engine;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** 玩家（对齐 kards_engine.Player）。 */
public final class Player {
    public final String name;
    public final String nation;
    public final CardDb.Hq hqCard;
    public final List<CardDef> deck;
    public final List<CardDef> hand = new ArrayList<>();
    public final List<Unit> board = new ArrayList<>();
    public final List<CardDef> discard = new ArrayList<>();
    public final List<CardDef> counters = new ArrayList<>();   // 暗置反制
    public int hq;
    public int cpSlots;          // 指挥点槽：开局 0，我方回合开始 +1（≤12），绝对上限 24
    public int kredits;          // 当前可用指挥点，回合开始回满到槽数
    public int morale;          // 士气伤害计数（旧"疲劳"，1起递增；牌库抽空与[协力]共用）
    /** [协力]回合开始时场上友方单位的国家快照（对齐 kards_engine.Player.turn_start_nations）。 */
    public final Set<String> turnStartNations = new HashSet<>();
    /** 本回合临时攻击增益（闪电战/呜啦/前线 buff）。 */
    public final List<Buff> tempBuffs = new ArrayList<>();
    public int ordersPlayed;    // 本回合已用指令数（廓尔喀联动）
    public int atsMark;         // 本土防卫军标记（1/2，0=无）
    public final Map<String, Integer> onceTurn = new LinkedHashMap<>();

    public static final class Buff {
        public final Unit unit;
        public final int amount;
        Buff(Unit u, int a) { unit = u; amount = a; }
    }

    public Player(String name, String nation, CardDb db, List<CardDef> deck) {
        this.name = name;
        this.nation = nation;
        this.hqCard = db.hq(nation);
        this.deck = new ArrayList<>(deck);
        this.hq = this.hqCard.hp;
    }

    public List<Unit> aliveUnits() {
        List<Unit> out = new ArrayList<>();
        for (Unit u : board) if (u.defense > 0) out.add(u);
        return out;
    }

    @Override public String toString() { return name; }
}
