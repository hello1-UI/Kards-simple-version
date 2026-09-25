# -*- coding: utf-8 -*-
"""
KARDS 简化版 —— 多语言支持

- 三种语言：简体中文 / English / 日本語
- 语言包集中在 LANGS，界面文本通过 t("key") 取当前语言
- 偏好保存在程序目录 settings.json（源码运行=模块目录；打包运行=exe 同目录），
  启动时自动恢复；无设置文件时默认简体中文
"""

import json
import os
import sys

# 打包(PyInstaller)运行时 __file__ 指向 _internal 临时目录，需改用 exe 所在目录
if getattr(sys, "frozen", False):
    _APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))
_SETTINGS_PATH = os.path.join(_APP_DIR, "settings.json")

# 语言显示名（固定，不随语言切换）
LANG_NAMES = {
    "zh": "简体中文",
    "en": "English",
    "ja": "日本語",
}

# 默认语言
_current = {"lang": "zh"}

# ---------------------------------------------------------------- 语言包
# zh 为基准包（缺 key 时兜底）；en / ja 只需覆盖需要翻译的 key

LANGS = {
    "zh": {
        # ---- 主界面 ----
        "app_title": "KARDS 简化版",
        "app_subtitle": "二战卡牌对战",
        "btn_settings": "⚙ 设置",
        "battle_title": "⚔ 战斗",
        "battle_sub": "联机对战（局域网）\n主机 / 加入，与好友实时对战",
        "practice_title": "🎯 练习",
        "practice_sub": "与人机 AI 对战\n可自组卡组 · 随机匹配",
        # ---- 设置 ----
        "settings_title": "设置",
        "settings_language": "语言 / Language",
        "btn_help": "📖 操作说明",
        "btn_quit": "🚪 退出游戏",
        "help_title": "操作说明",
        "help_text": (
            "· 拖拽手牌到「我方支援阵线」部署单位\n"
            "· 拖拽我方单位到敌方单位/总部进行攻击\n"
            "· 拖到「我方前线」行上前线，拖回支援阵线撤后\n"
            "· [闪击]部署当回合即可攻击；[冲击]攻击免反击（消耗）\n"
            "· [警卫]保护相邻目标；#0位警卫保护总部\n"
            "· 只有前线单位能攻击敌方总部；打单位未死会吃反击\n"
            "· [收缴]消灭敌方单位时缴获一张 1/1 副本入手牌\n"
            "· 联机：⚔ 战斗 → 主机/加入（局域网 TCP，默认端口 5555）"),
        "quit_title": "退出游戏",
        "quit_confirm": "确定退出 KARDS 吗？",
        # ---- 联机大厅 ----
        "lobby_title": "联机对战",
        "lobby_sub": "同一局域网内 TCP 直连（默认端口 5555，可自行修改）",
        "btn_back": "← 返回",
        "host_title": "🏠 主机对战（等待好友加入）",
        "join_title": "🔗 加入对战（连接主机）",
        "label_port": "端口:",
        "label_host_ip": "主机 IP:",
        "btn_start_wait": "开始等待连接",
        "btn_connect": "连接",
        "host_connected": "✅ 对手已连接！请选择阵营组卡。",
        "join_connected": "✅ 已连接到主机！请选择阵营组卡。",
        "host_fail": "⚠ 等待失败：{err}",
        "join_fail": "⚠ 连接失败：{err}",
        "warn_port_title": "端口",
        "warn_port_range": "端口必须是 1-65535 的数字。",
        "warn_port_num": "端口必须是数字。",
        "warn_ip_title": "IP",
        "warn_ip": "请输入主机 IP。",
        "host_fail_title": "主机失败",
        "host_fail_msg": "无法监听端口 {port}:\n{err}\n可能被占用或被防火墙拦截。",
        "host_waiting": "等待连接中…（0.0.0.0:{port}）把本机 IP 告诉好友吧。",
        "connecting": "连接中…（{ip}:{port}，超时 6 秒）",
        # ---- 阵营选择 / 组卡 ----
        "mode_mp": "联机模式",
        "mode_sp": "练习模式",
        "nation_sub": "选择主国（总部卡自带研发被动），之后自由组建卡组",
        "btn_import": "导入卡组",
        "btn_save": "保存卡组",
        "btn_load": "载入卡组",
        "btn_recommend": "推荐卡组",
        "btn_clear": "清空",
        "btn_start_mp": "开始对战",
        "btn_start_sp": "开始战斗",
        "label_pool": "可选用卡（点击加入卡组）",
        "label_deck": "当前卡组（点击移除）",
        "legend": "稀有度：普通（无标）｜{legend}",
        "deck_empty": "（卡组为空，点击左侧卡牌加入）",
        "ally_count": "盟国 {ally}/{limit}",
        "copies": "   （已带 {n}/{max}）",
        "import_prompt": "粘贴卡牌清单，每行一张卡：",
        "import_hint": ("支持格式：'3 谢尔曼坦克' / '谢尔曼坦克 x3' / '3x Sherman Tank'\n"
                        "原版英文名可自动识别（Sherman Tank、T-34、Spitfire、Zero 等）。\n"
                        "导入后未识别的行会被忽略，不足的张数可在下方手动补齐。"),
        "btn_import_go": "导入",
        "import_result_title": "导入结果",
        "import_result": "成功导入 {n} 张卡牌（上限裁剪后 {m} 张）。",
        "import_unmatched": "\n未识别 {k} 行（示例: {samples}），可在下方继续手动补卡。",
        "save_title": "保存卡组",
        "save_prompt": "给卡组起个名字：",
        "save_empty": "当前卡组为空，先加入一些卡牌再保存。",
        "save_ok": "卡组「{name}」已保存！\n文件：{path}\n下次组卡时点「载入卡组」即可一键恢复。",
        "load_title": "{nation} 的已保存卡组（点击载入）：",
        "load_none": "还没有保存过卡组。\n组好后点「保存卡组」即可保存。",
        "btn_close": "关闭",
        "load_missing": "找不到该卡组文件。",
        "load_ok": "已载入「{name}」（{n} 张）。\n不足 {size} 张可继续手动补卡。",
        # ---- 联机消息 ----
        "mp_title": "联机",
        "mp_disconnected": "连接已断开，请返回重新连接。",
        "waiting_opponent": "等待对手就绪…",
        "mp_peer_left_prep": "对手在准备阶段断开了连接。",
        "mp_bad_deck": "对手卡组数量异常，连接中止。",
        "mp_lost": "连接已断开。",
        "deck_invalid_title": "卡组不合法",
        # ---- 对局界面 ----
        "btn_ingame_settings": "⚙ 设置 / 投降",
        "log_title": "战场记录",
        "btn_slow": "🐢 慢速",
        "btn_fast": "🐇 快速",
        "btn_end_turn": "结束回合",
        "row_foe_rear": "敌方支援阵线",
        "row_foe_front": "敌方前线",
        "row_my_front": "我方前线",
        "row_my_rear": "我方支援阵线",
        "foe_hq": "敌方总部",
        "hq_hint": "拖我方单位到此攻击",
        "foe_no_units": "（敌方无单位）",
        "foe_front_empty": "（前线无单位）",
        "front_none": "⚔ 前线：无人占领（可抢占）",
        "front_mine": "⚔ 前线：我方占领 {n}/{total}",
        "front_foe": "⚔ 前线：敌方占领！先清掉敌方前线单位",
        "my_rear_empty": "（我方无单位，拖手牌到此行部署）",
        "my_front_empty": "（拖我方单位到此行上前线）",
        "hand_hidden": "（敌方回合 — 对手手牌保密）",
        "hand_empty": "（手牌已空）",
        "turn_tag": "   【敌方回合】",
        "foe_info": ("敌方  {name}（{nation}）   HQ {hq} HP   "
                     "手牌 {hand}   Kredits {kr}   反制 ❓×{cnt}{tag}"),
        "counter_zone": "   反制区: ",
        "my_info": ("我方  {name}（{nation}）   HQ {hq} HP   Kredits {kr}   "
                    "牌库 {deck}   {perk}{counters}"),
        # ---- 对局中设置 ----
        "btn_surrender": "🏳 投降",
        "btn_to_menu": "🏠 返回主菜单",
        "log_surrender": "  你选择了投降。",
        "surrender_title": "投降",
        "surrender_confirm": "确定投降吗？本局将判负。",
        "to_menu_title": "返回主菜单",
        "to_menu_confirm": "确定放弃本局并返回主菜单吗？",
        "quit_safe_confirm": "确定安全退出 KARDS 吗？",
        "leave_title": "退出本局",
        "leave_confirm": "确定要放弃本局并返回主菜单吗？",
        # ---- 结算动画 ----
        "win_big": "🏆  胜  利 ！",
        "lose_big": "💀  战  败 …",
        "win_sub": "战场已被你掌控，指挥官！",
        "lose_sub": "总部沦陷……再接再厉，指挥官。",
        "draw_big": "⚔  平  局  ⚔",
        "draw_sub": "双方总部同时陷落，胜负未分。",
        "click_hint": "▼ 点击屏幕回到大厅 ▼",
    },
    "en": {
        "app_title": "KARDS Lite",
        "app_subtitle": "WWII Card Battle",
        "btn_settings": "⚙ Settings",
        "battle_title": "⚔ Battle",
        "battle_sub": "Online play (LAN)\nHost / Join — real-time vs friends",
        "practice_title": "🎯 Practice",
        "practice_sub": "Play vs AI\nBuild your deck · random match",
        "settings_title": "Settings",
        "btn_help": "📖 How to Play",
        "btn_quit": "🚪 Quit",
        "help_title": "How to Play",
        "help_text": (
            "· Drag a hand card to 'My Support Line' to deploy\n"
            "· Drag my unit onto an enemy unit / HQ to attack\n"
            "· Drag to 'My Frontline' to advance; drag back to retreat\n"
            "· Blitz: can attack the turn deployed; Charge: no counterattack (consumed)\n"
            "· Guard protects adjacent slots; slot #0 Guard protects the HQ\n"
            "· Only frontline units can hit the enemy HQ; survivors counterattack\n"
            "· Confiscate: killing a unit adds a 1/1 copy to your hand\n"
            "· Online: Battle -> Host/Join (LAN TCP, default port 5555)"),
        "quit_title": "Quit",
        "quit_confirm": "Quit KARDS?",
        "lobby_title": "Online Battle",
        "lobby_sub": "TCP direct over LAN (default port 5555, editable)",
        "btn_back": "← Back",
        "host_title": "🏠 Host (waiting for a friend)",
        "join_title": "🔗 Join (connect to host)",
        "label_port": "Port:",
        "label_host_ip": "Host IP:",
        "btn_start_wait": "Start Waiting",
        "btn_connect": "Connect",
        "host_connected": "✅ Opponent connected! Pick a nation and build your deck.",
        "join_connected": "✅ Connected to host! Pick a nation and build your deck.",
        "host_fail": "⚠ Waiting failed: {err}",
        "join_fail": "⚠ Connect failed: {err}",
        "warn_port_title": "Port",
        "warn_port_range": "Port must be a number between 1 and 65535.",
        "warn_port_num": "Port must be a number.",
        "warn_ip_title": "IP",
        "warn_ip": "Enter the host IP.",
        "host_fail_title": "Host failed",
        "host_fail_msg": "Cannot listen on port {port}:\n{err}\nIt may be occupied or blocked by a firewall.",
        "host_waiting": "Waiting… (0.0.0.0:{port}) Share your IP with your friend.",
        "connecting": "Connecting… ({ip}:{port}, 6s timeout)",
        "mode_mp": "Online Mode",
        "mode_sp": "Practice Mode",
        "nation_sub": "Pick your main nation (HQ has a passive perk), then build your deck",
        "btn_import": "Import Deck",
        "btn_save": "Save Deck",
        "btn_load": "Load Deck",
        "btn_recommend": "Suggested",
        "btn_clear": "Clear",
        "btn_start_mp": "Start Battle",
        "btn_start_sp": "Start Battle",
        "label_pool": "Available cards (click to add)",
        "label_deck": "Current deck (click to remove)",
        "legend": "Rarity: Common (none) | {legend}",
        "deck_empty": "(Deck is empty — click cards on the left to add)",
        "ally_count": "Allies {ally}/{limit}",
        "copies": "   (owned {n}/{max})",
        "import_prompt": "Paste your deck list, one card per line:",
        "import_hint": ("Formats: '3 Sherman' / 'Sherman x3' / '3x Sherman Tank'\n"
                        "Original English names are recognized (Sherman Tank, T-34, Spitfire, Zero…).\n"
                        "Unrecognized lines are ignored; fill the rest by hand below."),
        "btn_import_go": "Import",
        "import_result_title": "Import Result",
        "import_result": "Imported {n} cards ({m} after cap trimming).",
        "import_unmatched": "\n{k} unrecognized lines (e.g. {samples}); add the rest by hand below.",
        "save_title": "Save Deck",
        "save_prompt": "Name this deck:",
        "save_empty": "Deck is empty — add some cards first.",
        "save_ok": "Deck \"{name}\" saved!\nFile: {path}\nUse Load Deck next time to restore it.",
        "load_title": "Saved decks for {nation} (click to load):",
        "load_none": "No saved decks yet.\nBuild one and click Save Deck.",
        "btn_close": "Close",
        "load_missing": "Deck file not found.",
        "load_ok": "Loaded \"{name}\" ({n} cards).\nAdd {size}-total by hand if short.",
        "mp_title": "Online",
        "mp_disconnected": "Connection lost — go back and reconnect.",
        "waiting_opponent": "Waiting for opponent…",
        "mp_peer_left_prep": "Opponent disconnected during setup.",
        "mp_bad_deck": "Opponent deck size invalid — connection aborted.",
        "mp_lost": "Connection lost.",
        "deck_invalid_title": "Invalid Deck",
        "btn_ingame_settings": "⚙ Settings / Surrender",
        "log_title": "Battle Log",
        "btn_slow": "🐢 Slow",
        "btn_fast": "🐇 Fast",
        "btn_end_turn": "End Turn",
        "row_foe_rear": "Enemy Support",
        "row_foe_front": "Enemy Frontline",
        "row_my_front": "My Frontline",
        "row_my_rear": "My Support",
        "foe_hq": "Enemy HQ",
        "hq_hint": "Drag my unit here to attack",
        "foe_no_units": "(No enemy units)",
        "foe_front_empty": "(Frontline empty)",
        "front_none": "⚔ Frontline: unoccupied (take it!)",
        "front_mine": "⚔ Frontline: ours {n}/{total}",
        "front_foe": "⚔ Frontline: enemy-held! Clear their frontline first",
        "my_rear_empty": "(No units — drag a hand card here to deploy)",
        "my_front_empty": "(Drag my unit here to advance)",
        "hand_hidden": "(Enemy turn — opponent's hand hidden)",
        "hand_empty": "(No cards in hand)",
        "turn_tag": "   [Enemy Turn]",
        "foe_info": ("Enemy  {name} ({nation})   HQ {hq} HP   "
                     "Hand {hand}   Kredits {kr}   Counters ❓×{cnt}{tag}"),
        "counter_zone": "   Counters: ",
        "my_info": ("Mine  {name} ({nation})   HQ {hq} HP   Kredits {kr}   "
                    "Deck {deck}   {perk}{counters}"),
        "btn_surrender": "🏳 Surrender",
        "btn_to_menu": "🏠 Main Menu",
        "log_surrender": "  You chose to surrender.",
        "surrender_title": "Surrender",
        "surrender_confirm": "Surrender? You will lose this game.",
        "to_menu_title": "Main Menu",
        "to_menu_confirm": "Abandon this game and return to the menu?",
        "quit_safe_confirm": "Quit KARDS safely?",
        "leave_title": "Leave Game",
        "leave_confirm": "Abandon this game and return to the menu?",
        "win_big": "🏆  V I C T O R Y !",
        "lose_big": "💀  D E F E A T …",
        "win_sub": "The battlefield is yours, Commander!",
        "lose_sub": "HQ has fallen… regroup and try again, Commander.",
        "draw_big": "⚔  D R A W  ⚔",
        "draw_sub": "Both HQs fell together. No victor this day.",
        "click_hint": "▼ Click anywhere to return to the lobby ▼",
    },
    "ja": {
        "app_title": "KARDS 簡易版",
        "app_subtitle": "第二次世界大戦カードバトル",
        "btn_settings": "⚙ 設定",
        "battle_title": "⚔ バトル",
        "battle_sub": "オンライン対戦（LAN）\nホスト / 参加、友達とリアルタイム対戦",
        "practice_title": "🎯 練習",
        "practice_sub": "AI と対戦\nデッキ構築可能 · ランダムマッチ",
        "settings_title": "設定",
        "btn_help": "📖 遊び方",
        "btn_quit": "🚪 終了",
        "help_title": "操作説明",
        "help_text": (
            "· 手札カードを「味方支援ライン」へドラッグして配置\n"
            "· 味方ユニットを敵ユニット/本部へドラッグして攻撃\n"
            "· 「味方前線」へドラッグで前進、支援ラインへ戻すと後退\n"
            "· 電撃：配置したターンに攻撃可；突撃：反撃を受けない（消費）\n"
            "· 護衛は隣接スロットを保護；#0番の護衛は本部も保護\n"
            "· 前線ユニットのみ敵本部を攻撃可；倒せなかった相手は反撃する\n"
            "· 接収：敵ユニットを倒すと 1/1 のコピーが手札に追加\n"
            "· オンライン：バトル → ホスト/参加（LAN TCP、既定ポート 5555）"),
        "quit_title": "終了",
        "quit_confirm": "KARDS を終了しますか？",
        "lobby_title": "オンライン対戦",
        "lobby_sub": "同一LAN内 TCP 直接接続（既定ポート 5555、変更可）",
        "btn_back": "← 戻る",
        "host_title": "🏠 ホスト（友達の参加を待機）",
        "join_title": "🔗 参加（ホストに接続）",
        "label_port": "ポート:",
        "label_host_ip": "ホスト IP:",
        "btn_start_wait": "接続待ち開始",
        "btn_connect": "接続",
        "host_connected": "✅ 対戦相手が接続しました！陣営を選んでデッキを組んでください。",
        "join_connected": "✅ ホストに接続しました！陣営を選んでデッキを組んでください。",
        "host_fail": "⚠ 待機失敗：{err}",
        "join_fail": "⚠ 接続失敗：{err}",
        "warn_port_title": "ポート",
        "warn_port_range": "ポートは 1-65535 の数字で入力してください。",
        "warn_port_num": "ポートは数字で入力してください。",
        "warn_ip_title": "IP",
        "warn_ip": "ホスト IP を入力してください。",
        "host_fail_title": "ホスト失敗",
        "host_fail_msg": "ポート {port} を監視できません:\n{err}\n使用中かファイアウォールで遮断されている可能性があります。",
        "host_waiting": "接続待ち中…（0.0.0.0:{port}）自分の IP を友達に教えてください。",
        "connecting": "接続中…（{ip}:{port}、タイムアウト 6 秒）",
        "mode_mp": "オンラインモード",
        "mode_sp": "練習モード",
        "nation_sub": "主国を選択（本部カードにパッシブあり）、その後デッキを構築",
        "btn_import": "デッキ取込",
        "btn_save": "デッキ保存",
        "btn_load": "デッキ読込",
        "btn_recommend": "推奨デッキ",
        "btn_clear": "クリア",
        "btn_start_mp": "対戦開始",
        "btn_start_sp": "戦闘開始",
        "label_pool": "使用可能カード（クリックで追加）",
        "label_deck": "現在のデッキ（クリックで除去）",
        "legend": "レアリティ：コモン（なし）｜{legend}",
        "deck_empty": "（デッキが空です。左のカードをクリックして追加）",
        "ally_count": "同盟 {ally}/{limit}",
        "copies": "   （所持 {n}/{max}）",
        "import_prompt": "デッキリストを貼り付け（1行に1枚）：",
        "import_hint": ("対応形式：'3 シャーマン' / 'シャーマン x3' / '3x Sherman Tank'\n"
                        "原名英語も認識（Sherman Tank、T-34、Spitfire、Zero など）。\n"
                        "認識できなかった行は無視され、残りは下で手動補充できます。"),
        "btn_import_go": "取込",
        "import_result_title": "取込結果",
        "import_result": "{n} 枚のカードを取込しました（上限調整後 {m} 枚）。",
        "import_unmatched": "\n認識できなかった {k} 行（例: {samples}）。下で手動補充できます。",
        "save_title": "デッキ保存",
        "save_prompt": "デッキに名前を付けてください：",
        "save_empty": "デッキが空です。先にカードを追加してください。",
        "save_ok": "デッキ「{name}」を保存しました！\nファイル：{path}\n次回は「デッキ読込」で一括復元できます。",
        "load_title": "{nation} の保存済みデッキ（クリックで読込）：",
        "load_none": "保存されたデッキはありません。\nデッキを組んで「デッキ保存」を押してください。",
        "btn_close": "閉じる",
        "load_missing": "デッキファイルが見つかりません。",
        "load_ok": "「{name}」を読込しました（{n} 枚）。\n{size} 枚に満たなければ手動で補充できます。",
        "mp_title": "オンライン",
        "mp_disconnected": "接続が切断されました。戻って再接続してください。",
        "waiting_opponent": "相手の準備を待っています…",
        "mp_peer_left_prep": "相手が準備中に切断しました。",
        "mp_bad_deck": "相手のデッキ枚数が不正のため接続を中止しました。",
        "mp_lost": "接続が切断されました。",
        "deck_invalid_title": "デッキ不正",
        "btn_ingame_settings": "⚙ 設定 / 降伏",
        "log_title": "戦闘ログ",
        "btn_slow": "🐢 スロー",
        "btn_fast": "🐇 高速",
        "btn_end_turn": "ターン終了",
        "row_foe_rear": "敵支援ライン",
        "row_foe_front": "敵前線",
        "row_my_front": "味方前線",
        "row_my_rear": "味方支援ライン",
        "foe_hq": "敵本部",
        "hq_hint": "味方ユニットをドラッグして攻撃",
        "foe_no_units": "（敵ユニットなし）",
        "foe_front_empty": "（前線にユニットなし）",
        "front_none": "⚔ 前線：誰も占領していない（奪取可）",
        "front_mine": "⚔ 前線：味方が占領 {n}/{total}",
        "front_foe": "⚔ 前線：敵が占領！まず敵前線ユニットを排除",
        "my_rear_empty": "（ユニットなし。手札をここへドラッグして配置）",
        "my_front_empty": "（味方ユニットをここへドラッグして前線へ）",
        "hand_hidden": "（相手ターン — 相手の手札は非公開）",
        "hand_empty": "（手札が空です）",
        "turn_tag": "   【相手ターン】",
        "foe_info": ("敵  {name}（{nation}）   HQ {hq} HP   "
                     "手札 {hand}   Kredits {kr}   対策 ❓×{cnt}{tag}"),
        "counter_zone": "   対策: ",
        "my_info": ("味方  {name}（{nation}）   HQ {hq} HP   Kredits {kr}   "
                    "デッキ {deck}   {perk}{counters}"),
        "btn_surrender": "🏳 降伏",
        "btn_to_menu": "🏠 メインメニュー",
        "log_surrender": "  降伏を選択しました。",
        "surrender_title": "降伏",
        "surrender_confirm": "降伏しますか？この試合は負けとなります。",
        "to_menu_title": "メインメニュー",
        "to_menu_confirm": "この試合を放棄してメインメニューに戻りますか？",
        "quit_safe_confirm": "KARDS を安全に終了しますか？",
        "leave_title": "試合を離脱",
        "leave_confirm": "この試合を放棄してメインメニューに戻りますか？",
        "win_big": "🏆  勝  利！",
        "lose_big": "💀  敗  北…",
        "win_sub": "戦場はあなたのものです、指揮官！",
        "lose_sub": "本部陥落……再挑戦しましょう、指揮官。",
        "draw_big": "⚔  引 き 分 け  ⚔",
        "draw_sub": "両方の本部が同時に陥落しました。",
        "click_hint": "▼ 画面をクリックしてロビーへ ▼",
    },
}


def load():
    """从 settings.json 恢复语言偏好（静默失败用默认值）"""
    try:
        with open(_SETTINGS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        lang = data.get("language")
        if lang in LANG_NAMES:
            _current["lang"] = lang
    except (OSError, ValueError):
        pass
    return _current["lang"]


def save():
    """把当前语言写入 settings.json"""
    try:
        data = {}
        try:
            with open(_SETTINGS_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        data["language"] = _current["lang"]
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


def get_lang():
    return _current["lang"]


def set_lang(code):
    if code not in LANG_NAMES:
        return False
    _current["lang"] = code
    save()
    return True


def t(key, **kw):
    """取当前语言文本；en/ja 缺 key 时回退中文；format 失败回退原文"""
    pack = LANGS.get(_current["lang"], LANGS["zh"])
    s = pack.get(key) or LANGS["zh"].get(key) or key
    if kw:
        try:
            s = s.format(**kw)
        except (KeyError, IndexError, ValueError):
            pass
    return s


load()   # 模块导入时恢复偏好
