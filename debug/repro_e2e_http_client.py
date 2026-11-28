"""HTTP 路径的联机客户端包装：把 127.0.0.1 伪装成「云端主机」，
让 KARDS 走 HttpServerLink（HTTPS/HTTP 长轮询桥接）而不是 TCP。

用法：python repro_e2e_http_client.py <relay端口> <A|B>
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ["KARDS_DEBUG_WITHDRAW"] = "1"

port = sys.argv[1]
tag = sys.argv[2] if len(sys.argv) > 2 else "A"

import kards_net

kards_net.VT_HOST = "127.0.0.1"                     # 让本机地址被认作云端主机
kards_net.VT_URL = f"http://127.0.0.1:{port}"       # 指向本地桥接

sys.argv = ["KARDS.py"]
import KARDS

KARDS.run_debug_auto(f"127.0.0.1:{port}", tag)
