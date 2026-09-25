# -*- coding: utf-8 -*-
"""
KARDS 联机模块：局域网 TCP 直连（主机 / 加入）+ 行动同步通道。

同步模型（锁定步 lockstep）：
  双方各自运行一份完全相同的对局状态，网络上只交换「行动指令」
  （出牌 / 攻击 / 机动 / 结束回合 / 投降）。开局时由主机生成随机
  种子发给对方，双方用同一种子 + 相同的行动序列保证抽牌与随机
  效果完全一致。

消息格式：换行分隔的 JSON（UTF-8）。
"""

import json
import queue
import socket
import threading


class NetLink:
    """一条已建立的 TCP 连接：后台线程收包入队，send() 线程安全。"""

    def __init__(self, sock, addr=None):
        self.sock = sock
        self.addr = addr
        self.inbox = queue.Queue()
        self.alive = True
        self._buf = b""
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _recv_loop(self):
        try:
            while self.alive:
                data = self.sock.recv(4096)
                if not data:
                    break
                self._buf += data
                while b"\n" in self._buf:
                    line, self._buf = self._buf.split(b"\n", 1)
                    if line.strip():
                        try:
                            self.inbox.put(json.loads(line.decode("utf-8")))
                        except (ValueError, UnicodeDecodeError):
                            pass  # 坏包直接丢弃，不让连接崩掉
        except OSError:
            pass
        finally:
            self.close()

    def send(self, obj):
        if not self.alive:
            return False
        try:
            payload = json.dumps(obj, ensure_ascii=False) + "\n"
            self.sock.sendall(payload.encode("utf-8"))
            return True
        except OSError:
            self.close()
            return False

    def close(self):
        if not self.alive:
            return
        self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class Acceptor:
    """主机端：后台监听指定端口，等待对手连接。

    用法：
        acc = Acceptor(5555)
        ...轮询 acc.result...
        acc.result == (NetLink,)          连接成功
        acc.result == ("err", "原因")     出错
        acc.cancel()                      取消等待
    """

    def __init__(self, port):
        self.result = None
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("", port))
        self._srv.listen(1)
        self._srv.settimeout(0.5)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while self.result is None:
            try:
                sock, addr = self._srv.accept()
                self.result = (NetLink(sock, addr),)
                return
            except socket.timeout:
                continue
            except OSError as e:
                self.result = ("err", str(e))
                return

    def cancel(self):
        try:
            self._srv.close()
        except OSError:
            pass
        if self.result is None:
            self.result = ("err", "已取消")


def connect_async(ip, port, holder):
    """客户端：后台连接 ip:port，结果写入 holder["result"]。

    成功：holder["result"] = (NetLink,)
    失败：holder["result"] = ("err", "原因")
    """
    def run():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(6)
        try:
            sock.connect((ip, port))
            sock.settimeout(None)
            holder["result"] = (NetLink(sock, (ip, port)),)
        except OSError as e:
            try:
                sock.close()
            except OSError:
                pass
            holder["result"] = ("err", str(e))
    threading.Thread(target=run, daemon=True).start()


def get_local_ips():
    """返回本机在局域网中的 IP 列表（用于告诉对手连接地址）。"""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    if not ips:
        try:
            ips.append(socket.gethostbyname(socket.gethostname()))
        except OSError:
            pass
    return ips or ["127.0.0.1"]
