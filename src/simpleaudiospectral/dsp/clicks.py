"""Isolated clicks (vinyl and other analogue-chain hints)."""

import numpy as np

from . import core


class IsolatedClicks:
    """Isolated spikes in the 2nd difference, over the WHOLE file.

    Definition, per consecutive window of window_s seconds (the last one
    shorter): d2 = |diff(w, 2)|; a candidate is d2 > 40 * median(d2); it is
    isolated when it exceeds 4x the max of d2 within +-1.5 ms, excluding
    +-4 samples; candidates closer than 5 ms count once. Returns clicks per
    minute over the whole duration.
    """

    def __init__(self, sr, window_s=60):
        self.sr = sr
        self.win = max(sr, int(window_s * sr))
        self.buf = np.zeros(0)
        self.events = 0
        self.total = 0
        self.half, self.excl = max(8, int(sr * 0.0015)), 4
        self.offs = np.r_[np.arange(-self.half, -self.excl), np.arange(self.excl + 1, self.half + 1)]

    def _window(self, w):
        if len(w) < 3:
            return 0
        d2 = np.abs(np.diff(w, 2))
        mad = np.median(d2) + 1e-12
        cand = np.flatnonzero(d2 > 40 * mad)
        if not len(cand):
            return 0
        iso = []
        for c0 in range(0, len(cand), 65536):
            c = cand[c0 : c0 + 65536]
            nb = c[:, None] + self.offs[None, :]
            ok = (nb >= 0) & (nb < len(d2))
            around = np.where(ok, d2[np.clip(nb, 0, len(d2) - 1)], 0).max(axis=1)
            iso.append(c[d2[c] > 4 * around])
        iso = np.concatenate(iso)
        return int((np.r_[True, np.diff(iso) > self.sr // 200]).sum()) if len(iso) else 0

    def feed(self, seg, _offset=0):
        self.total += len(seg)
        self.buf = np.concatenate([self.buf, core.f64(seg)])
        full = len(self.buf) // self.win
        if full:
            windows = [self.buf[i * self.win : (i + 1) * self.win] for i in range(full)]
            self.events += sum(core.POOL.map(self._window, windows))
            self.buf = self.buf[full * self.win :]

    def finish(self):
        self.events += self._window(self.buf)
        minutes = self.total / self.sr / 60
        return round(self.events / minutes, 1) if minutes else 0.0
