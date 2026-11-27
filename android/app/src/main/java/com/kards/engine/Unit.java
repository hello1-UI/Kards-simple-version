package com.kards.engine;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 场上的单位实例（对齐 kards_engine.Unit）。 */
public final class Unit {
    public final CardDef card;
    public final Player owner;
    public int attack;
    public int defense;
    public int maxDefense;
    public final List<String> keywords;
    public final String unitType;
    public String position = "后方";      // "后方" 或 "前线"
    public Integer slot;                  // 0..8，null=未上场
    public boolean moved;
    public boolean canAttack;             // 无闪击则下回合才能攻击
    public int attacksMade;
    public int mob;                       // [动员]已累积加成（记账，受伤后清零）
    public boolean freshDeploy;           // 本回合刚部署（无[闪击]不能动）
    public int operate;                   // 行动费：每次攻击/移动消耗
    public int dyingHq;                   // [亡计]对敌方总部伤害
    public boolean overflowTurn;          // 本回合溢出伤害转移敌方总部
    public boolean veteran;               // [老兵]已升级
    public boolean frontAtkActive;        // 第39：前线 +2 攻击临时加成在位
    public int katzAdded;                 // 卡茨曼团：本回合因出牌累计的行动费

    public Unit(CardDef card, Player owner) {
        this.card = card;
        this.owner = owner;
        this.attack = card.attack;
        this.defense = card.defense;
        this.maxDefense = card.defense;
        this.keywords = new ArrayList<>(card.keywords);
        this.unitType = card.unitType;
        this.canAttack = keywords.contains("闪击");
        this.traitsCopy(card);
        this.operate = card.operate;
        this.dyingHq = intTrait("dying_hq");
    }

    private Map<String, Object> tr = new LinkedHashMap<>();

    private void traitsCopy(CardDef card) {
        tr = new LinkedHashMap<>(card.traits);
    }

    /** 运行时 traits（如 deathwatch_owner 由部署效果写入）。 */
    public Map<String, Object> traits() { return tr; }

    public Object trait(String key) { return tr.get(key); }

    public boolean hasTrait(String key) {
        Object v = tr.get(key);
        if (v instanceof Boolean) return (Boolean) v;
        return v != null;
    }

    public int intTrait(String key) {
        Object v = tr.get(key);
        if (v instanceof Double) return (int) Math.round((Double) v);
        if (v instanceof Number) return ((Number) v).intValue();
        return 0;
    }

    public String strTrait(String key) {
        Object v = tr.get(key);
        return v == null ? null : String.valueOf(v);
    }

    @SuppressWarnings("unchecked")
    public List<String> listTrait(String key) {
        Object v = tr.get(key);
        List<String> out = new ArrayList<>();
        if (v instanceof List) {
            for (Object o : (List<Object>) v) out.add(String.valueOf(o));
        }
        return out;
    }

    public String name() { return card.name; }

    public boolean has(String kw) { return keywords.contains(kw); }

    public int armor() {
        if (has("装甲3")) return 3;
        if (has("装甲2")) return 2;
        if (has("装甲")) return 1;
        return 0;
    }

    public int maxAttacks() { return has("奋战") ? 2 : 1; }

    @Override public String toString() {
        return String.format("%s（%d/%d%s%s）", card.name, attack, defense,
                position.equals("前线") ? "·前线" : "",
                operate > 0 ? "·⚡" + operate : "");
    }
}
