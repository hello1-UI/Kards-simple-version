# -*- coding: utf-8 -*-
"""把《Kards各卡牌效果（残缺版）.txt》与当前卡池逐卡对照。

用法:
    python debug/check_card_doc.py [文档路径]

输出:
    - 文档卡片总数 / 命中数 / 缺失清单
    - 命中卡的费用/攻防/词条差异（数值层面对照）
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kards_engine as e  # noqa: E402

DOC = sys.argv[1] if len(sys.argv) > 1 else r"D:\Programs\P\P\TXT\Kards各卡牌效果（残缺版）.txt"


def norm(s):
    """去空白，便于对照（卡池里是 '第 4 先锋营'，文档里是 '第4先锋营'）。"""
    return re.sub(r"\s+", "", s or "")


# ---------------------------------------------------------------- 解析文档
lines = io.open(DOC, encoding="utf-8").read().splitlines()
cards = []          # (name, rarity, cost, act, atk, hp, keywords, effect, veteran)
i = 0
while i < len(lines):
    line = lines[i].rstrip()
    # 卡名行：名称 + 稀有度（或中立衍生牌无稀有度）
    m = re.match(r"^\t{3}(.+?)\s+(普通|精英|特殊|限定)$", line)
    m_tok = re.match(r"^\t{3}(.+)$", line) if "\t\t\t" in line and not m else None
    if m or (m_tok and lines[max(0, i - 1)].count("\t") == 2):
        name = (m.group(1) if m else m_tok.group(1)).strip()
        rar = m.group(2) if m else "衍生"
        # 细节行（\t\t\t\t 开头）
        j = i + 1
        while j < len(lines) and lines[j].startswith("\t\t\t\t"):
            det = lines[j].strip()
            vm = re.match(r"^(\d+)K\s+(\d+)/(\d+)\s+(.*)$", det)
            eff = None
            vet = None
            if vm:
                cost, atk, hp = int(vm.group(1)), int(vm.group(2)), int(vm.group(3))
                rest = vm.group(4).strip()
                # 老兵行在下一层
                if j + 1 < len(lines) and lines[j + 1].strip().startswith("老兵："):
                    vet = lines[j + 1].strip()
                    j += 1
                eff = rest or None
                cards.append(dict(name=name, rarity=rar, cost=cost, atk=atk,
                                  hp=hp, detail=eff, veteran=vet))
            elif det.startswith("获得") or det.startswith("对一个") or det.startswith("抽"):
                # 指令牌：0K/2K 无攻防
                cards.append(dict(name=name, rarity=rar, cost=None, atk=None,
                                  hp=None, detail=det, veteran=None))
            j += 1
        i = j
    else:
        i += 1

print(f"文档解析出 {len(cards)} 张卡")

# ---------------------------------------------------------------- 对照卡池
db = e.card_database()
by_norm = {norm(c.name): c for c in db.values()}

hit, miss, diff = [], [], []
for c in cards:
    key = norm(c["name"])
    card = by_norm.get(key)
    if card is None:
        miss.append(c["name"])
        continue
    hit.append(c["name"])
    probs = []
    if c["cost"] is not None and card.cost != c["cost"]:
        probs.append(f"费用 {card.cost}≠{c['cost']}")
    if c["atk"] is not None and getattr(card, "attack", None) not in (None, c["atk"]):
        probs.append(f"攻 {getattr(card, 'attack', '?')}≠{c['atk']}")
    if c["hp"] is not None and getattr(card, "defense", card.hp if hasattr(card, 'hp') else None) not in (None, c["hp"]):
        probs.append(f"防 {getattr(card, 'defense', '?')}≠{c['hp']}")
    if probs:
        diff.append((c["name"], "; ".join(probs)))

print(f"命中 {len(hit)} / 缺失 {len(miss)}")
print("命中:", hit)
if miss:
    print("\n--- 缺失（不在当前 214 张卡池）---")
    for n in miss:
        print("  ", n)
if diff:
    print("\n--- 数值差异 ---")
    for n, d in diff:
        print(f"  {n}: {d}")
