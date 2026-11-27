package com.kards.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import com.kards.engine.CardDb;
import com.kards.engine.CardDef;
import com.kards.engine.Game;
import com.kards.engine.MiniJson;
import com.kards.engine.Player;
import com.kards.net.OnlineClient;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** KARDS Java 版入口。
 *
 *  模式：
 *   · 人机对战：选国家 → AI 对战；
 *   · 联机对战：连接 kards_server（局域网 TCP 或云端 HTTPS 桥接），
 *     快速匹配 / 邀请码房间，与 Windows 版互通。
 *
 *  ⚠ Android 版只是联机客户端：本应用不含任何开服/监听代码，
 *    不能也没有任何入口可以在手机上架设服务器。
 */
public class MainActivity extends Activity {
    private CardDb db;
    private BoardView board;
    private OnlineClient session;
    private SharedPreferences prefs;

    // 联机准备阶段的状态
    private String myNation;
    private List<CardDef> myDeck;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("kards_net", MODE_PRIVATE);
        try {
            db = CardDb.fromStream(getAssets().open("cards.json"));
        } catch (IOException e) {
            Toast.makeText(this, "卡牌数据加载失败: " + e.getMessage(),
                    Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        mainMenu();
    }

    // ================================================================ 菜单

    private void mainMenu() {
        String[] items = {"人机对战", "联机对战（与 Windows 互通）"};
        new AlertDialog.Builder(this)
                .setTitle("KARDS 简化版")
                .setItems(items, (dlg, which) -> {
                    if (which == 0) pickNationThenAi();
                    else showOnlineLogin();
                })
                .setCancelable(false)
                .show();
    }

    // ================================================================ 人机

    private void pickNationThenAi() {
        final List<String> nations = db.rules.mainNations;
        String[] names = nations.toArray(new String[0]);
        new AlertDialog.Builder(this)
                .setTitle("选择你的国家")
                .setItems(names, (dlg, which) -> startAiGame(nations.get(which)))
                .setCancelable(false)
                .show();
    }

    private void startAiGame(String myNation) {
        // 对手随机一个不同的主国
        List<String> pool = new ArrayList<>(db.rules.mainNations);
        pool.remove(myNation);
        String foeNation = pool.get((int) (Math.random() * pool.size()));
        long seed = System.currentTimeMillis();
        List<CardDef> myDeck = db.buildDeck(myNation, new java.util.Random(seed));
        List<CardDef> foeDeck = db.buildDeck(foeNation, new java.util.Random(seed + 1));
        Player me = new Player("你", myNation, db, myDeck);
        Player ai = new Player("AI", foeNation, db, foeDeck);
        Game g = new Game(me, ai, db, seed);
        g.setLogSink(s -> { });
        g.setup();
        g.startTurn();          // 开启我方第一回合
        board = new BoardView(this, g);
        setContentView(board);
    }

    // ================================================================ 联机

    private void showOnlineLogin() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        box.setPadding(pad, pad, pad, pad);

        final EditText etAddr = new EditText(this);
        etAddr.setHint("服务器地址（vitural:6000 = 云端）");
        etAddr.setText(prefs.getString("addr", "vitural:6000"));
        etAddr.setSingleLine(true);
        final EditText etUser = new EditText(this);
        etUser.setHint("账号");
        etUser.setText(prefs.getString("user", ""));
        etUser.setSingleLine(true);
        final EditText etPw = new EditText(this);
        etPw.setHint("密码");
        etPw.setInputType(InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_VARIATION_PASSWORD);

        TextView hint = new TextView(this);
        hint.setText("Android 版为联机客户端，可在同一服务器与 Windows 玩家对战。\n"
                + "没有账号会自动注册一个。");
        hint.setTextSize(12);
        box.addView(hint);
        box.addView(etAddr);
        box.addView(etUser);
        box.addView(etPw);

        AlertDialog dlg = new AlertDialog.Builder(this)
                .setTitle("联机对战")
                .setView(scroll(box))
                .setCancelable(false)
                .create();
        ensureSession();
        dlg.setButton(AlertDialog.BUTTON_POSITIVE, "登录", (d, w) -> {
            d.dismiss();
            String addr = etAddr.getText().toString().trim();
            String u = etUser.getText().toString().trim();
            String p = etPw.getText().toString();
            prefs.edit().putString("addr", addr).putString("user", u).apply();
            session.connect(addr);
            session.login(u, p);
        });
        dlg.setButton(AlertDialog.BUTTON_NEUTRAL, "注册新账号", (d, w) -> {
            d.dismiss();
            String addr = etAddr.getText().toString().trim();
            String u = etUser.getText().toString().trim();
            String p = etPw.getText().toString();
            prefs.edit().putString("addr", addr).putString("user", u).apply();
            session.connect(addr);
            session.register(u, p);
        });
        dlg.setButton(AlertDialog.BUTTON_NEGATIVE, "返回", (d, w) -> {
            d.dismiss();
            mainMenu();
        });
        dlg.show();
    }

    private ScrollView scroll(LinearLayout box) {
        ScrollView sv = new ScrollView(this);
        sv.addView(box);
        return sv;
    }

    private void ensureSession() {
        if (session != null && session.connected()) return;
        session = new OnlineClient(new OnlineUi());
    }

    /** 联机大菜单：登录成功后出现。 */
    private void showLobby() {
        ensureSession();
        String[] items = {"快速匹配（休闲）", "创建房间", "加入房间…", "断开并返回"};
        new AlertDialog.Builder(this)
                .setTitle("联机大厅  ·  " + session.user)
                .setItems(items, (dlg, which) -> {
                    if (which == 0) {
                        session.quickMatch(true);
                        toast("匹配中…");
                    } else if (which == 1) {
                        session.createRoom(true);
                    } else if (which == 2) {
                        askRoomCode();
                    } else {
                        session.disconnect();
                        mainMenu();
                    }
                })
                .setCancelable(false)
                .show();
    }

    private void askRoomCode() {
        final EditText et = new EditText(this);
        et.setHint("邀请码（6 位）");
        et.setSingleLine(true);
        et.setInputType(InputType.TYPE_CLASS_TEXT
                | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
        et.setGravity(Gravity.CENTER);
        new AlertDialog.Builder(this)
                .setTitle("加入房间")
                .setView(et)
                .setPositiveButton("加入", (d, w) ->
                        session.joinRoom(et.getText().toString().trim()))
                .setNegativeButton("取消", null)
                .show();
    }

    /** 匹配成功 / 房主建房后：选国家并就绪。 */
    private void pickNationAndReady() {
        final List<String> nations = db.rules.mainNations;
        String[] names = nations.toArray(new String[0]);
        new AlertDialog.Builder(this)
                .setTitle("选择国家并准备")
                .setItems(names, (dlg, which) -> {
                    myNation = nations.get(which);
                    myDeck = db.buildDeck(myNation, new java.util.Random());
                    List<String> names2 = new ArrayList<>();
                    for (CardDef c : myDeck) names2.add(c.name);
                    session.sendReady(myNation, names2);
                    toast("已准备，等待对手…");
                })
                .setCancelable(false)
                .show();
    }

    /** 双方就绪 + 种子齐 → 开局（与 Windows _mp_launch 对称）。 */
    private void startOnlineGame(long seed, Map<String, Object> oppReady) {
        List<CardDef> oppCards = new ArrayList<>();
        for (Object n : MiniJson.arr(oppReady.get("deck"))) {
            CardDef c = db.get(String.valueOf(n));
            if (c != null) oppCards.add(c);
        }
        if (oppCards.size() != db.rules.deckSize) {
            toast("对手卡组数量异常（" + oppCards.size() + "），"
                    + "请确认双方版本一致。");
            backToMenuFromGame();
            return;
        }
        String oppNation = MiniJson.str(oppReady, "nation");
        boolean iFirst = OnlineClient.iAmFirst(seed, session.role);
        Player me = new Player(session.user, myNation, db, myDeck);
        Player foe = new Player(session.oppName, oppNation, db, oppCards);
        Game g = new Game(me, foe, db, seed);
        g.setLogSink(s -> { });
        g.drawCards(me, 5);
        g.drawCards(foe, 5);
        if (iFirst) g.drawCards(foe, 1);          // 后手多抽一张
        else g.drawCards(me, 1);
        g.current = iFirst ? me : foe;
        g.startTurn();                             // 双方对称各执行一次
        board = new BoardView(this, g, session, this::backToMenuFromGame);
        setContentView(board);
        toast(iFirst ? "先手：你" : "先手：对手");
    }

    private void backToMenuFromGame() {
        runOnUiThread(() -> {
            board = null;
            if (session != null && session.connected()) {
                session.leaveRoom();
                showLobby();
            } else {
                mainMenu();
            }
        });
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    // ================================================================ 网络回调

    private class OnlineUi implements OnlineClient.Ui {
        @Override public void onLog(String s) {
            // v1：大厅日志走 toast 太吵，仅在调试时打开
        }

        @Override public void onAuthOk(String user) {
            prefs.edit().putString("token", session.token).apply();
            runOnUiThread(() -> {
                toast("登录成功：" + user);
                showLobby();
            });
        }

        @Override public void onAuthErr(String err) {
            runOnUiThread(() -> {
                toast("登录失败：" + err);
                showOnlineLogin();
            });
        }

        @Override public void onMatching() {
            runOnUiThread(() -> toast("匹配中…"));
        }

        @Override public void onMatched(String role, String opp, boolean casual) {
            runOnUiThread(() -> {
                toast("匹配成功：" + opp + "（" + role + "）");
                pickNationAndReady();
            });
        }

        @Override public void onRoomCreated(String code) {
            runOnUiThread(() -> {
                toast("房间已创建，邀请码 " + code);
                pickNationAndReady();
            });
        }

        @Override public void onJoinErr(String err) {
            runOnUiThread(() -> {
                toast("加入失败：" + err);
                showLobby();
            });
        }

        @Override public void onStartGame(long seed, Map<String, Object> oppReady) {
            runOnUiThread(() -> startOnlineGame(seed, oppReady));
        }

        @Override public void onAct(Map<String, Object> act) {
            if (board != null) board.enqueueRemoteAct(act);
        }

        @Override public void onConcede() {
            if (board != null) board.remoteConcede();
        }

        @Override public void onPeerLeft(String reason) {
            runOnUiThread(() -> {
                if (board != null) {
                    board.remoteLeft();
                } else {
                    toast(reason);
                    showLobby();
                }
            });
        }

        @Override public void onDisconnected(String reason) {
            runOnUiThread(() -> {
                if (board != null) {
                    board.remoteLeft();          // 对局中掉线：判胜收尾回大厅
                } else {
                    toast(reason);
                    mainMenu();
                }
            });
        }
    }

    @Override
    public void onBackPressed() {
        if (board != null && board.isOnline()) {
            // 对局中返回键 = 投降
            if (session != null) session.sendConcede();
            board.concedeLocal();
        } else if (board != null) {
            finish();
        } else {
            mainMenu();
        }
    }
}
