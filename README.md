# KARDS 简化版

Python 实现的 KARDS 风格二战卡牌对战游戏（非官方粉丝作品；KARDS © 1939 Games）。

界面采用**混合架构**：主菜单 / 大厅 / 组卡 / 账号用 tkinter，**对战界面用 pygame**
（动画补间更流畅、支持图片卡面、为牌桌特效与音效留了接口）。经典 tkinter
对战界面完整保留，可在设置里一键切回。

## 特性

- **212 张卡牌**：德/苏/英/美/日/意/波/法/澳新九阵营 + 芬兰，基于原版数据扩充
- **完整机制**：闪击、警卫、伏击、动员、奋战、亡计、收缴、装甲 1-3 级、前线/支援阵线、行动费
- **两种对战**：人机练习（可自组卡组）+ 联机（服务器中转，支持匹配 / 邀请码 / 平局判定）
- **本机开服**：大厅里直接「建立服务器」，同一份 `KARDS.exe --server` 兼任服务器，无需命令行
- **账号与战绩**：服务器端账号（SQLite），本地账号首次登录联机时自动迁移并同步战绩
- **游客模式**：未登录自动以游客进入，可人机对战；触发联机时提示登录
- **自动更新**：设置里「检查更新」，比对 GitHub Release 后下载安装
- **多语言界面**：简体中文 / English / 日本語（默认中文）

## 运行

需要 Python 3.11+、tkinter 与 **pygame**：

```bash
pip install pygame
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

## 测试

```bash
python debug/test_board.py       # pygame 对战界面（169 项）
python debug/test_original.py    # 原版机制对齐（49 项）
python debug/test_tactics.py     # 战术规则（33 项）
python debug/test_server.py      # 联机服务器（54 项）
```

其余回归脚本见 `debug/`（另有拖拽、账号迁移、开服、自动更新、安装器等 20 余个）。

> GUI 相关测试需要带 tkinter 的解释器，请用系统 Python 运行。
