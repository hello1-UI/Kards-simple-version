# -*- coding: utf-8 -*-
"""生成 assets/music 下的占位背景音乐（纯标准库合成，无第三方依赖）

用法:
    python debug/gen_music.py [输出目录]

产出三首可无缝循环的 22.05kHz / 单声道 / 16bit WAV：
    menu.wav    主菜单：慢速、阴郁的弦乐垫 + 稀疏拨弦（A 小调）
    battle.wav  对局：军鼓行进 + 低音铜管固定音型（D 小调，112 BPM）
    result.wav  结算：铜管号角 + 定音鼓（C 大调）

⚠ 这三首是**占位曲**：风格对味但编曲简单。想要更好的效果，把真正的
menu.ogg / battle.ogg / result.ogg 丢进 assets/music 覆盖即可（kards_music
优先找 .ogg，其次是 .wav / .mp3），代码不用动。

实现要点：
- 循环无缝：所有音符/混响尾音都**环绕写入**缓冲区（超出末尾就从头写），
  所以循环点听不出断口。
- 固定随机种子：每次生成的噪声（军鼓/镲）完全一致，便于比对。
"""
import array
import math
import os
import random
import struct
import sys
import wave

SR = 22050
rng = random.Random(20261111)


# ---------------------------------------------------------------- 基础工具

def sec(x):
    return int(round(x * SR))


def note_freq(name):
    """'A4' / 'C#3' / 'Bb2' → 频率（十二平均律，A4=440）"""
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    step = base[name[0].upper()]
    i = 1
    while i < len(name) and name[i] in "#b":
        step += 1 if name[i] == "#" else -1
        i += 1
    octave = int(name[i:])
    midi = (octave + 1) * 12 + step
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def new_buf(seconds):
    n = sec(seconds)
    return array.array("f", bytes(4 * n)), n


def add(buf, n, start, samples, gain=1.0):
    """把 samples 叠加到 buf 的 start 位置；超出末尾**环绕**到开头（无缝循环）"""
    ln = len(samples)
    if ln == 0 or n == 0:
        return
    i = start % n
    for k in range(ln):
        buf[i] += samples[k] * gain
        i += 1
        if i >= n:
            i = 0


def env_adsr(length, attack, release, curve=2.0):
    """返回长度 length 的包络表（0..1）：线性起音 + 指数式衰减到 0"""
    a = max(1, min(length, sec(attack)))
    r = max(1, min(length - a, sec(release))) if length > a else 0
    out = [0.0] * length
    for i in range(a):
        out[i] = i / a
    for i in range(a, length - r):
        out[i] = 1.0
    for j in range(r):
        x = 1.0 - (j / r)
        out[a + j] = x ** curve
    return out


# ---------------------------------------------------------------- 乐器

def pad(freq, dur, amp=0.10):
    """弦乐垫：基频 + 弱二次谐波 + 轻微失谐，慢起慢收"""
    ln = sec(dur)
    env = env_adsr(ln, 0.55, 0.9, curve=1.6)
    out = [0.0] * ln
    for det in (-0.0016, 0.0, 0.0017):
        f = freq * (1 + det)
        for i in range(ln):
            t = i / SR
            v = math.sin(2 * math.pi * f * t) + 0.32 * math.sin(4 * math.pi * f * t)
            out[i] += v * env[i]
    norm = amp / 3.0
    return [v * norm for v in out]


def pluck(freq, dur, amp=0.14):
    """拨弦/钢琴感：前 4 个谐波，高次谐波衰减更快"""
    ln = sec(dur)
    out = [0.0] * ln
    for h, a in ((1, 1.0), (2, 0.45), (3, 0.22), (4, 0.12)):
        decay = 2.6 + h * 1.9
        f = freq * h
        for i in range(ln):
            t = i / SR
            out[i] += a * math.sin(2 * math.pi * f * t) * math.exp(-decay * t)
    attack = max(1, sec(0.004))
    for i in range(min(attack, ln)):
        out[i] *= i / attack
    peak = max(1e-6, max(abs(v) for v in out))
    return [v / peak * amp for v in out]


def brass(freq, dur, amp=0.13, vib=5.2):
    """铜管：奇偶谐波都有、略带颤音、起音偏硬"""
    ln = sec(dur)
    env = env_adsr(ln, 0.05, 0.16, curve=2.2)
    out = [0.0] * ln
    for h in range(1, 8):
        a = 1.0 / (h ** 1.35)
        f = freq * h
        for i in range(ln):
            t = i / SR
            ff = f * (1 + 0.0035 * math.sin(2 * math.pi * vib * t))
            out[i] += a * math.sin(2 * math.pi * ff * t)
    peak = max(1e-6, max(abs(v) for v in out))
    return [v / peak * amp * env[i] for i, v in enumerate(out)]


def snare(amp=0.16, dur=0.22):
    """军鼓：噪声瞬态 + 190Hz 鼓皮"""
    ln = sec(dur)
    out = [0.0] * ln
    prev = 0.0
    for i in range(ln):
        t = i / SR
        w = rng.uniform(-1, 1)
        hp = w - prev * 0.7          # 一阶差分 → 高频更亮
        prev = w
        out[i] = hp * 0.8 * math.exp(-26 * t)
        out[i] += 0.5 * math.sin(2 * math.pi * 190 * t) * math.exp(-32 * t)
    peak = max(1e-6, max(abs(v) for v in out))
    return [v / peak * amp for v in out]


def timpani(amp=0.22, dur=0.75, f0=98.0):
    """定音鼓/低鼓：音高下滑 + 指数衰减"""
    ln = sec(dur)
    out = [0.0] * ln
    for i in range(ln):
        t = i / SR
        f = f0 * (1 + 0.9 * math.exp(-18 * t))
        out[i] = math.sin(2 * math.pi * f * t) * math.exp(-4.2 * t)
    return [v * amp for v in out]


def cymbal(amp=0.07, dur=1.2):
    ln = sec(dur)
    out = [0.0] * ln
    prev = 0.0
    for i in range(ln):
        t = i / SR
        w = rng.uniform(-1, 1)
        out[i] = (w - prev) * math.exp(-3.2 * t)
        prev = w
    peak = max(1e-6, max(abs(v) for v in out))
    return [v / peak * amp for v in out]


# ---------------------------------------------------------------- 混响 / 母带

def reverb(buf, n, taps=((0.043, 0.28), (0.071, 0.20), (0.113, 0.13))):
    """简易梳状混响（环绕延迟，循环点自然衔接）"""
    src = array.array("f", buf)
    for delay_s, gain in taps:
        d = sec(delay_s)
        if d <= 0:
            continue
        for i in range(n):
            buf[i] += src[(i - d) % n] * gain


def master(buf, n, peak=0.80, rms_target=None):
    """归一化 + 软限幅。

    有 rms_target 时按**响度**对齐（军鼓/定音鼓这种尖峰多的曲子，只按峰值
    归一化会明显比别的曲子小声），峰值仍受 peak 约束，不会削波。
    """
    mx = max(1e-6, max(abs(v) for v in buf))
    rms = math.sqrt(sum(v * v for v in buf) / max(1, n))
    gain = peak / mx
    if rms_target and rms > 1e-6:
        # 取「响度增益」和「峰值上限」里更保守的那个
        gain = min(rms_target / rms, peak / mx)
    for i in range(n):
        v = buf[i] * gain
        # 软限幅：超过 0.95 的部分压回来，避免削波爆音
        if v > 0.95 or v < -0.95:
            v = math.tanh(v * 1.4) * 0.93
        buf[i] = v


def write_wav(path, buf, n):
    data = array.array("h", bytes(2 * n))
    for i in range(n):
        data[i] = int(max(-32767, min(32767, buf[i] * 32767)))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


# ---------------------------------------------------------------- 三首曲子

def build_menu():
    """主菜单：60 BPM，4 小节 ×2 的 Am–F–C–G，32 秒一循环"""
    bpm = 60.0
    beat = 60.0 / bpm
    bars = 8
    total = bars * 4 * beat
    buf, n = new_buf(total)

    prog = [("A2", ["A3", "C4", "E4", "A4"]),
            ("F2", ["F3", "A3", "C4", "F4"]),
            ("C3", ["C3", "E3", "G3", "C4"]),
            ("G2", ["G3", "B3", "D4", "G4"])]
    for b in range(bars):
        root, chord = prog[(b // 2) % 4]
        start = sec(b * 4 * beat)
        # 低音持续音
        add(buf, n, start, pad(note_freq(root), 4 * beat * 0.98, amp=0.20))
        # 弦乐垫
        for nm in chord:
            add(buf, n, start, pad(note_freq(nm), 4 * beat * 0.98, amp=0.045))
        # 稀疏拨弦：每小节 2 个音，节奏略错开
        for k, offset in enumerate((0.0, 2.5)):
            nm = chord[(b + k) % len(chord)]
            up = note_freq(nm) * (2 if k else 1)
            add(buf, n, sec((b * 4 + offset) * beat), pluck(up, 1.6, amp=0.10))
    reverb(buf, n)
    master(buf, n, peak=0.86, rms_target=0.13)
    return buf, n


def build_battle():
    """对局：112 BPM，8 小节，D 小调军乐，军鼓行进 + 铜管固定音型"""
    bpm = 112.0
    beat = 60.0 / bpm
    bars = 8
    total = bars * 4 * beat
    buf, n = new_buf(total)

    roots = ["D2", "D2", "Bb1", "C2", "D2", "D2", "Bb1", "A1"]
    stabs = [["D3", "F3", "A3"], ["D3", "F3", "A3"],
             ["Bb2", "D3", "F3"], ["C3", "E3", "G3"],
             ["D3", "F3", "A3"], ["D3", "F3", "A3"],
             ["Bb2", "D3", "F3"], ["A2", "C#3", "E3"]]
    for b in range(bars):
        root = roots[b]
        bar_start = b * 4 * beat
        # 低音固定音型：八分音符，第 3 个换成五度（×1.5 近似），其余走根音
        for k in range(8):
            nm = root if k % 4 in (0, 1, 3) else None
            if nm is None:
                # 五度：把根音频率 ×1.5 近似（同调内够用）
                sample = brass(note_freq(root) * 1.5, beat * 0.42, amp=0.10)
            else:
                sample = brass(note_freq(root), beat * 0.42, amp=0.13)
            add(buf, n, sec(bar_start + k * beat * 0.5), sample)
        # 小节头的铜管和弦
        for nm in stabs[b]:
            add(buf, n, sec(bar_start), brass(note_freq(nm), beat * 0.75, amp=0.055))
        # 军鼓：二、四拍 + 每两小节末尾一个十六分滚奏
        for k in (1, 3):
            add(buf, n, sec(bar_start + k * beat), snare(amp=0.13))
        if b % 2 == 1:
            for j in range(4):
                add(buf, n, sec(bar_start + 3 * beat + j * beat * 0.25),
                    snare(amp=0.07 + 0.02 * j, dur=0.16))
        # 定音鼓：每两小节一次
        if b % 2 == 0:
            add(buf, n, sec(bar_start), timpani(amp=0.20, f0=note_freq(root)))
        # 镲：四小节一次，撑开段落
        if b % 4 == 0:
            add(buf, n, sec(bar_start), cymbal(amp=0.05))
    reverb(buf, n, taps=((0.031, 0.20), (0.067, 0.13)))
    master(buf, n, peak=0.86, rms_target=0.12)
    return buf, n


def build_result():
    """结算：92 BPM，C 大调号角，12 秒一循环"""
    bpm = 92.0
    beat = 60.0 / bpm
    bars = 4
    total = bars * 4 * beat
    buf, n = new_buf(total)

    # 和弦进行：C – F – G – C（每小节一个）
    chords = [["C3", "E3", "G3", "C4"],
              ["F2", "A2", "C3", "F3"],
              ["G2", "B2", "D3", "G3"],
              ["C3", "E3", "G3", "C4"]]
    for b, chord in enumerate(chords):
        start = b * 4 * beat
        for nm in chord:
            add(buf, n, sec(start), brass(note_freq(nm), beat * 1.6, amp=0.075))
        add(buf, n, sec(start), timpani(amp=0.18, f0=note_freq(chord[0])))
        # 号角动机：根音-五度-八度
        motive = [chord[0], chord[2], chord[3]]
        for k, nm in enumerate(motive):
            add(buf, n, sec(start + k * beat * 0.5),
                brass(note_freq(nm), beat * 0.45, amp=0.11))
        if b == bars - 1:
            # 末小节加一个镲 + 长和弦收束
            add(buf, n, sec(start), cymbal(amp=0.06, dur=1.6))
            for nm in chord:
                add(buf, n, sec(start + beat), brass(note_freq(nm), beat * 2.6, amp=0.06))
    reverb(buf, n, taps=((0.049, 0.26), (0.079, 0.17)))
    master(buf, n, peak=0.86, rms_target=0.12)
    return buf, n


TRACKS = {"menu": build_menu, "battle": build_battle, "result": build_result}


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "assets", "music")
    os.makedirs(out_dir, exist_ok=True)
    for name, fn in TRACKS.items():
        buf, n = fn()
        path = os.path.join(out_dir, name + ".wav")
        write_wav(path, buf, n)
        dur = n / SR
        size = os.path.getsize(path) / 1048576
        rms = math.sqrt(sum(v * v for v in buf) / max(1, n))
        print("%-8s %5.1fs %5.2fMB  rms=%.3f  %s" % (name, dur, size, rms, path))


if __name__ == "__main__":
    main()
