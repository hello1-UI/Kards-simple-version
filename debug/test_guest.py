# -*- coding: utf-8 -*-
"""游客规则测试：未登录 = 游客，能打人机，不能联机（产品规则 2026-10-02）

规则要点：
  · 未登录即游客；游客**可以玩人机**（单机流程不受影响）
  · 游客**不能联机**：大厅里点快速匹配/建房/输码会被拦下并弹登录窗
  · 游客是**临时会话，退出即弃**：不写 accounts.json、不写 session.json、
    卡组落在系统临时目录，关掉游戏就没了
  · 登录/注册成功后立刻脱离游客；登出回到游客

必须用**系统 Python**（受控 Python 无 tkinter）：
    C:\\Users\\freet\\AppData\\Local\\Programs\\Python\\Python313\\python.exe debug/test_guest.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PASS, FAIL = [], []


def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [!!] ") + label + (f"  {extra}" if extra else ""))


def main():
    tmp = tempfile.mkdtemp(prefix="kards_guest_test_")
    import kards_account as account
    import kards_i18n as i18n
    import kards_engine as core

    account._ACCOUNTS = os.path.join(tmp, "accounts.json")
    account._SESSION = os.path.join(tmp, "session.json")
    core.DATA_DIR = tmp
    core.set_decks_dir(None)

    print("1. 游客状态机（纯逻辑，不碰界面）")
    check("全新进程：未登录", account.current() is None)
    check("未 start_guest 前不算游客", not account.is_guest())
    account.start_guest()
    check("start_guest 后是游客", account.is_guest())
    check("游客的显示名是哨兵值", account.as_guest() == account.GUEST, account.as_guest())
    check("游客不能联机", not account.can_play_online())

    print("2. 游客不落盘（退出即弃）")
    check("游客不写 accounts.json", not os.path.exists(account._ACCOUNTS))
    check("游客不写 session.json", not os.path.exists(account._SESSION))
    gd = account.guest_decks_dir()
    check("游客卡组目录在系统临时区（不在用户数据目录）",
          gd is not None and os.path.normcase(os.path.abspath(gd)).startswith(
              os.path.normcase(os.path.abspath(tempfile.gettempdir()))), gd)
    check("游客不建 decks_<账号> 目录",
          not any(n.startswith("decks_") for n in os.listdir(tmp)), os.listdir(tmp))

    print("3. 游客玩人机：单机流程不受影响")
    # 人机不需要账号 —— 随便挑一个主国，验证"能用默认卡组数据库建卡组"
    deck = core.build_deck(core.MAIN_NATIONS[0], core.card_database())
    check("游客能构建人机卡组", len(deck) > 0, f"{len(deck)} 张")
    # 单机不依赖 account.online()
    check("游客状态下 online() 为假（本来就没连服务器）", not account.online())

    print("4. 登录后脱离游客")
    ok, err = account.register("GuestTester", "pw12345")
    check("注册成功", ok, err)
    account.start_guest()          # 故意再置一次，验证 is_guest 会看 current()
    check("已有正式账号时不误判为游客", not account.is_guest())
    check("as_guest 返回正式账号名", account.as_guest() == "GuestTester", account.as_guest())
    check("注册后账号库落盘", os.path.exists(account._ACCOUNTS))

    print("5. 登出回到游客")
    account.logout()
    check("登出后是游客", account.is_guest())
    check("登出后 current 为 None", account.current() is None)
    check("登出后 as_guest 回到哨兵", account.as_guest() == account.GUEST)

    print("6. 文案齐备（三语言）")
    for key in ("guest_name", "guest_btn", "guest_note",
                "srv_need_login", "srv_need_login_title", "btn_login_or_reg"):
        for lang in ("zh", "en", "ja"):
            i18n.set_lang(lang)
            v = i18n.t(key)
            check(f"{lang} 有 {key}", bool(v) and v != key, str(v)[:40] if v != key else "缺键")
    i18n.set_lang("zh")
    # 游客提示里应说明"不能联机"，避免用户以为按钮坏了
    check("游客说明含「人机」与「联机」", "人机" in i18n.t("guest_note")
          and "联机" in i18n.t("guest_note"), i18n.t("guest_note"))
    check("登录按钮文案提到游客限制", "游客" in i18n.t("btn_login_or_reg"),
          i18n.t("btn_login_or_reg"))

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
