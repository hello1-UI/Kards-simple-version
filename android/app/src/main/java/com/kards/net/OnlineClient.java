package com.kards.net;

import com.kards.engine.MiniJson;

import java.io.IOException;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;

/** 联机会话机（对齐 KARDS.py 的联机流程）：
 *
 *  connect → login/register/resume → match|create_room|join_room
 *  → 双方 send ready{nation, deck} → host 发 seed → 双方开局
 *  → 对局中 act/concede 中转。
 *
 *  协议要点（与 Windows 端一致）：
 *   · 卡组以「卡名列表」互发——双方各自用收到的顺序构造对手卡组，
 *     无需跨端洗牌同步；
 *   · 先手判定 = 种子奇偶（seed 为奇 → 房主先手），与平台无关；
 *   · 对局内随机走引擎共享 Rng（两端同 seed 同序列）。
 */
public final class OnlineClient implements NetLink.Listener {
    public interface Ui {
        void onLog(String s);

        void onAuthOk(String user);

        void onAuthErr(String err);

        void onMatching();

        void onMatched(String role, String opp, boolean casual);

        void onRoomCreated(String code);

        void onJoinErr(String err);

        /** 双方就绪 + 种子齐了 → 可以开局 */
        void onStartGame(long seed, Map<String, Object> oppReady);

        /** 对手的一条对局行动 */
        void onAct(Map<String, Object> act);

        /** 对手投降 */
        void onConcede();

        void onPeerLeft(String reason);

        void onDisconnected(String reason);
    }

    public static final String VT_URL =
            "https://kards-cloud-server.app.workbuddy.host/?sharecode=NUCBKJ7U64";
    private static final java.util.Set<String> VT_HOSTS =
            new java.util.HashSet<>(java.util.Arrays.asList(
                    "vitural", "virtual", "vt", "cloud"));

    private final Ui ui;
    private NetLink link;
    public volatile String user = "";
    public volatile String token = "";
    public volatile String role = "";
    public volatile String oppName = "";
    public volatile boolean inGame = false;
    private volatile boolean myReady = false;
    private volatile Map<String, Object> oppReady;
    private volatile Long pendingSeed;
    private final Random seedRng = new SecureRandom();
    /** Android 主线程禁止网络阻塞操作：connect/登录/房间请求全部丢进这里执行 */
    private final java.util.concurrent.ExecutorService blocking =
            java.util.concurrent.Executors.newSingleThreadExecutor(r -> {
                Thread t = new Thread(r, "kards-net-ui");
                t.setDaemon(true);
                return t;
            });

    public OnlineClient(Ui ui) {
        this.ui = ui;
    }

    public boolean connected() {
        return link != null && link.alive;
    }

    /** 连接服务器：vitural/virtual/vt/cloud → 云端 HTTPS 桥接；否则 TCP。 */
    public void connect(String addr) {
        blocking.execute(() -> connectBlocking(addr));
    }

    private void connectBlocking(String addr) {
        String host = addr.trim();
        String port = "6000";
        int c = host.lastIndexOf(':');
        if (c > 0) {
            port = host.substring(c + 1).trim();
            host = host.substring(0, c).trim();
        }
        final NetLink l;
        try {
            if (VT_HOSTS.contains(host.toLowerCase())) {
                l = new HttpLink(VT_URL);
            } else {
                int p = Integer.parseInt(port);
                if (p < 1 || p > 65535) throw new NumberFormatException("端口越界");
                l = new TcpLink(host, p, 6000);
            }
        } catch (Exception e) {
            ui.onDisconnected("连接失败：" + e.getMessage());
            return;
        }
        link = l;
        l.setListener(this);
        ui.onLog("已连接服务器。");
    }

    public void disconnect() {
        inGame = false;
        if (link != null) {
            link.close();
            link = null;
        }
    }

    // ---------------- 账号 ----------------
    // ⚠ 这些方法都紧跟 connect() 提交到同一条单线程队列：执行时 connect
    //   已完成，所以 alive 检查放在执行体里（提交时 link 还没建好）。
    //   request() 的应答（auth_ok/auth_err/room_created/…）转交 onEvent
    //   统一路由，Ui 回调只看事件，不用关心请求/应答配对。

    public void login(String user, String pw) {
        blocking.execute(() -> {
            if (!checkLink()) return;
            Map<String, Object> r = link.request(
                    NetLink.msg("login", "user", user, "pw", pw),
                    "auth_ok", "auth_err");
            if (r == null) ui.onAuthErr("服务器无应答（超时）");
            else onEvent(r);
        });
    }

    public void register(String user, String pw) {
        blocking.execute(() -> {
            if (!checkLink()) return;
            Map<String, Object> r = link.request(
                    NetLink.msg("register", "user", user, "pw", pw),
                    "auth_ok", "auth_err");
            if (r == null) ui.onAuthErr("服务器无应答（超时）");
            else onEvent(r);
        });
    }

    public void resume(String token) {
        blocking.execute(() -> {
            if (!checkLink()) return;
            Map<String, Object> r = link.request(
                    NetLink.msg("resume", "token", token),
                    "auth_ok", "auth_err");
            if (r == null) ui.onAuthErr("服务器无应答（超时）");
            else onEvent(r);
        });
    }

    // ---------------- 匹配 / 房间 ----------------

    public void quickMatch(boolean casual) {
        if (!checkLink()) return;
        link.send(NetLink.msg("match", "casual", casual));
    }

    public void cancelMatch() {
        if (!checkLink()) return;
        link.send(NetLink.msg("cancel_match"));
    }

    public void createRoom(boolean casual) {
        blocking.execute(() -> {
            if (!checkLink()) return;
            Map<String, Object> r = link.request(
                    NetLink.msg("create_room", "casual", casual),
                    "room_created", "err");
            if (r == null) ui.onLog("  ⚠ 创建房间无应答");
            else onEvent(r);
        });
    }

    public void joinRoom(String code) {
        blocking.execute(() -> {
            if (!checkLink()) return;
            Map<String, Object> r = link.request(
                    NetLink.msg("join_room", "code", code),
                    "join_err", "err");
            if (r == null) ui.onJoinErr("服务器无应答（超时）");
            else onEvent(r);       // join_err / err；matched 是服务器推送
        });
    }

    public void leaveRoom() {
        if (!checkLink()) return;
        link.send(NetLink.msg("leave_room"));
    }

    // ---------------- 准备 / 对局 ----------------

    /** 发送就绪：nation + 洗好的卡名列表（顺序即卡组顺序）。 */
    public void sendReady(String nation, List<String> deckNames) {
        if (!checkLink()) return;
        myReady = true;
        link.send(NetLink.msg("ready", "nation", nation, "deck", deckNames));
        tryStart();                                  // host 可能早就等对手 ready 了
    }

    public void sendAct(Map<String, Object> act) {
        if (!checkLink()) return;
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("m", "act");
        m.putAll(act);
        link.send(m);
    }

    public void sendConcede() {
        if (!checkLink()) return;
        link.send(NetLink.msg("concede"));
    }

    /** 先手判定（跨端协议）：种子为奇 → 房主先手。 */
    public static boolean iAmFirst(long seed, String role) {
        return ((seed & 1L) == 1L) == "host".equals(role);
    }

    private void tryStart() {
        if (inGame) return;
        if ("host".equals(role)) {
            if (!myReady || oppReady == null) return;
            long seed = Math.abs(seedRng.nextLong() % 1_000_000_000L);
            if (link != null) link.send(NetLink.msg("seed", "seed", seed));
            startGame(seed);
        } else if ("guest".equals(role)) {
            if (pendingSeed == null || oppReady == null) return;
            startGame(pendingSeed);
        }
    }

    private void startGame(long seed) {
        inGame = true;
        ui.onStartGame(seed, oppReady);
    }

    private boolean checkLink() {
        if (link == null || !link.alive) {
            ui.onDisconnected("尚未连接服务器");
            return false;
        }
        return true;
    }

    // ---------------- 事件路由 ----------------

    @Override
    public void onEvent(Map<String, Object> msg) {
        String m = MiniJson.str(msg, "m");
        switch (m) {
            case "auth_ok":
                user = MiniJson.str(msg, "user");
                token = MiniJson.str(msg, "token");
                ui.onAuthOk(user);
                break;
            case "auth_err":
                ui.onAuthErr(MiniJson.str(msg, "err"));
                break;
            case "matching":
                ui.onMatching();
                break;
            case "matched":
                role = MiniJson.str(msg, "role");
                oppName = MiniJson.str(msg, "opp");
                myReady = false;
                oppReady = null;
                pendingSeed = null;
                ui.onMatched(role, oppName, MiniJson.bool(msg.get("casual")));
                break;
            case "room_created":
                ui.onRoomCreated(MiniJson.str(msg, "code"));
                break;
            case "join_err":
                ui.onJoinErr(MiniJson.str(msg, "err"));
                break;
            case "ready":
                oppReady = msg;
                ui.onLog("对手已就绪（" + MiniJson.str(msg, "nation") + "，"
                        + MiniJson.arr(msg.get("deck")).size() + " 张）。");
                tryStart();
                break;
            case "seed":
                if ("guest".equals(role)) {
                    pendingSeed = (long) MiniJson.getInt(msg, "seed");
                    tryStart();
                }
                break;
            case "act":
                if (inGame) ui.onAct(msg);
                break;
            case "concede":
                ui.onConcede();
                break;
            case "peer_left":
                inGame = false;
                ui.onPeerLeft("对手已离开");
                break;
            case "kick":
                String kickErr = MiniJson.str(msg, "err");
                ui.onPeerLeft(kickErr.isEmpty() ? "该账号已在别处登录" : kickErr);
                break;
            case "err":
                ui.onLog("  ⚠ 服务器：" + MiniJson.str(msg, "err"));
                break;
            default:
                // lobby / hall_* 等：Android v1 走动大厅不做，静默
                break;
        }
    }

    @Override
    public void onDead(String reason) {
        inGame = false;
        link = null;
        ui.onDisconnected(reason);
    }
}
