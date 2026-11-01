# -*- coding: utf-8 -*-
"""KARDS 简化版 · 自动打通「不同局域网」联机（UPnP / IGD 端口映射）

为什么需要这个模块
    联机是 TCP 直连（客户端 → 服务器），服务器默认监听 0.0.0.0，
    所以在**同一个局域网**里，别人拿 192.168.x.x:6000 就能连上。
    但换成外网（朋友在自己家）就连不进来了 —— 因为数据包到了你家的
    路由器就被拦下，路由器不知道要把它转给内网的哪台机器。

    主流家用路由器都支持 UPnP IGD（Internet Gateway Device）：
    局域网里的程序可以**自己**请求路由器开一个端口映射，不需要
    进路由器后台手动点。这个模块就干这件事，纯标准库实现：

        1. SSDP 组播发现网关（M-SEARCH → LOCATION）
        2. 取设备描述 XML，找到 WANIPConnection / WANPPPConnection 服务
        3. SOAP 调 AddPortMapping（TCP 外部端口 → 本机 IP:端口）
        4. SOAP 调 GetExternalIPAddress 拿公网 IP
        5. 退出游戏时 DeletePortMapping 收拾干净

失败是常态，不是异常
    路由器关着 UPnP、运营商给的是 100.64/10 大内网（CGNAT）、
    防火墙拦了……都会失败。所以所有函数都返回结果字典，
    **不抛异常**，由上层决定怎么提示玩家（见 kards_host.map_public_async）。

只用标准库：socket / urllib / xml.etree / threading。
"""

import re
import socket
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

SSDP_ADDR = ("239.255.255.250", 1900)
SSDP_MX = 2
DESC_TTL = 3.0                      # 设备描述 XML 的下载超时

# 想找的服务：WANIPConnection 最常见，WANPPPConnection 是 PPPoE 拨号型
WAN_SERVICES = (
    "urn:schemas-upnp-org:service:WANIPConnection:1",
    "urn:schemas-upnp-org:service:WANPPPConnection:1",
)

_SEARCH_TARGETS = (
    "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
    "urn:schemas-upnp-org:service:WANIPConnection:1",
    "urn:schemas-upnp-org:service:WANPPPConnection:1",
    "upnp:rootdevice",
)


class Gateway:
    """一个可用的网关（路由器）的 UPnP 控制点。"""

    def __init__(self, location, control_url, service_type, host=""):
        self.location = location
        self.control_url = control_url
        self.service_type = service_type
        self.host = host or _host_of(location)

    def __repr__(self):
        return f"<Gateway {self.host} {self.service_type.split(':')[-2]}>"


def _host_of(url):
    m = re.match(r"^[a-zA-Z]+://([^/:]+)", url or "")
    return m.group(1) if m else ""


# ------------------------------------------------------------------ SSDP 发现

def _msearch_msgs():
    """四种 ST 的搜索报文（有些路由器只应答其中一种）。"""
    return [(
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"MX: {SSDP_MX}\r\n"
        f"ST: {st}\r\n"
        "\r\n"
    ).encode("ascii") for st in _SEARCH_TARGETS]


def _parse_ssdp(data):
    """从一条 SSDP 应答里取 LOCATION（大小写不敏感）。"""
    head = {}
    text = data.decode("utf-8", "replace")
    for line in text.splitlines()[1:]:
        if ":" in line:
            k, _, v = line.partition(":")
            head[k.strip().upper()] = v.strip()
    return head.get("LOCATION", "")


def _local_ipv4s():
    """本机所有 IPv4 地址（去掉回环与链路本地）。

    为什么要枚举：开发机常装 VMware / Hyper-V / WSL，有 3~5 张虚拟网卡。
    组播只从"默认路由那张卡"发的话，虚拟网卡上收不到路由器的 SSDP 应答，
    表现为"家里路由器明明支持 UPnP 却找不到网关"。
    """
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    # 补一个「朝公网方向」的地址（多网卡时上面可能只返回一张）
    probe = local_ip_towards("8.8.8.8")
    if probe and probe not in ips:
        ips.append(probe)
    return [ip for ip in ips
            if not ip.startswith("127.") and not ip.startswith("169.254.")]


def discover(timeout=2.6):
    """SSDP 找网关，返回可用的 Gateway 列表（找不到返回 []）。

    ⚠ 四种 ST 的报文**在同一个 socket 上连发**，然后统一收 2.6 秒。
      早先按 ST 串行发送/等待，找一次要 8 秒以上，界面像卡死。
    ⚠ 每张网卡都要单独发（IP_MULTICAST_IF）：虚拟网卡会把组播吞掉。
    """
    seen = {}
    deadline = time.time() + timeout
    for ip in (_local_ipv4s() or [""]):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            if ip:
                try:
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                                 socket.inet_aton(ip))
                except OSError:
                    pass
                s.bind((ip, 0))
            else:
                s.bind(("", 0))
            s.settimeout(0.8)
            for msg in _msearch_msgs():
                try:
                    s.sendto(msg, SSDP_ADDR)
                except OSError:
                    pass
            while time.time() < deadline:
                try:
                    data, addr = s.recvfrom(4096)
                except socket.timeout:
                    break        # 这张卡没戏了，换下一张
                except OSError:
                    break
                loc = _parse_ssdp(data)
                if loc:
                    seen.setdefault(loc, addr[0])
        finally:
            try:
                s.close()
            except OSError:
                pass

    # ⚠ 不能用「有应答就收工」当结束条件：局域网里还有一堆非网关设备
    #   （电视盒子、投屏、NAS）照样会回 SSDP，它们没有 WAN 服务。
    #   必须把所有网卡的应答都收齐，再靠 describe() 筛出真正带
    #   WANIPConnection 的那台 —— 否则虚拟网卡先回一堆垃圾，
    #   真实路由器连被问到都没轮到（实测踩过）。

    if not seen:
        return []

    # 多个 LOCATION 并行解析（每个最多 3 秒，串行会叠成十几秒）
    gateways = []
    lock = threading.Lock()
    threads = []

    def fetch(loc, ip):
        gw = describe(loc)
        if gw is None:
            return
        gw.host = ip or gw.host
        with lock:
            gateways.append(gw)

    for loc, ip in list(seen.items())[:6]:      # 上限 6 个，防异常网络刷屏
        t = threading.Thread(target=fetch, args=(loc, ip), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=DESC_TTL + 0.5)

    # WANIPConnection 优先（PPP 型网关对 AddPortMapping 的参数更挑剔）
    gateways.sort(key=lambda g: 0 if "WANIPConnection" in g.service_type else 1)
    return gateways


# ------------------------------------------------------------ 设备描述解析

def describe(location, timeout=DESC_TTL):
    """下载并解析设备描述，返回 Gateway 或 None。"""
    xml = _http_get(location, timeout=timeout)
    if not xml:
        return None
    return parse_description(xml, location)


def _local(tag):
    """去掉 ElementTree 的 {namespace} 前缀。

    ⚠ 设备描述一定带默认命名空间（urn:schemas-upnp-org:device-1-0），
      ET 会把标签变成 "{urn:...}serviceType"，`findtext("serviceType")`
      直接返回 None —— 表现为"所有路由器都不支持 UPnP"，非常难查。
    """
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(elem, name):
    for ch in elem:
        if _local(ch.tag) == name:
            return (ch.text or "").strip()
    return ""


def parse_description(xml_bytes, base_url):
    """从设备描述 XML 里挑出 WAN 连接服务（单独抽出以便测试）。"""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    candidates = []
    for svc in root.iter():
        if _local(svc.tag) != "service":
            continue
        stype = _child_text(svc, "serviceType")
        ctrl = _child_text(svc, "controlURL")
        if not ctrl or not stype:
            continue
        # 版本号不锁死：WANIPConnection:1 与 :2 的 AddPortMapping 参数一致
        if "WANIPConnection" in stype or "WANPPPConnection" in stype:
            candidates.append((stype, ctrl))
    if not candidates:
        return None

    candidates.sort(key=lambda c: 0 if "WANIPConnection" in c[0] else 1)
    stype, ctrl = candidates[0]
    # controlURL 可能是相对路径（绝大多数路由器都是 /upnp/control/WANIPConn1）
    url = _urljoin(base_url, ctrl)
    return Gateway(base_url, url, stype, _host_of(base_url))


def _urljoin(base, ref):
    if re.match(r"^[a-zA-Z]+://", ref or ""):
        return ref
    m = re.match(r"^([a-zA-Z]+://[^/]+)(/.*)?$", base or "")
    if not m:
        return ref
    origin = m.group(1)
    if ref.startswith("/"):
        return origin + ref
    root = (m.group(2) or "/")
    root = root.rsplit("/", 1)[0] + "/"
    return origin + root + ref


def _opener():
    """UPnP 只走局域网，**必须绕过系统代理**。

    ⚠ 踩过的坑：机器上一旦有 http_proxy（公司/代理软件很常见），
      urllib 会把 http://192.168.x.x:5000/rootDesc.xml 也发给代理，
      拿到 403/超时 → UPnP 永远失败，而且报错看起来像"路由器不支持"。
    """
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http_get(url, timeout=DESC_TTL):
    req = urllib.request.Request(url, headers={"User-Agent": "KARDS/UPnP"})
    try:
        with _opener().open(req, timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, OSError, ValueError):
        return None


# ------------------------------------------------------------------ SOAP 调用

_SOAP_TMPL = (
    '<?xml version="1.0"?>\n'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
    's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
    "<s:Body><u:{action} xmlns:u=\"{service}\">{args}</u:{action}></s:Body>"
    "</s:Envelope>"
)


def _esc(v):
    return (str(v).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def soap(gw, action, args=None, timeout=4.0):
    """调一个 UPnP 动作，返回 (ok, 响应XML文本 或 错误码字符串)。

    SOAP 出错时路由器返回 HTTP 500 + Fault XML，里面 <errorCode> 是
    真正的原因（718=端口已被占用、725=只支持永久租约、714=条目不存在）。
    """
    body_args = "".join(f"<{k}>{_esc(v)}</{k}>" for k, v in (args or {}).items())
    body = _SOAP_TMPL.format(action=action, service=gw.service_type, args=body_args)
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPACTION": f'"{gw.service_type}#{action}"',
        "Connection": "close",
    }
    req = urllib.request.Request(gw.control_url, data=body.encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with _opener().open(req, timeout=timeout) as r:
            return True, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        text = ""
        try:
            text = e.read().decode("utf-8", "replace")
        except OSError:
            pass
        return False, _fault_code(text) or f"HTTP {e.code}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, f"{type(e).__name__}: {e}"


def _fault_code(text):
    m = re.search(r"<errorCode>\s*(\d+)\s*</errorCode>", text or "")
    return m.group(1) if m else ""


def _tag_value(text, tag):
    m = re.search(rf"<{tag}>\s*([^<]*?)\s*</{tag}>", text or "")
    return m.group(1) if m else ""


# ------------------------------------------------------------------ 具体动作

def add_mapping(gw, ext_port, int_ip, int_port, proto="TCP",
                desc="KARDS", lease=0, timeout=4.0):
    """请求路由器开映射，返回 (ok, 错误说明)。

    处理两种常见的「其实已经成功」的错误：
      718 ConflictInMappingEntry → 先删掉旧条目再重试（上次没退干净）
      725 OnlyPermanentLeasesSupported → 用租约 0（永久）重试
    """
    def call(le):
        args = {
            "NewRemoteHost": "",
            "NewExternalPort": ext_port,
            "NewProtocol": proto,
            "NewInternalPort": int_port,
            "NewInternalClient": int_ip,
            "NewEnabled": 1,
            "NewPortMappingDescription": desc,
            "NewLeaseDuration": le,
        }
        return soap(gw, "AddPortMapping", args, timeout=timeout)

    ok, msg = call(lease)
    if ok:
        return True, ""
    if msg == "725" and lease != 0:
        ok, msg = call(0)
        return (True, "") if ok else (False, _explain(msg))
    if msg == "718":
        delete_mapping(gw, ext_port, proto, timeout=timeout)
        ok, msg = call(lease)
        if ok:
            return True, ""
    return False, _explain(msg)


def delete_mapping(gw, ext_port, proto="TCP", timeout=3.0):
    ok, _ = soap(gw, "DeletePortMapping", {
        "NewRemoteHost": "",
        "NewExternalPort": ext_port,
        "NewProtocol": proto,
    }, timeout=timeout)
    return ok


def external_ip(gw, timeout=4.0):
    """取路由器 WAN 口地址（就是别人要连的公网 IP）。失败返回 ""。"""
    ok, text = soap(gw, "GetExternalIPAddress", {}, timeout=timeout)
    if not ok:
        return ""
    return _tag_value(text, "NewExternalIPAddress")


def _explain(code):
    text = str(code)
    if text == "714":
        return "路由器没有这条端口映射"
    if text == "718":
        return "端口已被其他程序占用（路由器里已有同端口映射）"
    if text == "724":
        return "路由器不允许映射到本机地址"
    if text in ("401", "402", "403", "501"):
        return f"路由器拒绝该操作（错误码 {text}）"
    return text or "未知错误"


# ---------------------------------------------------------------- 私网地址判断

def is_cgnat(ip):
    """是不是运营商大内网（100.64.0.0/10）。

    和普通私网要分开：普通私网说明**上面还有一台自己家的路由/光猫**
    （做双层映射就能通），CGNAT 则是运营商那边，家里怎么配都通不了。
    """
    parts = (ip or "").split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return a == 100 and 64 <= b <= 127


def is_private_ip(ip):
    """是否是内网 / 回环 / 共享地址（含运营商 CGNAT 的 100.64/10）。

    ⚠ CGNAT（100.64.0.0/10）必须单独认出来：路由器 WAN 口拿到这种地址
      说明你在运营商的大内网里，**做端口映射也没用** —— 外网根本到不了
      这个地址。这种情况只能换方案（公网服务器 / 内网穿透）。
    """
    if not ip:
        return True
    if ":" in ip:                    # IPv6 不在此判断范围
        return False
    parts = (ip or "").split(".")
    if len(parts) != 4:
        return True
    try:
        a, b, c, d = (int(x) for x in parts)
    except ValueError:
        return True
    if a == 10:                              # 10/8
        return True
    if a == 172 and 16 <= b <= 31:           # 172.16/12
        return True
    if a == 192 and b == 168:                # 192.168/16
        return True
    if a == 100 and 64 <= b <= 127:          # 100.64/10 CGNAT
        return True
    if a == 127:                             # 回环
        return True
    if a == 169 and b == 254:                # 链路本地
        return True
    if a == 0:
        return True
    return False


def local_ip_towards(host):
    """本机通向 host 的那张网卡的 IP（用于填 NewInternalClient）。"""
    if not host:
        return ""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, 1900))
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        try:
            s.close()
        except OSError:
            pass


# ------------------------------------------------------------------ 高层入口

# 上一次成功用过的网关：退出游戏时撤销映射直接复用它，
# 免得为了删一条映射又花 2 秒重新 SSDP 发现（退出会明显变慢）。
_LAST_GW = None


def map_port(port, local_ip="", gateway=None, proto="TCP", timeout=4.0):
    """一条龙：找网关 → 开映射 → 取公网 IP。

    返回字典（**永远不抛异常**）：
        {"ok": bool, "external_ip": str, "port": int, "local_ip": str,
         "gateway": str, "error": str, "cg_nat": bool, "manual": bool,
         "direct": bool}
    """
    res = {"ok": False, "external_ip": "", "port": int(port), "local_ip": "",
           "gateway": "", "error": "", "cg_nat": False, "double_nat": False,
           "manual": False, "direct": False}

    gw = gateway or _first_gateway()
    # 拿本机地址：有网关就问网关，没有就朝公网方向看一眼
    ip = local_ip or local_ip_towards(gw.host if gw else "8.8.8.8")
    res["local_ip"] = ip or ""
    if gw is not None:
        res["gateway"] = gw.host

    # 情况一：这台机器本来就拿着公网地址（没有 NAT）→ 不需要映射
    if ip and not is_private_ip(ip):
        res.update(ok=True, external_ip=ip, direct=True)
        return res

    if gw is None:
        res["error"] = "no_gateway"
        res["manual"] = True
        return res
    if not ip:
        res["error"] = "no_local_ip"
        res["manual"] = True
        return res

    ok, err = add_mapping(gw, port, ip, port, proto=proto, timeout=timeout)
    if not ok:
        res["error"] = err
        res["manual"] = True
        return res

    global _LAST_GW
    _LAST_GW = gw                     # 记住用它，撤销时不用再发现一遍
    res["ok"] = True
    ext = external_ip(gw, timeout=timeout)
    res["external_ip"] = ext
    if ext and is_private_ip(ext):
        # 路由器的 WAN 口也是私网地址 → 路径断在上一层
        res["ok"] = False
        res["manual"] = True
        if is_cgnat(ext):
            res["cg_nat"] = True
            res["error"] = "cgnat"
        else:
            # 自家光猫/上级路由也开了路由（双重 NAT）：两层都映射就还能通
            res["double_nat"] = True
            res["error"] = "double_nat"
    return res


def _first_gateway():
    forced = _forced_location()
    if forced:
        return describe(forced)
    gws = discover()
    return gws[0] if gws else None


def _forced_location():
    """调试/测试用：KARDS_UPNP_LOCATION 直接指定设备描述地址，跳过 SSDP。"""
    import os
    return os.environ.get("KARDS_UPNP_LOCATION", "").strip()


def unmap_port(port, gateway=None, proto="TCP"):
    """关掉我们开的映射（游戏退出时调用，别在路由器里留垃圾）。"""
    gw = gateway or _LAST_GW or _first_gateway()
    if gw is None:
        return False
    return delete_mapping(gw, port, proto)


def map_port_async(port, local_ip="", callback=None, proto="TCP", timeout=4.0):
    """后台执行 map_port（GUI 主线程不能卡 5~8 秒）。

    callback(result) 在**工作线程**里调用 —— GUI 侧记得用 after 切回主线程。
    """
    def run():
        try:
            res = map_port(port, local_ip=local_ip, proto=proto, timeout=timeout)
        except Exception as e:                       # noqa: BLE001 兜底
            res = {"ok": False, "external_ip": "", "port": int(port),
                   "local_ip": "", "gateway": "", "error": f"{type(e).__name__}: {e}",
                   "cg_nat": False, "double_nat": False, "manual": True}
        if callback is not None:
            try:
                callback(res)
            except Exception:
                pass

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t
