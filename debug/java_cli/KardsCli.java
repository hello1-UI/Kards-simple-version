import com.kards.engine.CardDb;
import com.kards.engine.CardDef;
import com.kards.engine.Effects;
import com.kards.engine.Game;
import com.kards.engine.Player;
import com.kards.engine.Unit;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

/** Java 引擎自测：--test 规则回归 / --battle [N] AI 对战。
 *  用法（仓库根目录）:
 *    javac -d debug/java_cli/build \
 *      android/app/src/main/java/com/kards/engine/*.java debug/java_cli/KardsCli.java
 *    java -cp debug/java_cli/build KardsCli --test
 *    java -cp debug/java_cli/build KardsCli --battle 5
 */
public final class KardsCli {
    private static int passed = 0, failed = 0;
    private static boolean quiet = true;
    private static CardDb db;

    public static void main(String[] args) throws Exception {
        String cardsPath = "android/app/src/main/assets/cards.json";
        db = CardDb.fromFile(cardsPath);
        boolean quiet = true;
        if (args.length > 0 && args[0].equals("--battle")) {
            int n = args.length > 1 ? Integer.parseInt(args[1]) : 3;
            battle(n);
            return;
        }
        tests(quiet);
        System.out.println();
        System.out.println("== Java 引擎规则回归: " + passed + " 通过 / " + failed + " 失败 ==");
        if (failed > 0) System.exit(1);
    }

    // ---------------- 检查工具 ----------------
    private static void check(boolean ok, String label, Object detail) {
        if (ok) {
            passed++;
            System.out.println("  PASS " + label);
        } else {
            failed++;
            System.out.println("  FAIL " + label + "  ← " + detail);
        }
    }

    private static Game newGame(String a, String b, long seed) {
        List<CardDef> da = db.buildDeck(a, new java.util.Random(seed));
        List<CardDef> dbd = db.buildDeck(b, new java.util.Random(seed + 1));
        Player pa = new Player("甲", a, db, da);
        Player pb = new Player("乙", b, db, dbd);
        Game g = new Game(pa, pb, db, seed);
        if (quiet) g.setLogSink(s -> { });
        return g;
    }

    /** 部署指定卡到某方场上（绕过费用）。 */
    private static Unit deploy(Game g, Player p, String cardName) {
        CardDef c = db.get(cardName);
        if (c == null) throw new IllegalArgumentException("无此卡: " + cardName);
        Unit u = g.deployUnit(p, c);
        Effects.onDeploy(g, u);
        return u;
    }

    /** 原始部署（不结算部署效果，纯规则测试用）。 */
    private static Unit deployRaw(Game g, Player p, String cardName) {
        CardDef c = db.get(cardName);
        if (c == null) throw new IllegalArgumentException("无此卡: " + cardName);
        return g.deployUnit(p, c);
    }

    private static List<Unit> only(List<Unit> list) { return list; }

    // ---------------- 规则测试 ----------------
    private static void tests(boolean q) {
        quiet = q;
        System.out.println("== 1. 指挥点槽 ==");
        Game g = newGame("德国", "苏联", 1);
        Player me = g.players[0];
        g.setup();
        check(me.cpSlots == 0, "开局槽为 0", me.cpSlots);
        g.startTurn();
        check(me.cpSlots == 1 && me.kredits == 1, "回合开始槽 +1、指挥点=槽",
                me.cpSlots + "/" + me.kredits);
        me.cpSlots = 12;
        g.startTurn();
        check(me.cpSlots == 12 && me.kredits == 12, "成长上限 12", me.cpSlots);

        System.out.println("== 2. 动员 ==");
        g = newGame("苏联", "德国", 2);
        me = g.players[0];
        g.setup();
        Unit col = deployRaw(g, me, "殖民步兵");       // 1/1 闪击 动员
        g.startTurn();
        check(col.attack == 2 && col.defense == 2 && col.mob == 1,
                "回合开始 +1/+1", col.attack + "/" + col.defense);
        g.damageUnit(col, 1, null, false);
        check(col.attack == 2 && col.defense == 1 && !col.has("动员"),
                "受伤失去关键词、加成保留", col.attack + "/" + col.defense + " kw=" + col.has("动员"));
        g.startTurn();
        check(col.attack == 2 && col.defense == 1, "失去后不再成长",
                col.attack + "/" + col.defense);

        System.out.println("== 3. 装甲与动员保留 ==");
        g = newGame("苏联", "德国", 3);
        me = g.players[0];
        g.setup();
        Unit mob = deployRaw(g, me, "殖民步兵");
        mob.keywords.add("装甲");
        g.startTurn();
        g.damageUnit(mob, 1, null, true);
        check(mob.has("动员") && mob.defense == 2 && mob.defense > 0,
                "装甲完全抵消：动员保留", mob.defense + " kw=" + mob.has("动员"));

        System.out.println("== 4. 反击规则 ==");
        g = newGame("德国", "苏联", 4);
        Player meP = g.players[0], foe = g.players[1];
        g.setup();
        Unit att = deploy(g, meP, "殖民步兵");         // 1/1 闪击
        Unit tgt = deploy(g, foe, "游骑兵");           // 4/6 步兵
        int preDef = att.defense;
        g.doAttack(att, tgt);
        check(att.defense == preDef - tgt.attack && tgt.defense > 0,
                "无冲击攻击后吃反击", att.defense + " vs " + tgt.attack);
        Unit shock = deploy(g, meP, "波波沙冲锋队");   // 3/1 冲击
        int preDef2 = shock.defense;
        g.doAttack(shock, tgt);
        check(shock.defense == preDef2 && !shock.has("冲击"),
                "冲击免反击且消耗", shock.defense + " kw=" + shock.has("冲击"));

        System.out.println("== 5. 攻击射程 ==");
        g = newGame("德国", "苏联", 5);
        meP = g.players[0];
        foe = g.players[1];
        g.setup();
        Unit inf = deploy(g, meP, "殖民步兵");         // 支援线步兵
        Unit fighter = deploy(g, meP, "Bf-109战斗机"); // 支援线战斗机（远程）
        Unit enemyRear = deploy(g, foe, "游骑兵");     // 敌方支援线
        check(!g.attackTargets(inf).contains(enemyRear) || !enemyRear.owner.board.contains(enemyRear),
                "支援线步兵打不到敌方支援线", g.attackTargets(inf).size());
        check(g.attackTargets(fighter).contains(enemyRear),
                "战斗机可打任意阵线", g.attackTargets(fighter).size());

        System.out.println("== 6. 前线占领 ==");
        g = newGame("德国", "苏联", 6);
        meP = g.players[0];
        foe = g.players[1];
        g.setup();
        Unit f1 = deploy(g, foe, "游骑兵");
        g.keywordMove(f1, "前线", "");
        check(g.frontlineOwner() == foe, "敌方占领前线", g.frontlineOwner());
        check(!g.canTakeFrontline(meP), "敌方占线时我不能上前线", false);
        Unit myInf = deploy(g, meP, "殖民步兵");
        check(g.attackTargets(myInf).contains(f1), "支援线可打敌方前线单位",
                g.attackTargets(myInf).size());
        g.destroyUnit(f1);
        check(g.canTakeFrontline(meP), "清空后可上前线", true);

        System.out.println("== 7. 警卫 ==");
        g = newGame("英国", "德国", 7);
        meP = g.players[0];
        foe = g.players[1];
        g.setup();
        Unit guard = deployRaw(g, foe, "丘吉尔坦克");  // 警卫+装甲
        Unit plain = deployRaw(g, foe, "游骑兵");
        g.keywordMove(guard, "前线", "");
        g.keywordMove(plain, "前线", "");
        boolean adjacent = guard.slot != null && plain.slot != null
                && Math.abs(guard.slot - plain.slot) == 1;
        Unit myAttacker = deployRaw(g, meP, "殖民步兵");
        List<Unit> targets = g.attackTargets(myAttacker);
        if (adjacent) {
            check(targets.contains(guard) && !targets.contains(plain),
                    "警卫保护相邻单位", targets);
        } else {
            check(!targets.isEmpty(), "警卫不相邻时不保护", targets.size());
        }

        System.out.println("== 8. 总部攻击 ==");
        g = newGame("德国", "苏联", 8);
        meP = g.players[0];
        foe = g.players[1];
        g.setup();
        Unit tank = deploy(g, meP, "四号坦克");        // 5/5
        g.keywordMove(tank, "前线", "");
        int hq0 = foe.hq;
        g.doHqAttack(tank);
        check(foe.hq == hq0 - 5, "前线坦克直击总部", hq0 + "->" + foe.hq);
        Unit bmb = deploy(g, meP, "斯图卡俯冲轰炸机");
        check(g.hqDamage(bmb) == bmb.attack + 2, "轰炸机打总部 +2", g.hqDamage(bmb));

        System.out.println("== 9. 反制 ==");
        g = newGame("德国", "美国", 9);
        meP = g.players[0];
        foe = g.players[1];
        g.setup();
        Unit atkTank = deploy(g, meP, "四号坦克");
        g.keywordMove(atkTank, "前线", "");
        CardDef at = db.get("反坦克炮");
        foe.counters.add(at);
        int boardBefore = meP.board.size();
        g.doAttack(atkTank, deploy(g, foe, "游骑兵"));
        check(meP.board.size() == boardBefore - 1,
                "反坦克炮反制消灭攻击坦克", meP.board.size());

        System.out.println("== 10. 出牌与费用 ==");
        g = newGame("德国", "苏联", 10);
        meP = g.players[0];
        g.setup();
        g.startTurn();
        meP.hand.add(db.get("虎式坦克"));              // 8 费
        int idx = meP.hand.size() - 1;
        meP.kredits = 100;
        boolean played = g.playCard(meP, idx);
        check(played && meP.kredits == 100 - 7,
                "德国研发：坦克费用 -1", meP.kredits);

        System.out.println("== 11. 奋战 ==");
        g = newGame("日本", "德国", 11);
        meP = g.players[0];
        foe = g.players[1];
        g.setup();
        Unit naruto = deploy(g, meP, "步兵联队");      // 奋战
        Unit t1 = deploy(g, foe, "游骑兵");
        Unit t2 = deploy(g, foe, "游骑兵");
        g.startTurn();
        check(g.unitReady(naruto) && naruto.maxAttacks() == 2, "奋战两次", naruto.maxAttacks());

        System.out.println("== 12. 胜负判定 ==");
        g = newGame("德国", "苏联", 12);
        g.setup();
        g.damageHq(g.players[1], 999, null);
        check(g.over && g.winnerOf() == g.players[0], "总部倒下判负", g.winnerOf());
        g = newGame("德国", "苏联", 13);
        g.setup();
        g.damageHq(g.players[0], 999, null);
        g.damageHq(g.players[1], 999, null);
        check(g.winnerOf() == null, "双死平局", g.winnerOf());

        System.out.println("== 13. 卡组校验 ==");
        List<CardDef> deck = db.buildDeck("德国", new java.util.Random(99));
        check(db.validateDeck(deck, "德国") == null, "随机卡组合法",
                db.validateDeck(deck, "德国"));
        deck.add(db.get("虎式坦克"));
        check(db.validateDeck(deck, "德国") != null, "多一张被拒", deck.size());
    }

    // ---------------- AI 对战 ----------------
    private static void battle(int n) throws Exception {
        int aWin = 0, bWin = 0, draw = 0;
        for (int i = 0; i < n; i++) {
            String na = db.rules.mainNations.get(i % db.rules.mainNations.size());
            String nb = db.rules.mainNations.get((i + 2) % db.rules.mainNations.size());
            long seed = 1000 + i;
            Game g = newGame(na, nb, seed);
            StringBuilder logBuf = new StringBuilder();
            g.setLogSink(logBuf::append);
            g.runAiVsAi();
            Player w = g.winnerOf();
            String res = w == null ? "平局" : w.name + "(" + w.nation + ")";
            if (w == g.players[0]) aWin++;
            else if (w == g.players[1]) bWin++;
            else draw++;
            System.out.printf("#%d %s(%s) vs %s(%s) → %s，回合 %d，日志 %d 字%n",
                    i + 1, g.players[0].name, na, g.players[1].name, nb,
                    res, g.turnNum, logBuf.length());
            if (g.turnNum < 4) {
                System.out.println("  ⚠ 对局异常提前结束，日志前 40 行：");
                int shown = 0;
                for (String line : logBuf.toString().split("\n")) {
                    System.out.println("  " + line);
                    if (++shown >= 40) break;
                }
            }
        }
        System.out.println("== AI 对战 " + n + " 局：甲胜 " + aWin + " / 乙胜 " + bWin
                + " / 平 " + draw + " ==");
    }

    private KardsCli() { }
}
