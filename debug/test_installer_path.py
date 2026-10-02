# -*- coding: utf-8 -*-
"""安装路径询问逻辑的回归测试（安装器「不能自定义路径」问题）

背景（用户实际遇到）：
    安装器双击运行时**没有询问路径**，用户输入的路径根本没被读进去，
    静默用了默认值。

根因（实测确认）：
    - 原实现用 `not sys.stdin.isatty()` 判断"非交互" → 双击 exe 时
      stdin 被重定向，isatty() 返回 False → 直接跳过询问。
    - 换成 `GetConsoleWindow()` 预判同样不可靠（无常驻控制台时返回 0）。
    → **结论：不能预判"有没有控制台"，只能直接尝试读输入，失败才回退。**

本测试锁定：
  1. 有 stdin 时一定会尝试询问并采纳用户输入
  2. 回车 = 默认；EOF / 无 stdin 不崩，安全回退默认
  3. 命令行参数优先，完全不询问
  4. 非法输入（磁盘根目录 / 无法解析）会重问，3 次后回退默认
  5. 引号 / 空格 / `~` 都被正确处理
  6. 默认目录绝不是安装器自己所在的目录（不会把 Setup 解压目录当安装目录）

运行: python debug/test_installer_path.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "apk"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import install                      # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [!!] ") + name + (f"  {extra}" if extra else ""))


CHILD = r'''
import sys, os
sys.path.insert(0, r"__APK__")
import install
d, how = install.ask_install_dir()
print("RESULT=" + d + "|" + how)
'''


def run_child(stdin_data=None, argv=(), close_stdin=False):
    """在子进程跑 ask_install_dir；返回 (解码后的输出, 退出码)"""
    script = os.path.join(tempfile.gettempdir(), "kards_path_child.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(CHILD.replace("__APK__", os.path.join(ROOT, "apk")))
    kw = {}
    if stdin_data is not None:
        kw["input"] = stdin_data
    elif close_stdin:
        kw["stdin"] = subprocess.DEVNULL
    p = subprocess.run([sys.executable, script, *argv],
                       capture_output=True, **kw)
    raw = p.stdout + p.stderr
    for enc in ("utf-8", "gbk", "mbcs", "latin-1"):
        try:
            return raw.decode(enc), p.returncode
        except (UnicodeDecodeError, LookupError):
            continue
    return repr(raw), p.returncode


def result_of(out):
    for line in out.splitlines():
        if line.startswith("RESULT="):
            path, _, how = line[len("RESULT="):].partition("|")
            return path, how.strip()
    return None, None


def main():
    print("1. 有输入时一定会询问（不再静默跳过）")
    out, rc = run_child(b"D:\\Games\\MyKards\r\n")
    path, how = result_of(out)
    check("子进程正常退出", rc == 0, rc)
    check("打印了询问提示", "想装在哪里" in out, out[-200:])
    check("用户输入的路径被采纳",
          (path or "").lower().startswith("d:\\games\\mykards"), path)
    check("标记为「手动输入」", how == "手动输入", how)

    print("2. 回车 = 默认路径")
    out, rc = run_child(b"\r\n")
    path, how = result_of(out)
    check("回车走默认", path == install.DEFAULT_DIR, path)
    check("标记为「默认（回车）」", how == "默认（回车）", how)

    print("3. EOF / 无 stdin 不崩，安全回退")
    out, rc = run_child(b"")
    check("EOF 不异常退出", rc == 0, rc)
    path, how = result_of(out)
    check("EOF 走默认", path == install.DEFAULT_DIR, path)
    check("标记为「默认（非交互）」", how == "默认（非交互）", how)
    check("没有 Traceback", "Traceback" not in out)

    out, rc = run_child(close_stdin=True)
    check("stdin=DEVNULL 不异常退出", rc == 0, rc)
    path, _how = result_of(out)
    check("stdin=DEVNULL 走默认", path == install.DEFAULT_DIR, path)
    check("没有 Traceback(DEVNULL)", "Traceback" not in out)

    print("4. 命令行参数优先，不询问")
    out, rc = run_child(b"", argv=["E:\\Arg Path\\Kards"])
    path, how = result_of(out)
    check("命令行路径被采纳",
          (path or "").lower().startswith("e:\\arg path\\kards"), path)
    check("标记为「命令行参数」", how == "命令行参数", how)
    check("没有出现询问提示", "想装在哪里" not in out)

    print("5. 非法输入会重问")
    out, rc = run_child(b"C:\\\r\nD:\\Games\\Kards\r\n")
    path, how = result_of(out)
    check("提示是磁盘根目录", "根目录" in out, out[-260:])
    check("继续读下次输入并采纳",
          (path or "").lower().startswith("d:\\games\\kards"), path)
    check("标记为「手动输入」(重问后)", how == "手动输入", how)

    print("6. 连续 3 次非法 → 回退默认")
    out, rc = run_child(b"C:\\\r\nC:\\\r\nC:\\\r\n")
    path, how = result_of(out)
    check("3 次后回退默认", path == install.DEFAULT_DIR, path)
    check("标记为「默认（输入无效）」", how == "默认（输入无效）", how)

    print("7. 引号 / 空格 / ~ 处理")
    out, rc = run_child(b'"D:\\My Games\\Kards"\r\n')
    path, _how = result_of(out)
    check("引号被剥离", path and not path.startswith('"'), path)
    check("含空格的路径正确",
          (path or "").lower().startswith("d:\\my games\\kards"), path)

    out, rc = run_child(b"  D:\\Games\\Kards  \r\n")
    path, _how = result_of(out)
    check("首尾空格被剥离",
          (path or "").lower().startswith("d:\\games\\kards"), path)

    out, rc = run_child(b"~\\KardsTest\r\n")
    path, _how = result_of(out)
    check("~ 被展开为家目录", "~" not in (path or ""), path)

    print("7b. 非法字符 / 转义序列被拒绝")
    # 实测踩过：printf 喂入 "D:\Games\X\n" 时字面量 \n 进了路径，
    # 建出一个叫 "n" 的目录
    out, rc = run_child(b"D:\\Games\\X\\n\r\n" + b"D:\\Good\\Kards\r\n")
    path, how = result_of(out)
    check("含字面量 \\n 的路径被拒绝", "转义写法" in out, out[-220:])
    check("拒绝后采纳正确路径",
          (path or "").lower().startswith("d:\\good\\kards"), path)
    check("标记为「手动输入」", how == "手动输入", how)

    out, rc = run_child(b"D:\\Bad*Name\\Kards\r\n" + b"D:\\Ok\\Kards\r\n")
    path, _how = result_of(out)
    check("含 * 的路径被拒绝", "不允许的字符" in out, out[-200:])
    check("拒绝后采纳正确路径",
          (path or "").lower().startswith("d:\\ok\\kards"), path)

    print("7c. 下载超时常量必须大于停滞阈值")
    check("DL_READ_TIMEOUT > DL_STALL_TIMEOUT",
          install.DL_READ_TIMEOUT > install.DL_STALL_TIMEOUT,
          f"{install.DL_READ_TIMEOUT} vs {install.DL_STALL_TIMEOUT}")
    check("DL_TOTAL_TIMEOUT 足够大（>=300s）",
          install.DL_TOTAL_TIMEOUT >= 300, install.DL_TOTAL_TIMEOUT)

    print("8. 默认目录合理且不是安装器自己所在目录")
    check("默认不是磁盘根",
          os.path.dirname(install.DEFAULT_DIR) != install.DEFAULT_DIR,
          install.DEFAULT_DIR)
    check("默认在 Program Files 下", "Program Files" in install.DEFAULT_DIR,
          install.DEFAULT_DIR)
    # 关键：绝不把「安装器所在目录」（用户解压 Setup 包的目录）当默认安装目录
    check("默认目录 != 安装器所在目录",
          os.path.normcase(os.path.abspath(install.DEFAULT_DIR))
          != os.path.normcase(os.path.abspath(install.bundled_dir())),
          install.bundled_dir())

    print()
    if FAIL:
        print(f"FAILED: {len(FAIL)}/{len(PASS) + len(FAIL)}")
        for f in FAIL:
            print("  -", f)
        sys.exit(1)
    print(f"ALL OK ({len(PASS)} checks)")


if __name__ == "__main__":
    main()
