# -*- coding: utf-8 -*-
"""从 KARDS 官方 GraphQL API 拉取全量卡牌数据（简中），存为 debug/kards_cards_zh.json"""
import json
import os
import sys
import time
import urllib.request

API_URL = "https://herokuapi.kards.com/graphql"
LANGUAGE = "zh-Hans"
NATIONS = {1: "苏联", 2: "美国", 3: "日本", 4: "德国", 5: "英国",
           6: "法国", 7: "意大利", 8: "波兰", 9: "芬兰", 10: "澳新军团", 11: "中立"}

QUERY = """\
query getCards($language: String, $offset: Int, $nationIds: [Int], \
$kredits: [Int], $q: String, $type: [String], $rarity: [String], \
$set: [String], $showSpawnables: Boolean, $showExiles: Boolean, $showReserved: Boolean) {
  cards(
    language: $language
    first: 100
    offset: $offset
    nationIds: $nationIds
    kredits: $kredits
    q: $q
    type: $type
    set: $set
    rarity: $rarity
    showSpawnables: $showSpawnables
    showExiles: $showExiles
    showReserved: $showReserved
  ) {
    pageInfo { count hasNextPage __typename }
    edges { node { id cardId importId json reserved __typename } __typename }
    __typename
  }
}"""

HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": "https://www.kards.com",
    "referer": "https://www.kards.com/",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"),
}


def fetch_page(nation_ids, offset):
    payload = {
        "operationName": "getCards",
        "variables": {
            "language": LANGUAGE, "offset": offset, "nationIds": nation_ids,
            "kredits": None, "q": None, "type": None, "rarity": None, "set": None,
            "showSpawnables": False, "showExiles": True, "showReserved": False,
        },
        "query": QUERY,
    }
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode("utf-8"),
        headers=HEADERS, method="POST")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as exc:  # 网络抖动重试
            print(f"  retry {attempt + 1}: {exc}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("API 请求连续失败")


def fetch_all_cards():
    cards = {}
    for nid, name in NATIONS.items():
        offset, page = 0, 0
        while True:
            data = fetch_page([nid], offset)
            conn = data.get("data", {}).get("cards")
            if not conn:
                print(f"  [{name}] offset={offset} 无数据: {json.dumps(data)[:200]}")
                break
            for edge in conn["edges"]:
                node = edge["node"]
                try:
                    card = json.loads(node["json"])
                except (TypeError, ValueError):
                    continue
                card["_nationId"] = nid
                card["_nation"] = name
                card["_cardId"] = node["cardId"]
                key = f"{nid}:{node['cardId']}"
                cards[key] = card
            page += 1
            info = conn["pageInfo"]
            print(f"  [{name}] page {page} offset {offset} "
                  f"count={info['count']} more={info['hasNextPage']}")
            if not info["hasNextPage"]:
                break
            offset += 100
            time.sleep(0.4)
    return cards


if __name__ == "__main__":
    all_cards = fetch_all_cards()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kards_cards_zh.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(all_cards, fh, ensure_ascii=False, indent=1)
    print(f"共 {len(all_cards)} 张卡牌 -> {out}")
