#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kards_hall —— 走动大厅（pygame 场景，主菜单第 4 张卡进入）

服务器里的其他玩家以头像形式出现在同一个房间里：
  - WASD / 方向键移动自己，别人实时跟随（服务器 ~100ms 广播 + 客户端插值）
  - 靠近某人按 R：对话（头顶气泡）或 对战（邀请 → 接受后直接开局）
  - 经常对战过的人头像带绿圈（本地熟悉度：同一个人打过 ≥2 局）
  - 装饰：墙面横幅 + 五国旗帜 + 地毯 + 木桌 + 绿植

复用 kards_board 的字体 / 主题 / 圆角矩形等绘制设施。注意主题色必须
经 kb.C(kb.BG) 这种**运行时**读取（theme.sync 会改写 kards_board 的
模块全局），直接 from kards_board import BG 会拿到旧值。
"""

import os
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import json
import time

import pygame

import kards_board as kb
from kards_board import font, wrap_text, truncate, rr, plain

import kards_i18n as i18n

# ---------------------------------------------------------------- 熟悉度存档
# 「好友（经常对战）」的判定数据：本地记录每个对手的对战场次。
# 独立小文件（不混进 accounts.json），坏文件按空表处理，绝不拖垮大厅。

FAMILIAR_MIN = 2              # 打过 ≥2 局算熟脸（绿圈）
DATA_DIR = None               # 延迟从 kards_account 取（避免循环 import）
_FAMILIAR = None


def _familiar_path():
    global DATA_DIR
    if DATA_DIR is None:
        try:
            import kards_account
            DATA_DIR = kards_account.DATA_DIR
        except Exception:                          # noqa: BLE001
            DATA_DIR = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(DATA_DIR, "hall_familiar.json")


def _familiar_load():
    global _FAMILIAR
    if _FAMILIAR is not None:
        return _FAMILIAR
    try:
        with open(_familiar_path(), "r", encoding="utf-8") as f:
            _FAMILIAR = {str(k): int(v) for k, v in json.load(f).items()}
    except Exception:                              # noqa: BLE001  坏/缺文件=空表
        _FAMILIAR = {}
    return _FAMILIAR


def _familiar_save():
    try:
        with open(_familiar_path(), "w", encoding="utf-8") as f:
            json.dump(_familiar_load(), f, ensure_ascii=False)
    except Exception:                              # noqa: BLE001
        pass


def familiar_count(name):
    """与 name 打过的联机对局数（本地记录）。"""
    return _familiar_load().get(name or "", 0)


def familiar_add_battle(name):
    """一局联机结束：熟悉度 +1 并落盘。"""
    if not name:
        return
    db = _familiar_load()
    db[name] = db.get(name, 0) + 1
    _familiar_save()


def is_familiar(name):
    return familiar_count(name) >= FAMILIAR_MIN


# ---------------------------------------------------------------- 场景

class HallView:
    """走动大厅。用法（App 内）：

        h = kards_hall.HallView(self)
        h.run(pump=self.update)      # 阻塞至离开，期间泵 Tk 事件
        # h.result: "back"=回主菜单 / "matched"=大厅邀请开局 / "quit"=退出程序
        # h.matched: matched 时的 dict(role, opp, room, casual)
    """

    W, H = 1280, 800
    SPEED = 230.0             # 自机速度 px/s
    R_ME = 21                 # 头像半径
    R_TALK = 95               # 可交互距离
    MOVE_EPS = 14.0           # 累计位移多少 px 发一次 hall_move
    CHAT_TTL_MS = 8000        # 气泡展示时长（与服务器 HALL_CHAT_TTL 一致）
    WALL_H = 96               # 墙面高度
    CHAT_MAX = 60             # 本地输入长度上限（服务器还会再截 120）

    # 装饰：木桌（椭圆）与绿植的固定位置（房间坐标系）
    TABLES = [(260, 620, 120, 62), (1020, 600, 130, 66), (640, 700, 110, 56)]
    PLANTS = [(80, 700), (1195, 690), (1180, 170)]

    def __init__(self, app, name=None):
        self.app = app
        kb.theme.sync(vars(kb))            # 主菜单刚选过主题时保证首帧正确
        self.link = getattr(app, "mp_link", None)
        self.me_name = name or getattr(app, "mp_user", "") or "我"
        # 出生点：房间中下部靠左
        self.me = {"x": 200.0, "y": 560.0}
        self.others = {}                   # name -> dict(x,y,tx,ty,chat,chat_t)
        self.running = True
        self.result = None
        self.matched = None
        self.kicked = False
        self.t_now = 0

        # 交互状态：roam（走动）/ menu（R 交互菜单）/ chat（输入）/ invite（被邀请）/ wait（等回应）
        self.mode = "roam"
        self.menu = None                   # dict(name, sel)
        self.chat_text = ""
        self.invite = None                 # dict(from)
        self.wait_until = 0
        self.wait_for = None
        self.banner = None                 # dict(text, until, color)
        self.mouse = (0, 0)
        self._sent_pos = (self.me["x"], self.me["y"])
        self._menu_rects = []              # 菜单条目热区（draw 时填）
        self._invite_rects = []
        self.screen = None
        self.clock = None
        try:
            pygame.font.init()
        except Exception:                  # noqa: BLE001
            pass

    # ------------------------------------------------------------ 收发

    # 大厅只消费这些消息；其余（ready/seed/act/peer_left/concede/lobby…）
    # 原序归还 inbox，交回 App 的轮询 —— 走动大厅曾把开局协议消息整个吞掉
    # （对手的 ready/seed 被吃 → 永远开不了局 / 对局中对手动作全部失灵）。
    _HALL_MSGS = {"hall_state", "hall_invite", "hall_decline", "hall_gone",
                  "matched", "kick", "err"}

    def _srv_send(self, obj):
        link = self.link
        if link is None or not getattr(link, "alive", False):
            return False
        try:
            return link.send(obj)
        except Exception:                  # noqa: BLE001
            return False

    def _drain(self):
        """消费大厅自己的推送；不属于大厅的消息按序归还 inbox。"""
        link = self.link
        if link is None:
            return
        n = 0
        keep = []
        while n < 200:
            try:
                msg = link.inbox.get_nowait()
            except Exception:              # noqa: BLE001  queue.Empty 等
                break
            n += 1
            if isinstance(msg, dict) and msg.get("m") in self._HALL_MSGS:
                self._handle_msg(msg)
            else:
                keep.append(msg)
            if not self.running:
                break
        for m in keep:
            try:
                link.inbox.put(m)
            except Exception:              # noqa: BLE001
                pass

    def _handle_msg(self, msg):
        m = msg.get("m")
        if m == "hall_state":
            self._apply_state(msg.get("players") or [])
        elif m == "hall_invite":
            if self.mode in ("roam", "menu"):
                self.mode = "invite"
                self.invite = {"from": msg.get("from") or "?"}
        elif m == "hall_decline":
            if self.mode == "wait" and self.wait_for == msg.get("from"):
                self.mode = "roam"
            self.show_banner(i18n.t("hall_declined",
                                    name=msg.get("from") or "?"))
        elif m == "hall_gone":
            if self.mode == "wait" and self.wait_for == msg.get("to"):
                self.mode = "roam"
            self.show_banner(i18n.t("hall_gone", name=msg.get("to") or "?"))
        elif m == "matched":
            # 大厅邀请被接受：交回 App 走选国家 → 开局流程
            self.matched = {"role": "host" if msg.get("role") == "host"
                            else "client",
                            "opp": msg.get("opp"),
                            "room": msg.get("room"),
                            "casual": bool(msg.get("casual", True))}
            self.result = "matched"
            self.running = False
        elif m == "kick":
            self.kicked = True
            self.result = "back"
            self.running = False
        elif m == "err":
            if self.mode == "wait":
                self.mode = "roam"
            self.show_banner("⚠ " + str(msg.get("err") or "err"))

    def _apply_state(self, players):
        """快照合并：已有头像保留插值（只更新目标点），新头像直接落位。"""
        names = set()
        for p in players:
            nm = p.get("name")
            if not nm or nm == self.me_name:
                continue
            names.add(nm)
            try:
                tx = float(p.get("x", 0))
                ty = float(p.get("y", 0))
            except (TypeError, ValueError):
                continue
            o = self.others.get(nm)
            if o is None:
                self.others[nm] = {"x": tx, "y": ty, "tx": tx, "ty": ty,
                                   "chat": p.get("chat"), "chat_t": self.t_now}
            else:
                o["tx"], o["ty"] = tx, ty
                if p.get("chat") and p.get("chat") != o.get("chat"):
                    o["chat"] = p.get("chat")
                    o["chat_t"] = self.t_now
                elif not p.get("chat"):
                    o["chat"] = None
        for nm in [n for n in self.others if n not in names]:
            del self.others[nm]            # 离场的人立即消失

    # ------------------------------------------------------------ 主循环

    def run(self, pump=None, fps=60, max_frames=None):
        pygame.init()
        self.screen = pygame.display.set_mode((self.W, self.H))
        pygame.display.set_caption("KARDS 简化版 — " + i18n.t("hall_title"))
        self.clock = pygame.time.Clock()
        # 向服务器登记进场：服务器只把 in_hall 玩家放进快照/广播，
        # 不发 hall_join 就等于隐身（谁也看不见你、你也看不见谁，
        # 实测主症状「大厅看不见别人但能匹配上」）。
        self._srv_send({"m": "hall_join",
                        "x": self.me["x"], "y": self.me["y"]})
        frames = 0
        try:
            while self.running:
                dt = self.clock.tick(fps)
                self.step(dt)
                self._drain()
                if not self.running:
                    break
                for ev in pygame.event.get():
                    self.handle_event(ev)
                    if not self.running:
                        break
                if pump is not None:
                    try:
                        pump()
                    except Exception:          # noqa: BLE001
                        import traceback
                        traceback.print_exc()
                self.draw(self.screen)
                pygame.display.flip()
                frames += 1
                if max_frames is not None and frames >= max_frames:
                    break
        finally:
            self.screen = None
            self.clock = None
            pygame.display.quit()
        return self.result

    def show_banner(self, text, ms=2200):
        self.banner = {"text": text, "until": self.t_now + ms}

    # ------------------------------------------------------------ 逻辑步进

    def step(self, dt_ms):
        self.t_now += dt_ms
        dt = dt_ms / 1000.0

        # 别人朝目标点插值（服务器 ~100ms 一拍，插值让移动平滑）
        k = min(1.0, dt * 9.0)
        for o in self.others.values():
            o["x"] += (o["tx"] - o["x"]) * k
            o["y"] += (o["ty"] - o["y"]) * k
            if o["chat"] and self.t_now - o["chat_t"] > self.CHAT_TTL_MS:
                o["chat"] = None

        # 等回应超时
        if self.mode == "wait" and self.t_now > self.wait_until:
            self.mode = "roam"
            self.show_banner(i18n.t("hall_no_reply", name=self.wait_for or "?"))

        # 自机移动（走动模式才可动）
        if self.mode == "roam":
            dx, dy = self._move_vector()
            if dx or dy:
                L = math_hypot(dx, dy) or 1.0
                self.me["x"] += dx / L * self.SPEED * dt
                self.me["y"] += dy / L * self.SPEED * dt
                self._clamp_me()
                self._maybe_send_move()

    def _move_vector(self):
        """当前移动方向（-1/0/1, -1/0/1）。

        独立成方法：单测里覆写它即可驱动移动，不必真的按键盘。
        """
        if self.screen is None:
            return (0, 0)
        keys = pygame.key.get_pressed()
        dx = dy = 0
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            dy -= 1
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            dy += 1
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            dx -= 1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            dx += 1
        return (dx, dy)

    def _clamp_me(self):
        pad = self.R_ME + 6
        self.me["x"] = max(pad, min(self.W - pad, self.me["x"]))
        self.me["y"] = max(self.WALL_H + pad, min(self.H - pad - 8, self.me["y"]))

    def _maybe_send_move(self):
        dx = self.me["x"] - self._sent_pos[0]
        dy = self.me["y"] - self._sent_pos[1]
        if math_hypot(dx, dy) >= self.MOVE_EPS:
            self._sent_pos = (self.me["x"], self.me["y"])
            self._srv_send({"m": "hall_move",
                            "x": int(self.me["x"]), "y": int(self.me["y"])})

    def _nearest(self, max_d=None):
        """范围内最近的人（没有则 None）。"""
        best, bd = None, (max_d or self.R_TALK) ** 2
        for nm, o in self.others.items():
            d = (o["x"] - self.me["x"]) ** 2 + (o["y"] - self.me["y"]) ** 2
            if d < bd:
                best, bd = nm, d
        return best

    # ------------------------------------------------------------ 事件

    def handle_event(self, ev):
        if ev.type == pygame.QUIT:
            self._leave("quit")
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self._click(ev.pos)
            return
        if ev.type == pygame.MOUSEMOTION:
            self.mouse = ev.pos
        if ev.type != pygame.KEYDOWN:
            return

        key = ev.key
        if self.mode == "chat":
            self._chat_key(ev)
            return
        if self.mode == "invite":
            if key in (pygame.K_RETURN, pygame.K_y):
                self._accept_invite()
            elif key in (pygame.K_ESCAPE, pygame.K_n):
                self._decline_invite()
            return
        if self.mode == "wait":
            if key == pygame.K_ESCAPE:
                self.mode = "roam"          # 不通知服务器：邀请仍然有效
            return
        if self.mode == "menu":
            self._menu_key(key)
            return
        # roam
        if key in (pygame.K_ESCAPE, pygame.K_p):
            self._leave("back")
        elif key == pygame.K_r:
            nm = self._nearest()
            if nm is not None:
                self.mode = "menu"
                self.menu = {"name": nm, "sel": 0}
            else:
                self.show_banner(i18n.t("hall_nobody_near"))

    def _chat_key(self, ev):
        if ev.key == pygame.K_RETURN:
            text = self.chat_text.strip()
            self.mode = "roam"
            self.chat_text = ""
            if text:
                self._srv_send({"m": "hall_chat", "text": text})
        elif ev.key == pygame.K_ESCAPE:
            self.mode = "roam"
            self.chat_text = ""
        elif ev.key == pygame.K_BACKSPACE:
            self.chat_text = self.chat_text[:-1]
        elif ev.unicode:
            ch = ev.unicode
            if ch >= " " or ch == "\t":     # 过滤控制字符
                if len(self.chat_text) < self.CHAT_MAX:
                    self.chat_text += ch

    def _menu_key(self, key):
        if key in (pygame.K_UP, pygame.K_w):
            self.menu["sel"] = (self.menu["sel"] - 1) % 2
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.menu["sel"] = (self.menu["sel"] + 1) % 2
        elif key in (pygame.K_RETURN, pygame.K_r):
            self._menu_pick(self.menu["sel"])
        elif key == pygame.K_ESCAPE:
            self.mode = "roam"
            self.menu = None

    def _menu_pick(self, idx):
        nm = self.menu["name"]
        self.menu = None
        self.mode = "roam"
        if idx == 0:                        # 对话
            self.mode = "chat"
            self.chat_text = ""
        else:                               # 对战
            if self._srv_send({"m": "hall_invite", "to": nm}):
                self.mode = "wait"
                self.wait_for = nm
                self.wait_until = self.t_now + 10000
                self.show_banner(i18n.t("hall_wait", name=nm), ms=10000)

    def _accept_invite(self):
        frm = (self.invite or {}).get("from")
        self.invite = None
        self.mode = "roam"
        if frm:
            self._srv_send({"m": "hall_accept", "to": frm})

    def _decline_invite(self):
        frm = (self.invite or {}).get("from")
        self.invite = None
        self.mode = "roam"
        if frm:
            self._srv_send({"m": "hall_decline", "to": frm})

    def _click(self, pos):
        if self.mode == "invite":
            for rect, act in self._invite_rects:
                if rect.collidepoint(pos):
                    (self._accept_invite if act == "ok" else self._decline_invite)()
                    return
            self._decline_invite()          # 点空白 = 婉拒
            return
        if self.mode == "menu":
            for rect, idx in self._menu_rects:
                if rect.collidepoint(pos):
                    self._menu_pick(idx)
                    return
            self.mode = "roam"              # 点空白 = 关菜单
            self.menu = None
            return

    def _leave(self, result):
        self._srv_send({"m": "hall_leave"})
        self.result = result
        if result == "quit":
            self.result = "quit"
        self.running = False

    # ------------------------------------------------------------ 绘制

    def draw(self, surf):
        surf.fill(kb.C(kb.BG))
        self._draw_room(surf)
        # 他人（名字排序保证遮挡顺序稳定）
        for nm in sorted(self.others):
            self._draw_avatar(surf, nm, self.others[nm], me=False)
        self._draw_avatar(surf, self.me_name, self.me, me=True)
        self._draw_hud(surf)
        if self.mode == "menu":
            self._draw_menu(surf)
        if self.mode == "invite":
            self._draw_invite(surf)
        if self.mode == "chat":
            self._draw_chat_input(surf)
        if self.mode == "wait":
            self._draw_wait(surf)
        if self.banner is not None:
            self._draw_banner(surf)

    def _draw_room(self, surf):
        wall = kb.C(kb.PANEL)
        pygame.draw.rect(surf, wall, (0, 0, self.W, self.WALL_H))
        pygame.draw.line(surf, kb.C(kb.BORDER), (0, self.WALL_H),
                         (self.W, self.WALL_H), 2)
        # 横幅标题
        f = font(26, True)
        surf.blit(f.render(plain(i18n.t("hall_title")), True, kb.C(kb.GOLD)),
                  (self.W // 2 - f.size(plain(i18n.t("hall_title")))[0] // 2, 18))
        # 五国旗帜（颜色小三角旗）
        nc = kb.NATION_COLOR
        nations = ["德国", "苏联", "英国", "美国", "波兰"]
        x0 = self.W // 2 - len(nations) * 46 // 2
        for i, nat in enumerate(nations):
            col = nc.get(nat) or kb.C(kb.ACCENT)
            bx = x0 + i * 46
            pygame.draw.polygon(surf, kb.C(col),
                                [(bx, 64), (bx + 34, 64), (bx + 17, 92)])
            pygame.draw.line(surf, kb.C(kb.BORDER), (bx, 62), (bx, 64))
        # 地毯
        rug = kb.C(kb.PANEL_ALT)
        rr(surf, (self.W // 2 - 340, 360, 680, 330), rug, radius=24)
        pygame.draw.rect(surf, kb.C(kb.BORDER),
                         (self.W // 2 - 340, 360, 680, 330), width=2,
                         border_radius=24)
        # 木桌
        for tx, ty, tw, th in self.TABLES:
            pygame.draw.ellipse(surf, kb.C(kb.CARD_BG), (tx - tw // 2,
                                                         ty - th // 2, tw, th))
            pygame.draw.ellipse(surf, kb.C(kb.BORDER),
                                (tx - tw // 2, ty - th // 2, tw, th), 2)
        # 绿植
        for px, py in self.PLANTS:
            pygame.draw.circle(surf, kb.C(kb.SUCCESS), (px, py - 8), 16)
            pygame.draw.circle(surf, kb.C(kb.GREEN), (px - 10, py + 2), 11)
            pygame.draw.circle(surf, kb.C(kb.GREEN), (px + 10, py + 2), 11)
            pygame.draw.rect(surf, kb.C(kb.BORDER), (px - 7, py + 6, 14, 16),
                             border_radius=3)

    def _draw_avatar(self, surf, name, pos, me=False):
        x, y = int(pos["x"]), int(pos["y"])
        r = self.R_ME
        # 熟脸绿圈
        if is_familiar(name):
            pygame.draw.circle(surf, kb.C(kb.SUCCESS), (x, y), r + 5, 4)
        # 身体
        body = kb.C(kb.PRIMARY) if me else kb.C(kb.ACCENT)
        pygame.draw.circle(surf, body, (x, y), r)
        pygame.draw.circle(surf, kb.C(kb.TEXT) if me else kb.C(kb.BORDER),
                           (x, y), r, 2)
        # 名字首字
        ch = plain((name or "?")[:1])
        f = font(18, True)
        surf.blit(f.render(ch, True, kb.C(kb.TEXT)),
                  (x - f.size(ch)[0] // 2, y - f.size(ch)[1] // 2 - 1))
        # 名牌
        nf = font(13, True if me else False)
        nm = plain(truncate(name or "?", nf, 110))
        surf.blit(nf.render(nm, True, kb.C(kb.GOLD) if me else kb.C(kb.TEXT)),
                  (x - nf.size(nm)[0] // 2, y + r + 4))
        # 气泡
        chat = pos.get("chat")
        if chat:
            self._draw_bubble(surf, x, y - r - 10, chat)

    def _draw_bubble(self, surf, x, y, text):
        f = font(14)
        lines = wrap_text(plain(str(text)), f, 200)[:3]
        w = max(f.size(ln)[0] for ln in lines) + 18
        h = len(lines) * 19 + 12
        rect = pygame.Rect(int(x - w // 2), int(y - h), w, h)
        rect.clamp_ip(pygame.Rect(4, self.WALL_H + 4, self.W - 8,
                                  self.H - self.WALL_H - 8))
        rr(surf, rect, kb.C(kb.CARD_BG), radius=8,
           border_color=kb.C(kb.BORDER))
        for i, ln in enumerate(lines):
            surf.blit(f.render(ln, True, kb.C(kb.TEXT)),
                      (rect.x + 9, rect.y + 6 + i * 19))
        # 小尾巴
        tip_y = rect.bottom
        if tip_y < y + 2:
            pygame.draw.polygon(surf, kb.C(kb.CARD_BG),
                                [(x - 6, tip_y - 1), (x + 6, tip_y - 1), (x, tip_y + 6)])

    def _draw_hud(self, surf):
        # 左上提示
        f = font(14)
        surf.blit(f.render(plain(i18n.t("hall_hint")), True, kb.C(kb.DIM)),
                  (16, self.WALL_H + 12))
        # 右上在场人数
        n = len(self.others) + 1
        cnt = plain(i18n.t("hall_online", n=n))
        surf.blit(f.render(cnt, True, kb.C(kb.TEXT)),
                  (self.W - 16 - f.size(cnt)[0], self.WALL_H + 12))
        # 交互提示
        if self.mode == "roam":
            nm = self._nearest()
            if nm is not None:
                tip = plain(i18n.t("hall_talk_hint", name=nm))
                surf.blit(f.render(tip, True, kb.C(kb.GOLD)),
                          (self.W // 2 - f.size(tip)[0] // 2, self.H - 34))

    def _draw_banner(self, surf):
        if self.t_now >= self.banner["until"]:
            self.banner = None
            return
        f = font(17, True)
        text = plain(self.banner["text"])
        w = f.size(text)[0] + 36
        rect = pygame.Rect(self.W // 2 - w // 2, self.WALL_H + 40, w, 38)
        rr(surf, rect, kb.C(kb.PANEL), radius=10,
           border_color=kb.C(kb.BORDER))
        surf.blit(f.render(text, True, kb.C(kb.GOLD)),
                  (rect.x + 18, rect.y + 8))

    def _draw_menu(self, surf):
        nm = self.menu["name"]
        o = self.others.get(nm) or self.me
        x, y = int(o["x"]), int(o["y"]) - (self.R_ME + 46)
        items = [i18n.t("hall_menu_chat"), i18n.t("hall_menu_battle")]
        f = font(16, True)
        title = plain(i18n.t("hall_menu_title", name=nm))
        rects = []
        w = max([f.size(i)[0] for i in items] + [f.size(title)[0]]) + 40
        h = 34 + len(items) * 34 + 10
        rect = pygame.Rect(x - w // 2, y - h, w, h)
        rect.clamp_ip(pygame.Rect(6, self.WALL_H + 6, self.W - 12,
                                  self.H - self.WALL_H - 12))
        rr(surf, rect, kb.C(kb.PANEL), radius=10,
           border_color=kb.C(kb.BORDER))
        surf.blit(f.render(title, True, kb.C(kb.GOLD)),
                  (rect.x + 20, rect.y + 8))
        self._menu_rects = []
        for i, it in enumerate(items):
            ir = pygame.Rect(rect.x + 12, rect.y + 36 + i * 34,
                             rect.w - 24, 30)
            sel = i == self.menu["sel"]
            hovered = ir.collidepoint(self.mouse)
            if sel or hovered:
                rr(surf, ir, kb.C(kb.PANEL_ALT), radius=6)
            col = kb.C(kb.TEXT) if (sel or hovered) else kb.C(kb.DIM)
            surf.blit(f.render(plain(it), True, col), (ir.x + 12, ir.y + 4))
            rects.append((ir, i))
        self._menu_rects = rects

    def _draw_invite(self, surf):
        dim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 140))
        surf.blit(dim, (0, 0))
        f = font(20, True)
        sf = font(15)
        text = plain(i18n.t("hall_invite_from",
                            name=(self.invite or {}).get("from") or "?"))
        w = max(f.size(text)[0] + 60, 420)
        rect = pygame.Rect(self.W // 2 - w // 2, self.H // 2 - 90, w, 180)
        rr(surf, rect, kb.C(kb.PANEL), radius=14,
           border_color=kb.C(kb.GOLD))
        surf.blit(f.render(text, True, kb.C(kb.TEXT)),
                  (self.W // 2 - f.size(text)[0] // 2, rect.y + 30))
        ok, no = i18n.t("hall_accept"), i18n.t("hall_decline")
        bw = (w - 60) // 2
        self._invite_rects = []
        for i, (label, act) in enumerate(((ok, "ok"), (no, "no"))):
            br = pygame.Rect(rect.x + 20 + i * (bw + 20), rect.y + 100,
                             bw, 44)
            col = kb.C(kb.SUCCESS) if act == "ok" else kb.C(kb.DANGER)
            rr(surf, br, col, radius=8)
            bf = font(17, True)
            surf.blit(bf.render(plain(label), True, kb.C(kb.TEXT)),
                      (br.centerx - bf.size(plain(label))[0] // 2,
                       br.centery - 11))
            self._invite_rects.append((br, act))
        # 提示可点空白拒绝
        tip = plain(i18n.t("hall_decline_tip"))
        surf.blit(sf.render(tip, True, kb.C(kb.DIM)),
                  (self.W // 2 - sf.size(tip)[0] // 2, rect.bottom + 14))

    def _draw_chat_input(self, surf):
        f = font(17)
        shown = "> " + self.chat_text + ("_" if (self.t_now // 500) % 2 else "")
        w = max(420, f.size(plain(shown))[0] + 30)
        rect = pygame.Rect(self.W // 2 - w // 2, self.H - 84, w, 42)
        rr(surf, rect, kb.C(kb.CARD_BG), radius=8,
           border_color=kb.C(kb.GOLD))
        surf.blit(f.render(plain(shown), True, kb.C(kb.TEXT)),
                  (rect.x + 14, rect.y + 9))
        hf = font(13)
        tip = plain(i18n.t("hall_chat_hint"))
        surf.blit(hf.render(tip, True, kb.C(kb.DIM)),
                  (self.W // 2 - hf.size(tip)[0] // 2, rect.bottom + 6))

    def _draw_wait(self, surf):
        f = font(16, True)
        text = plain(i18n.t("hall_wait", name=self.wait_for or "?"))
        w = f.size(text)[0] + 36
        rect = pygame.Rect(self.W // 2 - w // 2, self.H - 140, w, 38)
        rr(surf, rect, kb.C(kb.PANEL), radius=10,
           border_color=kb.C(kb.BORDER))
        surf.blit(f.render(text, True, kb.C(kb.TEXT)),
                  (rect.x + 18, rect.y + 8))


def math_hypot(a, b):
    return (a * a + b * b) ** 0.5
