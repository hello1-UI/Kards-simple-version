package com.kards.engine;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 卡牌定义（不可变）。kind: unit / order / counter。 */
public final class CardDef {
    public final String kind;
    public final String name;
    public final String nation;
    public final int cost;
    public final String rarity;
    // unit 专属
    public final int attack;
    public final int defense;
    public final List<String> keywords;
    public final String unitType;
    public final int operate;
    public final Map<String, Object> traits;
    // order / counter 专属
    public final String desc;
    public final String effectId;              // null = 无
    public final Map<String, Object> effectParams;
    public final String trigger;               // counter 触发条件

    public CardDef(Map<String, Object> m) {
        this.kind = MiniJson.str(m, "kind");
        this.name = MiniJson.str(m, "name");
        this.nation = MiniJson.str(m, "nation");
        this.cost = MiniJson.getInt(m, "cost");
        this.rarity = MiniJson.str(m, "rarity");
        this.desc = MiniJson.str(m, "desc");
        this.attack = MiniJson.getInt(m, "attack");
        this.defense = MiniJson.getInt(m, "defense");
        List<String> kws = new ArrayList<>();
        for (Object k : MiniJson.arr(m.get("keywords"))) kws.add(String.valueOf(k));
        this.keywords = Collections.unmodifiableList(kws);
        this.unitType = MiniJson.str(m, "unitType");
        this.operate = MiniJson.getInt(m, "operate");
        Map<String, Object> t = new LinkedHashMap<>();
        Object raw = m.get("traits");
        if (raw instanceof Map) {
            for (Map.Entry<String, Object> e : ((Map<String, Object>) raw).entrySet()) {
                t.put(e.getKey(), e.getValue());
            }
        }
        this.traits = Collections.unmodifiableMap(t);
        Object eff = m.get("effect");
        if (eff instanceof Map) {
            Map<String, Object> em = (Map<String, Object>) eff;
            this.effectId = MiniJson.str(em, "id");
            Map<String, Object> ep = new LinkedHashMap<>();
            for (Map.Entry<String, Object> e : MiniJson.obj(em.get("params")).entrySet()) {
                ep.put(e.getKey(), e.getValue());
            }
            this.effectParams = Collections.unmodifiableMap(ep);
        } else {
            this.effectId = null;
            this.effectParams = Collections.emptyMap();
        }
        this.trigger = MiniJson.str(m, "trigger");
    }

    public boolean isUnit() { return "unit".equals(kind); }
    public boolean isOrder() { return "order".equals(kind); }
    public boolean isCounter() { return "counter".equals(kind); }

    /** 反制触发条件匹配（对齐 CounterCard.matches）。 */
    public boolean matches(String event, Unit ctx) {
        if ("attack_tank".equals(trigger))
            return "attack".equals(event) && "坦克".equals(ctx.unitType);
        if ("attack_air".equals(trigger))
            return "attack".equals(event)
                    && ("战斗机".equals(ctx.unitType) || "轰炸机".equals(ctx.unitType));
        if ("attack_inf".equals(trigger))
            return "attack".equals(event) && "步兵".equals(ctx.unitType);
        if ("attack_any".equals(trigger)) return "attack".equals(event);
        if ("order".equals(trigger)) return "order".equals(event);
        if ("hq_damage".equals(trigger)) return "hq_damage".equals(event);
        return false;
    }

    /** 深拷贝（部署费用为 0 等运行时改 traits 用）。 */
    public CardDef copy() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("kind", kind); m.put("name", name); m.put("nation", nation);
        m.put("cost", (double) cost); m.put("rarity", rarity);
        m.put("attack", (double) attack); m.put("defense", (double) defense);
        List<Object> kws = new ArrayList<>(); kws.addAll(keywords);
        m.put("keywords", kws);
        m.put("unitType", unitType); m.put("operate", (double) operate);
        m.put("traits", new LinkedHashMap<>(traits));
        m.put("desc", desc); m.put("trigger", trigger);
        if (effectId != null) {
            Map<String, Object> em = new LinkedHashMap<>();
            em.put("id", effectId);
            em.put("params", new LinkedHashMap<>(effectParams));
            m.put("effect", em);
        }
        return new CardDef(m);
    }

    /** 生成衍生的 1/1 副本（收缴用）：费用 min(cost,3)。 */
    public CardDef confiscateCopy() {
        CardDef c = copy();
        Map<String, Object> m = new LinkedHashMap<>(c.traits);
        return new CardDef(c.toMutableMap(m, Math.min(cost, 3), 1, 1));
    }

    private Map<String, Object> toMutableMap(Map<String, Object> traits,
                                             int cost, int atk, int def) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("kind", kind); m.put("name", name); m.put("nation", nation);
        m.put("cost", (double) cost); m.put("rarity", rarity);
        m.put("attack", (double) atk); m.put("defense", (double) def);
        m.put("keywords", new ArrayList<Object>(keywords));
        m.put("unitType", unitType); m.put("operate", 0.0);
        m.put("traits", traits);
        m.put("desc", ""); m.put("trigger", trigger);
        return m;
    }
}
