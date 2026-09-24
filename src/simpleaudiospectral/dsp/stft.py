"""Viewport spectrogram columns from every frame."""

import math

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from . import core


def stft_columns(x, sr, t0, t1, cols, fft, win, reduce=None):
    """Mean power spectrum per display column, from EVERY frame.

    Frames are centred every fft/2 samples; column j averages the power of
    every frame whose centre lies in its time slot. When a slot is shorter
    than fft/2 (zoomed in), the column shows the single frame centred on it.

    Columns are processed in groups; `reduce(power[g, fft/2+1])` maps each
    group's exact column spectra to what the caller keeps (the viewer pools
    bins to display rows), so the full-resolution matrix never exists at once.
    Frames are cut from one contiguous read per work unit.
    """
    n = len(x)
    nb = fft // 2 + 1
    hop = fft // 2
    a, b = t0 * sr, t1 * sr
    slot = (b - a) / cols
    reduce = reduce or (lambda p: p)
    per = max(1, (4 * 1024 * 1024) // (fft * 8))
    group = max(1, core.STFT_GROUP_BYTES // (nb * 8))

    def spec(starts):
        lo, hi = int(starts[0]), int(starts[-1]) + fft
        span = np.zeros(hi - lo)
        s0, s1 = max(0, lo), min(n, hi)
        if s1 > s0:
            span[s0 - lo : s1 - lo] = core.f64(x[s0:s1])
        fr = sliding_window_view(span, fft)[starts - lo]
        return core.spec_power(fr, win)

    if slot < hop:
        centers = (a + (np.arange(cols) + 0.5) * slot).astype(np.int64)
        parts = []
        for g0 in range(0, cols, group):
            g1 = min(cols, g0 + group)
            blocks = list(
                core.POOL.map(
                    lambda c0, g1=g1: spec(centers[c0 : min(g1, c0 + per)] - fft // 2), range(g0, g1, per)
                )
            )
            parts.append(reduce(np.concatenate(blocks)))
        return np.concatenate(parts)

    k0 = math.ceil(a / hop)
    k1 = math.ceil(b / hop)
    centers = np.arange(k0, k1, dtype=np.int64) * hop
    col = np.minimum(cols - 1, ((centers - a) / slot).astype(np.int64))
    counts = np.bincount(col, minlength=cols)
    first = np.searchsorted(col, np.arange(cols + 1))
    parts = []
    for g0 in range(0, cols, group):
        g1 = min(cols, g0 + group)
        acc = np.zeros((g1 - g0, nb))
        f_lo, f_hi = first[g0], first[g1]

        def work(f0, f_hi=f_hi, g0=g0):
            f1 = min(f_hi, f0 + per)
            p = spec(centers[f0:f1] - fft // 2)
            cc = col[f0:f1]
            st = np.flatnonzero(np.r_[True, cc[1:] != cc[:-1]])
            return cc[st] - g0, np.add.reduceat(p, st, axis=0)

        for cids, sums in core.POOL.map(work, range(f_lo, f_hi, per)):
            acc[cids] += sums
        c = counts[g0:g1]
        nz = c > 0
        acc[nz] /= c[nz][:, None]
        parts.append(reduce(acc))
    return np.concatenate(parts)
