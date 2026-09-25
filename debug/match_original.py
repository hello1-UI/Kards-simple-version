# -*- coding: utf-8 -*-
"""把本作卡池与原版 CSV（; 分隔）按英文名匹配，输出对照报告 debug/original_match.txt"""
import csv
import io
import re

OUR_CARDS = {
    # 中文名: 候选原版英文名（按优先级）
    "步兵班": ["Infantry Squad"],
    "装甲掷弹兵": ["Panzergrenadiers"],
    "山地猎兵": ["Gebirgsjager", "Gebirgsjäger", "Mountain Infantry"],
    "Bf-109战斗机": ["Bf-109", "Messerschmitt Bf 109"],
    "四号坦克": ["Panzer IV"],
    "88毫米炮": ["88mm Flak", "8.8cm Flak", "88mm Flak 36"],
    "三号突击炮": ["StuG III", "Sturmgeschutz III", "Sturmgeschütz III"],
    "追猎者坦克歼击车": ["Hetzer"],
    "斯图卡俯冲轰炸机": ["Stuka", "Ju 87 Stuka"],
    "虎式坦克": ["Tiger", "Tiger I"],
    "闪电战": ["Blitzkrieg", "Lightning War"],
    "反坦克炮": ["Anti-tank Gun", "AT Gun", "PaK 36", "Anti-Tank Gun"],
    "动员兵": ["Conscript"],
    "波波沙冲锋队": ["PPSh", "PPSh-41", "PPSh Squad"],
    "近卫步兵": ["Guards Infantry"],
    "拉-7战斗机": ["La-7", "Lavochkin La-7"],
    "T-34坦克": ["T-34"],
    "惩戒营": ["Penal Battalion", "Penal Battalion ", "Shtrafbat"],
    "SU-85坦克歼击车": ["SU-85", "SU-85 Tank Destroyer"],
    "伊尔-2攻击机": ["Il-2", "IL-2", "Ilyushin Il-2"],
    "喀秋莎": ["Katyusha", "BM-13 Katyusha", "BM-13"],
    "IS-2重型坦克": ["IS-2", "IS-2 Stalin", "Iosif Stalin"],
    "为了祖国": ["For the Motherland"],
    "游骑兵": ["Rangers"],
    "伞兵连": ["Paratroopers"],
    "海军陆战队": ["Marines", "US Marines"],
    "谢尔曼坦克": ["Sherman", "M4 Sherman"],
    "P-51野马": ["P-51", "P-51 Mustang"],
    "M10狼獾": ["M10 Wolverine", "M10"],
    "远程榴弹炮": ["M2A1 Howitzer", "105mm Howitzer", "Long Tom", "M1 155mm"],
    "M4A3E8": ["M4A3E8", "M4A3E8 Easy Eight", "Easy Eight"],
    "B-17空中堡垒": ["B-17", "B-17 Flying Fortress"],
    "步兵增援": ["Infantry Reinforcement", "Reinforcements"],
    "防空火力": ["AA Gun", "Anti-Aircraft Gun", "Flak Gun"],
    "本土防卫军": ["Home Guard"],
    "特种空勤团": ["SAS"],
    "廓尔喀步枪团": ["Gurkha Rifles", "Gurkha"],
    "喷火战斗机": ["Spitfire", "Supermarine Spitfire"],
    "克伦威尔坦克": ["Cromwell"],
    "德哈维兰蚊式": ["Mosquito", "De Havilland Mosquito", "de Havilland Mosquito"],
    "丘吉尔坦克": ["Churchill"],
    "兰开斯特轰炸机": ["Lancaster", "Avro Lancaster"],
    "战地医疗": ["Field Medic", "Medical Aid", "First Aid", "Field Hospital"],
    "皇家海军炮击": ["Naval Support", "Royal Navy", "Naval Bombardment", "Offshore Bombardment"],
    "总动员": ["Total Mobilization", "Mobilization"],
    "战术欺骗": ["Tactical Deception", "Deception", "Counter Intelligence"],
    "步兵联队": ["Infantry Regiment"],
    "九五式轻战车": ["Type 95", "Type 95 Ha-Go", "Ha-Go"],
    "丛林渗透队": ["Jungle Patrol", "Jungle Warfare", "Jungle Raider"],
    "零式战斗机": ["Zero", "A6M Zero", "Mitsubishi Zero"],
    "海军特别陆战队": ["Special Naval Landing Force", "SNLF"],
    "隼式战斗机": ["Hayabusa", "Ki-43", "Nakajima Ki-43"],
    "九七式坦克": ["Type 97", "Type 97 Chi-Ha", "Chi-Ha"],
    "神风特攻队": ["Kamikaze"],
    "大和号战列舰": ["Yamato"],
    "万岁冲锋": ["Banzai", "Banzai Charge"],
    "舰炮支援": ["Naval Gun Support", "Gun Support", "Artillery Support"],
    "黑衫军": ["Blackshirts", "Black Shirts"],
    "M13/40坦克": ["M13/40", "M 13/40"],
    "意大利炮兵团": ["Artillery Regiment", "Italian Artillery"],
    "炮火准备": ["Barrage", "Artillery Barrage", "Preparation Barrage"],
    "山地伏击": ["Mountain Ambush", "Ambush"],
    "殖民步兵": ["Colonial Infantry", "Colonials"],
    "索玛S35": ["Somua S35", "S35"],
    "抵抗网络": ["Resistance Network", "The Resistance"],
    "地下抵抗": ["Underground Resistance", "The Underground", "Partisans"],
    "芬兰猎兵": ["Sissi", "Jaakari", "Jaeger", "Finnish Jaeger"],
    "芬兰狙击手": ["Finnish Sniper", "Sniper", "Marksman"],
    "冬季战争": ["Winter War"],
    "雪地伏击": ["Winter Ambush", "Snow Ambush"],
    "波兰枪骑兵": ["Polish Lancers", "Lancers", "Uhlans"],
    "华沙守军": ["Warsaw Defender", "Defenders of Warsaw", "Warsaw Garrison"],
    "翼骑兵冲锋": ["Winged Hussars", "Cavalry Charge", "Hussar Charge"],
    "华沙战士": ["Warsaw Fighter", "Warsaw Uprising"],
    "长程沙漠群": ["Long Range Desert Group", "LRDG"],
    "第25澳新营": ["25th ANZAC Battalion", "25th Anzac Battalion"],
    "RAAF飓风": ["RAAF Hurricane", "Hurricane"],
    "澳新风暴": ["ANZAC Storm", "Anzac Storm"],
    "澳新军团精神": ["Spirit of ANZAC", "Spirit of the ANZAC", "ANZAC Spirit"],
    "滩头阵地": ["Beachhead", "Beach Head"],
}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


rows = []
with io.open("debug/all_cards_original.csv", encoding="utf-8", newline="") as fh:
    reader = csv.DictReader(fh, delimiter=";")
    rows = list(reader)

print(f"原版卡牌 {len(rows)} 张")

by_norm = {}
for r in rows:
    t = (r.get("title en-EN") or "").strip()
    if t:
        by_norm.setdefault(norm(t), []).append(r)

FLAG_COLS = ["blitz", "mobilize", "smokescreen", "fury", "pincer", "alpine",
             "guard", "ambush", "intel3", "heavyArmor1", "intel2", "heavyArmor2"]

out = io.open("debug/original_match.txt", "w", encoding="utf-8")
matched, missed = 0, []
for zh, candidates in OUR_CARDS.items():
    hit = None
    for cand in candidates:
        lst = by_norm.get(norm(cand))
        if lst:
            # 同名多张时优先精确小写匹配
            hit = lst[0]
            break
    if not hit:
        missed.append((zh, candidates))
        out.write(f"\n### {zh}\n  !! 未匹配 候选={candidates}\n")
        continue
    matched += 1
    flags = [c for c in FLAG_COLS if (hit.get(c) or "").strip().lower() in ("1", "true", "yes")]
    out.write(f"\n### {zh}  ->  {hit.get('title en-EN')} ({hit.get('title zh-Hans', '')})\n")
    out.write(f"  国家={hit.get('faction')} 类型={hit.get('type')} 费用={hit.get('kredits')} "
              f"攻={hit.get('attack')} 防={hit.get('defense')} 稀有={hit.get('rarity')}\n")
    out.write(f"  关键词旗标: {', '.join(flags) if flags else '无'}\n")
    out.write(f"  原文(中): {(hit.get('text zh-Hans') or '(空)')}\n")
    out.write(f"  原文(英): {(hit.get('text en-EN') or '(空)')}\n")
out.close()
print(f"匹配 {matched}/{len(OUR_CARDS)}，报告 -> debug/original_match.txt")
print("未匹配:", [m[0] for m in missed])
