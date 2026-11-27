package com.kards.engine;

import java.util.Collections;
import java.util.List;

/** 跨端确定性随机数（xorshift32，逐位对齐 kards_engine.EngineRng）。
 *
 * 对局内的随机效果（喀秋莎加成 / 拦截目标 / 随机伤害目标 / 弃牌等）统一
 * 走它：联机双方用同一 match seed 构造 Game，同一行动序列消耗同一随机
 * 序列 → Python↔Android 结算一致，不会分叉。
 *
 * ⚠ AI 决策不在两端共同结算路径上（AI 的选择会作为明确行动发出去），
 *   必须用独立的 java.util.Random，不能消耗这条共享序列。
 * 取模直接截断（有偏但确定），两端同式即可。
 */
public final class Rng {
    private int state;

    public Rng(long seed) {
        int s = (int) seed;
        state = s != 0 ? s : 0x9E3779B9;    // xorshift32 状态不能为 0
    }

    public int next32() {
        int x = state;
        x ^= (x << 13);
        x ^= (x >>> 17);
        x ^= (x << 5);
        state = x;
        return x;
    }

    /** [0, bound) 的随机整数（bound > 0） */
    public int nextInt(int bound) {
        if (bound <= 0) throw new IllegalArgumentException("bound must be > 0");
        return (int) ((next32() & 0xFFFFFFFFL) % bound);
    }

    /** [a, b] 闭区间 */
    public int nextInt(int a, int b) {
        return a + nextInt(b - a + 1);
    }

    public <T> T choice(List<T> seq) {
        return seq.get(nextInt(seq.size()));
    }

    /** Fisher-Yates，从尾往前（Python 端同式） */
    public void shuffle(List<?> seq) {
        for (int i = seq.size() - 1; i > 0; i--) {
            int j = nextInt(i + 1);
            Collections.swap(seq, i, j);
        }
    }
}
