# KARDS 简化版

Python 实现的 KARDS 风格二战卡牌对战游戏（非官方粉丝作品；KARDS © 1939 Games）。

界面采用**混合架构**：主菜单 / 大厅 / 组卡 / 账号用 tkinter，**对战界面用 pygame**
（动画补间更流畅、支持图片卡面、为牌桌特效与音效留了接口）。经典 tkinter
对战界面完整保留，可在设置里一键切回。

## 特性

- **212 张卡牌**：德/苏/英/美/日/意/波/法/澳新九阵营 + 芬兰，基于原版数据扩充
- **完整机制**：闪击、警卫、伏击、动员、奋战、亡计、收缴、装甲 1-3 级、前线/支援阵线、行动费
- **组卡规则同原版**：卡组 39 张 + 总部卡，单卡上限按稀有度 —— 普通 4 / 稀有 3 /
  史诗 2 / 传说 1（对应 Standard / Limited / Special / Elite），盟国卡上限 20 张
- **两种对战**：人机练习（可自组卡组）+ 联机（服务器中转，支持匹配 / 邀请码 / 平局判定）
- **本机开服**：大厅里直接「建立服务器」，同一份 `KARDS.exe --server` 兼任服务器，无需命令行
- **账号与战绩**：服务器端账号（SQLite），本地账号首次登录联机时自动迁移并同步战绩
- **游客模式**：未登录自动以游客进入，可人机对战；触发联机时提示登录
- **自动更新**：设置里「检查更新」，比对 GitHub Release 后下载安装，
  下载完按 **SHA256** 校验完整性（校验值取自 Release 的 digest 或
  `SHA256SUMS.txt`）；对不上就换源重下，绝不装来路不明的东西
- **多语言界面**：简体中文 / English / 日本語（默认中文）

## 运行

需要 Python 3.11+、tkinter 与 **pygame**：

```bash
pip install -r requirements.txt
python KARDS.py
```

常用命令行开关：

```bash
python KARDS.py --server [--port 6000]   # 只跑服务器（大厅「建立服务器」用的就是这个）
python KARDS.py --legacy-board           # 本局强制用经典 tkinter 对战界面
python KARDS.py --board                  # 本局强制用 pygame 对战界面
python KARDS.py --smoke                  # 自检：AI 互打一整局
python KARDS.py --board-smoke            # 自检：pygame 棋盘跑若干帧 + 模拟操作
```

对战界面渲染引擎在「设置 → 对战界面」里切换（增强 / 经典），下一局生效。
pygame 缺失或装坏时会自动降级到经典界面，不会因此打不开游戏。

## 卡面 / 音效资产（可选）

把图片丢进 `assets/` 就会自动使用，不改一行代码；缺失时程序化绘制兜底：

```
assets/cards/<卡牌名>.png     # 卡面（不含文件名后缀，如「虎式坦克.png」）
assets/hq/<国家>.png          # 总部图（如「德国.png」）
assets/sfx/<事件>.wav|ogg     # 音效：deploy / move / attack / win / lose
```

安装版会优先读 **exe 同级目录**下的 `assets/`，所以玩家可以自己补图而不用重新打包。

## 模块一览

| 文件 | 职责 |
|---|---|
| `KARDS.py` | 主程序：tkinter 主菜单/大厅/组卡/账号，命令行入口 |
| `kards_engine.py` | 纯规则引擎（卡池、回合、战斗、AI），不依赖任何 GUI |
| `kards_board.py` | pygame 对战棋盘（动画、卡面、音效），可脱离 Tk 单测 |
| `kards_theme.py` | **配色与字体清单的唯一真源**，两套渲染器共用 |
| `kards_i18n.py` | 三语文本与本地偏好（`settings.json`） |
| `kards_net.py` / `kards_server.py` | 联机客户端 / 中继服务器 |
| `kards_account.py` | 本地账号与游客会话 |
| `kards_update.py` | 自动更新（查询、下载、SHA256 校验、解压覆盖） |
| `kards_host.py` | 大厅里「一键开服」拉起服务器子进程 |
| `debug/` | 回归测试与打包/发版工具（非运行必需） |

## 测试

```bash
python debug/test_board.py       # pygame 对战界面（SDL dummy 驱动，无需窗口）
python debug/test_original.py    # 原版机制对齐
python debug/test_tactics.py     # 战术规则（射程、拦截、空袭）
python debug/test_server.py      # 联机服务器
python debug/test_update.py      # 自动更新（含 SHA256 校验，离线部分不联网）
python debug/test_i18n.py        # 三语文案完整性
```

其余回归脚本见 `debug/`（另有拖拽、账号迁移、开服、安装器等 20 余个）。
CI 会在 Windows 上跑其中的核心子集，见 `.github/workflows/ci.yml`。

> GUI 相关测试需要带 tkinter 的解释器，请用系统 Python 运行。
> 拿不准用哪个解释器时，`python debug/pyfind.py` 会列出本机候选。

## 许可

原创代码 MIT（见 `LICENSE`）。本项目是非官方粉丝作品，KARDS 的名称、
卡牌数据与美术归 1939 Games 所有 —— 详见 `NOTICE.md`。
