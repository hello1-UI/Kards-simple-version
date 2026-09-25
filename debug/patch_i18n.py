# -*- coding: utf-8 -*-
"""把 kards_gui.py 的静态 UI 文本接入 kards_i18n（多语言）。逐条替换并断言唯一。"""
import ast
import io

P = "kards_gui.py"
src = io.open(P, encoding="utf-8").read()
applied = []


def rep(old, new, tag, expect=1):
    global src
    n = src.count(old)
    assert n == expect, f"[{tag}] 期望 {expect} 处，实际 {n} 处: {old[:60]!r}"
    src = src.replace(old, new)
    applied.append(tag)


# ============ 0) import ============
rep("""import kards as core
import kards_net as net""",
    """import kards as core
import kards_i18n as i18n
import kards_net as net""", "import")

# ============ 1) 主界面 _build_start ============
rep('''        tk.Label(self.start_frame, text="KARDS 简化版", bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(100, 8))
        tk.Label(self.start_frame, text="二战卡牌对战", bg=BG, fg=DIM,
                 font=FONT).pack(pady=(0, 40))
        tk.Button(self.start_frame, text="⚙ 设置", bg="#4a4f5a", fg=TEXT,''',
    '''        tk.Label(self.start_frame, text=i18n.t("app_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(100, 8))
        tk.Label(self.start_frame, text=i18n.t("app_subtitle"), bg=BG, fg=DIM,
                 font=FONT).pack(pady=(0, 40))
        tk.Button(self.start_frame, text=i18n.t("btn_settings"), bg="#4a4f5a", fg=TEXT,''',
    "start labels")

rep('''        CardWidget(row, title="⚔ 战斗", sub="联机对战（局域网）\\n主机 / 加入，与好友实时对战",
                   cost=None, color="#8a3a3a", big=True,
                   on_click=self.on_battle).pack(side="left", padx=14, ipady=8)
        CardWidget(row, title="🎯 练习", sub="与人机 AI 对战\\n可自组卡组 · 随机匹配",''',
    '''        CardWidget(row, title=i18n.t("battle_title"), sub=i18n.t("battle_sub"),
                   cost=None, color="#8a3a3a", big=True,
                   on_click=self.on_battle).pack(side="left", padx=14, ipady=8)
        CardWidget(row, title=i18n.t("practice_title"), sub=i18n.t("practice_sub"),''',
    "start cards")

# ============ 2) 主界面设置窗（整方法替换，加语言切换） ============
rep('''    def open_start_settings(self):
        """主界面右上角设置：操作说明 / 退出游戏"""
        win = tk.Toplevel(self)
        win.title("设置")
        win.configure(bg=BG)
        win.geometry("360x260")
        win.transient(self)
        tk.Label(win, text="设置", bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(18, 14))

        def show_help():
            messagebox.showinfo(
                "操作说明",
                "· 拖拽手牌到「我方支援阵线」部署单位\\n"
                "· 拖拽我方单位到敌方单位/总部进行攻击\\n"
                "· 拖到「我方前线」行上前线，拖回支援阵线撤后\\n"
                "· [闪击]部署当回合即可攻击；[冲击]攻击免反击（消耗）\\n"
                "· [警卫]保护相邻目标；#0位警卫保护总部\\n"
                "· 只有前线单位能攻击敌方总部；打单位未死会吃反击\\n"
                "· [收缴]消灭敌方单位时缴获一张 1/1 副本入手牌\\n"
                "· 联机：⚔ 战斗 → 主机/加入（局域网 TCP，默认端口 5555）")

        def quit_app():
            if messagebox.askyesno("退出游戏", "确定退出 KARDS 吗？"):
                win.destroy()
                self.destroy()

        for text, cmd, color in (("📖 操作说明", show_help, "#3a5a80"),
                                 ("🚪 退出游戏", quit_app, "#4a4f5a")):
            tk.Button(win, text=text, bg=color, fg=TEXT, font=FONT_B, bd=0,
                      padx=18, pady=8, cursor="hand2", command=cmd).pack(pady=6)''',
    '''    def open_start_settings(self):
        """主界面右上角设置：语言 / 操作说明 / 退出游戏"""
        win = tk.Toplevel(self)
        win.title(i18n.t("settings_title"))
        win.configure(bg=BG)
        win.geometry("380x400")
        win.transient(self)
        tk.Label(win, text=i18n.t("settings_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(18, 6))

        def apply_lang():
            # 切换语言：保存偏好 → 重建主界面 → 重开设置窗（立即生效）
            i18n.set_lang(i18n.get_lang())
            self.start_frame.destroy()
            self._build_start()
            win.destroy()
            self.open_start_settings()

        self._lang_buttons(win, on_change=apply_lang)

        def show_help():
            messagebox.showinfo(i18n.t("help_title"), i18n.t("help_text"))

        def quit_app():
            if messagebox.askyesno(i18n.t("quit_title"), i18n.t("quit_confirm")):
                win.destroy()
                self.destroy()

        for text, cmd, color in ((i18n.t("btn_help"), show_help, "#3a5a80"),
                                 (i18n.t("btn_quit"), quit_app, "#4a4f5a")):
            tk.Button(win, text=text, bg=color, fg=TEXT, font=FONT_B, bd=0,
                      padx=18, pady=8, cursor="hand2", command=cmd).pack(pady=6)

    def _lang_buttons(self, win, on_change):
        """设置窗中的语言切换行：三个语言按钮，当前语言置灰不可点"""
        tk.Label(win, text=i18n.t("settings_language"), bg=BG, fg=DIM,
                 font=FONT_S).pack(pady=(12, 4))
        row = tk.Frame(win, bg=BG)
        row.pack()
        for code in i18n.LANG_NAMES:
            cur = i18n.get_lang() == code
            tk.Button(row, text=i18n.LANG_NAMES[code],
                      bg="#3a5a80" if cur else "#4a4f5a",
                      fg=TEXT, font=FONT_S, bd=0, padx=12, pady=6,
                      cursor="hand2", state="disabled" if cur else "normal",
                      command=lambda c=code: (i18n.set_lang(c), on_change())
                      ).pack(side="left", padx=4)''',
    "open_start_settings")

# ============ 3) 联机大厅 ============
rep('tk.Label(self.start_frame, text="联机对战", bg=BG, fg=TEXT,',
    'tk.Label(self.start_frame, text=i18n.t("lobby_title"), bg=BG, fg=TEXT,',
    "lobby title")
rep('tk.Label(self.start_frame, text="同一局域网内 TCP 直连（默认端口 5555，可自行修改）",',
    'tk.Label(self.start_frame, text=i18n.t("lobby_sub"),',
    "lobby sub")
rep('tk.Button(self.start_frame, text="← 返回", bg="#4a4f5a", fg=TEXT,',
    'tk.Button(self.start_frame, text=i18n.t("btn_back"), bg="#4a4f5a", fg=TEXT,',
    "btn back")
rep('tk.Label(box, text="🏠 主机对战（等待好友加入）", bg=PANEL, fg=TEXT,',
    'tk.Label(box, text=i18n.t("host_title"), bg=PANEL, fg=TEXT,',
    "host title")
rep('tk.Label(row1, text="端口:", bg=PANEL, fg=DIM, font=FONT_S).pack(side="left")',
    'tk.Label(row1, text=i18n.t("label_port"), bg=PANEL, fg=DIM, font=FONT_S).pack(side="left")',
    "row1 port")
rep('self.host_btn = tk.Button(row1, text="开始等待连接", bg="#2e6b46", fg=TEXT,',
    'self.host_btn = tk.Button(row1, text=i18n.t("btn_start_wait"), bg="#2e6b46", fg=TEXT,',
    "host btn")
rep('tk.Label(box2, text="🔗 加入对战（连接主机）", bg=PANEL, fg=TEXT,',
    'tk.Label(box2, text=i18n.t("join_title"), bg=PANEL, fg=TEXT,',
    "join title")
rep('tk.Label(row2, text="主机 IP:", bg=PANEL, fg=DIM, font=FONT_S).pack(side="left")',
    'tk.Label(row2, text=i18n.t("label_host_ip"), bg=PANEL, fg=DIM, font=FONT_S).pack(side="left")',
    "row2 ip")
rep('tk.Label(row2, text="端口:", bg=PANEL, fg=DIM, font=FONT_S).pack(side="left")',
    'tk.Label(row2, text=i18n.t("label_port"), bg=PANEL, fg=DIM, font=FONT_S).pack(side="left")',
    "row2 port")
rep('self.join_btn = tk.Button(row2, text="连接", bg="#3a5a80", fg=TEXT,',
    'self.join_btn = tk.Button(row2, text=i18n.t("btn_connect"), bg="#3a5a80", fg=TEXT,',
    "join btn")

# ---- 大厅状态 / 校验消息 ----
rep('self.host_status.configure(text="✅ 对手已连接！请选择阵营组卡。")',
    'self.host_status.configure(text=i18n.t("host_connected"))', "host ok")
rep('self.join_status.configure(text="✅ 已连接到主机！请选择阵营组卡。")',
    'self.join_status.configure(text=i18n.t("join_connected"))', "join ok")
rep('self.host_status.configure(text=f"⚠ 等待失败：{res[1]}")',
    'self.host_status.configure(text=i18n.t("host_fail", err=res[1]))', "host fail")
rep('self.join_status.configure(text=f"⚠ 连接失败：{res[1]}")',
    'self.join_status.configure(text=i18n.t("join_fail", err=res[1]))', "join fail")
rep('messagebox.showwarning("端口", "端口必须是 1-65535 的数字。")',
    'messagebox.showwarning(i18n.t("warn_port_title"), i18n.t("warn_port_range"))',
    "warn range")
rep('''messagebox.showerror("主机失败", f"无法监听端口 {port}:\\n{e}\\n"
                                             "可能被占用或被防火墙拦截。")''',
    '''messagebox.showerror(i18n.t("host_fail_title"),
                                 i18n.t("host_fail_msg", port=port, err=e))''',
    "host fail msg")
rep('self.host_status.configure(text=f"等待连接中…（0.0.0.0:{port}）把本机 IP 告诉好友吧。")',
    'self.host_status.configure(text=i18n.t("host_waiting", port=port))', "host waiting")
rep('messagebox.showwarning("端口", "端口必须是数字。")',
    'messagebox.showwarning(i18n.t("warn_port_title"), i18n.t("warn_port_num"))',
    "warn num")
rep('messagebox.showwarning("IP", "请输入主机 IP。")',
    'messagebox.showwarning(i18n.t("warn_ip_title"), i18n.t("warn_ip"))', "warn ip")
rep('self.join_status.configure(text=f"连接中…（{ip}:{port}，超时 6 秒）")',
    'self.join_status.configure(text=i18n.t("connecting", ip=ip, port=port))', "connecting")

# ============ 4) 阵营选择 ============
rep('tk.Label(self.start_frame, text="联机模式" if mp else "练习模式", bg=BG, fg=TEXT,',
    'tk.Label(self.start_frame, text=i18n.t("mode_mp") if mp else i18n.t("mode_sp"), bg=BG, fg=TEXT,',
    "mode title")
rep('tk.Label(self.start_frame, text="选择主国（总部卡自带研发被动），之后自由组建卡组",',
    'tk.Label(self.start_frame, text=i18n.t("nation_sub"),',
    "nation sub")

# ============ 5) 组卡界面 ============
rep('tk.Button(right_t, text="导入卡组", bg="#6b4c7a", fg=TEXT, font=FONT_S,',
    'tk.Button(right_t, text=i18n.t("btn_import"), bg="#6b4c7a", fg=TEXT, font=FONT_S,',
    "btn import")
rep('tk.Button(right_t, text="保存卡组", bg="#6b5a2a", fg=TEXT, font=FONT_S,',
    'tk.Button(right_t, text=i18n.t("btn_save"), bg="#6b5a2a", fg=TEXT, font=FONT_S,',
    "btn save")
rep('tk.Button(right_t, text="载入卡组", bg="#4a5a6b", fg=TEXT, font=FONT_S,',
    'tk.Button(right_t, text=i18n.t("btn_load"), bg="#4a5a6b", fg=TEXT, font=FONT_S,',
    "btn load")
rep('tk.Button(right_t, text="推荐卡组", bg="#3a5a80", fg=TEXT, font=FONT_S,',
    'tk.Button(right_t, text=i18n.t("btn_recommend"), bg="#3a5a80", fg=TEXT, font=FONT_S,',
    "btn recommend")
rep('tk.Button(right_t, text="清空", bg="#4a4f5a", fg=TEXT, font=FONT_S,',
    'tk.Button(right_t, text=i18n.t("btn_clear"), bg="#4a4f5a", fg=TEXT, font=FONT_S,',
    "btn clear")
rep('right_t, text="开始对战" if mp else "开始战斗", state="disabled",',
    'right_t, text=i18n.t("btn_start_mp") if mp else i18n.t("btn_start_sp"),\n            state="disabled",',
    "btn start")
rep('tk.Label(leftw, text="可选用卡（点击加入卡组）", bg=BG, fg=DIM,',
    'tk.Label(leftw, text=i18n.t("label_pool"), bg=BG, fg=DIM,',
    "label pool")
rep('tk.Label(leftw, text=f"稀有度：普通（无标）｜{legend}", bg=BG, fg=DIM,',
    'tk.Label(leftw, text=i18n.t("legend", legend=legend), bg=BG, fg=DIM,',
    "legend")
rep('tk.Label(rightw, text="当前卡组（点击移除）", bg=BG, fg=DIM,',
    'tk.Label(rightw, text=i18n.t("label_deck"), bg=BG, fg=DIM,',
    "label deck")
rep('tk.Label(self.deck_inner, text="（卡组为空，点击左侧卡牌加入）",',
    'tk.Label(self.deck_inner, text=i18n.t("deck_empty"),',
    "deck empty")
rep('text=self._card_row_text(c) + f"   （已带 {n}/{core.MAX_COPIES}）")',
    'text=self._card_row_text(c) + i18n.t("copies", n=n, max=core.MAX_COPIES))',
    "copies")
rep('self.ally_count_lbl.configure(text=f"盟国 {ally}/{core.ALLY_LIMIT}")',
    'self.ally_count_lbl.configure(text=i18n.t("ally_count", ally=ally, limit=core.ALLY_LIMIT))',
    "ally count")
rep('messagebox.showwarning("卡组不合法", msg)',
    'messagebox.showwarning(i18n.t("deck_invalid_title"), msg)', "deck invalid",
    expect=2)

# ============ 6) 导入 / 保存 / 载入对话框 ============
rep('win.title("导入卡组")', 'win.title(i18n.t("btn_import"))', "import title")
rep('tk.Label(win, text="粘贴卡牌清单，每行一张卡：", bg=BG, fg=TEXT,',
    'tk.Label(win, text=i18n.t("import_prompt"), bg=BG, fg=TEXT,', "import prompt")
rep('''        tk.Label(win, text="支持格式：'3 谢尔曼坦克' / '谢尔曼坦克 x3' / '3x Sherman Tank'\\n"
                           "原版英文名可自动识别（Sherman Tank、T-34、Spitfire、Zero 等）。\\n"
                           "导入后未识别的行会被忽略，不足的张数可在下方手动补齐。",
                 bg=BG, fg=DIM, font=FONT_S, justify="left").pack(anchor="w", padx=14)''',
    '''        tk.Label(win, text=i18n.t("import_hint"),
                 bg=BG, fg=DIM, font=FONT_S, justify="left").pack(anchor="w", padx=14)''',
    "import hint")
rep('''            msg = f"成功导入 {sum(counts.values())} 张卡牌（上限裁剪后 {self._deck_total()} 张）。"
            if unmatched:
                msg += f"\\n未识别 {len(unmatched)} 行（示例: {'；'.join(unmatched[:3])}），可在下方继续手动补卡。"
            messagebox.showinfo("导入结果", msg)''',
    '''            msg = i18n.t("import_result", n=sum(counts.values()), m=self._deck_total())
            if unmatched:
                msg += i18n.t("import_unmatched", k=len(unmatched),
                              samples="；".join(unmatched[:3]))
            messagebox.showinfo(i18n.t("import_result_title"), msg)''',
    "import result")
rep('tk.Button(win, text="导入", bg="#2e6b46", fg=TEXT, font=FONT_B, bd=0,',
    'tk.Button(win, text=i18n.t("btn_import_go"), bg="#2e6b46", fg=TEXT, font=FONT_B, bd=0,',
    "btn import go")
rep('messagebox.showinfo("保存卡组", "当前卡组为空，先加入一些卡牌再保存。")',
    'messagebox.showinfo(i18n.t("save_title"), i18n.t("save_empty"))', "save empty")
rep('name = simpledialog.askstring("保存卡组", "给卡组起个名字：", parent=self)',
    'name = simpledialog.askstring(i18n.t("save_title"), i18n.t("save_prompt"), parent=self)',
    "save prompt")
rep('''        messagebox.showinfo("保存卡组",
                            f"卡组「{name.strip()}」已保存！\\n"
                            f"文件：{path}\\n"
                            f"下次组卡时点「载入卡组」即可一键恢复。")''',
    '''        messagebox.showinfo(i18n.t("save_title"),
                            i18n.t("save_ok", name=name.strip(), path=path))''',
    "save ok")
rep('win.title("载入卡组")', 'win.title(i18n.t("btn_load"))', "load title")
rep('tk.Label(win, text=f"{self.deck_nation} 的已保存卡组（点击载入）：",',
    'tk.Label(win, text=i18n.t("load_title", nation=self.deck_nation),', "load head")
rep('tk.Label(win, text="还没有保存过卡组。\\n组好后点「保存卡组」即可保存。",',
    'tk.Label(win, text=i18n.t("load_none"),', "load none")
rep('tk.Button(win, text="关闭", bg="#4a4f5a", fg=TEXT, font=FONT_S, bd=0,',
    'tk.Button(win, text=i18n.t("btn_close"), bg="#4a4f5a", fg=TEXT, font=FONT_S, bd=0,',
    "btn close")
rep('messagebox.showwarning("载入卡组", "找不到该卡组文件。")',
    'messagebox.showwarning(i18n.t("btn_load"), i18n.t("load_missing"))', "load missing")
rep('''            messagebox.showinfo("载入卡组",
                                f"已载入「{nm}」（{self._deck_total()} 张）。"
                                f"\\n不足 {core.DECK_SIZE} 张可继续手动补卡。")''',
    '''            messagebox.showinfo(i18n.t("btn_load"),
                                i18n.t("load_ok", name=nm, n=self._deck_total(),
                                       size=core.DECK_SIZE))''',
    "load ok")

# ============ 7) 联机消息 ============
rep('messagebox.showerror("联机", "连接已断开，请返回重新连接。")',
    'messagebox.showerror(i18n.t("mp_title"), i18n.t("mp_disconnected"))', "mp disc")
rep('self.start_btn.configure(state="disabled", text="等待对手就绪…")',
    'self.start_btn.configure(state="disabled", text=i18n.t("waiting_opponent"))', "waiting")
rep('messagebox.showerror("联机", "对手在准备阶段断开了连接。")',
    'messagebox.showerror(i18n.t("mp_title"), i18n.t("mp_peer_left_prep"))', "peer left")
rep('messagebox.showerror("联机", "对手卡组数量异常，连接中止。")',
    'messagebox.showerror(i18n.t("mp_title"), i18n.t("mp_bad_deck"))', "bad deck")
rep('messagebox.showinfo("联机", "连接已断开。")',
    'messagebox.showinfo(i18n.t("mp_title"), i18n.t("mp_lost"))', "mp lost")

# ============ 8) 对局界面 ============
rep('''self.foe_rear_row = self._board_row(left, "敌方支援阵线")
        self.foe_front_row = self._board_row(left, "敌方前线")''',
    '''self.foe_rear_row = self._board_row(left, i18n.t("row_foe_rear"))
        self.foe_front_row = self._board_row(left, i18n.t("row_foe_front"))''',
    "foe rows")
rep('''self.my_front_row = self._board_row(left, "我方前线")
        self.my_rear_row = self._board_row(left, "我方支援阵线")''',
    '''self.my_front_row = self._board_row(left, i18n.t("row_my_front"))
        self.my_rear_row = self._board_row(left, i18n.t("row_my_rear"))''',
    "my rows")
rep('tk.Button(right, text="⚙ 设置 / 投降", bg="#4a4f5a", fg=TEXT, font=FONT_S,',
    'tk.Button(right, text=i18n.t("btn_ingame_settings"), bg="#4a4f5a", fg=TEXT, font=FONT_S,',
    "ingame settings btn")
rep('tk.Label(right, text="战场记录", bg=BG, fg=DIM, font=FONT).pack(anchor="w")',
    'tk.Label(right, text=i18n.t("log_title"), bg=BG, fg=DIM, font=FONT).pack(anchor="w")',
    "log title")
rep('self.speed_btn = tk.Button(bottom, text="🐢 慢速", bg="#4a4f5a", fg=TEXT,',
    'self.speed_btn = tk.Button(bottom, text=i18n.t("btn_slow"), bg="#4a4f5a", fg=TEXT,',
    "speed btn init")
rep('self.end_btn = tk.Button(bottom, text="结束回合", bg="#3a5a80", fg=TEXT,',
    'self.end_btn = tk.Button(bottom, text=i18n.t("btn_end_turn"), bg="#3a5a80", fg=TEXT,',
    "end btn")
rep('self.speed_btn.configure(text="🐇 快速" if self.fast_ai else "🐢 慢速")',
    'self.speed_btn.configure(text=i18n.t("btn_fast") if self.fast_ai else i18n.t("btn_slow"))',
    "speed toggle")

# ---- refresh() 渲染文本 ----
rep('''hq = CardWidget(self.foe_rear_row, title="敌方总部",
                        sub="拖我方单位到此攻击", cost=None, color="#8a3a3a",''',
    '''hq = CardWidget(self.foe_rear_row, title=i18n.t("foe_hq"),
                        sub=i18n.t("hq_hint"), cost=None, color="#8a3a3a",''',
    "foe hq card")
rep('tk.Label(self.foe_rear_row, text="（敌方无单位）", bg="#1f232b", fg=DIM,',
    'tk.Label(self.foe_rear_row, text=i18n.t("foe_no_units"), bg="#1f232b", fg=DIM,',
    "foe none")
rep('tk.Label(self.foe_front_row, text="（前线无单位）", bg="#1f232b", fg="#5a616b",',
    'tk.Label(self.foe_front_row, text=i18n.t("foe_front_empty"), bg="#1f232b", fg="#5a616b",',
    "foe front empty")
rep('turn_tag = "" if human_turn else "   【敌方回合】"',
    'turn_tag = "" if human_turn else i18n.t("turn_tag")', "turn tag")
rep('''        self.foe_info.configure(
            text=f"敌方  {foe.name}（{foe.nation}）   HQ {foe.hq} HP   "
                 f"手牌 {len(foe.hand)}   Kredits {foe.kredits}   "
                 f"反制 ❓×{len(foe.counters)}{turn_tag}", fg=RED)''',
    '''        self.foe_info.configure(
            text=i18n.t("foe_info", name=foe.name, nation=foe.nation, hq=foe.hq,
                        hand=len(foe.hand), kr=foe.kredits,
                        cnt=len(foe.counters), tag=turn_tag), fg=RED)''',
    "foe info")
rep('counter_txt = ("   反制区: " + " | ".join(c.name for c in me.counters)) if me.counters else ""',
    'counter_txt = (i18n.t("counter_zone") + " | ".join(c.name for c in me.counters)) if me.counters else ""',
    "counter zone")
rep('''        self.my_info.configure(
            text=f"我方  {me.name}（{me.nation}）   HQ {me.hq} HP   Kredits {me.kredits}   "
                 f"牌库 {len(me.deck)}   {me.hq_card.perk_desc}{counter_txt}", fg=TEXT)''',
    '''        self.my_info.configure(
            text=i18n.t("my_info", name=me.name, nation=me.nation, hq=me.hq,
                        kr=me.kredits, deck=len(me.deck),
                        perk=me.hq_card.perk_desc, counters=counter_txt), fg=TEXT)''',
    "my info")
rep('front_txt, front_fg = "⚔ 前线：无人占领（可抢占）", DIM',
    'front_txt, front_fg = i18n.t("front_none"), DIM', "front none")
rep('front_txt, front_fg = f"⚔ 前线：我方占领 {own_front}/{core.FRONTLINE_SLOTS}", GOLD',
    'front_txt, front_fg = i18n.t("front_mine", n=own_front, total=core.FRONTLINE_SLOTS), GOLD',
    "front mine")
rep('front_txt, front_fg = "⚔ 前线：敌方占领！先清掉敌方前线单位", RED',
    'front_txt, front_fg = i18n.t("front_foe"), RED', "front foe")
rep('tk.Label(self.my_rear_row, text="（我方无单位，拖手牌到此行部署）",',
    'tk.Label(self.my_rear_row, text=i18n.t("my_rear_empty"),', "my rear empty")
rep('tk.Label(self.my_front_row, text="（拖我方单位到此行上前线）",',
    'tk.Label(self.my_front_row, text=i18n.t("my_front_empty"),', "my front empty")
rep('tk.Label(self.hand_frame, text="（敌方回合 — 对手手牌保密）", bg=PANEL, fg=DIM,',
    'tk.Label(self.hand_frame, text=i18n.t("hand_hidden"), bg=PANEL, fg=DIM,', "hand hidden")
rep('tk.Label(self.hand_frame, text="（手牌已空）", bg=PANEL, fg=DIM,',
    'tk.Label(self.hand_frame, text=i18n.t("hand_empty"), bg=PANEL, fg=DIM,', "hand empty")

# ============ 9) 对局中设置窗（整方法替换，加语言切换） ============
rep('''    def open_settings(self):
        win = tk.Toplevel(self)
        win.title("设置")
        win.configure(bg=BG)
        win.geometry("320x240")
        win.transient(self)
        tk.Label(win, text="设置", bg=BG, fg=TEXT, font=FONT_XL).pack(pady=(16, 12))

        def surrender():
            if messagebox.askyesno("投降", "确定投降吗？本局将判负。"):
                win.destroy()
                self.add_log("  你选择了投降。")
                if self.mp_link is not None:
                    self.mp_link.send({"t": "concede"})
                self.finish(winner=self.game.players[1] if self.game else None)

        def to_menu():
            if messagebox.askyesno("返回主菜单", "确定放弃本局并返回主菜单吗？"):
                win.destroy()
                self.back_to_menu()

        def quit_app():
            if messagebox.askyesno("退出游戏", "确定安全退出 KARDS 吗？"):
                win.destroy()
                self.destroy()

        for text, cmd, color in (("🏳 投降", surrender, "#8a3a3a"),
                                 ("🏠 返回主菜单", to_menu, "#3a5a80"),
                                 ("🚪 退出游戏", quit_app, "#4a4f5a")):
            tk.Button(win, text=text, bg=color, fg=TEXT, font=FONT_B, bd=0,
                      padx=18, pady=8, cursor="hand2", command=cmd).pack(pady=5)''',
    '''    def open_settings(self):
        win = tk.Toplevel(self)
        win.title(i18n.t("settings_title"))
        win.configure(bg=BG)
        win.geometry("340x380")
        win.transient(self)
        tk.Label(win, text=i18n.t("settings_title"), bg=BG, fg=TEXT,
                 font=FONT_XL).pack(pady=(16, 6))
        # 对局中切语言：偏好立即保存，界面文本随下次界面重建生效
        self._lang_buttons(win, on_change=win.destroy)

        def surrender():
            if messagebox.askyesno(i18n.t("surrender_title"), i18n.t("surrender_confirm")):
                win.destroy()
                self.add_log(i18n.t("log_surrender"))
                if self.mp_link is not None:
                    self.mp_link.send({"t": "concede"})
                self.finish(winner=self.game.players[1] if self.game else None)

        def to_menu():
            if messagebox.askyesno(i18n.t("to_menu_title"), i18n.t("to_menu_confirm")):
                win.destroy()
                self.back_to_menu()

        def quit_app():
            if messagebox.askyesno(i18n.t("quit_title"), i18n.t("quit_safe_confirm")):
                win.destroy()
                self.destroy()

        for text, cmd, color in ((i18n.t("btn_surrender"), surrender, "#8a3a3a"),
                                 (i18n.t("btn_to_menu"), to_menu, "#3a5a80"),
                                 (i18n.t("btn_quit"), quit_app, "#4a4f5a")):
            tk.Button(win, text=text, bg=color, fg=TEXT, font=FONT_B, bd=0,
                      padx=18, pady=8, cursor="hand2", command=cmd).pack(pady=5)''',
    "open_settings")

# ============ 10) Esc 退出确认 ============
rep('if messagebox.askyesno("退出本局", "确定要放弃本局并返回主菜单吗？"):',
    'if messagebox.askyesno(i18n.t("leave_title"), i18n.t("leave_confirm")):', "esc leave")
rep('if messagebox.askyesno("退出游戏", "确定退出 KARDS 吗？"):',
    'if messagebox.askyesno(i18n.t("quit_title"), i18n.t("quit_confirm")):', "esc quit")

# ============ 11) 结算动画 ============
rep('txt = "🏆  胜  利 ！" if won else "💀  战  败 …"',
    'txt = i18n.t("win_big") if won else i18n.t("lose_big")', "end big")
rep('text="战场已被你掌控，指挥官！" if won else "总部沦陷……再接再厉，指挥官。",',
    'text=i18n.t("win_sub") if won else i18n.t("lose_sub"),', "end sub")
rep('hint = tk.Label(overlay, text="▼ 点击屏幕回到大厅 ▼", bg="#0d1017",',
    'hint = tk.Label(overlay, text=i18n.t("click_hint"), bg="#0d1017",', "click hint")

io.open(P, "w", encoding="utf-8", newline="\n").write(src)
print(f"共应用 {len(applied)} 处替换")
ast.parse(io.open(P, encoding="utf-8").read())
print("syntax OK")
