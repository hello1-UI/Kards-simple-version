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

# 打包(PyInstaller)运行时: 用户数据统一存到 %USERPROFILE%\AppData\Kards-Simple-Version
if getattr(sys, "frozen", False):
    _DATA_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Kards-Simple-Version")
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
    except OSError:
        _DATA_DIR = os.path.dirname(os.path.abspath(sys.executable))
    _SETTINGS_PATH = os.path.join(_DATA_DIR, "settings.json")
else:
    # 源码运行: 设置保存在项目根目录
    _SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "settings.json")

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
        # ---- 自动更新 ----
        "update_title": "检查更新",
        "btn_check_update": "检查更新",
        "update_checking": "正在检查更新…",
        "update_new": "发现新版本 {ver}（当前 {cur}）",
        "update_none": "已是最新版本 {cur}",
        "update_fail": "检查更新失败：{err}",
        "update_downloading": "正在下载 {done}%",
        "update_extracting": "正在解压 {done}%",
        "update_ready": "更新完成（{ver}）",
        "update_restart_needed": "更新已就绪，重启游戏后生效。",
        "update_restart_btn": "立即重启",
        "update_later_btn": "稍后",
        "update_btn_do": "立即更新",
        "update_btn_cancel": "取消",
        "update_btn_open_page": "打开发布页",
        "update_notes": "更新内容",
        "update_confirm": "检测到新版本 {ver}（当前 {cur}）。现在下载并安装吗？",
        "update_guest_hint": "更新不受游客/账号影响，任何人可用",
        "battle_title": "⚔ 战斗",
        "battle_sub": "联机对战（局域网）\n主机 / 加入，与好友实时对战",
        "practice_title": "🎯 练习",
        "practice_sub": "与人机 AI 对战\n可自组卡组 · 随机匹配",
        # ---- 设置 ----
        "settings_title": "设置",
        "settings_language": "语言 / Language",
        "btn_help": "📖 操作说明",
        "btn_keywords": "🔑 关键词说明",
        "kw_title": "关键词与机制说明",
        "kw_sub": "卡牌上会出现下面这些词，含义如下（对局中随时可查）",
        "kw_group_unit": "单位关键词",
        "kw_group_trigger": "触发类关键词",
        "kw_group_term": "规则术语",
        "kw_group_planned": "原版词条（本作暂未实装，供查阅规则）",
        "kw_close": "知道了",
        "btn_quit": "🚪 退出游戏",
        "help_title": "操作说明",
        "help_text": (
            "· 拖拽手牌到「我方支援阵线」部署单位\n"
            "· 拖拽我方单位到敌方单位/总部进行攻击\n"
            "· 拖到「我方前线」行上前线，拖回支援阵线撤后\n"
            "· 移动与攻击都消耗行动费(⚡)；无[闪击]部署当回合不能移动/攻击\n"
            "· 步兵每回合移动/攻击二选一；坦克可以移动并攻击\n"
            "· 空军/炮兵在支援线即可攻击（敌方前线单位与总部）\n"
            "· 炮兵/轰炸机无视[警卫]；轰炸机必须优先打战斗机且会被战斗机拦截\n"
            "· 炮兵/轰炸机攻击不吃反击；轰炸机不反击（打它不吃反击）\n"
            "· 卡牌上不认识的关键词 → 设置里的「🔑 关键词说明」\n"
            "· 联机：⚔ 战斗 → 服务器模式（填服务器地址）或局域网直连"),
        "quit_title": "退出游戏",
        "quit_confirm": "确定退出 KARDS 吗？",
        # ---- 联机大厅 ----
        "lobby_title": "联机对战",
        "lobby_sub": "先连服务器，登录后可快速匹配或开邀请码房间",
        "btn_back": "← 返回",
        # ---- 大厅：服务器连接 ----
        "srv_title": "① 连接服务器",
        "label_server": "服务器地址:",
        "btn_srv_connect": "连接",
        "btn_login_or_reg": "登录 / 注册（游客不能联机）",
        "btn_srv_reconnect": "重新连接",
        "srv_default_hint": "默认 {addr}（开黑请填主机地址，例如 192.168.1.10:6000）",
        "srv_connecting": "连接中…（超时 6 秒）",
        "srv_connected": "✅ 已连接 {addr}（账号：{name}）",
        "srv_connected_nouser": "✅ 已连接 {addr}｜游客（登录后才能联机）",
        "srv_fail": "⚠ 连接失败：{err}",
        "srv_fail_hint": ("连不上服务器。\n\n"
                          "· 单机请先运行 kards_server.py\n"
                          "· 联机请确认地址写对（主机:端口，例如 192.168.1.10:6000）\n"
                          "· 服务器端防火墙需放行该端口\n\n"
                          "错误：{err}"),
        "srv_warn_addr_title": "服务器地址",
        "srv_warn_addr": "地址格式应为 主机:端口，例如 127.0.0.1:6000",
        "srv_need_login_title": "游客不能联机",
        "srv_need_login": "当前是游客身份，可以打人机对战，但联机/云卡组需要正式账号。\n点「登录 / 注册」后即可继续匹配。",
        "guest_name": "游客",
        "guest_btn": "👤 游客（点击登录）",
        "guest_note": "游客模式：可打人机，不能联机",
        "srv_offline_title": "未连接",
        "srv_offline": "还没有连接服务器，请先点「连接」。",
        # ---- 大厅：本机开服 ----
        "btn_host_server": "建立服务器",
        "host_started": "已在本机启动服务器，正在连接…",
        "host_running": "本机服务器已在运行，正在连接…",
        "host_already": "端口已被占用，直接连接现有服务器…",
        "host_fail_title": "无法建立服务器",
        "host_fail": "启动本机服务器失败：\n{err}",
        "host_firewall_hint": "同一局域网的玩家请把上面地址发给他们；"
                              "首次启动时系统可能弹出防火墙提示，需要选「允许访问」。",
        # ---- 大厅：在线玩家 ----
        "lobby_players": "② 在线玩家",
        "lobby_no_players": "（还没有其他人在线）",
        "lobby_count": "在线 {n} 人",
        "player_ingame": "对局中",
        "player_idle": "空闲",
        "player_stats": "战绩 {w} 胜 {l} 负 {d} 平",
        # ---- 大厅：出击 ----
        "match_title": "③ 开始对战",
        "btn_quick_match": "⚡ 快速匹配",
        "btn_cancel_match": "✕ 取消匹配",
        "matching": "匹配中…等待对手加入",
        "match_cancelled": "已取消匹配。",
        "matched": "✅ 匹配成功！对手：{opp}　请选择阵营组卡。",
        "btn_create_room": "🔑 创建房间",
        "btn_leave_room": "✕ 关闭房间",
        "room_none": "尚未创建房间",
        "room_code": "邀请码：{code}　把它发给好友，让他在下面输入",
        "room_created": "房间已创建，邀请码 {code}",
        "label_join_code": "邀请码:",
        "btn_join_code": "加入",
        "warn_code_title": "邀请码",
        "warn_code": "请输入房主给你的邀请码。",
        "joined": "✅ 已加入对局！房主：{opp}　请选择阵营组卡。",
        # ---- 大厅：日志 ----
        "lobby_log": "🏓 房间日志",
        "log_lobby_in": "{name} 进入大厅",
        "log_lobby_out": "{name} 离开大厅",
        "log_peer_left": "对手离开了对局。",
        "log_kicked": "⚠ 该账号在别处登录，本连接已被服务器断开。",
        "log_srv_down": "⚠ 与服务器的连接已断开。",
        # ---- 兼容旧键（局域网直连版遗留）----
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
        "account_btn": "👤 {name}｜{w}胜 {l}负 {d}平",
        "account_nouser": "👤 游客（点击登录 / 注册）",
        "account_title": "账号管理",
        "account_user": "用户名（2-16 位，中文/字母/数字）",
        "account_pw": "密码（至少 4 位）",
        "account_login": "登 录",
        "account_register": "注 册 账 号",
        "account_logout": "退出登录",
        "account_stats": "战绩：{w} 胜 / {l} 负 / {d} 平",
        "click_hint": "▼ 点击屏幕回到大厅 ▼",
        # ---- AI 投降 ----
        "ai_concede_log": "  🏳 AI 认为已无胜算，选择投降！",
        "ai_concede_reason": "  （{reason}）",
    },
    "en": {
        "app_title": "KARDS Lite",
        "app_subtitle": "WWII Card Battle",
        "btn_settings": "⚙ Settings",
        # ---- auto update ----
        "update_title": "Check for updates",
        "btn_check_update": "Check for updates",
        "update_checking": "Checking for updates…",
        "update_new": "New version {ver} available (current {cur})",
        "update_none": "You're on the latest version {cur}",
        "update_fail": "Update check failed: {err}",
        "update_downloading": "Downloading {done}%",
        "update_extracting": "Extracting {done}%",
        "update_ready": "Update complete ({ver})",
        "update_restart_needed": "Update is ready — restart the game to apply it.",
        "update_restart_btn": "Restart now",
        "update_later_btn": "Later",
        "update_btn_do": "Update now",
        "update_btn_cancel": "Cancel",
        "update_btn_open_page": "Open release page",
        "update_notes": "What's new",
        "update_confirm": "New version {ver} is available (current {cur}). Download and install now?",
        "update_guest_hint": "Updates work for everyone, guests included",
        "battle_title": "⚔ Battle",
        "battle_sub": "Online play (LAN)\nHost / Join — real-time vs friends",
        "practice_title": "🎯 Practice",
        "practice_sub": "Play vs AI\nBuild your deck · random match",
        "settings_title": "Settings",
        "settings_language": "Language / 语言",
        "btn_help": "📖 How to Play",
        "btn_keywords": "🔑 Keywords",
        "kw_title": "Keywords & Mechanics",
        "kw_sub": "These words appear on cards — here is what they mean (available anytime in a match)",
        "kw_group_unit": "Unit keywords",
        "kw_group_trigger": "Triggered keywords",
        "kw_group_term": "Rules glossary",
        "kw_group_planned": "Original KARDS keywords (not yet implemented here — for reference)",
        "kw_close": "Got it",
        "btn_quit": "🚪 Quit",
        "help_title": "How to Play",
        "help_text": (
            "· Drag a hand card to 'My Support Line' to deploy\n"
            "· Drag my unit onto an enemy unit / HQ to attack\n"
            "· Drag to 'My Frontline' to advance; drag back to retreat\n"
            "· Moving and attacking both cost Operation (⚡); without Blitz a unit cannot move/attack the turn it deploys\n"
            "· Infantry: move OR attack each turn; tanks may move and attack\n"
            "· Air & artillery can attack from the support line (enemy frontline & HQ)\n"
            "· Artillery & bombers ignore Guard; bombers must target fighters and can be intercepted\n"
            "· Artillery & bombers take no counterattack; bombers never counterattack\n"
            "· Don't know a keyword on a card? Settings -> '🔑 Keywords'\n"
            "· Online: Battle -> server mode (enter server address) or direct LAN"),
        "quit_title": "Quit",
        "quit_confirm": "Quit KARDS?",
        "lobby_title": "Online Battle",
        "lobby_sub": "Connect to a server, then quick-match or open an invite-code room",
        "btn_back": "← Back",
        # ---- Lobby: server ----
        "srv_title": "① Connect to server",
        "label_server": "Server:",
        "btn_srv_connect": "Connect",
        "btn_login_or_reg": "Log in / Register (guests can't play online)",
        "btn_srv_reconnect": "Reconnect",
        "srv_default_hint": "Default {addr} (LAN play: enter the host, e.g. 192.168.1.10:6000)",
        "srv_connecting": "Connecting… (6s timeout)",
        "srv_connected": "✅ Connected to {addr} (account: {name})",
        "srv_connected_nouser": "✅ Connected to {addr} | Guest (log in to play online)",
        "srv_fail": "⚠ Connect failed: {err}",
        "srv_fail_hint": ("Cannot reach the server.\n\n"
                          "· Solo play: start kards_server.py first\n"
                          "· Check the address (host:port, e.g. 192.168.1.10:6000)\n"
                          "· The server firewall must allow that port\n\n"
                          "Error: {err}"),
        "srv_warn_addr_title": "Server address",
        "srv_warn_addr": "Format must be host:port, e.g. 127.0.0.1:6000",
        "srv_need_login_title": "Guests can't play online",
        "srv_need_login": "You're signed in as a guest. Single-player works, but online play and cloud decks need a real account.\nUse Login / Register to continue.",
        "guest_name": "Guest",
        "guest_btn": "👤 Guest (click to log in)",
        "guest_note": "Guest mode: single-player only, no online play",
        "srv_offline_title": "Not connected",
        "srv_offline": "Not connected to a server yet — press Connect first.",
        # ---- Lobby: host a server ----
        "btn_host_server": "Host server",
        "host_started": "Server started on this PC, connecting…",
        "host_running": "Local server already running, connecting…",
        "host_already": "Port already in use — connecting to the existing server…",
        "host_fail_title": "Cannot start server",
        "host_fail": "Failed to start the local server:\n{err}",
        "host_firewall_hint": "Send the address above to players on your LAN; "
                              "the firewall prompt on first launch must be allowed.",
        # ---- Lobby: players ----
        "lobby_players": "② Players online",
        "lobby_no_players": "(nobody else online yet)",
        "lobby_count": "{n} online",
        "player_ingame": "in game",
        "player_idle": "idle",
        "player_stats": "{w}W {l}L {d}D",
        # ---- Lobby: battle ----
        "match_title": "③ Start a battle",
        "btn_quick_match": "⚡ Quick match",
        "btn_cancel_match": "✕ Cancel match",
        "matching": "Matching… waiting for an opponent",
        "match_cancelled": "Match cancelled.",
        "matched": "✅ Matched! Opponent: {opp} — pick a nation and build your deck.",
        "btn_create_room": "🔑 Create room",
        "btn_leave_room": "✕ Close room",
        "room_none": "No room created",
        "room_code": "Invite code: {code} — send it to your friend",
        "room_created": "Room created, invite code {code}",
        "label_join_code": "Invite code:",
        "btn_join_code": "Join",
        "warn_code_title": "Invite code",
        "warn_code": "Enter the invite code from the host.",
        "joined": "✅ Joined the battle! Host: {opp} — pick a nation and build your deck.",
        # ---- Lobby: log ----
        "lobby_log": "🏓 Room log",
        "log_lobby_in": "{name} entered the lobby",
        "log_lobby_out": "{name} left the lobby",
        "log_peer_left": "Your opponent left the battle.",
        "log_kicked": "⚠ This account signed in elsewhere; the server closed this connection.",
        "log_srv_down": "⚠ Lost connection to the server.",
        # ---- legacy (LAN direct) ----
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
        "account_btn": "👤 {name} | {w}W {l}L {d}D",
        "account_nouser": "👤 Guest (click to log in / register)",
        "account_title": "Account",
        "account_user": "Username (2-16 chars: letters/CJK/digits)",
        "account_pw": "Password (at least 4 chars)",
        "account_login": "Log In",
        "account_register": "Register",
        "account_logout": "Log Out",
        "account_stats": "Record: {w}W / {l}L / {d}D",
        "click_hint": "▼ Click anywhere to return to the lobby ▼",
        "ai_concede_log": "  🏳 The AI sees no way to win and surrenders!",
        "ai_concede_reason": "  ({reason})",
    },
    "ja": {
        "app_title": "KARDS 簡易版",
        "app_subtitle": "第二次世界大戦カードバトル",
        "btn_settings": "⚙ 設定",
        # ---- 自動更新 ----
        "update_title": "アップデート確認",
        "btn_check_update": "アップデート確認",
        "update_checking": "アップデートを確認中…",
        "update_new": "新しいバージョン {ver} があります（現在 {cur}）",
        "update_none": "最新バージョンです（{cur}）",
        "update_fail": "確認に失敗しました：{err}",
        "update_downloading": "ダウンロード中 {done}%",
        "update_extracting": "展開中 {done}%",
        "update_ready": "更新が完了しました（{ver}）",
        "update_restart_needed": "更新の準備ができました。再起動で反映されます。",
        "update_restart_btn": "今すぐ再起動",
        "update_later_btn": "後で",
        "update_btn_do": "今すぐ更新",
        "update_btn_cancel": "キャンセル",
        "update_btn_open_page": "リリースページを開く",
        "update_notes": "更新内容",
        "update_confirm": "新しいバージョン {ver}（現在 {cur}）があります。今すぐダウンロードしてインストールしますか？",
        "update_guest_hint": "アップデートはゲストでも利用できます",
        "battle_title": "⚔ バトル",
        "battle_sub": "オンライン対戦（LAN）\nホスト / 参加、友達とリアルタイム対戦",
        "practice_title": "🎯 練習",
        "practice_sub": "AI と対戦\nデッキ構築可能 · ランダムマッチ",
        "settings_title": "設定",
        "settings_language": "言語 / Language",
        "btn_help": "📖 遊び方",
        "btn_keywords": "🔑 キーワード説明",
        "kw_title": "キーワードとルール",
        "kw_sub": "カードに出てくる用語の意味（対戦中いつでも確認できます）",
        "kw_group_unit": "ユニットキーワード",
        "kw_group_trigger": "誘発型キーワード",
        "kw_group_term": "ルール用語",
        "kw_group_planned": "オリジナル KARDS のキーワード（本作では未実装・参考用）",
        "kw_close": "閉じる",
        "btn_quit": "🚪 終了",
        "help_title": "操作説明",
        "help_text": (
            "· 手札カードを「味方支援ライン」へドラッグして配置\n"
            "· 味方ユニットを敵ユニット/本部へドラッグして攻撃\n"
            "· 「味方前線」へドラッグで前進、支援ラインへ戻すと後退\n"
            "· 移動と攻撃は両方行動コスト(⚡)を消費；電撃なしの配置ターンは移動/攻撃不可\n"
            "· 歩兵は毎ターン移動か攻撃のどちらか；戦車は移動して攻撃も可\n"
            "· 空軍・砲兵は支援ラインから攻撃可（敵前線ユニットと本部）\n"
            "· 砲兵・爆撃機は護衛を無視；爆撃機は戦闘機を優先攻撃し、迎撃される\n"
            "· 砲兵・爆撃機の攻撃は反撃を受けない；爆撃機は反撃しない\n"
            "· カードの用語が分からない → 設定の「🔑 キーワード説明」\n"
            "· オンライン：バトル → サーバーモード（アドレス入力）または LAN 直結"),
        "quit_title": "終了",
        "quit_confirm": "KARDS を終了しますか？",
        "lobby_title": "オンライン対戦",
        "lobby_sub": "サーバーに接続してから、クイックマッチか招待コード部屋で対戦",
        "btn_back": "← 戻る",
        # ---- ロビー：サーバー ----
        "srv_title": "① サーバーに接続",
        "label_server": "サーバー:",
        "btn_srv_connect": "接続",
        "btn_login_or_reg": "ログイン／登録（ゲストはオンライン対戦不可）",
        "btn_srv_reconnect": "再接続",
        "srv_default_hint": "既定 {addr}（LAN 対戦はホストを入力、例 192.168.1.10:6000）",
        "srv_connecting": "接続中…（タイムアウト 6 秒）",
        "srv_connected": "✅ {addr} に接続（アカウント：{name}）",
        "srv_connected_nouser": "✅ {addr} に接続｜ゲスト（ログインで対戦可）",
        "srv_fail": "⚠ 接続失敗：{err}",
        "srv_fail_hint": ("サーバーに到達できません。\n\n"
                          "· ソロなら kards_server.py を先に起動\n"
                          "· アドレスを確認（ホスト:ポート、例 192.168.1.10:6000）\n"
                          "· サーバー側のファイアウォールで当該ポートを許可\n\n"
                          "エラー：{err}"),
        "srv_warn_addr_title": "サーバーアドレス",
        "srv_warn_addr": "ホスト:ポート の形式で入力してください（例 127.0.0.1:6000）",
        "srv_need_login_title": "ゲストはオンライン対戦不可",
        "srv_need_login": "現在ゲストです。CPU 戦は遊べますが、オンライン対戦とクラウドデッキには正規アカウントが必要です。\n「ログイン／登録」から続行してください。",
        "guest_name": "ゲスト",
        "guest_btn": "👤 ゲスト（クリックでログイン）",
        "guest_note": "ゲストモード：CPU 戦のみ、オンライン対戦不可",
        "srv_offline_title": "未接続",
        "srv_offline": "まだサーバーに接続していません。先に「接続」を押してください。",
        # ---- ロビー：自前サーバー ----
        "btn_host_server": "サーバーを立てる",
        "host_started": "この PC でサーバーを起動しました。接続中…",
        "host_running": "ローカルサーバーは起動済みです。接続中…",
        "host_already": "ポートが使用中です。既存のサーバーに接続します…",
        "host_fail_title": "サーバーを起動できません",
        "host_fail": "ローカルサーバーの起動に失敗しました：\n{err}",
        "host_firewall_hint": "同じ LAN のプレイヤーに上のアドレスを伝えてください。"
                              "初回起動時のファイアウォール確認は「許可」を選んでください。",
        # ---- ロビー：プレイヤー ----
        "lobby_players": "② オンラインプレイヤー",
        "lobby_no_players": "（まだ他の人はいません）",
        "lobby_count": "オンライン {n} 人",
        "player_ingame": "対戦中",
        "player_idle": "待機中",
        "player_stats": "戦績 {w}勝 {l}敗 {d}分",
        # ---- ロビー：対戦開始 ----
        "match_title": "③ 対戦を開始",
        "btn_quick_match": "⚡ クイックマッチ",
        "btn_cancel_match": "✕ マッチ取消",
        "matching": "マッチング中… 対戦相手を待っています",
        "match_cancelled": "マッチングを取消しました。",
        "matched": "✅ マッチ成功！相手：{opp}　陣営を選んでデッキを組んでください。",
        "btn_create_room": "🔑 部屋を作成",
        "btn_leave_room": "✕ 部屋を閉じる",
        "room_none": "部屋は未作成",
        "room_code": "招待コード：{code}　友達に送って入力してもらいましょう",
        "room_created": "部屋を作成しました。招待コード {code}",
        "label_join_code": "招待コード:",
        "btn_join_code": "参加",
        "warn_code_title": "招待コード",
        "warn_code": "ホストから受け取った招待コードを入力してください。",
        "joined": "✅ 対戦に参加しました！ホスト：{opp}　陣営を選んでデッキを組んでください。",
        # ---- ロビー：ログ ----
        "lobby_log": "🏓 部屋ログ",
        "log_lobby_in": "{name} がロビーに入りました",
        "log_lobby_out": "{name} がロビーを離れました",
        "log_peer_left": "相手が対戦を離れました。",
        "log_kicked": "⚠ このアカウントは別の場所でログインしたため、サーバーが接続を切断しました。",
        "log_srv_down": "⚠ サーバーとの接続が切断されました。",
        # ---- 旧キー（LAN 直結版の名残）----
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
        "account_btn": "👤 {name}｜{w}勝 {l}負 {d}分",
        "account_nouser": "👤 ゲスト（クリックでログイン／登録）",
        "account_title": "アカウント管理",
        "account_user": "ユーザー名（2-16 文字）",
        "account_pw": "パスワード（4 文字以上）",
        "account_login": "ログイン",
        "account_register": "新規登録",
        "account_logout": "ログアウト",
        "account_stats": "戦績：{w} 勝 / {l} 負 / {d} 分",
        "click_hint": "▼ 画面をクリックしてロビーへ ▼",
        "ai_concede_log": "  🏳 AI は勝ち目がないと判断し、降伏しました！",
        "ai_concede_reason": "  （{reason}）",
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
