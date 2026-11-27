package com.kards.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.widget.Toast;

import com.kards.engine.CardDb;
import com.kards.engine.CardDef;
import com.kards.engine.Game;
import com.kards.engine.Player;

import java.io.IOException;
import java.util.List;

/** KARDS Java 版入口：选国家 → 开局（玩家 vs AI）。 */
public class MainActivity extends Activity {
    private CardDb db;
    private BoardView board;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            db = CardDb.fromStream(getAssets().open("cards.json"));
        } catch (IOException e) {
            Toast.makeText(this, "卡牌数据加载失败: " + e.getMessage(),
                    Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        pickNations();
    }

    private void pickNations() {
        final List<String> nations = db.rules.mainNations;
        String[] names = nations.toArray(new String[0]);
        new AlertDialog.Builder(this)
                .setTitle("选择你的国家")
                .setItems(names, (dlg, which) -> startGame(nations.get(which)))
                .setCancelable(false)
                .show();
    }

    private void startGame(String myNation) {
        // 对手随机一个不同的主国
        List<String> pool = new java.util.ArrayList<>(db.rules.mainNations);
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
}
