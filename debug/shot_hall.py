# -*- coding: utf-8 -*-
"""把走动大厅渲染成 PNG，用来**肉眼检查**排版/气泡/菜单。

    python debug/shot_hall.py [输出目录]
"""
import os
import queue
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame  # noqa: E402

import kards_hall as hall  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "shots")
os.makedirs(OUT, exist_ok=True)

pygame.init()
pygame.display.init()


class FakeLink:
    def __init__(self):
        self.sent = []
        self.inbox = queue.Queue()
        self.alive = True

    def send(self, obj):
        self.sent.append(obj)
        return True


class FakeApp:
    def __init__(self):
        self.mp_link = FakeLink()
        self.mp_user = "CGT"


def shoot(h, name, frames=3):
    for _ in range(frames):
        h.step(16)
    surf = pygame.Surface((h.W, h.H))
    h.draw(surf)
    path = os.path.join(OUT, name)
    pygame.image.save(surf, path)
    print("  写出", name)


hall._FAMILIAR = {"老对手甲": 5}

# 1. 走动中：几名玩家 + 气泡
h = hall.HallView(FakeApp(), name="CGT")
h.others = {
    "老对手甲": {"x": 520, "y": 470, "tx": 520, "ty": 470,
                 "chat": "来一把排位？", "chat_t": 0},
    "新来的乙": {"x": 860, "y": 560, "tx": 860, "ty": 560,
                 "chat": None, "chat_t": 0},
    "kards_fan": {"x": 300, "y": 350, "tx": 300, "ty": 350,
                  "chat": "有人想打休闲吗？", "chat_t": 0},
}
shoot(h, "hall_01_roam.png")

# 2. 交互菜单（靠近老对手甲）
h.me["x"], h.me["y"] = 560, 480
h.mode = "menu"
h.menu = {"name": "老对手甲", "sel": 0}
shoot(h, "hall_02_menu.png")

# 3. 邀请弹窗
h.mode = "invite"
h.menu = None
h.invite = {"from": "新来的乙"}
shoot(h, "hall_03_invite.png")

# 4. 聊天输入
h.mode = "chat"
h.invite = None
h.chat_text = "打完这把就睡_"
shoot(h, "hall_04_chat.png")

# 5. 等待回应 + 横幅
h.mode = "wait"
h.chat_text = ""
h.wait_for = "新来的乙"
h.show_banner("等待 新来的乙 回应…", ms=999999)
shoot(h, "hall_05_wait.png")

pygame.quit()
print("输出目录:", os.path.abspath(OUT))
