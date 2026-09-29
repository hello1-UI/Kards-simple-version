# -*- coding: utf-8 -*-
"""本地账号系统测试

运行: python debug/test_account.py
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 把 DATA_DIR 重定向到临时目录，避免污染真实用户数据
import kards_engine as core
core.DATA_DIR = tempfile.mkdtemp(prefix="kards_acc_test_")
# kards_account 在 import 时读取 DATA_DIR，需先改再导入
import kards_account as acc

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail else ""))


check("初始未登录", acc.current() is None)

ok, err = acc.register("指挥官小张", "secret1")
check("注册成功并自动登录", ok and acc.current() == "指挥官小张", err)

ok, err = acc.register("指挥官小张", "abc123")
check("重名注册被拒", not ok and "已被注册" in err, err)

ok, err = acc.register("x", "abc123")
check("用户名过短被拒", not ok)

ok, err = acc.register("坏/名字", "abc123")
check("非法字符被拒", not ok)

acc.logout()
check("退出登录", acc.current() is None)

ok, err = acc.login("指挥官小张", "wrongpw")
check("错误密码被拒", not ok and "密码错误" in err, err)

ok, err = acc.login("指挥官小张", "secret1")
check("正确密码登录", ok and acc.current() == "指挥官小张", err)

# 战绩
acc.stats_add("指挥官小张", "win")
acc.stats_add("指挥官小张", "win")
acc.stats_add("指挥官小张", "lose")
acc.stats_add("指挥官小张", "draw")
s = acc.get_stats("指挥官小张")
check("战绩 2胜1负1平", s == {"win": 2, "lose": 1, "draw": 1}, str(s))

# 卡组目录按账号隔离
d1 = acc.deck_dir("指挥官小张")
check("卡组目录含账号名", "指挥官小张" in d1 and os.path.isdir(d1), d1)

# 第二个账号互不干扰
ok, err = acc.register("player2", "pw1234")
check("第二账号注册", ok and acc.current() == "player2", err)
check("第二账号战绩为 0", acc.get_stats("player2") == {"win": 0, "lose": 0, "draw": 0})
acc.stats_add("player2", "win")
s2 = acc.get_stats("player2")
s1 = acc.get_stats("指挥官小张")
check("战绩互不干扰", s2["win"] == 1 and s1["win"] == 2)

# 引擎 set_decks_dir 切换
core.set_decks_dir(d1)
check("set_decks_dir 生效", core.DECKS_DIR == d1)
core.set_decks_dir(None)
check("set_decks_dir(None) 还原默认", core.DECKS_DIR == os.path.join(core.DATA_DIR, "decks"))

fails = [r for r in results if not r[1]]
print(f"\n=== 结果: {len(results) - len(fails)} 通过 / {len(fails)} 失败 ===")
sys.exit(1 if fails else 0)
