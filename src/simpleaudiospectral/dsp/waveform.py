"""Waveform index: exact min/max per column without reading every sample."""

import numpy as np


class BlockExtremes:
    """Min and max of every block of B samples: the waveform index. An exact
    column min/max is the min/max of the whole blocks inside the column plus
    the samples of the partial blocks at its two edges."""

    def __init__(self, B=4096):
        self.B = B
        self.mn, self.mx = [], []
        self.tail = np.zeros(0, np.float32)

    def feed(self, seg, _a=0):
        v = np.concatenate([self.tail, np.asarray(seg, dtype=np.float32)])
        m = len(v) // self.B
        if m:
            blk = v[: m * self.B].reshape(m, self.B)
            self.mn.append(blk.min(axis=1))
            self.mx.append(blk.max(axis=1))
        self.tail = v[m * self.B :]

    def finish(self):
        if len(self.tail):
            self.mn.append(np.array([self.tail.min()]))
            self.mx.append(np.array([self.tail.max()]))
        return (np.concatenate(self.mn), np.concatenate(self.mx)) if self.mn else (np.zeros(0), np.zeros(0))


def column_extremes(x, a, b, cols, index, B):
    """Exact min/max of x over each of `cols` equal spans of [a, b), using the
    BlockExtremes index for whole blocks and reading only the partial blocks
    at each span's edges. Identical to np.minimum/maximum.reduceat over the
    samples."""
    mn_i, mx_i = index
    edges = np.linspace(a, b, cols + 1).astype(np.int64)
    out = np.zeros((cols, 2), dtype=np.float32)
    for j in range(cols):
        s, e = int(edges[j]), int(max(edges[j + 1], edges[j] + 1))
        e = min(e, len(x))
        if e <= s:
            continue
        b0, b1 = -(-s // B), e // B  # whole blocks fully inside [s, e)
        lo, hi = np.inf, -np.inf
        if b1 > b0:
            lo, hi = float(mn_i[b0:b1].min()), float(mx_i[b0:b1].max())
            parts = [(s, b0 * B), (b1 * B, e)]
        else:
            parts = [(s, e)]
        for p0, p1 in parts:
            if p1 > p0:
                v = np.asarray(x[p0:p1], dtype=np.float32)
                lo, hi = min(lo, float(v.min())), max(hi, float(v.max()))
        out[j] = (lo, hi)
    return out
