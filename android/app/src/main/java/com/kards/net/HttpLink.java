package com.kards.net;

import com.kards.engine.MiniJson;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/** 云端默认服务器：HTTPS 长轮询桥接（对齐 kards_net.HttpServerLink）。
 *
 *  服务器侧为每个会话保持一条真 TCP 连接：
 *    POST /c            → {sid}  创建会话
 *    POST /s {sid,d}    → 上行（d 为若干行 JSON 文本）
 *    GET  /p?sid&wait   → 长轮询下行 {m:[msgs]}
 *    POST /x {sid}      → 关闭
 */
public final class HttpLink extends NetLink {
    public static final int POLL_WAIT = 20;          // 长轮询挂起秒数
    public static final int HEARTBEAT_MS = 25000;    // 上行静默多久补一次 ping
    private static final int MAX_POLL_ERR = 3;

    private final String origin;
    private final String share;      // 平台分享链接的固定门牌（sharecode），缺了会 403
    private final String sid;
    private final LinkedBlockingQueue<String> upQueue = new LinkedBlockingQueue<>();
    private volatile boolean closedByUs = false;

    public HttpLink(String baseUrl) throws IOException {
        int q = baseUrl.indexOf('?');
        origin = (q >= 0 ? baseUrl.substring(0, q) : baseUrl).replaceAll("/+$", "");
        share = q >= 0 ? baseUrl.substring(q + 1) : "";
        Map<String, Object> r = httpReq("/c", null, 12000);
        sid = MiniJson.str(r, "sid");
        if (sid.isEmpty()) throw new IOException("云端服务器创建会话失败");
        Thread up = new Thread(this::upLoop, "kards-up");
        up.setDaemon(true);
        up.start();
        Thread down = new Thread(this::downLoop, "kards-down");
        down.setDaemon(true);
        down.start();
    }

    private String url(String path) {
        return origin + path
                + (share.isEmpty() ? "" : (path.contains("?") ? "&" : "?") + share);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> httpReq(String path, String payloadJson, int timeoutMs)
            throws IOException {
        HttpURLConnection conn = (HttpURLConnection) new URL(url(path)).openConnection();
        conn.setConnectTimeout(timeoutMs);
        conn.setReadTimeout(timeoutMs);
        if (payloadJson != null) {
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/json");
            byte[] d = payloadJson.getBytes("UTF-8");
            conn.setFixedLengthStreamingMode(d.length);
            OutputStream os = conn.getOutputStream();
            os.write(d);
            os.flush();
            os.close();
        }
        int code = conn.getResponseCode();
        InputStream is = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while (is != null && (n = is.read(buf)) > 0) bos.write(buf, 0, n);
        if (is != null) is.close();
        conn.disconnect();
        try {
            Object o = MiniJson.parse(bos.toString("UTF-8"));
            return o instanceof Map ? (Map<String, Object>) o : new LinkedHashMap<>();
        } catch (Exception e) {
            return new LinkedHashMap<>();
        }
    }

    private void upLoop() {
        long lastUp = System.currentTimeMillis();
        while (alive) {
            try {
                StringBuilder sb = new StringBuilder();
                String line;
                while (sb.length() < 60000
                        && (line = upQueue.poll(1, TimeUnit.SECONDS)) != null) {
                    sb.append(line).append('\n');
                }
                if (sb.length() > 0) {
                    Map<String, Object> req = new LinkedHashMap<>();
                    req.put("sid", sid);
                    req.put("d", sb.toString());
                    httpReq("/s", MiniJson.write(req), 30000);
                    lastUp = System.currentTimeMillis();
                } else if (alive
                        && System.currentTimeMillis() - lastUp > HEARTBEAT_MS) {
                    httpReq("/s", MiniJson.write(NetLink.msg("ping")), 30000);
                    lastUp = System.currentTimeMillis();
                }
            } catch (Exception e) {
                if (!alive) return;
                // 瞬时网络抖动：靠下行泵的失败计数判掉线，这里继续重试
            }
        }
    }

    private void downLoop() {
        int errs = 0;
        while (alive) {
            Map<String, Object> r;
            try {
                r = httpReq("/p?sid=" + sid + "&w=" + POLL_WAIT, null,
                        (POLL_WAIT + 15) * 1000);
                errs = 0;
            } catch (Exception e) {
                if (!alive) return;
                if (++errs >= MAX_POLL_ERR) break;
                try { Thread.sleep(1500); } catch (InterruptedException ie) { return; }
                continue;
            }
            if (!alive) return;
            if (MiniJson.bool(r.get("gone"))) break;
            for (Object o : MiniJson.arr(r.get("m"))) {
                if (o instanceof Map) {
                    @SuppressWarnings("unchecked")
                    Map<String, Object> msg = (Map<String, Object>) o;
                    dispatch(msg);
                }
            }
        }
        dead("云端连接已断开");
    }

    @Override
    protected void rawSend(byte[] data) {
        // NetLink 传入的是 "json\n"：去掉换行存成行，由上行泵拼批 POST /s
        String s = new String(data, java.nio.charset.StandardCharsets.UTF_8).trim();
        upQueue.add(s);
    }

    @Override
    public void close() {
        boolean wasAlive = alive;
        alive = false;
        closedByUs = true;
        if (wasAlive) {
            try {
                httpReq("/x", MiniJson.write(NetLink.msg("sid", sid)), 3000);
            } catch (Exception ignored) {
            }
            dead("连接已关闭");
        }
    }
}
