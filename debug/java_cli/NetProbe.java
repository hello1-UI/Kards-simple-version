import com.kards.engine.CardDb;
import com.kards.engine.CardDef;
import com.kards.engine.MiniJson;
import com.kards.net.NetLink;
import com.kards.net.OnlineClient;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/** 联机互通探针：同一 JVM 内两个 OnlineClient 会话连到真实 kards_server，
 *  走完 注册 → 建房/加入 → 双方 ready → 主机发种子 → act 中转 → 投降
 *  全流程。退出码 0 = 全部通过。
 *
 *  用法：java KardsCli --netprobe <port>
 */
public final class NetProbe {
    private static int passed = 0, failed = 0;

    private static void check(boolean ok, String label, String detail) {
        if (ok) {
            passed++;
        } else {
            failed++;
        }
        System.out.println((ok ? "  [OK] " : "  [!!] ") + label
                + (detail == null || detail.isEmpty() ? "" : "  " + detail));
    }

    /** 事件收集式 Ui：每个回调入队 "事件名[:附加信息]"。 */
    private static final class Session implements OnlineClient.Ui {
        final String tag;
        final LinkedBlockingQueue<String> events = new LinkedBlockingQueue<>();
        volatile String role = "", roomCode = "", oppNation = "";
        volatile long seed = -1;
        volatile boolean started, conceded, gotAct, gotConcede;
        volatile Map<String, Object> oppReady, act;

        Session(String tag) { this.tag = tag; }

        public void onLog(String s) { }
        public void onAuthOk(String user) { events.add("auth_ok"); }
        public void onAuthErr(String err) { events.add("auth_err:" + err); }
        public void onMatching() { events.add("matching"); }
        public void onMatched(String role, String opp, boolean casual) {
            this.role = role;
            events.add("matched:" + role);
        }
        public void onRoomCreated(String code) {
            roomCode = code;
            events.add("room_created:" + code);
        }
        public void onJoinErr(String err) { events.add("join_err:" + err); }
        public void onStartGame(long seed, Map<String, Object> oppReady) {
            this.seed = seed;
            this.oppReady = oppReady;
            this.oppNation = MiniJson.str(oppReady, "nation");
            started = true;
            events.add("start");
        }
        public void onAct(Map<String, Object> act) {
            this.act = act;
            gotAct = true;
            events.add("act:" + act.get("k") + ":"
                    + MiniJson.str(act, "from_role"));
        }
        public void onConcede() { conceded = true; gotConcede = true;
            events.add("concede"); }
        public void onPeerLeft(String reason) { events.add("peer_left:" + reason); }
        public void onDisconnected(String reason) { events.add("dead:" + reason); }

        String waitEvent(String prefix, long timeoutMs) throws InterruptedException {
            long end = System.currentTimeMillis() + timeoutMs;
            while (System.currentTimeMillis() < end) {
                String e = events.poll(200, TimeUnit.MILLISECONDS);
                if (e != null && e.startsWith(prefix)) return e;
                if (e != null && e.startsWith("dead:")) return null;
            }
            return null;
        }
    }

    public static void run(int port) throws Exception {
        CardDb db = CardDb.fromFile("android/app/src/main/assets/cards.json");
        String suffix = Long.toString(System.currentTimeMillis() % 1000000);
        String userA = "探针甲" + suffix, userB = "探针乙" + suffix;

        Session sa = new Session("甲"), sb = new Session("乙");
        OnlineClient ca = new OnlineClient(sa), cb = new OnlineClient(sb);

        System.out.println("== NetProbe: Java 客户端 ↔ Python kards_server 互通对拍 ==");
        ca.connect("127.0.0.1:" + port);
        cb.connect("127.0.0.1:" + port);
        Thread.sleep(500);                       // 等 TCP 建立读线程
        ca.register(userA, "pass1234");
        cb.register(userB, "pass1234");

        boolean ok = true;
        ok &= sa.waitEvent("auth_ok", 8000) != null;
        ok &= sb.waitEvent("auth_ok", 8000) != null;
        check(ok, "双方注册+登录", userA + " / " + userB);

        ca.createRoom(true);
        String ev = sa.waitEvent("room_created", 8000);
        check(ev != null, "甲创建房间", sa.roomCode);
        if (ev == null) { finish(); return; }

        cb.joinRoom(sa.roomCode);
        String mA = sa.waitEvent("matched:", 8000);
        String mB = sb.waitEvent("matched:", 8000);
        check("matched:host".equals(mA) && "matched:guest".equals(mB),
                "甲=房主 / 乙=客人", mA + " / " + mB);

        // 双方就绪（卡名列表互发，顺序即卡组顺序）
        List<String> namesA = deckNames(db, "德国", 7);
        List<String> namesB = deckNames(db, "苏联", 8);
        ca.sendReady("德国", namesA);
        cb.sendReady("苏联", namesB);

        ok = sa.waitEvent("start", 10000) != null
                && sb.waitEvent("start", 10000) != null;
        check(ok, "双方进入开局（host 自动发种子）",
                "seed=" + sa.seed + " / " + sb.seed);
        if (!ok) { finish(); return; }
        check(sa.seed == sb.seed && sa.seed >= 0,
                "两端种子一致", String.valueOf(sa.seed));
        check(OnlineClient.iAmFirst(sa.seed, sa.role)
                        != OnlineClient.iAmFirst(sb.seed, sb.role),
                "先手判定恰一方先手（种子奇偶协议）",
                "甲first=" + OnlineClient.iAmFirst(sa.seed, sa.role)
                        + " 乙first=" + OnlineClient.iAmFirst(sb.seed, sb.role));
        check("苏联".equals(sa.oppNation) && "德国".equals(sb.oppNation),
                "对手国家随 ready 交换", sa.oppNation + " / " + sb.oppNation);

        ca.sendAct(NetLink.act("play", "i", 0));
        String act = sb.waitEvent("act:play:host", 8000);
        check(act != null, "act 中转（乙收到甲的 play，带 from_role）", act);

        ca.sendConcede();
        ok = sb.waitEvent("concede", 8000) != null;
        check(ok, "投降中转（乙收到甲投降）", "");

        ca.disconnect();
        cb.disconnect();
        finish();
    }

    private static List<String> deckNames(CardDb db, String nation, long rngSeed) {
        List<String> names = new ArrayList<>();
        for (CardDef c : db.buildDeck(nation, new Random(rngSeed))) {
            names.add(c.name);
        }
        return names;
    }

    private static void finish() {
        System.out.println("== NetProbe: " + passed + " 通过 / " + failed + " 失败 ==");
        System.exit(failed == 0 ? 0 : 1);
    }

    private NetProbe() { }
}
