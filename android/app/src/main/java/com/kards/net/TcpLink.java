package com.kards.net;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;

/** 局域网/自架服务器：TCP 长连接（对齐 kards_net.ServerLink 的 socket 通路）。 */
public final class TcpLink extends NetLink {
    private final Socket sock;
    private final OutputStream out;

    public TcpLink(String host, int port, int connectTimeoutMs) throws IOException {
        sock = new Socket();
        sock.connect(new InetSocketAddress(host, port), connectTimeoutMs);
        sock.setTcpNoDelay(true);
        out = sock.getOutputStream();
        Thread t = new Thread(this::readLoop, "kards-tcp");
        t.setDaemon(true);
        t.start();
    }

    private void readLoop() {
        try {
            InputStream in = sock.getInputStream();
            byte[] buf = new byte[8192];
            while (alive) {
                int n = in.read(buf);
                if (n < 0) break;
                feed(new String(buf, 0, n, "UTF-8"));
            }
        } catch (IOException ignored) {
            // 落到下面的 dead()
        }
        dead("与服务器的连接已断开");
    }

    @Override
    protected void rawSend(byte[] data) throws IOException {
        out.write(data);
        out.flush();
    }

    @Override
    public void close() {
        boolean wasAlive = alive;
        alive = false;
        try {
            sock.close();
        } catch (IOException ignored) {
        }
        if (wasAlive) dead("连接已关闭");
    }
}
