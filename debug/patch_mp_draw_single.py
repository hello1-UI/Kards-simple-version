# -*- coding: utf-8 -*-
"""联机「两边都会赢」修复 + 单实例启动：
1. 同归于尽（双方总部同时 <=0）判平局，不再每边各判自己赢
   - kards_gui.finish(): winner=None 平局；show_end_animation 支持 won=None
   - kards.py run(): CLI 同样输出平局
   - i18n 增加 draw_big/draw_sub（zh/en/ja）
2. 单实例：kards_gui main() 启动时用命名互斥体检测，已有实例则
   提示「游戏已经在运行」并把已有窗口调到最前面后退出
   （--smoke / --debug-on-net 不受限制）
"""
import ast
import io

GUI = "kards_gui.py"
CORE = "kards.py"
I18N = "kards_i18n.py"
applied = []


def rep(path, old, new, tag, expect=1):
    src = io.open(path, encoding="utf-8").read()
    n = src.count(old)
    if n != expect:
        raise SystemExit(f"[{tag}] 期望 {expect} 处，实际 {n} 处")
    src = src.replace(old, new)
    ast.parse(src)
    io.open(path, "w", encoding="utf-8", newline="").write(src)
    applied.append(tag)


# ---- 1a. finish(): 平局判定 ----
rep(GUI,
    '''        if winner is None:
            winner = g.players[0] if g.players[1].hq <= 0 else g.players[1]
        me = g.players[0]
        won = winner is me
        self.add_log(f"战斗结束！{winner.name} 获胜！")''',
    '''        if winner is None:
            if g.players[0].hq <= 0 and g.players[1].hq <= 0:
                winner = None            # 同归于尽：平局
            else:
                winner = g.players[0] if g.players[1].hq <= 0 else g.players[1]
        me = g.players[0]
        if winner is None:
            won = None
            self.add_log("战斗结束！双方总部同时陷落——平局！")
        else:
            won = winner is me
            self.add_log(f"战斗结束！{winner.name} 获胜！")''',
    "finish-draw")

# ---- 1b. show_end_animation: won=None 平局文案与表现 ----
rep(GUI,
    '''        txt = i18n.t("win_big") if won else i18n.t("lose_big")
        color = GOLD if won else RED''',
    '''        if won is None:
            txt, color = i18n.t("draw_big"), DIM
        else:
            txt, color = (i18n.t("win_big"), GOLD) if won else (i18n.t("lose_big"), RED)''',
    "anim-title")

rep(GUI,
    '''        sub = tk.Label(overlay,
                       text=i18n.t("win_sub") if won else i18n.t("lose_sub"),
                       bg="#0d1017", fg=DIM, font=FONT_B)''',
    '''        sub = tk.Label(overlay,
                       text=i18n.t("win_sub") if won is True
                       else (i18n.t("lose_sub") if won is False else i18n.t("draw_sub")),
                       bg="#0d1017", fg=DIM, font=FONT_B)''',
    "anim-sub")

rep(GUI,
    '''        if won:
            # 粒子庆祝：小星星从下往上飘散''',
    '''        if won is None:
            pass                      # 平局：无庆祝/无震动
        elif won:
            # 粒子庆祝：小星星从下往上飘散''',
    "anim-fx")

# ---- 1c. CLI run(): 同归于尽输出平局 ----
rep(CORE,
    '''        winner = self.players[0] if self.players[1].hq <= 0 else self.players[1]
        print(f"\\n{'='*40}")
        print(f"  战斗结束！{winner.name} 获胜！")
        print(f"{'='*40}")
        return winner''',
    '''        if self.players[0].hq <= 0 and self.players[1].hq <= 0:
            winner = None             # 同归于尽：平局
        else:
            winner = self.players[0] if self.players[1].hq <= 0 else self.players[1]
        print(f"\\n{'='*40}")
        if winner is None:
            print("  战斗结束！双方总部同时陷落——平局！")
        else:
            print(f"  战斗结束！{winner.name} 获胜！")
        print(f"{'='*40}")
        return winner''',
    "cli-draw")

# ---- 1d. i18n 三语言包加 draw_big/draw_sub ----
rep(I18N,
    '''        "win_sub": "战场已被你掌控，指挥官！",
        "lose_sub": "总部沦陷……再接再厉，指挥官。",''',
    '''        "win_sub": "战场已被你掌控，指挥官！",
        "lose_sub": "总部沦陷……再接再厉，指挥官。",
        "draw_big": "⚔  平  局  ⚔",
        "draw_sub": "双方总部同时陷落，胜负未分。",''',
    "i18n-zh")

rep(I18N,
    '''        "win_sub": "The battlefield is yours, Commander!",
        "lose_sub": "HQ has fallen… regroup and try again, Commander.",''',
    '''        "win_sub": "The battlefield is yours, Commander!",
        "lose_sub": "HQ has fallen… regroup and try again, Commander.",
        "draw_big": "⚔  D R A W  ⚔",
        "draw_sub": "Both HQs fell together. No victor this day.",''',
    "i18n-en")

rep(I18N,
    '''        "win_sub": "戦場はあなたのものです、指揮官！",
        "lose_sub": "本部陥落……再挑戦しましょう、指揮官。",''',
    '''        "win_sub": "戦場はあなたのものです、指揮官！",
        "lose_sub": "本部陥落……再挑戦しましょう、指揮官。",
        "draw_big": "⚔  引 き 分 け  ⚔",
        "draw_sub": "両方の本部が同時に陥落しました。",''',
    "i18n-ja")

# ---- 2. 单实例 ----
rep(GUI,
    '''FONT = ("Microsoft YaHei UI", 12)''',
    '''APP_TITLE = "KARDS 简化版 - 二战卡牌对战"

FONT = ("Microsoft YaHei UI", 12)''',
    "app-title-const")

rep(GUI,
    '''        self.title("KARDS 简化版 - 二战卡牌对战")''',
    '''        self.title(APP_TITLE)''',
    "use-title-const")

rep(GUI,
    '''def main():
    core.setup_error_log()
    if "--debug-on-net" in sys.argv:
        run_debug_net()
        return
    app = App()''',
    '''def _another_instance_running():
    """Windows 下用命名互斥体检测是否已有实例在运行；若有则提示并聚焦旧窗口"""
    if sys.platform != "win32":
        return False
    import ctypes
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    k32.CreateMutexW(None, False, "KARDS_SIMPLE_SINGLETON")
    if k32.GetLastError() != 183:      # ERROR_ALREADY_EXISTS
        return False
    hwnd = u32.FindWindowW(None, APP_TITLE)
    if hwnd:
        u32.ShowWindow(hwnd, 9)        # SW_RESTORE
        u32.SetForegroundWindow(hwnd)
        u32.FlashWindow(hwnd, True)
    u32.MessageBoxW(None, "游戏已经在运行了！已为你切换到已打开的窗口。",
                    APP_TITLE, 0x40)   # MB_ICONINFORMATION
    return True


def main():
    core.setup_error_log()
    if "--debug-on-net" in sys.argv:
        run_debug_net()
        return
    if "--smoke" not in sys.argv and _another_instance_running():
        return
    app = App()''',
    "single-instance")

ast.parse(io.open(GUI, encoding="utf-8").read())
ast.parse(io.open(CORE, encoding="utf-8").read())
print("OK, 应用补丁:", ", ".join(applied))
