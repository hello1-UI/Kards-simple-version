# -*- coding: utf-8 -*-
"""kards_hall.py 走动大厅逻辑测试（SDL dummy，无真实窗口）

覆盖：熟悉度存档 / hall_state 合并与插值 / 移动与节流上报 / R 交互菜单 /
聊天输入 / 对战邀请全流程（邀请-接受-matched / 婉拒 / 无回应）/ kick / 绘制冒烟。

用法: python debug/test_hall.py
"""
import os
import queue
import sys

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import pygame  # noqa: E402

import kards_hall as hall  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


class FakeLink:
    """假 ServerLink：send 全记下来，inbox 手动塞消息。"""

    def __init__(self):
        self.sent = []
        self.inbox = queue.Queue()
        self.alive = True

    def send(self, obj):
        self.sent.append(obj)
        return True


class FakeApp:
    def __init__(self):
        self.mp_link = None
        self.mp_user = "我自己"


def make_hall(sent_msgs=None):
    link = FakeLink()
    app = FakeApp()
    app.mp_link = link
    h = hall.HallView(app, name="我自己")
    return h, link


def keydown(key, uni=""):
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode=uni,
                              mod=pygame.KMOD_NONE)


# ---------------------------------------------------------------- 熟悉度

def test_familiar():
    print("== 熟悉度 ==")
    hall._FAMILIAR = {"老对手": 1}
    hall._familiar_path()
    check("打过 1 局不算熟脸", not hall.is_familiar("老对手"))
    hall._FAMILIAR["老对手"] = 2
    check("打过 2 局是熟脸", hall.is_familiar("老对手"))
    hall.familiar_add_battle("路人甲")
    check("加一场后熟悉度=1", hall.familiar_count("路人甲") == 1)
    check("陌生人熟悉度=0", hall.familiar_count("陌生人") == 0)
    check("空名字不崩", (hall.familiar_add_battle("") or True))


# ---------------------------------------------------------------- 状态合并

def test_state():
    print("== hall_state 合并 ==")
    h, link = make_hall()
    h._handle_msg({"m": "hall_state", "players": [
        {"name": "我自己", "x": 1, "y": 1, "chat": None},      # 自己要被忽略
        {"name": "甲", "x": 100, "y": 120, "chat": "你好"},
        {"name": "乙", "x": 400, "y": 500, "chat": None},
    ]})
    check("两个他人进场", set(h.others) == {"甲", "乙"}, str(set(h.others)))
    check("新头像直接落位", h.others["甲"]["x"] == 100 and h.others["甲"]["y"] == 120)
    check("气泡带时间戳", h.others["甲"]["chat"] == "你好"
          and h.others["甲"]["chat_t"] == h.t_now)
    check("自己不在 others", "我自己" not in h.others)

    # 插值：只更新目标点，不瞬移
    h.others["甲"]["x"] = 0.0
    h._handle_msg({"m": "hall_state", "players": [
        {"name": "甲", "x": 200, "y": 300, "chat": None}]})
    check("快照只更新目标点", h.others["甲"]["tx"] == 200
          and h.others["甲"]["x"] == 0.0, str(h.others["甲"]))
    check("渲染位置未瞬移", h.others["甲"]["x"] == 0.0)
    h.step(50)                               # 推进插值（小步长，系数未封顶）
    check("插值朝目标移动", 0 < h.others["甲"]["x"] < 200, str(h.others["甲"]["x"]))
    check("气泡过期清除", h._handle_msg({"m": "hall_state", "players": [
        {"name": "甲", "x": 200, "y": 300, "chat": None}]}
    ) is None and h.others["甲"]["chat"] is None)
    h.others["甲"]["chat"] = "旧话"
    h.others["甲"]["chat_t"] = -99999        # 早就过期
    h.step(10)
    check("过期气泡被清", h.others["甲"]["chat"] is None)

    # 离场
    h._handle_msg({"m": "hall_state", "players": []})
    check("离场立即消失", h.others == {}, str(h.others))


# ---------------------------------------------------------------- 移动

def test_move():
    print("== 移动与上报 ==")
    h, link = make_hall()
    h._move_vector = lambda: (1, 0)          # 向右
    h.step(1000)                             # 1 秒 → 移动 SPEED px
    check("移动了 SPEED px", abs(h.me["x"] - (200 + hall.HallView.SPEED)) < 1,
          str(h.me["x"]))
    check("发出 hall_move", any(m.get("m") == "hall_move" for m in link.sent))
    n_sent = len(link.sent)
    h._move_vector = lambda: (0, 0)
    h.step(500)
    check("静止不再上报", len(link.sent) == n_sent)
    # 上报节流：小幅移动不发包
    h._move_vector = lambda: (1, 0)
    h.step(10)                               # ~2.3px < MOVE_EPS
    check("小幅移动节流不上报", len(link.sent) == n_sent,
          str(len(link.sent) - n_sent))
    h.step(1000)
    check("累计位移足够才上报", len(link.sent) > n_sent)

    # 边界夹取
    h.me["x"] = -50
    h._move_vector = lambda: (0, 0)
    h._clamp_me()
    check("左边界夹取", h.me["x"] >= hall.HallView.R_ME, str(h.me["x"]))
    h.me["y"] = -500
    h._clamp_me()
    check("上边界夹到墙下", h.me["y"] >= hall.HallView.WALL_H + hall.HallView.R_ME,
          str(h.me["y"]))


# ---------------------------------------------------------------- 交互菜单

def test_menu():
    print("== R 交互菜单 ==")
    h, link = make_hall()
    h.others["甲"] = {"x": h.me["x"] + 40, "y": h.me["y"], "tx": 0, "ty": 0,
                      "chat": None, "chat_t": 0}
    h.handle_event(keydown(pygame.K_r))
    check("附近有人按 R 进菜单", h.mode == "menu" and h.menu["name"] == "甲")
    h.handle_event(keydown(pygame.K_s))      # 选中「对战」
    check("下键换选中", h.menu["sel"] == 1, str(h.menu))
    h.handle_event(keydown(pygame.K_w))
    check("上键换回", h.menu["sel"] == 0)
    h.handle_event(keydown(pygame.K_ESCAPE))
    check("Esc 关菜单", h.mode == "roam" and h.menu is None)

    # 选对话
    h.handle_event(keydown(pygame.K_r))
    h.handle_event(keydown(pygame.K_RETURN))
    check("Enter 选对话进输入", h.mode == "chat")
    for ch in "来一把":
        h.handle_event(keydown(pygame.K_a, ch))
    check("输入累积", h.chat_text == "来一把", h.chat_text)
    h.handle_event(keydown(pygame.K_BACKSPACE))
    check("退格删字", h.chat_text == "来一")
    h.handle_event(keydown(pygame.K_RETURN))
    check("Enter 发送 hall_chat",
          any(m.get("m") == "hall_chat" and m.get("text") == "来一"
              for m in link.sent), str(link.sent))
    check("发送后回走动", h.mode == "roam" and h.chat_text == "")

    # 选对战 → 等回应
    h.handle_event(keydown(pygame.K_r))
    h.handle_event(keydown(pygame.K_s))
    h.handle_event(keydown(pygame.K_RETURN))
    check("选对战进等待", h.mode == "wait" and h.wait_for == "甲")
    check("发出 hall_invite",
          any(m.get("m") == "hall_invite" and m.get("to") == "甲"
              for m in link.sent), str(link.sent))
    h.handle_msg_direct = None
    h._handle_msg({"m": "hall_decline", "from": "甲"})
    check("婉拒后回走动", h.mode == "roam")
    check("婉拒出横幅", h.banner is not None and "甲" in h.banner["text"])

    # 等待超时
    h.handle_event(keydown(pygame.K_r))
    h.handle_event(keydown(pygame.K_s))
    h.handle_event(keydown(pygame.K_RETURN))
    h.step(11000)
    check("超时回走动", h.mode == "roam")
    check("超时横幅", h.banner is not None and "回应" in h.banner["text"])


def test_no_body_near():
    print("== 附近没人 ==")
    h, link = make_hall()
    h.others["远方"] = {"x": h.me["x"] + 500, "y": h.me["y"], "tx": 0, "ty": 0,
                        "chat": None, "chat_t": 0}
    h.handle_event(keydown(pygame.K_r))
    check("不在范围内 R 不进菜单", h.mode == "roam" and h.menu is None)
    check("提示附近没有人", h.banner is not None)


# ---------------------------------------------------------------- 邀请与开局

def test_invite_flow():
    print("== 邀请全流程 ==")
    h, link = make_hall()
    # 被邀请
    h._handle_msg({"m": "hall_invite", "from": "乙"})
    check("被邀请进弹窗", h.mode == "invite" and h.invite["from"] == "乙")
    h._handle_msg({"m": "hall_invite", "from": "丙"})   # roam 下才会再进
    check("邀请弹窗期间忽略新邀请", h.mode == "invite" and h.invite["from"] == "乙")
    h.handle_event(keydown(pygame.K_y))
    check("Y 接受并发 hall_accept",
          any(m.get("m") == "hall_accept" and m.get("to") == "乙"
              for m in link.sent), str(link.sent))
    check("接受后回走动", h.mode == "roam" and h.invite is None)

    # Esc 拒绝
    h._handle_msg({"m": "hall_invite", "from": "丙"})
    h.handle_event(keydown(pygame.K_n))
    check("N 拒绝并发 hall_decline",
          any(m.get("m") == "hall_decline" and m.get("to") == "丙"
              for m in link.sent), str(link.sent))

    # 接受后服务器 matched → 直接交回开局
    h._handle_msg({"m": "hall_invite", "from": "乙"})
    h.handle_event(keydown(pygame.K_RETURN))
    h._handle_msg({"m": "matched", "room": 7, "role": "guest",
                   "opp": "乙", "casual": True})
    check("matched 结束大厅", h.result == "matched" and not h.running)
    check("matched 数据完整", h.matched == {"role": "client", "opp": "乙",
                                            "room": 7, "casual": True},
          str(h.matched))


# ---------------------------------------------------------------- 异常与退出

def test_misc():
    print("== 异常与退出 ==")
    h, link = make_hall()
    h._handle_msg({"m": "kick", "err": "别处登录"})
    check("kick 退出并标记", h.result == "back" and h.kicked and not h.running)

    h2, link2 = make_hall()
    h2._handle_msg({"m": "err", "err": "未知消息类型 x"})
    check("err 只出横幅不退出", h2.running and h2.banner is not None)

    h3, link3 = make_hall()
    h3.mode = "chat"
    h3.chat_text = "abc"
    h3.handle_event(keydown(pygame.K_ESCAPE))
    check("Esc 取消输入", h3.mode == "roam" and h3.chat_text == "")
    h3.mode = "roam"
    h3.handle_event(keydown(pygame.K_ESCAPE))
    check("走动中 Esc 离开", h3.result == "back" and not h3.running)
    check("离开发 hall_leave", any(m.get("m") == "hall_leave" for m in link3.sent))

    # 聊天长度上限
    h4, link4 = make_hall()
    h4.mode = "chat"
    for _ in range(70):
        h4.handle_event(keydown(pygame.K_a, "a"))
    check("输入上限 60", len(h4.chat_text) == hall.HallView.CHAT_MAX,
          str(len(h4.chat_text)))

    # 空聊天不发
    h5, link5 = make_hall()
    h5.mode = "chat"
    h5.chat_text = "   "
    h5.handle_event(keydown(pygame.K_RETURN))
    check("空白消息不发送", not any(m.get("m") == "hall_chat" for m in link5.sent))


# ---------------------------------------------------------------- 绘制冒烟

def test_draw_smoke():
    print("== 绘制冒烟（dummy）==")
    h, link = make_hall()
    h.others["甲"] = {"x": 400, "y": 500, "tx": 500, "ty": 520,
                      "chat": "你好呀朋友", "chat_t": 0}
    h.others["乙"] = {"x": 900, "y": 300, "tx": 900, "ty": 300,
                      "chat": None, "chat_t": 0}
    hall._FAMILIAR = {"甲": 5}               # 画绿圈分支
    h.run(pump=None, fps=60, max_frames=30)
    check("30 帧绘制不崩", True)
    # 各模式各画一帧
    h2, _ = make_hall()
    h2.others["甲"] = {"x": 400, "y": 500, "tx": 400, "ty": 500,
                       "chat": None, "chat_t": 0}
    pygame.display.init()
    screen = pygame.display.set_mode((h2.W, h2.H))
    for mode in ("menu", "invite", "chat", "wait"):
        h2.mode = mode
        if mode == "menu":
            h2.menu = {"name": "甲", "sel": 0}
        if mode == "invite":
            h2.invite = {"from": "甲"}
        if mode == "wait":
            h2.wait_for = "甲"
        try:
            h2.draw(screen)
            check(f"模式 {mode} 绘制不崩", True)
        except Exception as e:                 # noqa: BLE001
            check(f"模式 {mode} 绘制不崩", False, repr(e))
    h2.mode = "roam"
    h2.banner = {"text": "横幅", "until": h2.t_now + 5000}
    try:
        h2.draw(screen)
        check("横幅绘制不崩", True)
    except Exception as e:                     # noqa: BLE001
        check("横幅绘制不崩", False, repr(e))
    pygame.display.quit()


def main():
    pygame.init()
    try:
        test_familiar()
        test_state()
        test_move()
        test_menu()
        test_no_body_near()
        test_invite_flow()
        test_misc()
        test_draw_smoke()
    finally:
        try:
            pygame.quit()
        except Exception:                      # noqa: BLE001
            pass
    print("\n" + "=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
