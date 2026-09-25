# KARDS 简化版

Python/tkinter 实现的 KARDS 风格二战卡牌对战游戏（非官方粉丝作品；KARDS © 1939 Games）。

## 特性

- **208 张卡牌**：德/苏/英/美/日/意/波/法/澳新九阵营，基于原版数据扩充
- **完整机制**：闪击、警卫、伏击、动员、奋战、亡计、收缴、装甲 1-3 级、前线/支援阵线
- **两种对战**：人机练习（可自组卡组）+ 局域网联机（TCP 直连，支持平局判定）
- **多语言界面**：简体中文 / English / 日本語
- **组卡系统**：自组卡组、内置推荐卡组、悬停查看卡牌详情

## 运行

```bash
python kards_gui.py        # 图形界面（推荐）
python kards.py --demo     # 命令行演示对局
```

打包版（PyInstaller）见 `dist/`。

## 测试

```bash
python debug/test_original.py   # 49 项回归测试
```
