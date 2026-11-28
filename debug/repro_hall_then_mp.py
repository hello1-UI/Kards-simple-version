"""复现 bug 2 变体：先跑休战大厅（pygame 第一窗口）退出，再 _mp_launch
开对战棋盘（同进程第二个 pygame 窗口）——模拟玩家 大厅→退→联机→开局 的顺序。
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.argv = ["KARDS.py"]

import queue
import kards_engine as core
import KARDS as gui
import kards_board
import kards_hall

_orig_board_run = kards_board.PygameBoard.run


def _spy_board_run(self, pump=None, fps=60, max_frames=None):
    print("[spy] board.run 进入")
    _orig_board_run(self, pump=pump, fps=fps, max_frames=max_frames or 300)
    print(f"[spy] board.run 退出：running={self.running} result={self.result!r} "
          f"end_state={'有' if self.end_state is not None else '无'} "
          f"game.over={self.app.game.over if self.app.game else '?'}")


kards_board.PygameBoard.run = _spy_board_run

_orig_hall_run = kards_hall.HallView.run


def _spy_hall_run(self, pump=None, fps=60, max_frames=None):
    print("[spy] hall.run 进入")
    r = _orig_hall_run(self, pump=pump, fps=fps, max_frames=max_frames or 120)
    print(f"[spy] hall.run 退出：result={self.result!r}")
    return r


kards_hall.HallView.run = _spy_hall_run


class FakeLink:
    def __init__(self):
        self.inbox = queue.Queue()
        self.alive = True
        self.sent = []

    def send(self, obj):
        self.sent.append(obj)
        return True

    def close(self):
        pass


def main():
    app = gui.App()
    app.withdraw()
    app.update()
    db = core.card_database()

    # 1) 先进休战大厅（模拟玩家先逛大厅）
    app.mp_link = FakeLink()
    app.mp_user = "我"
    h = kards_hall.HallView(app)
    h.run(max_frames=120)          # 120 帧后自然退出
    print("大厅退出后 pygame display 状态：",
          "quit" if not pygame_ok() else "alive")

    # 2) 退大厅 → 联机匹配 → 组卡 → 开始战斗
    app.mp_mode = True
    app.mp_role = "host"
    app.mp_opp_name = "对手"
    app.mp_room_id = 1
    app.deck_nation = "德国"
    app.mp_my_deck = [c.name for c in core.build_deck("德国", db)]
    app.mp_opp = {"m": "ready", "nation": "苏联",
                  "deck": [c.name for c in core.build_deck("苏联", db)]}
    app._mp_me_ready = True
    app._build_deck_builder("德国", mp=True)
    app.update()
    try:
        app._mp_launch(12345)
    except Exception:
        traceback.print_exc()
        print("!!! _mp_launch 抛异常（卡出页面复现）")
        return 1
    print("board 最终状态：", "存活" if app._pyboard is not None
          else "已退出", " game.over =", app.game.over)
    try:
        app.destroy()
    except Exception:
        pass
    print("=== 完成 ===")
    return 0


def pygame_ok():
    import pygame
    try:
        pygame.display.get_init()
        return pygame.display.get_init()
    except Exception:                              # noqa: BLE001
        return False


if __name__ == "__main__":
    sys.exit(main())
