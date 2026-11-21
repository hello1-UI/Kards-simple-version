# -*- coding: utf-8 -*-
"""用带 tkinter 但**没有 pygame** 的解释器验证：
1) 视图兜底方法齐全可调；
2) _activate_pyboard 失败返回 None；
3) new_game / _mp_launch 激活失败时明确报错且不开局（用假 messagebox 截获）。
运行: py debug/test_no_pygame_path.py
"""
import io
import contextlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name +
          (f"  [{detail}]" if detail and not cond else ""))


def main():
    try:
        import tkinter
    except Exception as exc:
        print("  [--] 无 tkinter，跳过（请用系统 Python 运行）", exc)
        return
    try:
        import pygame  # noqa: F401
        print("  [--] 本解释器装有 pygame，此测试意义不大，跳过")
        return
    except Exception:
        pass

    sys.argv.append("--no-update-check")
    import KARDS as K
    import kards_i18n as i18n

    # 截获弹窗（无头环境不能真的弹框等待）
    err_calls = []
    K.messagebox.showerror = lambda *a, **k: err_calls.append(a)
    K.messagebox.showinfo = lambda *a, **k: err_calls.append(("info", a))
    K.messagebox.showwarning = lambda *a, **k: err_calls.append(("warn", a))

    app = K.App()
    app.update()

    # 1) 兜底
    missing = [a for a in K.App._PY_VIEW_ATTRS
               if not callable(getattr(app, a, None))]
    check("视图兜底齐全", not missing, str(missing))
    try:
        app.refresh()
        app.show_banner("兜底", "#fff", 10)
        check("兜底调用不报错", True)
    except Exception as exc:                       # noqa: BLE001
        check("兜底调用不报错", False, repr(exc))

    # 2) 激活失败
    check("无 pygame 时激活失败返回 None", app._activate_pyboard() is None)
    check("失败后 _pyboard 为 None", app._pyboard is None)

    # 3) new_game 激活失败 → 报错不开局
    n0 = len(err_calls)
    app.new_game("德国")
    check("new_game 报 err_need_pygame",
          any("need_pygame" in str(a) or "pygame" in str(a) for a in err_calls[n0:]),
          str(err_calls[n0:]))
    check("new_game 不创建对局", app.game is None)

    # 4) _mp_launch 激活失败 → 报错 + 清理回大厅
    core = __import__("kards_engine")
    unit = core.card_database()["步兵班"]
    app.mp_my_deck = [unit.name] * core.DECK_SIZE
    app.mp_opp = {"deck": [unit.name] * core.DECK_SIZE, "nation": "苏联"}
    n0 = len(err_calls)
    with contextlib.redirect_stdout(io.StringIO()):
        app._mp_launch(42)
    check("_mp_launch 报 err_need_pygame",
          any("need_pygame" in str(a) or "pygame" in str(a) for a in err_calls[n0:]),
          str(err_calls[n0:]))
    check("_mp_launch 不创建对局", app.game is None)

    print("=" * 60)
    print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        sys.exit(1)
    print("全部通过 ✓")


if __name__ == "__main__":
    main()
