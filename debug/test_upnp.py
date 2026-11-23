# -*- coding: utf-8 -*-
"""kards_upnp 回归测试（不依赖真实路由器、不依赖网络）

做法：起一个**假的 UPnP 网关**（本机 HTTP 服务），它提供
    GET  /rootDesc.xml    设备描述
    POST /ctl             SOAP 控制点
然后让 kards_upnp 直接连它，把「解析描述 → AddPortMapping →
GetExternalIPAddress → DeletePortMapping」整条链路跑一遍。

覆盖的真实坑：
  · controlURL 是相对路径（几乎所有路由器都是）
  · 718（端口已被占用）→ 删旧条目再重试
  · 725（只支持永久租约）→ 用 lease=0 重试
  · HTTP 500 + SOAP Fault 里的 errorCode 才是真原因
  · CGNAT（100.64/10）→ 映射成功也必须判失败
  · SOAP 参数里的 & < > " 必须转义

跑法：python debug/test_upnp.py
"""
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_upnp as up                                      # noqa: E402

PASS = 0
FAIL = []


def ok(name, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(f"{name} {extra}")


def eq(name, got, want):
    ok(name, got == want, f"→ 得到 {got!r}，期望 {want!r}")


# --------------------------------------------------------------- 假网关

DEVICE_XML = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <deviceType>urn:schemas-upnp-org:device:InternetGatewayDevice:1</deviceType>
    <deviceList><device><serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType>
        <controlURL>/ctl</controlURL>
      </service>
    </serviceList></device></deviceList>
  </device>
</root>
"""

NO_WAN_XML = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0"><device>
  <serviceList><service>
    <serviceType>urn:schemas-upnp-org:service:ContentDirectory:1</serviceType>
    <controlURL>/ctl</controlURL>
  </service></serviceList>
</device></root>
"""


class State:
    def __init__(self):
        self.mappings = {}
        self.external = "203.0.113.7"
        self.fault_718_once = False
        self.fault_725_first = False
        self.fault_501 = False
        self.actions = []
        self.last_body = ""


ST = State()


def _resp_xml(action, inner=""):
    svc = "urn:schemas-upnp-org:service:WANIPConnection:1"
    return (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/'
            f'soap/envelope/"><s:Body><u:{action}Response xmlns:u="{svc}">'
            f'{inner}</u:{action}Response></s:Body></s:Envelope>')


def _fault(code, desc="err"):
    return ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/'
            'soap/envelope/"><s:Body><s:Fault><faultcode>s:Client</faultcode>'
            '<faultstring>UPnPError</faultstring><detail>'
            '<UPnPError xmlns="urn:schemas-upnp-org:control-1-0">'
            f'<errorCode>{code}</errorCode><errorDescription>{desc}</errorDescription>'
            '</UPnPError></detail></s:Fault></s:Body></s:Envelope>')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", 'text/xml; charset="utf-8"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/rootDesc.xml":
            self._send(200, DEVICE_XML)
        elif self.path == "/nowan.xml":
            self._send(200, NO_WAN_XML)
        else:
            self._send(404, "")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8", "replace")
        ST.last_body = body
        action = ""
        soapaction = self.headers.get("SOAPACTION", "")
        if "#" in soapaction:
            action = soapaction.split("#")[-1].strip('"')
        ST.actions.append(action)

        if action == "AddPortMapping":
            if ST.fault_501:
                return self._send(500, _fault(501, "Action Failed"))
            if ST.fault_725_first:
                ST.fault_725_first = False
                if "<NewLeaseDuration>0</NewLeaseDuration>" not in body:
                    return self._send(500, _fault(725, "OnlyPermanentLeasesSupported"))
            if ST.fault_718_once:
                ST.fault_718_once = False
                return self._send(500, _fault(718, "ConflictInMappingEntry"))
            port = _field(body, "NewExternalPort")
            ST.mappings[port] = body
            return self._send(200, _resp_xml("AddPortMapping"))
        if action == "DeletePortMapping":
            ST.mappings.pop(_field(body, "NewExternalPort"), None)
            return self._send(200, _resp_xml("DeletePortMapping"))
        if action == "GetExternalIPAddress":
            if not ST.external:
                return self._send(500, _fault(501, "Action Failed"))
            return self._send(200, _resp_xml(
                "GetExternalIPAddress",
                f"<NewExternalIPAddress>{ST.external}</NewExternalIPAddress>"))
        return self._send(500, _fault(401, "Invalid Action"))


def _field(body, tag):
    s = body.find(f"<{tag}>")
    if s < 0:
        return ""
    s += len(tag) + 2
    e = body.find(f"</{tag}>", s)
    return body[s:e] if e >= 0 else ""


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


srv, PORT = serve()
BASE = f"http://127.0.0.1:{PORT}"
DESC = BASE + "/rootDesc.xml"


# ================================================================ 1. 描述解析

print("1. 设备描述解析")
gw = up.describe(DESC)
ok("1.1 解析出网关", gw is not None)
eq("1.2 服务类型", gw.service_type,
   "urn:schemas-upnp-org:service:WANIPConnection:1")
eq("1.3 相对 controlURL 补全", gw.control_url, BASE + "/ctl")
eq("1.4 网关主机", gw.host, "127.0.0.1")
ok("1.5 没有 WAN 服务的描述 → None",
   up.parse_description(NO_WAN_XML.encode(), BASE) is None)
ok("1.6 非法 XML → None", up.describe(BASE + "/nope.xml") is None)


# ================================================================ 2. URL 拼接

print("2. controlURL 拼接")
eq("2.1 绝对路径", up._urljoin("http://1.2.3.4:5000/rootDesc.xml", "/ctl"),
   "http://1.2.3.4:5000/ctl")
eq("2.2 相对路径", up._urljoin("http://1.2.3.4:5000/a/b/rootDesc.xml", "ctl"),
   "http://1.2.3.4:5000/a/b/ctl")
eq("2.3 已是绝对 URL", up._urljoin("http://1.2.3.4/x.xml", "http://9.9.9.9/c"),
   "http://9.9.9.9/c")
eq("2.4 带端口 + 无路径", up._urljoin("http://1.2.3.4:5000", "/ctl"),
   "http://1.2.3.4:5000/ctl")


# ================================================================ 3. SOAP

print("3. SOAP 调用")
good, text = up.add_mapping(gw, 6000, "192.168.1.5", 6000)
ok("3.1 AddPortMapping 成功", good, text)
ok("3.2 路由器收到了映射", "6000" in ST.mappings)
ok("3.3 内部客户端地址正确", "<NewInternalClient>192.168.1.5</NewInternalClient>" in ST.last_body)
ok("3.4 协议 TCP", "<NewProtocol>TCP</NewProtocol>" in ST.last_body)
eq("3.5 公网 IP", up.external_ip(gw), "203.0.113.7")

# 718：端口冲突 → 删旧条目再重试
ST.fault_718_once = True
ST.actions.clear()
good, err = up.add_mapping(gw, 6001, "192.168.1.5", 6001)
ok("3.6 718 冲突后重试成功", good, err)
eq("3.7 重试前确实删过", "DeletePortMapping" in ST.actions, True)

# 725：只支持永久租约
ST.fault_725_first = True
good, err = up.add_mapping(gw, 6002, "192.168.1.5", 6002, lease=3600)
ok("3.8 725 后改用永久租约成功", good, err)
eq("3.9 最终写入的是 lease=0", "<NewLeaseDuration>0</NewLeaseDuration>" in ST.last_body, True)

# 501：真失败
ST.fault_501 = True
good, err = up.add_mapping(gw, 6003, "192.168.1.5", 6003)
ok("3.10 501 判失败", not good)
ok("3.11 错误说明可读", "拒绝" in err or "501" in err, err)
ST.fault_501 = False

# 转义
good, _ = up.add_mapping(gw, 6004, "10.0.0.1", 6004, desc='A&B<C>"D"')
ok("3.12 参数转义", "A&amp;B&lt;C&gt;&quot;D&quot;" in ST.last_body)

# 删除
ok("3.13 DeletePortMapping", up.delete_mapping(gw, 6004))
ok("3.14 条目已删除", "6004" not in ST.mappings)


# ================================================================ 4. 私网判断

print("4. 私网 / CGNAT 判定")
for ip in ("10.1.2.3", "192.168.0.9", "172.16.5.5", "172.31.255.1",
           "127.0.0.1", "169.254.1.1", "100.64.0.1", "100.127.255.254", "0.0.0.0"):
    ok(f"4.x {ip} 是内网", up.is_private_ip(ip), ip)
for ip in ("203.0.113.7", "8.8.8.8", "1.1.1.1", "172.15.0.1", "172.32.0.1",
           "100.63.0.1", "100.128.0.1", "223.5.5.5"):
    ok(f"4.y {ip} 是公网", not up.is_private_ip(ip), ip)
ok("4.z 空串算内网", up.is_private_ip(""))


# ================================================================ 5. 高层 map_port

print("5. map_port 一条龙")
ST.mappings.clear()
st = up.map_port(6000, local_ip="192.168.1.5", gateway=gw)
ok("5.1 ok", st["ok"], st)
eq("5.2 公网 IP", st["external_ip"], "203.0.113.7")
eq("5.3 端口", st["port"], 6000)
eq("5.4 本机地址", st["local_ip"], "192.168.1.5")
ok("5.5 路由器里真的有这条", "6000" in ST.mappings)

# CGNAT：路由器 WAN 口是 100.64.x.x
ST.external = "100.72.5.9"
st = up.map_port(6000, local_ip="192.168.1.5", gateway=gw)
ok("5.6 CGNAT 判失败", not st["ok"])
ok("5.7 CGNAT 标记", st["cg_nat"])
eq("5.8 CGNAT 错误码", st["error"], "cgnat")
ok("5.9 需要手动处理", st["manual"])
ST.external = "203.0.113.7"

# 双重 NAT：路由器 WAN 口是 192.168.1.2（家里光猫也在路由）
ST.external = "192.168.1.2"
st = up.map_port(6000, local_ip="192.168.31.133", gateway=gw)
ok("5.9a 双重 NAT 判失败", not st["ok"], st)
ok("5.9b 标记 double_nat", st["double_nat"], st)
ok("5.9c 不误判成 CGNAT", not st["cg_nat"], st)
eq("5.9d 错误码", st["error"], "double_nat")
ST.external = "203.0.113.7"

# 没有网关
st = None
saved = up._first_gateway
up._first_gateway = lambda: None
st = up.map_port(6000)
up._first_gateway = saved
ok("5.10 无网关判失败", not st["ok"])
eq("5.11 无网关错误码", st["error"], "no_gateway")
ok("5.12 无网关要提示手动", st["manual"])

# 没有本机地址
st = up.map_port(6000, local_ip="", gateway=gw, )
ok("5.13 拿不到本机地址时不崩", isinstance(st, dict))

# 传入不存在的网关也不能抛异常
class Broken:
    service_type = "urn:x"
    control_url = "http://127.0.0.1:1/ctl"
    host = "127.0.0.1"


st = up.map_port(6000, local_ip="10.0.0.2", gateway=Broken())
ok("5.14 网关不可达 → 失败不抛", isinstance(st, dict) and not st["ok"], st)

# 本机直接持有公网地址（没有 NAT）：不该去找路由器，直接就能用
saved_gw = up._first_gateway
up._first_gateway = lambda: None
st = up.map_port(6000, local_ip="203.0.113.9")
up._first_gateway = saved_gw
ok("5.15 本机公网 IP 直接可用", st["ok"], st)
ok("5.16 标记为 direct", st["direct"], st)
eq("5.17 direct 的公网地址", st["external_ip"], "203.0.113.9")


# ================================================================ 6. SSDP 报文解析

print("6. SSDP 应答解析")
raw = (b"HTTP/1.1 200 OK\r\n"
       b"cache-control: max-age=120\r\n"
       b"location: http://192.168.1.1:1900/rootDesc.xml\r\n"
       b"ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n"
       b"USN: uuid:abc::urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n")
eq("6.1 大小写不敏感取 LOCATION", up._parse_ssdp(raw),
   "http://192.168.1.1:1900/rootDesc.xml")
eq("6.2 没有 LOCATION 返回空", up._parse_ssdp(b"HTTP/1.1 200 OK\r\nST: x\r\n\r\n"), "")
eq("6.3 四种 ST 报文都准备了", len(up._msearch_msgs()), len(up._SEARCH_TARGETS))


# ================================================================ 7. 环境变量覆盖

print("7. KARDS_UPNP_LOCATION 覆盖")
os.environ["KARDS_UPNP_LOCATION"] = DESC
gw2 = up._first_gateway()
ok("7.1 用环境变量里的描述", gw2 is not None and gw2.control_url == BASE + "/ctl")
del os.environ["KARDS_UPNP_LOCATION"]


# ================================================================ 7. 异步封装

print("8. map_port_async")
box = {}
# ⚠ 这里不能让它真的去 SSDP 扫本机路由器（会在真实路由器上开端口），
#   把"找网关"钉死成 None：只验证「后台线程 + 回调必达 + 不卡主线程」。
saved7 = up._first_gateway
up._first_gateway = lambda: None
try:
    t0 = time.time()
    t = up.map_port_async(6000, local_ip="192.168.1.5",
                          callback=lambda r: box.update(r))
    ok("8.0 调用立即返回（不阻塞）", time.time() - t0 < 0.2, time.time() - t0)
    t.join(timeout=15)
finally:
    up._first_gateway = saved7
ok("9.1 回调被调用", "ok" in box, box)
ok("9.2 回调带 port", box.get("port") == 6000, box)
ok("9.3 无网关时回调里是失败", box.get("error") == "no_gateway", box)

box2 = {}
saved = up._first_gateway
up._first_gateway = lambda: gw
t = up.map_port_async(6000, callback=lambda r: box2.update(r))
t.join(timeout=10)
up._first_gateway = saved
ok("7.3 走假网关时成功", box2.get("ok") is True, box2)
eq("7.4 回调里的公网 IP", box2.get("external_ip"), "203.0.113.7")


# ================================================================ 9. kards_host 封装

print("9. kards_host 封装（GUI 只读这个状态）")
import kards_host                                            # noqa: E402

saved_gw = up._first_gateway
up._first_gateway = lambda: gw
try:
    eq("9.1 初始状态 idle", kards_host.public_status()["state"], "idle")
    eq("9.2 没打通时 public_addr 为空", kards_host.public_addr(), "")
    kards_host.map_public_async(6000)
    eq("9.3 立刻是 working", kards_host.public_status()["state"], "working")
    deadline = time.time() + 15
    while (kards_host.public_status()["state"] == "working"
           and time.time() < deadline):
        time.sleep(0.05)
    st = kards_host.public_status()
    eq("9.4 完成后 state=done", st["state"], "done")
    ok("9.5 映射成功", st["ok"], st)
    eq("9.6 public_addr 可直接发给朋友", kards_host.public_addr(),
       "203.0.113.7:6000")
    ok("9.7 端口带出来", st["port"] == 6000, st)
finally:
    up._first_gateway = saved_gw

saved_gw = up._first_gateway
up._first_gateway = lambda: gw
try:
    kards_host.clear_public()
finally:
    up._first_gateway = saved_gw
eq("9.8 撤销后回到 idle", kards_host.public_status()["state"], "idle")
eq("9.9 撤销后 public_addr 为空", kards_host.public_addr(), "")


# ================================================================ 10. 清理

print("10. 解映射")
ok("9.1 unmap", up.unmap_port(6000, gateway=gw))
ok("9.2 条目消失", "6000" not in ST.mappings)

srv.shutdown()

# ================================================================ 结果

print()
if FAIL:
    print(f"❌ {len(FAIL)} 项失败：")
    for f in FAIL:
        print("   ·", f)
    sys.exit(1)
print(f"=== UPnP 全部通过（{PASS} 项）===")
