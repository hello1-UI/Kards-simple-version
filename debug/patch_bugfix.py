# -*- coding: utf-8 -*-
"""bugfix 补丁 2026-09-23：
1. log() 控制台句柄失效（OSError: [Errno 22]）不再崩溃
2. [动员]加成只在受到实际伤害时移除（装甲完全抵消伤害时保留）
3. 大和号效果对之后部署的日军单位同样生效（原版语义）
4. 双倍力量复制卡用 deepcopy，避免手牌/卡组共享同一对象
5. AI 击杀判定计入[装甲]减免
"""
import io
import ast

PATH = "kards.py"
src = io.open(PATH, encoding="utf-8").read()
orig = src
applied = []


def rep(old, new, tag, expect=1):
    global src
    n = src.count(old)
    if n != expect:
        raise SystemExit(f"[{tag}] 期望 {expect} 处，实际 {n} 处")
    src = src.replace(old, new)
    applied.append(tag)


# ---- 1. log() 防 OSError ----
rep("""    def log(self, msg):
        print(msg)
        write_game_log(msg)""",
    """    def log(self, msg):
        try:
            print(msg)
        except Exception:
            pass    # 控制台句柄失效（窗口被关闭/管道断开）时不再崩溃
        try:
            write_game_log(msg)
        except Exception:
            pass""",
    "log-safe")

# ---- 2. 动员：只有实际受到伤害才移除加成 ----
rep("""            if unit.mob:      # [动员]加成在受伤时移除""",
    """            if amount > 0 and unit.mob:   # [动员]加成只在受到实际伤害时移除（被装甲完全抵消则保留）""",
    "mob-armor")

# ---- 3. 大和号：后续部署的日军单位也获得亡计 ----
rep("""        self.ats_mark = 0       # 本土防卫军标记（1/2=标记方索引+1，0=无）""",
    """        self.ats_mark = 0       # 本土防卫军标记（1/2=标记方索引+1，0=无）
        self.yamato = False     # 大和号坐镇：之后部署的日军单位也获得[亡计]""",
    "player-yamato")
rep("""def effect_yamato(game, caster):
    \"\"\"大和号: 你的所有日军单位获得 亡计：对敌方总部造成 2 点伤害\"\"\"
    n = 0""",
    """def effect_yamato(game, caster):
    \"\"\"大和号: 你的所有日军单位（含之后部署的）获得 亡计：对敌方总部造成 2 点伤害\"\"\"
    caster.yamato = True
    n = 0""",
    "yamato-flag")
rep("""        u = Unit(card, p)
        u.slot = self.next_slot(p)
        p.board.append(u)""",
    """        u = Unit(card, p)
        u.slot = self.next_slot(p)
        if p.yamato and card.nation == "日本":
            u.dying_hq = 2
            self.log(f"  [大和号] {u.name} 获得 [亡计：对敌方总部 2 伤]。")
        p.board.append(u)""",
    "deploy-yamato")

# ---- 4. 双倍力量 deepcopy ----
rep("""import os
import random
import re
import sys
import time""",
    """import copy
import os
import random
import re
import sys
import time""",
    "import-copy")
rep("""    c = random.choice(orders)
    caster.deck.insert(random.randrange(len(caster.deck) + 1), c)
    game.log(f"  双倍力量：复制了一张 [ {c.name} ] 洗入卡组。")""",
    """    c = random.choice(orders)
    caster.deck.insert(random.randrange(len(caster.deck) + 1), copy.deepcopy(c))
    game.log(f"  双倍力量：复制了一张 [ {c.name} ] 洗入卡组。")""",
    "double-strength-copy")

# ---- 5. AI 击杀判定计入装甲 ----
rep("""                    killable = [t for t in targets if u.attack >= t.defense]""",
    """                    killable = [t for t in targets if u.attack - t.armor >= t.defense]""",
    "ai-armor")

ast.parse(src)
if src == orig:
    raise SystemExit("没有任何改动")
io.open(PATH, "w", encoding="utf-8", newline="").write(src)
print("OK, 应用补丁:", ", ".join(applied))
