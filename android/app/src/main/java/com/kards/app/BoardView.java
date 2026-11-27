package com.kards.app;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.MotionEvent;
import android.view.SurfaceHolder;
import android.view.SurfaceView;

import com.kards.engine.CardDef;
import com.kards.engine.Game;
import com.kards.engine.MiniJson;
import com.kards.engine.Player;
import com.kards.engine.Unit;
import com.kards.net.NetLink;
import com.kards.net.OnlineClient;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentLinkedQueue;

/** 极简对战棋盘（SurfaceView 自绘，对应 pygame 棋盘架构）：
 *  敌我信息条 + 支援线/前线两行 + 手牌 + 结束回合/移动按钮。
 *  交互：点手牌出牌；点我方单位选中；点敌方单位/总部攻击；「移动」切换阵线。
 *  联机模式（session != null）：本地动作同步发给对手、对手行动从
 *  remoteActs 队列在渲染线程里回放；非本方回合锁定操作；无 AI。 */
public final class BoardView extends SurfaceView
        implements SurfaceHolder.Callback, Runnable {
    private final Game g;
    private final Thread thread = new Thread(this);
    private volatile boolean running;
    private final Paint pText = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pFill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint pStroke = new Paint(Paint.ANTI_ALIAS_FLAG);

    private final OnlineClient net;         // null = 单机 AI 模式
    private final ConcurrentLinkedQueue<Map<String, Object>> remoteActs
            = new ConcurrentLinkedQueue<>();
    private Runnable onGameOver;            // 联机对局结束回调（回大厅）
    private boolean gameOverShown;

    private Unit selected;
    private String message = "";
    private long messageUntil;
    private boolean aiThinking;

    // 手牌/按钮命中区
    private final List<RectF> handRects = new ArrayList<>();
    private RectF endBtn, moveBtn, concedeBtn;

    private static final int C_BG = 0xFF221C16;
    private static final int C_PANEL = 0xFF322A21;
    private static final int C_GOLD = 0xFFE7C88A;
    private static final int C_RED = 0xFFD96C5F;
    private static final int C_GREEN = 0xFF7FA860;
    private static final int C_SEL = 0xFFFFD966;

    public BoardView(Context ctx, Game game) {
        this(ctx, game, null, null);
    }

    /** 联机模式：session 非空时启用网络同步。 */
    public BoardView(Context ctx, Game game, OnlineClient session,
                     Runnable gameOverCb) {
        super(ctx);
        this.g = game;
        this.net = session;
        this.onGameOver = gameOverCb;
        getHolder().addCallback(this);
        setFocusable(true);
    }

    /** 对手的一条行动（网络线程调用，渲染线程里回放）。 */
    public void enqueueRemoteAct(Map<String, Object> act) {
        remoteActs.add(act);
    }

    /** 对手投降（网络线程调用）。 */
    public void remoteConcede() {
        if (g.over) return;
        g.conceded = g.players[1];      // 对手举旗 → 我方胜
        g.over = true;
    }

    /** 对手断线（网络线程调用）：判我方胜并结束。 */
    public void remoteLeft() {
        if (g.over) return;
        flash("对手已断线！");
        g.conceded = g.players[1];
        g.over = true;
    }

    @Override public void surfaceCreated(SurfaceHolder h) {
        running = true;
        if (!thread.isAlive()) thread.start();
    }

    @Override public void surfaceChanged(SurfaceHolder h, int f, int w, int ht) { }

    @Override public void surfaceDestroyed(SurfaceHolder h) {
        running = false;
        try { thread.join(); } catch (InterruptedException ignored) { }
    }

    @Override public void run() {
        while (running) {
            // 联机：回放对手行动（在渲染线程里改引擎状态，与本机 AI 线程同策略）
            Map<String, Object> act;
            while ((act = remoteActs.poll()) != null) {
                applyRemote(act);
            }
            SurfaceHolder holder = getHolder();
            Canvas c = null;
            try {
                c = holder.lockCanvas();
                if (c != null) draw(c);
            } finally {
                if (c != null) holder.unlockCanvasAndPost(c);
            }
            try { Thread.sleep(33); } catch (InterruptedException ignored) { }
        }
    }

    /** 对手的行动回放（对齐 KARDS.py _mp_handle；players[1] = 对手）。 */
    private void applyRemote(Map<String, Object> msg) {
        if (g.over) return;
        Player me = g.players[0], foe = g.players[1];
        String k = msg.get("k") == null ? "" : String.valueOf(msg.get("k"));
        if ("end".equals(k)) {
            g.endTurn();
            if (g.over) { gameOver(); return; }
            g.startTurn();
            selected = null;
            flash(g.current == me ? "你的回合" : "敌方回合");
            return;
        }
        if ("play".equals(k)) {
            int i = MiniJson.getInt(msg, "i");
            if (i >= 0 && i < foe.hand.size()) g.playCard(foe, i);
        } else if ("attack".equals(k)) {
            Unit att = bySlot(foe, MiniJson.getInt(msg, "s"));
            Unit tgt = bySlot(me, MiniJson.getInt(msg, "t"));
            if (att != null && tgt != null) g.doAttack(att, tgt);
        } else if ("hq".equals(k)) {
            Unit att = bySlot(foe, MiniJson.getInt(msg, "s"));
            if (att != null) g.doHqAttack(att);
        } else if ("move".equals(k)) {
            Unit u = bySlot(foe, MiniJson.getInt(msg, "s"));
            String p = MiniJson.str(msg, "p");
            if (u != null) g.moveUnit(u, p.isEmpty() ? "前线" : p);
        }
        cleanupDead();
    }

    private void cleanupDead() {
        for (Player pl : g.players) {
            for (Unit u : new ArrayList<>(pl.board)) {
                if (u.defense <= 0) g.destroyUnit(u);
            }
        }
    }

    private Unit bySlot(Player p, int slot) {
        for (Unit u : p.board) if (u.slot == slot) return u;
        return null;
    }

    private void gameOver() {
        if (gameOverShown) return;
        gameOverShown = true;
        if (onGameOver != null) onGameOver.run();
    }

    public boolean isOnline() { return net != null; }

    /** 本地投降（返回键等入口；「🏳 投降」按钮自己处理网络发送）。 */
    public void concedeLocal() {
        if (!g.over) {
            g.conceded = g.players[0];
            g.over = true;
            gameOver();
        }
    }

    // ---------------- 绘制 ----------------
    private void draw(Canvas c) {
        int w = c.getWidth(), h = c.getHeight();
        pFill.setStyle(Paint.Style.FILL);
        pFill.setColor(C_BG);
        c.drawRect(0, 0, w, h, pFill);

        Player me = g.players[0], foe = g.players[1];
        float cardW = Math.min(150, w / 6f - 12);
        float cardH = cardW * 0.62f;

        pText.setTextSize(30);
        // 敌方信息条
        text(c, foeInfo(foe), 20, 40, C_GOLD);
        // 敌方支援线
        float y = 60;
        drawRow(c, rear(foe), 30, y, cardW, cardH, false);
        // 敌方前线
        y += cardH + 14;
        drawRow(c, front(foe), 30 + cardW, y, cardW, cardH, false);
        // 前线分隔
        y += cardH + 16;
        pFill.setColor(frontOwnerColor());
        c.drawRect(20, y, w - 20, y + 4, pFill);
        pText.setColor(Color.GRAY);
        pText.setTextSize(24);
        c.drawText(frontlineLabel(), 30, y + 30, pText);

        // 我方前线
        y += 44;
        drawRow(c, front(me), 30 + cardW, y, cardW, cardH, true);
        // 我方支援线
        y += cardH + 14;
        drawRow(c, rear(me), 30, y, cardW, cardH, true);
        // 我方信息条
        y += cardH + 10;
        text(c, myInfo(me), 20, y + 22, C_GOLD);

        // 手牌
        float hy = h - cardH - 18;
        handRects.clear();
        List<CardDef> hand = me.hand;
        float hx = 20;
        for (int i = 0; i < hand.size() && hx + cardW < w - 260; i++) {
            CardDef card = hand.get(i);
            RectF r = new RectF(hx, hy, hx + cardW, hy + cardH);
            handRects.add(r);
            boolean playable = g.getCost(card, me) <= me.kredits
                    && (!card.isUnit() || g.canDeploy(me));
            drawCard(c, r, card.name + " ¥" + g.getCost(card, me),
                    card.isUnit() ? card.attack + "/" + card.defense : card.kind,
                    playable ? C_PANEL : 0xFF241F1A, false);
            hx += cardW + 8;
        }

        // 按钮
        float bw = 200, bh = 64;
        boolean myTurn = myTurn();
        endBtn = new RectF(w - bw - 24, hy, w - 24, hy + bh);
        button(c, endBtn,
                net != null && !myTurn ? "等待对手…" : "结束回合",
                myTurn ? 0xFF6E5630 : 0xFF4A4238);
        moveBtn = new RectF(w - bw - 24, hy - bh - 10, w - 24, hy - 10);
        button(c, moveBtn, selected == null ? "移动（先选单位）" : "移动到"
                        + ("后方".equals(selected.position) ? "前线" : "后方"),
                selected == null ? 0xFF40382E : 0xFF3E5A34);
        if (net != null) {
            concedeBtn = new RectF(w - bw - 24, hy - 2 * bh - 20, w - 24,
                    hy - bh - 20);
            button(c, concedeBtn, "🏳 投降", 0xFF6B3226);
        } else {
            concedeBtn = null;
        }

        // 消息
        if (System.currentTimeMillis() < messageUntil) {
            pText.setTextSize(26);
            pText.setColor(0xFFFFE0B2);
            c.drawText(message, 24, h - cardH - 40, pText);
        }
        if (g.over) {
            Player winner = g.winnerOf();
            pText.setTextSize(64);
            pText.setColor(winner == me ? C_GREEN : C_RED);
            String s = winner == null ? "平局" : (winner == me ? "胜利！" : "战败…");
            c.drawText(s, w / 2f - pText.measureText(s) / 2, h / 2f, pText);
            pText.setTextSize(26);
            pText.setColor(Color.LTGRAY);
            String hint = net != null ? "点击屏幕返回大厅" : "";
            if (!hint.isEmpty()) {
                c.drawText(hint, w / 2f - pText.measureText(hint) / 2,
                        h / 2f + 50, pText);
            }
        }
    }

    /** 本方是否可操作：单机=AI 没在想；联机=轮到我且对手没在动画中。 */
    private boolean myTurn() {
        if (net != null) return g.current == g.players[0];
        return !aiThinking;
    }

    private void drawRow(Canvas c, List<Unit> units, float x, float y,
                         float cardW, float cardH, boolean mine) {
        for (Unit u : units) {
            RectF r = new RectF(x, y, x + cardW, y + cardH);
            boolean sel = u == selected;
            drawCard(c, r, u.name(), u.attack + "/" + u.defense
                            + ("前线".equals(u.position) ? " ⚔" : ""),
                    sel ? 0xFF5A4B26 : C_PANEL, sel);
            if (u.operate > 0) {
                pText.setTextSize(18);
                pText.setColor(Color.GRAY);
                c.drawText("⚡" + u.operate, r.right - 40, r.top + 22, pText);
            }
            x += cardW + 8;
        }
    }

    private void drawCard(Canvas c, RectF r, String title, String stat,
                          int bg, boolean sel) {
        pFill.setColor(bg);
        c.drawRoundRect(r, 10, 10, pFill);
        pStroke.setStyle(Paint.Style.STROKE);
        pStroke.setStrokeWidth(sel ? 4 : 2);
        pStroke.setColor(sel ? C_SEL : 0xFF8A7A5E);
        c.drawRoundRect(r, 10, 10, pStroke);
        pFill.setStyle(Paint.Style.FILL);
        pText.setColor(Color.WHITE);
        pText.setTextSize(20);
        c.drawText(ellipsize(title, r.width() - 12), r.left + 6, r.top + 24, pText);
        pText.setTextSize(26);
        pText.setColor(C_GOLD);
        c.drawText(stat, r.left + 8, r.bottom - 10, pText);
    }

    private String ellipsize(String s, float maxW) {
        if (pText.measureText(s) <= maxW) return s;
        while (s.length() > 1 && pText.measureText(s + "…") > maxW) {
            s = s.substring(0, s.length() - 1);
        }
        return s + "…";
    }

    private void text(Canvas c, String s, float x, float y, int color) {
        pText.setTextSize(30);
        pText.setColor(color);
        c.drawText(s, x, y, pText);
    }

    private void button(Canvas c, RectF r, String label, int bg) {
        pFill.setColor(bg);
        c.drawRoundRect(r, 12, 12, pFill);
        pText.setTextSize(26);
        pText.setColor(Color.WHITE);
        c.drawText(label, r.centerX() - pText.measureText(label) / 2,
                r.centerY() + 9, pText);
    }

    private List<Unit> front(Player p) {
        List<Unit> l = new ArrayList<>();
        for (Unit u : p.board) if ("前线".equals(u.position)) l.add(u);
        return l;
    }

    private List<Unit> rear(Player p) {
        List<Unit> l = new ArrayList<>();
        for (Unit u : p.board) if (!"前线".equals(u.position)) l.add(u);
        return l;
    }

    private String foeInfo(Player foe) {
        return "敌方 " + foe.name + "(" + foe.nation + ")  HQ " + foe.hq
                + "  手牌 " + foe.hand.size() + "  指挥点 " + foe.kredits
                + "  反制 " + foe.counters.size();
    }

    private String myInfo(Player me) {
        return me.name + "(" + me.nation + ")  HQ " + me.hq + "  指挥点 "
                + me.kredits + "/" + me.cpSlots + "（槽）  牌库 " + me.deck.size();
    }

    private int frontOwnerColor() {
        Player o = g.frontlineOwner();
        if (o == null) return Color.DKGRAY;
        return o == g.players[0] ? C_GREEN : C_RED;
    }

    private String frontlineLabel() {
        Player o = g.frontlineOwner();
        if (o == null) return "前线：无人占领";
        return "前线：" + (o == g.players[0] ? "我方" : "敌方") + "占领";
    }

    private void flash(String msg) {
        message = msg;
        messageUntil = System.currentTimeMillis() + 2200;
    }

    // ---------------- 交互 ----------------
    @Override
    public boolean onTouchEvent(MotionEvent ev) {
        if (ev.getAction() != MotionEvent.ACTION_DOWN) return true;
        float x = ev.getX(), y = ev.getY();
        Player me = g.players[0], foe = g.players[1];

        if (g.over) {
            gameOver();                     // 联机对局结束后点击 → 回大厅
            return true;
        }
        if (concedeBtn != null && concedeBtn.contains(x, y)) {
            if (net != null && myTurn()) {
                net.sendConcede();
                g.conceded = me;            // 我方举旗
                g.over = true;
                gameOver();
            }
            return true;
        }

        if (!myTurn()) return true;         // 联机等待对手 / 单机 AI 行动中
        if (endBtn != null && endBtn.contains(x, y)) {
            endMyTurn();
            return true;
        }
        if (moveBtn != null && moveBtn.contains(x, y)) {
            if (selected != null) {
                String dest = "后方".equals(selected.position) ? "前线" : "后方";
                if (g.moveUnit(selected, dest)) {
                    if (net != null) net.sendAct(NetLink.act("move",
                            "s", selected.slot, "p", dest));
                } else {
                    flash("无法移动");
                }
            }
            return true;
        }
        // 手牌
        for (int i = 0; i < handRects.size() && i < me.hand.size(); i++) {
            if (handRects.get(i).contains(x, y)) {
                if (g.playCard(me, i)) {
                    selected = null;
                    if (net != null) net.sendAct(NetLink.act("play", "i", i));
                } else {
                    flash("出牌失败（费用/场地）");
                }
                return true;
            }
        }
        // 敌方单位 → 攻击
        for (Unit u : foe.board) {
            if (hitUnit(u, x, y)) {
                if (selected == null) { flash("先点选一个我方单位"); return true; }
                if (!g.unitReady(selected)) { flash("该单位本回合不能攻击"); return true; }
                if (!g.attackTargets(selected).contains(u)) { flash("不在攻击范围"); return true; }
                g.doAttack(selected, u);
                if (net != null) net.sendAct(NetLink.act("attack",
                        "s", selected.slot, "t", u.slot));
                selected = null;
                return true;
            }
        }
        // 敌方信息条区域 → 攻击总部
        if (selected != null && y < 60) {
            if (!g.canHitHq(selected)) { flash("该单位无法攻击总部"); return true; }
            if (!g.unitReady(selected)) { flash("该单位本回合不能攻击"); return true; }
            g.doHqAttack(selected);
            if (net != null) net.sendAct(NetLink.act("hq", "s", selected.slot));
            selected = null;
            return true;
        }
        // 我方单位 → 选中/取消
        for (Unit u : me.board) {
            if (hitUnit(u, x, y)) {
                selected = (selected == u) ? null : u;
                return true;
            }
        }
        return true;
    }

    private boolean hitUnit(Unit u, float x, float y) {
        // 与 drawRow 的布局保持一致：前线行偏移 cardW
        float cardW = Math.min(150, getWidth() / 6f - 12);
        float cardH = cardW * 0.62f;
        Player p = u.owner;
        boolean isFront = "前线".equals(u.position);
        int idx = (isFront ? front(p) : rear(p)).indexOf(u);
        float rowX = 30 + (isFront ? cardW : 0);
        float rowY;
        if (p == g.players[1]) {
            rowY = 60 + (isFront ? cardH + 14 : 0);
        } else {
            float hy = getHeight() - cardH - 18;
            rowY = hy - 44 - cardH - 14;          // 我方支援线
            if (isFront) rowY -= cardH + 14;      // 我方前线在其上
        }
        float ux = rowX + idx * (cardW + 8);
        return x >= ux && x <= ux + cardW && y >= rowY && y <= rowY + cardH;
    }

    private void endMyTurn() {
        selected = null;
        if (net != null) {
            // 联机：只翻自己的回合，等对手发回 end 再开启我方新回合
            net.sendAct(NetLink.act("end"));
            g.endTurn();
            if (g.over) gameOver();
            return;
        }
        g.endTurn();
        if (g.over) return;
        aiThinking = true;
        new Thread(() -> {
            try {
                g.startTurn();
                if (!g.over) g.aiTurn();
                if (!g.over) g.endTurn();
                if (!g.over) g.startTurn();       // 轮回玩家：开启我方新回合
            } finally {
                aiThinking = false;
                postInvalidate();
            }
        }).start();
    }
}
