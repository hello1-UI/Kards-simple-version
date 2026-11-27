package com.kards.net;

import com.kards.engine.MiniJson;

import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/** 与 kards_server 的长连接基类（对齐 kards_net.ServerLink 语义）。
 *
 *  协议：换行分隔的 JSON，每行一个消息；信封字段一律用 "m"。
 *  （⚠ 不能用 "t" —— 行动指令里 "t" 是攻击目标槽位，会被覆盖，历史 bug。）
 *
 *  应答配对与 Python 端一致：
 *   · 服务器握手类应答（auth_ok/auth_err/matched/…）**不回显 id**，
 *     用「命令 → 应答类型映射」等待（request(obj, expectTypes...)）。
 */
public abstract class NetLink {
    public interface Listener {
        /** 非应答推送事件（ready/seed/act/concede/matched/peer_left/…） */
        void onEvent(Map<String, Object> msg);

        /** 连接断开（只回调一次） */
        void onDead(String reason);
    }

    public volatile boolean alive = true;
    private volatile Listener listener;
    private final CopyOnWriteArrayList<ReplyWait> waits = new CopyOnWriteArrayList<>();

    private static final class ReplyWait {
        final Set<String> types;
        final LinkedBlockingQueue<Map<String, Object>> q = new LinkedBlockingQueue<>();

        ReplyWait(Set<String> t) { types = t; }
    }

    public void setListener(Listener l) { listener = l; }

    public boolean send(Map<String, Object> obj) {
        if (!alive) return false;
        try {
            byte[] data = (MiniJson.write(obj) + "\n").getBytes("UTF-8");
            synchronized (this) {
                rawSend(data);
            }
            return true;
        } catch (Exception e) {
            close();
            return false;
        }
    }

    /** 发请求并按应答 "m" 类型等待。超时/断线返回 null。 */
    public Map<String, Object> request(Map<String, Object> obj, String... expectTypes) {
        if (!alive) return null;
        ReplyWait w = new ReplyWait(new HashSet<>(Arrays.asList(expectTypes)));
        waits.add(w);
        if (!send(obj)) {
            waits.remove(w);
            return null;
        }
        try {
            return w.q.poll(8, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            return null;
        } finally {
            waits.remove(w);
        }
    }

    /** 便捷构造：{"m": type, ...} */
    public static Map<String, Object> msg(String type, Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("m", type);
        for (int i = 0; i + 1 < kv.length; i += 2) {
            m.put(String.valueOf(kv[i]), kv[i + 1]);
        }
        return m;
    }

    /** 便捷构造对局行动：{k: kind, ...}（"m":"act" 信封由 sendAct 统一加）。 */
    public static Map<String, Object> act(String k, Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("k", k);
        for (int i = 0; i + 1 < kv.length; i += 2) {
            m.put(String.valueOf(kv[i]), kv[i + 1]);
        }
        return m;
    }

    /** TCP 文本流入口：按行拆包后逐条 dispatch（HTTP 通路不走这里）。 */
    protected void feed(String chunk) {
        dispatchLines(chunk, null);
    }

    /** 按 \n 拆行并 dispatch；restBuf 传 null 表示内部缓冲（TCP 用）。 */
    private final StringBuilder lineBuf = new StringBuilder();

    protected void dispatchLines(String chunk, StringBuilder restBuf) {
        lineBuf.append(chunk);
        int idx;
        while ((idx = lineBuf.indexOf("\n")) >= 0) {
            String line = lineBuf.substring(0, idx).trim();
            lineBuf.delete(0, idx + 1);
            if (line.isEmpty()) continue;
            try {
                Object o = MiniJson.parse(line);
                if (o instanceof Map) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> msg = (Map<String, Object>) o;
                    dispatch(msg);
                }
            } catch (Exception ignored) {
                // 坏包直接丢弃，不让连接崩掉（对齐 Python 端）
            }
        }
    }

    protected void dispatch(Map<String, Object> obj) {
        String m = MiniJson.str(obj, "m");
        // 保活：服务器在自身收包超时会发 ping，客户端必须 pong
        if ("ping".equals(m)) {
            Map<String, Object> pong = new LinkedHashMap<>();
            pong.put("m", "pong");
            send(pong);
            return;
        }
        for (ReplyWait w : waits) {
            if (w.types.contains(m) && waits.remove(w)) {
                w.q.add(obj);
                return;
            }
        }
        Listener l = listener;
        if (l != null) l.onEvent(obj);
    }

    protected abstract void rawSend(byte[] data) throws Exception;

    public abstract void close();

    protected void dead(String reason) {
        if (!alive) return;
        alive = false;
        Listener l = listener;
        if (l != null) l.onDead(reason);
    }
}
