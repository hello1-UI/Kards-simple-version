# -*- coding: utf-8 -*-
"""自动更新测试：版本比较 / 资产挑选 / 解压剥前缀 / 真实 Release 查询 / 后台任务

分两层：
  · **离线层**：纯逻辑（版本号比较、选资产、解压、bat 生成），必定可跑
  · **联网层**：真查一次 GitHub Release。本机网络对 github.com 有 DNS 投毒，
    api.github.com 也可能不通 —— 所以联网失败**不算失败**，只标注跳过，
    避免把「网络环境问题」误报成「代码坏了」。

运行（需 tkinter 的那个系统 Python 也行，本文件不依赖 tkinter）：
    python debug/test_update.py
"""
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kards_update as up                      # noqa: E402

PASS, FAIL, SKIP = [], [], []


def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  [OK] " if cond else "  [!!] ") + label + (f"  {extra}" if extra else ""))


def skip(label, why=""):
    SKIP.append(label)
    print(f"  [--] {label}  (跳过: {why})")


def main():
    print("1. 版本号解析")
    check("v1.2.0.3 → (1,2,0,3)", up.parse_version("v1.2.0.3") == (1, 2, 0, 3),
          up.parse_version("v1.2.0.3"))
    check("1.2.0.3（无 v）", up.parse_version("1.2.0.3") == (1, 2, 0, 3))
    check("v1.2 → (1,2)", up.parse_version("v1.2") == (1, 2))
    check("带后缀也能解析 v1.2.0.3-beta", up.parse_version("v1.2.0.3-beta") == (1, 2, 0, 3),
          up.parse_version("v1.2.0.3-beta"))
    check("空串 → ()", up.parse_version("") == ())
    check("乱码 → ()", up.parse_version("latest") == ())
    check("元组转字符串", up.version_str((1, 2, 0, 3)) == "1.2.0.3")

    print("2. 版本比较（短的一侧补 0）")
    check("1.2.0.4 > 1.2.0.3", up.is_newer("v1.2.0.4", "1.2.0.3"))
    check("1.2.0.3 不比 1.2.0.3 新", not up.is_newer("v1.2.0.3", "1.2.0.3"))
    check("1.2.0.2 不比 1.2.0.3 新", not up.is_newer("v1.2.0.2", "1.2.0.3"))
    check("1.2.1 > 1.2.0.3（第三位进位）", up.is_newer("v1.2.1", "1.2.0.3"))
    check("1.3 > 1.2.0.3（次位进位）", up.is_newer("v1.3", "1.2.0.3"))
    check("2.0 > 1.9.9.9（首位进位）", up.is_newer("v2.0", "1.9.9.9"))
    check("1.2.0.10 > 1.2.0.9（按数值不是字典序）",
          up.is_newer("v1.2.0.10", "1.2.0.9"))
    check("坏版本号不算新（避免误报）", not up.is_newer("latest", "1.2.0.3"))

    print("2b. 元组入参（KARDS.py 的 VERSION 就是元组，极易顺手传进来）")
    # ⚠ 回归锁：曾经的 bug 是 str((1,3,0,0)) == "(1, 3, 0, 0)" 在 '(' 处断掉
    #   → parse_version 返回 () → is_newer 把本地补成 (0,0,0,0)
    #   → **任何版本都被判成有更新**，每次启动都弹假更新窗。
    check("parse_version 吃元组", up.parse_version((1, 3, 0, 0)) == (1, 3, 0, 0),
          up.parse_version((1, 3, 0, 0)))
    check("parse_version 吃列表", up.parse_version([1, 3, 0, 0]) == (1, 3, 0, 0))
    check("parse_version 吃 int", up.parse_version(7) == (7,))
    check("元组入参下同版本不算新", not up.is_newer("v1.3.0.0", (1, 3, 0, 0)))
    check("元组入参下旧版本不算新", not up.is_newer("v1.2.9.9", (1, 3, 0, 0)))
    check("元组入参下新版本算新", up.is_newer("v1.3.0.1", (1, 3, 0, 0)))
    check("本地解析失败时宁可不提示（不误报）",
          not up.is_newer("v1.3.0.0", "latest"))
    check("两侧都是元组也正确", up.is_newer((1, 3, 0, 1), (1, 3, 0, 0)))

    print("3. 资产挑选")
    assets = [{"name": "KARDS_SimpleVersion-Setup.zip", "url": "u1", "size": 1},
              {"name": "KARDS.zip", "url": "u2", "size": 2},
              {"name": "notes.txt", "url": "u3", "size": 3}]
    got = up.pick_asset(assets)
    check("优先挑 KARDS.zip", got and got["name"] == "KARDS.zip", got and got["name"])
    got2 = up.pick_asset([{"name": "other.zip", "url": "u", "size": 0}])
    check("没有 KARDS.zip 时退而取任意 zip",
          got2 and got2["name"] == "other.zip")
    check("没有任何 zip → None", up.pick_asset([{"name": "a.txt", "url": "", "size": 0}]) is None)
    check("空列表 → None", up.pick_asset([]) is None)

    print("4. 解压：自动剥掉 KARDS/ 前缀（发行包格式）")
    tmp = tempfile.mkdtemp(prefix="kards_upd_test_")
    try:
        zpath = os.path.join(tmp, "KARDS.zip")
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("KARDS/KARDS.py", "print('hi')")
            zf.writestr("KARDS/kards_engine.py", "VERSION=(1,2,0,4)")
            zf.writestr("KARDS/sub/data.txt", "x")
        out = os.path.join(tmp, "out")
        ok, err = up.extract_zip(zpath, out)
        check("解压成功", ok, err)
        check("前缀已剥掉（KARDS.py 在根）", os.path.exists(os.path.join(out, "KARDS.py")))
        check("子目录保持结构", os.path.exists(os.path.join(out, "sub", "data.txt")))
        check("没有多余的一层 KARDS/ 目录", not os.path.exists(os.path.join(out, "KARDS")))
        os.remove(os.path.join(out, "KARDS.py"))

        print("5. 解压：无前缀包不误剥")
        zpath2 = os.path.join(tmp, "flat.zip")
        with zipfile.ZipFile(zpath2, "w") as zf:
            zf.writestr("KARDS.py", "a")
            zf.writestr("kards_engine.py", "b")
        out2 = os.path.join(tmp, "out2")
        ok, err = up.extract_zip(zpath2, out2)
        check("扁平包解压成功", ok, err)
        check("扁平包文件在根", os.path.exists(os.path.join(out2, "KARDS.py")))

        print("5b. 解压：显式 strip_root 的两种写法都要能用")
        # ⚠ 回归锁：曾经传 'KARDS'（不带结尾斜杠）会命中前缀、剥成 '/x'，
        #   在 Windows 上是绝对路径 → 被 zip-slip 守卫全拦 → 一个文件都没解压
        #   却返回成功。自更新走到这里就是把游戏目录清空。
        for label, root in (("带斜杠 'KARDS/'", "KARDS/"), ("不带斜杠 'KARDS'", "KARDS")):
            o = os.path.join(tmp, "out_sr_" + root.replace("/", "_"))
            okx, errx = up.extract_zip(zpath, o, strip_root=root)
            check(f"显式 strip_root {label} 解压成功", okx, errx)
            check(f"显式 strip_root {label} 文件到位",
                  os.path.exists(os.path.join(o, "KARDS.py")))
        # 前缀对不上时**不该报错**（等价于不剥），只是会多留一层目录 ——
        # 这是个中性行为，但必须显式钉住，免得以后有人改成"静默丢弃"。
        o2 = os.path.join(tmp, "out_nomatch")
        okn, errn = up.extract_zip(zpath, o2, strip_root="不相干的前缀")
        check("前缀对不上时不报错（等价于不剥）", okn, errn)
        check("前缀对不上时多留一层目录（文件没丢）",
              os.path.exists(os.path.join(o2, "KARDS", "KARDS.py")))

        # 空目录哨兵：整包条目都被 zip-slip 拦掉 → 必须报错而不是假装成功。
        # （这是「装上一个空目录」唯一还会走到的路径，所以值得专门锁住）
        zbad = os.path.join(tmp, "all_evil.zip")
        with zipfile.ZipFile(zbad, "w") as zf:
            zf.writestr("KARDS/../../evil1.txt", "bad")
            zf.writestr("KARDS/../../evil2.txt", "bad")
        o3 = os.path.join(tmp, "out_all_evil")
        okg, errg = up.extract_zip(zbad, o3)
        check("全部条目越界时报错（不静默装空目录）", not okg, errg)
        check("报错信息里点明了 strip_root", "strip_root" in (errg or ""), errg)

        print("6. 解压：防护 zip slip（../../ 不能越界）")
        zpath3 = os.path.join(tmp, "evil.zip")
        with zipfile.ZipFile(zpath3, "w") as zf:
            zf.writestr("KARDS/ok.py", "fine")
            zf.writestr("KARDS/../../../evil.txt", "bad")
        out3 = os.path.join(tmp, "out3")
        ok, err = up.extract_zip(zpath3, out3)
        check("恶意包不抛异常（跳过越界项）", ok, err)
        check("越界文件没有写到外面",
              not os.path.exists(os.path.join(tmp, "..", "evil.txt"))
              and not os.path.exists(os.path.join(tempfile.gettempdir(), "evil.txt")))
        check("正常文件仍然解压出来", os.path.exists(os.path.join(out3, "ok.py")))

        print("7. 下载：官方 + 镜像都失败时要明确报错（不静默成功）")
        bad = {"name": "KARDS.zip", "url": "http://127.0.0.1:1/nope.zip", "size": 10}
        ok, err = up.download(bad, os.path.join(tmp, "dl.zip"), timeout=3)
        check("下载失败返回 False", not ok)
        check("失败原因非空", bool(err), err)
        check("失败后不留下 .part 残留",
              not any(n.endswith(".part") for n in os.listdir(tmp)), os.listdir(tmp))

        print("7b. 进度回调写错签名时，下载本身不能被拖垮")
        # ⚠ 回归锁：download() 外层那个 `except Exception` 是拿来换镜像的，
        #   一开始没给回调单独 try，于是「回调签名写错」被误判成「网络失败」，
        #   白白把所有镜像重试一遍、耗时多几十秒，最后报一个和真因无关的错误。
        import http.server
        import threading

        srv_dir = os.path.join(tmp, "srv")
        os.makedirs(srv_dir, exist_ok=True)
        payload = b"K" * 300000
        with open(os.path.join(srv_dir, "KARDS.zip"), "wb") as f:
            f.write(payload)

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def __init__(self, *a, **kw):
                super().__init__(*a, directory=srv_dir, **kw)

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]
        try:
            good = {"name": "KARDS.zip",
                    "url": f"http://127.0.0.1:{port}/KARDS.zip",
                    "size": len(payload)}
            # 1) 正常回调：能收到进度，且分母正确
            seen = []
            okp, errp = up.download(good, os.path.join(tmp, "dl_ok.zip"),
                                    progress=lambda d, t: seen.append((d, t)),
                                    timeout=10)
            check("正常回调下下载成功", okp, errp)
            check("进度回调被调用过", len(seen) > 0, f"{len(seen)} 次")
            check("进度分母是总长度（不是 0）",
                  bool(seen) and seen[-1][1] == len(payload),
                  seen[-1] if seen else "无")

            # 2) 坏回调（签名少一个参数）：下载仍须成功
            def bad_cb(done):                     # noqa: ARG001
                raise AssertionError("签名不对")

            okb, errb = up.download(good, os.path.join(tmp, "dl_bad.zip"),
                                    progress=bad_cb, timeout=10)
            check("回调抛异常时下载仍然成功", okb, errb)
            check("坏回调下文件完整",
                  os.path.isfile(os.path.join(tmp, "dl_bad.zip"))
                  and os.path.getsize(os.path.join(tmp, "dl_bad.zip")) == len(payload))
        finally:
            httpd.shutdown()
            httpd.server_close()

        print("7c. 解压进度不会冲过 100%")
        # infolist() 含目录项、还会跳过 zip-slip 与空名项，
        # 早先用 infolist 下标当分子会让进度条超过 1.0。
        zpath4 = os.path.join(tmp, "prog.zip")
        with zipfile.ZipFile(zpath4, "w") as zf:
            zf.writestr("KARDS/", "")                    # 目录项
            for i in range(5):
                zf.writestr(f"KARDS/f{i}.txt", "x" * 10)
            zf.writestr("KARDS/../../../skip.txt", "nope")   # 会被跳过
        frac = []
        ok4, err4 = up.extract_zip(zpath4, os.path.join(tmp, "out4"),
                                   progress=lambda d, t: frac.append(d / t))
        check("解压成功", ok4, err4)
        check("有进度回调", len(frac) > 0, f"{len(frac)} 次")
        check("进度全程不超过 100%", bool(frac) and max(frac) <= 1.0,
              f"max={max(frac):.3f}" if frac else "无")
        check("进度最终收敛到 100%", bool(frac) and abs(frac[-1] - 1.0) < 1e-9,
              f"last={frac[-1]:.3f}" if frac else "无")

        print("8. bat 生成（Windows 免锁替换用）")
        bat = up.write_update_bat(pid=999999, exe=sys.executable, args=[])
        if sys.platform == "win32":
            check("生成了 bat", bat is not None and os.path.exists(bat), bat)
            if bat and os.path.exists(bat):
                raw = open(bat, "rb").read()
                check("bat 是纯 ASCII（cmd.exe 不会乱码）", all(b < 128 for b in raw))
                txt = raw.decode("ascii")
                check("bat 里等的是自己的 PID", "999999" in txt)
                check("bat 结尾会重启程序", "start" in txt)
                os.remove(bat)
        else:
            skip("bat 生成", "非 Windows")

        print("9. 更新目标目录判定")
        d = up.can_self_update()
        check("能给出一个存在的目录", d and os.path.isdir(d), d)
        check("该目录不是用户数据目录（frozen 时 DATA_DIR 在 AppData）",
              os.path.basename(d) not in ("Kards-Simple-Version",), d)
        # 本测试是被 `python debug/test_update.py` 启动的，argv[0] 指向 debug/，
        # 所以这里只能验证「目录存在于磁盘」+「跟 argv[0] 一致」。
        # 真正的游戏路径另有断言（下面用显式 argv 复现一次）。
        check("目录与启动脚本所在目录一致",
              os.path.normcase(d) == os.path.normcase(
                  os.path.dirname(os.path.abspath(sys.argv[0]))), d)
        old_argv = sys.argv
        try:
            sys.argv = [os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "KARDS.py")]
            gdir = up.can_self_update()
            check("以 KARDS.py 启动时指向项目根目录",
                  os.path.exists(os.path.join(gdir, "KARDS.py")), gdir)
        finally:
            sys.argv = old_argv
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("9b. 打包形态判定（onefile vs onedir —— PyInstaller 6 的 _MEIPASS 陷阱）")
    # PyInstaller 6 起 onedir 也设置 sys._MEIPASS（指向 _internal/），
    # 旧判据 `bool(_MEIPASS)` 会把安装版 exe 误报成单文件版 → 无法更新。
    # 这里用假目录 + 临时改 sys 属性模拟三种形态。
    tmpf = tempfile.mkdtemp(prefix="kards_shape_")
    exe_dir = os.path.join(tmpf, "KARDS")
    os.makedirs(os.path.join(exe_dir, "_internal"), exist_ok=True)
    fake_exe = os.path.join(exe_dir, "KARDS.exe")
    mei_onefile = os.path.join(tempfile.gettempdir(), "_MEI123456")

    def _with_shape(frozen, mei, exe, fn):
        """临时伪装 sys 属性跑 fn，返回其结果"""
        saved = (getattr(sys, "frozen", None), getattr(sys, "_MEIPASS", None),
                 sys.executable)
        try:
            if frozen is None:
                if hasattr(sys, "frozen"):
                    del sys.frozen
            else:
                sys.frozen = frozen
            if mei is None:
                if hasattr(sys, "_MEIPASS"):
                    del sys._MEIPASS
            else:
                sys._MEIPASS = mei
            sys.executable = exe
            return fn()
        finally:
            if saved[0] is None:
                if hasattr(sys, "frozen"):
                    del sys.frozen
            else:
                sys.frozen = saved[0]
            if saved[1] is None:
                if hasattr(sys, "_MEIPASS"):
                    del sys._MEIPASS
            else:
                sys._MEIPASS = saved[1]
            sys.executable = saved[2]

    try:
        # ① 源码运行
        r = _with_shape(None, None, __file__,
                        lambda: (up.has_meipass(), up.can_self_update()))
        check("源码运行：非 onefile", r[0] is False)
        check("源码运行：能就地更新", r[1] is not None)
        # ② onedir PyInstaller 6：_MEIPASS 指向 exe 旁的 _internal/
        r = _with_shape(True, os.path.join(exe_dir, "_internal"), fake_exe,
                        lambda: (up.has_meipass(), up.can_self_update(),
                                 up.restart_dir()))
        check("onedir(PyInstaller6)：**不是** onefile（v1.6.3.8 回归）",
              r[0] is False, str(r))
        check("onedir(PyInstaller6)：更新目标 = _internal/",
              r[1] and os.path.samefile(r[1], os.path.join(exe_dir, "_internal")),
              r[1])
        check("onedir(PyInstaller6)：重启目录 = exe 层",
              r[2] and os.path.samefile(r[2], exe_dir), r[2])
        # ③ onedir PyInstaller ≤5 旧布局：_MEIPASS 就是 exe 目录
        r = _with_shape(True, exe_dir, fake_exe, up.has_meipass)
        check("onedir(旧布局)：不是 onefile", r is False)
        # ④ onefile：_MEIPASS 在 %TEMP%
        r = _with_shape(True, mei_onefile, fake_exe,
                        lambda: (up.has_meipass(), up.can_self_update(),
                                 up.restart_dir()))
        check("onefile：判定为 onefile", r[0] is True)
        check("onefile：拒绝就地更新（target_dir=None）", r[1] is None)
        check("onefile：重启目录 = exe 层",
              r[2] and os.path.samefile(r[2], exe_dir), r[2])
        # ⑤ onefile 的 UpdateTask 会给出明确报错而不是默默解压到临时目录
        #   （构造器会把 None 兜底成 can_self_update()，须事后置 None 模拟 onefile）
        t = up.UpdateTask("1.2.0.3")
        t.target_dir = None
        ok = t.start()
        check("onefile：start() 拒绝启动", ok is False)
        check("onefile：报错文案提单文件版", "单文件" in t.message, t.message)
        # ⑥ TEMP 与 exe 跨盘符（relpath ValueError → 应算 onefile）
        r = _with_shape(True, mei_onefile, fake_exe, up.has_meipass)
        check("onefile：判据不依赖同盘符", r is True)
        # ⑦ frozen 但没有 _MEIPASS（非常规打包）→ 不当 onefile，可更新
        r = _with_shape(True, None, fake_exe,
                        lambda: (up.has_meipass(), up.can_self_update()))
        check("frozen 无 _MEIPASS：不是 onefile", r[0] is False)
        check("frozen 无 _MEIPASS：更新目标仍能给出（_internal 存在 → _internal）",
              r[1] and os.path.samefile(r[1], os.path.join(exe_dir, "_internal")),
              r[1])
    finally:
        shutil.rmtree(tmpf, ignore_errors=True)
    # 收尾：确保模拟属性已还原，后续段落不受污染（本测试从源码跑，应无 frozen/_MEIPASS）
    check("形态模拟后 sys 属性已还原",
          not hasattr(sys, "frozen") and not hasattr(sys, "_MEIPASS"))

    print("10. 后台任务状态机（用一个假 info 走一遍 found 分支）")
    t = up.UpdateTask("1.2.0.3", auto_install=False)
    check("初始状态 idle", t.state == "idle")
    check("本地版本已规范化", t.local == "1.2.0.3", t.local)
    t.cancel()                                  # 未启动时取消也安全
    check("未启动时 cancel 不崩", True)

    print("10b. SHA256 完整性校验（离线，用 file:// 当真源）")
    import hashlib
    H = "a" * 64
    check("digest 'sha256:xxx' 归一化", up.digest_to_sha256("sha256:" + H) == H)
    check("digest 全大写也认", up.digest_to_sha256("SHA256:" + H.upper()) == H)
    check("digest 纯哈希也认", up.digest_to_sha256(H) == H)
    check("不认识的算法 → 空（当作没校验值）", up.digest_to_sha256("md5:abc") == "")
    check("None / 空串 → 空", up.digest_to_sha256(None) == "" and up.digest_to_sha256("") == "")
    check("校验文件：标准两列", up.parse_sums(f"{H}  KARDS.zip", "KARDS.zip") == H)
    check("校验文件：二进制标记 *", up.parse_sums(f"{H} *KARDS.zip", "KARDS.zip") == H)
    check("校验文件：带目录前缀", up.parse_sums(f"{H}  dist/KARDS.zip", "KARDS.zip") == H)
    check("校验文件：单行光杆哈希", up.parse_sums(H, "KARDS.zip") == H)
    check("校验文件：注释与空行不干扰",
          up.parse_sums(f"# sum\n\n{H}  KARDS.zip\n", "KARDS.zip") == H)
    check("校验文件：没有自己的条目 → 空",
          up.parse_sums(f"{H}  other.zip", "KARDS.zip") == "")
    check("校验文件：多条光杆哈希不瞎猜",
          up.parse_sums(f"{H}\n{'b' * 64}", "KARDS.zip") == "")

    d = tempfile.mkdtemp(prefix="kards_sha_test_")
    try:
        src = os.path.join(d, "KARDS.zip")
        payload = b"PK" + b"payload" * 900
        with open(src, "wb") as f:
            f.write(payload)
        real = hashlib.sha256(payload).hexdigest()
        check("_sha256_file 与 hashlib 一致", up._sha256_file(src) == real)
        asset = {"name": "KARDS.zip",
                 "url": "file:///" + src.replace(os.sep, "/"),
                 "size": len(payload)}

        out1 = os.path.join(d, "ok.zip")
        ok, err, meta = up.download_ex(asset, out1, want_sha=real)
        check("哈希对得上 → 成功且 verified=True",
              ok and meta["verified"] and os.path.getsize(out1) == len(payload), err)
        check("回传算出哈希便于排查", meta.get("sha256") == real)

        out2 = os.path.join(d, "bad.zip")
        ok, err, meta = up.download_ex(asset, out2, want_sha="b" * 64)
        check("哈希对不上 → 失败", not ok and "SHA256" in err, err[:50])
        check("校验失败不留下半成品",
              not os.path.exists(out2) and not os.path.exists(out2 + ".part"))
        check("校验失败标记 verified=False", meta["verified"] is False)

        out3 = os.path.join(d, "noverify.zip")
        ok, err, meta = up.download_ex(asset, out3)          # 没有校验值
        check("无校验值也能下载（但标记未校验）",
              ok and meta["verified"] is False and os.path.exists(out3))

        def boom(_done, _total):
            raise up.Cancelled()
        out4 = os.path.join(d, "cancel.zip")
        ok, err, _m = up.download_ex(asset, out4, progress=boom)
        check("取消不是「换个源重试」", not ok and err == "已取消", err)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("11. 真查一次 GitHub Release（网络不通则跳过，不算失败）")
    info = up.check_latest(timeout=12)
    if info.get("ok"):
        check("查到最新版本号", bool(info["version"]), info["version"])
        check("版本号可解析", bool(up.parse_version(info["version"])), info["version"])
        check("带回发布页链接", info.get("page", "").startswith("http"), info.get("page"))
        check("资产列表非空", len(info.get("assets") or []) > 0,
              [a["name"] for a in info.get("assets") or []])
        a = up.pick_asset(info.get("assets") or [])
        if a:
            check("能选出一个可下载的 zip", a["url"].startswith("http"), a["name"])
        else:
            skip("选出 zip 资产", "该 Release 没有 zip")
    else:
        skip("查询 GitHub Release", info.get("err", "")[:60])

    print()
    print("=" * 56)
    print(f"通过 {len(PASS)} 项 / 失败 {len(FAIL)} 项 / 跳过 {len(SKIP)} 项")
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
