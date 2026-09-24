"""Goniometer density and stereo correlation."""

import math

import numpy as np

from . import core


class Goniometer:
    """Mid/side density over EVERY sample: np.histogram2d of (-m/lim, s/lim)
    with lim = max(|m|, |s|) over the range (known before this pass), plus the
    exact correlation sum(L*R)/sqrt(sum(L^2)*sum(R^2))."""

    def __init__(self, size, lim):
        self.size, self.lim = size, lim
        self.h = np.zeros((size, size))
        self.ll, self.rr, self.lr = [], [], []
        # np.histogram2d's edges and rule: bin = searchsorted(edges, v, 'right') - 1,
        # the last edge belongs to the last bin, values outside the range are dropped.
        self.edges = np.linspace(-1, 1, size + 1)

    def _bins(self, v):
        i = np.searchsorted(self.edges, v, side="right") - 1
        i[v == self.edges[-1]] = self.size - 1
        return i

    def _part(self, L, R):
        m, s = (L + R) / 2, (L - R) / 2
        x, y = -m / self.lim, s / self.lim
        ix, iy = self._bins(x), self._bins(y)
        ok = (ix >= 0) & (ix < self.size) & (iy >= 0) & (iy < self.size)
        h = np.bincount(ix[ok] * self.size + iy[ok], minlength=self.size * self.size)
        return (
            h.reshape(self.size, self.size),
            float((L * L).sum()),
            float((R * R).sum()),
            float((L * R).sum()),
        )

    def feed_pair(self, L32, R32, _a=0):
        L, R = core.f64(L32), core.f64(R32)
        per = 1 << 18
        for h, ll, rr, lr in core.POOL.map(
            lambda i: self._part(L[i : i + per], R[i : i + per]), range(0, len(L), per)
        ):
            self.h += h
            self.ll.append(ll)
            self.rr.append(rr)
            self.lr.append(lr)

    def finish(self):
        den = math.sqrt(math.fsum(self.ll) * math.fsum(self.rr))
        return self.h, (math.fsum(self.lr) / den if den > 0 else 1.0)


def goniometer(left, right, a, b, size):
    """Goniometer over [a, b) (two reads: the extreme, then the counts)."""
    lim = 1e-6
    for c in range(a, b, core.CHUNK):
        L = core.f64(left[c : min(b, c + core.CHUNK)])
        R = core.f64(right[c : min(b, c + core.CHUNK)])
        lim = max(lim, float(np.abs((L + R) / 2).max(initial=0)), float(np.abs((L - R) / 2).max(initial=0)))
    g = Goniometer(size, lim)
    for c in range(a, b, core.CHUNK):
        g.feed_pair(
            np.asarray(left[c : min(b, c + core.CHUNK)]), np.asarray(right[c : min(b, c + core.CHUNK)])
        )
    return g.finish()
