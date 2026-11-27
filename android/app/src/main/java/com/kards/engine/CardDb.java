package com.kards.engine;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 卡牌数据库：从 cards.json（classpath / 文件 / InputStream）加载。 */
public final class CardDb {
    /** 对局规则常量（来自 JSON meta.rules）。 */
    public static final class Rules {
        public final int deckSize, handLimit, startHand, boardSize, rearSlots,
                frontlineSlots, counterSlots, cpSlotGrowthCap, cpSlotMax,
                allyLimit, hqHp;
        public final List<String> mainNations, allyNations, rangedTypes;
        public final Map<String, Integer> rarityCopies;

        Rules(Map<String, Object> r) {
            deckSize = MiniJson.getInt(r, "deckSize");
            handLimit = MiniJson.getInt(r, "handLimit");
            startHand = MiniJson.getInt(r, "startHand");
            boardSize = MiniJson.getInt(r, "boardSize");
            rearSlots = MiniJson.getInt(r, "rearSlots");
            frontlineSlots = MiniJson.getInt(r, "frontlineSlots");
            counterSlots = MiniJson.getInt(r, "counterSlots");
            cpSlotGrowthCap = MiniJson.getInt(r, "cpSlotGrowthCap");
            cpSlotMax = MiniJson.getInt(r, "cpSlotMax");
            allyLimit = MiniJson.getInt(r, "allyLimit");
            hqHp = MiniJson.getInt(r, "hqHp");
            mainNations = strList(r.get("mainNations"));
            allyNations = strList(r.get("allyNations"));
            rangedTypes = strList(r.get("rangedTypes"));
            Map<String, Integer> rc = new LinkedHashMap<>();
            for (Map.Entry<String, Object> e : MiniJson.obj(r.get("rarityCopies")).entrySet()) {
                rc.put(e.getKey(), MiniJson.getInt(MiniJson.obj(r.get("rarityCopies")), e.getKey()));
            }
            rarityCopies = Collections.unmodifiableMap(rc);
        }

        private static List<String> strList(Object v) {
            List<String> l = new ArrayList<>();
            for (Object o : MiniJson.arr(v)) l.add(String.valueOf(o));
            return Collections.unmodifiableList(l);
        }

        public boolean isAlly(String nation) { return allyNations.contains(nation); }

        public int maxCopies(String rarity) {
            Integer n = rarityCopies.get(rarity);
            return n == null ? 4 : n;
        }
    }

    /** 总部定义。 */
    public static final class Hq {
        public final String nation, name, perk, perkDesc;
        public final int hp;

        Hq(Map<String, Object> m) {
            nation = MiniJson.str(m, "nation");
            name = MiniJson.str(m, "name");
            hp = MiniJson.getInt(m, "hp");
            perk = MiniJson.str(m, "perk");
            perkDesc = MiniJson.str(m, "perkDesc");
        }
    }

    public final Rules rules;
    private final Map<String, CardDef> byName;
    private final List<CardDef> all;
    private final Map<String, Hq> hqs;

    private CardDb(Map<String, Object> root) {
        rules = new Rules(MiniJson.obj(root.get("rules"))
                .isEmpty() ? metaRules(root) : MiniJson.obj(root.get("rules")));
        byName = new LinkedHashMap<>();
        List<CardDef> list = new ArrayList<>();
        for (Object o : MiniJson.arr(root.get("cards"))) {
            CardDef c = new CardDef(MiniJson.obj(o));
            byName.put(c.name, c);
            list.add(c);
        }
        all = Collections.unmodifiableList(list);
        Map<String, Hq> h = new LinkedHashMap<>();
        for (Object o : MiniJson.arr(root.get("hqs"))) {
            Hq q = new Hq(MiniJson.obj(o));
            h.put(q.nation, q);
        }
        hqs = Collections.unmodifiableMap(h);
    }

    private static Map<String, Object> metaRules(Map<String, Object> root) {
        return MiniJson.obj(MiniJson.obj(root.get("meta")).get("rules"));
    }

    public static CardDb fromStream(InputStream in) throws IOException {
        StringBuilder sb = new StringBuilder();
        try (BufferedReader r = new BufferedReader(
                new InputStreamReader(in, StandardCharsets.UTF_8))) {
            String line;
            while ((line = r.readLine()) != null) sb.append(line).append('\n');
        }
        return new CardDb(MiniJson.obj(MiniJson.parse(sb.toString())));
    }

    public static CardDb fromFile(String path) throws IOException {
        try (InputStream in = new java.io.FileInputStream(path)) {
            return fromStream(in);
        }
    }

    /** 从 classpath 资源加载（Android assets / CLI resources）。 */
    public static CardDb fromResource(String res) throws IOException {
        try (InputStream in = CardDb.class.getResourceAsStream(res)) {
            if (in == null) throw new IOException("资源不存在: " + res);
            return fromStream(in);
        }
    }

    public CardDef get(String name) { return byName.get(name); }
    public List<CardDef> cards() { return all; }
    public Hq hq(String nation) {
        Hq q = hqs.get(nation);
        if (q == null) throw new IllegalArgumentException("未知国家: " + nation);
        return q;
    }

    /** 组卡可用卡牌：主国本国卡 + 全部盟国卡（对齐 allowed_cards，按费用+名字排序）。 */
    public List<CardDef> allowedCards(String nation) {
        List<CardDef> pool = new ArrayList<>();
        for (CardDef c : all) {
            if (c.nation.equals(nation) || rules.isAlly(c.nation)) pool.add(c);
        }
        pool.sort((a, b) -> {
            int d = Integer.compare(a.cost, b.cost);
            return d != 0 ? d : a.name.compareTo(b.name);
        });
        return pool;
    }

    /** 校验卡组（对齐 validate_deck）。合法返回 null，否则返回错误信息。 */
    public String validateDeck(List<CardDef> deck, String nation) {
        if (deck.size() != rules.deckSize) {
            return "卡组必须恰好 " + rules.deckSize + " 张（当前 " + deck.size() + " 张）";
        }
        Map<String, Integer> counts = new LinkedHashMap<>();
        int allyN = 0;
        for (CardDef c : deck) counts.merge(c.name, 1, Integer::sum);
        for (Map.Entry<String, Integer> e : counts.entrySet()) {
            CardDef c = byName.get(e.getKey());
            if (c == null) return "未知卡牌: " + e.getKey();
            int cap = rules.maxCopies(c.rarity);
            if (e.getValue() > cap) {
                return "[" + c.name + "] 是" + c.rarity + "卡，最多 " + cap
                        + " 张（当前 " + e.getValue() + " 张）";
            }
            if (!c.nation.equals(nation) && !rules.isAlly(c.nation)) {
                return "[" + c.name + "] 不属于 " + nation + " 或盟国阵营";
            }
            if (rules.isAlly(c.nation)) allyN += e.getValue();
        }
        if (allyN > rules.allyLimit) {
            return "盟国卡超过 " + rules.allyLimit + " 张上限（当前 " + allyN + " 张）";
        }
        return null;
    }

    /** 随机推荐卡组（对齐 build_deck：低费加权 + 稀有度上限 + 盟国上限）。 */
    public List<CardDef> buildDeck(String nation, java.util.Random rng) {
        int[] costWeight = {0, 3, 3, 3, 2, 2, 1, 1};
        List<CardDef> pool = allowedCards(nation);
        Map<String, Integer> counts = new LinkedHashMap<>();
        int allyN = 0;
        List<CardDef> deck = new ArrayList<>();
        int guard = 0;
        while (deck.size() < rules.deckSize && guard++ < 200000) {
            int totalW = 0;
            for (CardDef c : pool) {
                int w = c.cost < costWeight.length ? costWeight[c.cost] : 1;
                totalW += w;
            }
            int roll = rng.nextInt(totalW);
            CardDef pick = pool.get(pool.size() - 1);
            for (CardDef c : pool) {
                int w = c.cost < costWeight.length ? costWeight[c.cost] : 1;
                roll -= w;
                if (roll < 0) { pick = c; break; }
            }
            Integer have = counts.get(pick.name);
            if (have != null && have >= rules.maxCopies(pick.rarity)) continue;
            if (rules.isAlly(pick.nation) && allyN >= rules.allyLimit) continue;
            counts.merge(pick.name, 1, Integer::sum);
            if (rules.isAlly(pick.nation)) allyN++;
            deck.add(pick);
        }
        Collections.shuffle(deck, rng);
        return deck;
    }
}
