"""复现：联机组卡 → 点开始战斗 → _mp_launch 全链路是否卡出页面。

模拟真实流程：App 实例 + 假 link（对手 ready + seed 已在 inbox）→
直接走 _mp_poll_hello → _mp_launch → _run_pyboard（ pygame 窗口开起来后
2 秒强制退出），捕获任何异常。
"""
import os
import sys
import queue
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")   # 无头：不在用户桌面弹窗
sys.path.insert(0, ROOT)
MODE = sys.argv[1] if len(sys.argv) > 1 else "mp"   # 先取参数（后面 argv 会被覆盖）
sys.argv = ["KARDS.py"]

import kards_engine as core
import KARDS as gui
import kards_board

_orig_run = kards_board.PygameBoard.run


def _spy_run(self, pump=None, fps=60, max_frames=None):
    print("[spy] board.run 进入")
    _orig_run(self, pump=pump, fps=fps, max_frames=max_frames or 300)
    print(f"[spy] board.run 退出：running={self.running} result={self.result!r} "
          f"end_state={'有' if self.end_state is not None else '无'} "
          f"game.over={self.app.game.over if self.app.game else '?'} "
          f"turn={self.app.game.turn_num if self.app.game else '?'}")


kards_board.PygameBoard.run = _spy_run

_orig_handle = kards_board.PygameBoard.handle_event


def _spy_handle(self, ev):
    if ev.type == getattr(kards_board.pygame, "QUIT", -1):
        import traceback
        print("[spy] 收到 pygame.QUIT，调用栈：")
        traceback.print_stack()
    return _orig_handle(self, ev)


kards_board.PygameBoard.handle_event = _spy_handle

_orig_destroy = gui.App.destroy


def _spy_destroy(self):
    import traceback
    print("[spy] App.destroy() 被调用，调用栈：")
    traceback.print_stack()
    _orig_destroy(self)


gui.App.destroy = _spy_destroy

_orig_finish = gui.App.finish


def _spy_finish(self, winner=None):
    import traceback
    print(f"[spy] App.finish(winner={winner}) 被调用，调用栈：")
    traceback.print_stack()
    g = self.game
    if g is not None:
        print(f"[spy] game.over={g.over} conceded={g.conceded} "
              f"turn={g.turn_num} HQ 你={g.players[0].hq} 敌={g.players[1].hq}")
    _orig_finish(self, winner=winner)


gui.App.finish = _spy_finish

_orig_check_over = gui.App.check_over


def _spy_check_over(self):
    g = self.game
    _spy_check_over.n += 1
    if g is not None and g.over:
        print(f"[spy] check_over 第{_spy_check_over.n}次：game 已 over，调用栈：")
        traceback.print_stack()
    _orig_check_over(self)


_spy_check_over.n = 0
gui.App.check_over = _spy_check_over


class FakeLink:
    """足够骗过 _mp_poll_hello / _mp_send_act 的假链路。"""

    def __init__(self, msgs):
        self.inbox = queue.Queue()
        for m in msgs:
            self.inbox.put(m)
        self.sent = []
        self.alive = True

    def send(self, obj):
        self.sent.append(obj)
        return True

    def close(self):
        pass


def main():
    import time
    mode = MODE
    app = gui.App()
    app.update()
    db = core.card_database()
    opp_deck = core.build_deck("苏联", db)
    opp_deck = [c.name for c in opp_deck]

    # 联机状态：已匹配、已 ready、点开始（host 视角）
    app.mp_mode = True
    app.mp_role = "host"
    app.mp_opp_name = "对手"
    app.mp_room_id = 1
    app.deck_nation = "德国"
    app.mp_my_deck = [c.name for c in core.build_deck("德国", db)]
    app.mp_opp = {"m": "ready", "nation": "苏联", "deck": opp_deck}
    app._mp_me_ready = True
    app.mp_link = FakeLink([])
    # 模拟组卡页存在
    app._build_deck_builder("德国", mp=True)
    app.update()

    if mode == "mp":
        seed = 12345          # 奇数 → 房主先手
        try:
            app._mp_launch(seed)
        except Exception:
            traceback.print_exc()
            print("!!! _mp_launch 抛异常")
            return 1
    else:
        deck = [db[n] for n in app.mp_my_deck]
        try:
            app.new_game("德国", deck)
        except Exception:
            traceback.print_exc()
            print("!!! new_game 抛异常")
            return 1
    print(f"({mode}) 开局调用正常返回，pyboard =", app._pyboard)
    try:
        app.winfo_exists()
    except Exception:
        print(f"({mode}) App 已在开局过程中被销毁（卡出页面复现）")
        return 1
    # 泵几秒事件，让 pygame 主循环跑起来
    import time
    t0 = time.time()
    err = None
    while time.time() - t0 < 3.0:
        try:
            app.update()
        except Exception:
            err = traceback.format_exc()
            break
        time.sleep(0.02)
    if err:
        print("!!! update 泵期间异常：")
        print(err)
        return 1
    b = app._pyboard
    print("board alive:", b is not None and getattr(b, "running", "?"))
    # 检查 board 是否还在运行
    if b is not None:
        print("board.result =", getattr(b, "result", "?"))
        try:
            b.quit()
        except Exception:
            pass
    app.destroy()
    print("=== 复现脚本正常结束 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
