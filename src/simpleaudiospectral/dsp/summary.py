"""Exact per-block statistics of a whole track."""

import math

import numpy as np

from . import core
from .runs import RunCounter


class Summary:
    """Exact per-block statistics of a whole track.

    For each block size B used by the analysis (3 s for DR, 1 s for the
    correlation series, 0.5 s for the loudest window, 0.4 s for the quiet
    floor), block i is exactly x[i*B : (i+1)*B], full blocks only, as in the
    whole-array definition x[:nb*B].reshape(nb, B). Fed in chunks that are a
    multiple of every block size (Summary.chunk), so no block is ever split.
    Also: exact whole-file totals, peak, identical-channel flag, clip runs,
    and the mid/side extreme the goniometer scale needs.
    """

    SIGNALS = ("left", "right", "mix", "side")

    def __init__(self, sr, n, stereo):
        self.sr, self.n, self.stereo = sr, n, stereo
        self.sizes = {"b3": 3 * sr, "b1": sr, "b05": int(0.5 * sr), "b04": int(0.4 * sr)}
        lcm = 1
        for b in self.sizes.values():
            lcm = math.lcm(lcm, b)
        self.chunk = core.chunk_len(lcm)
        nb = {k: n // b for k, b in self.sizes.items()}
        self.ss = {k: {s: np.zeros(nb[k]) for s in self.SIGNALS} for k in self.sizes}
        self.pk = {k: {s: np.zeros(nb[k]) for s in self.SIGNALS} for k in self.sizes}
        self.lr = {k: np.zeros(nb[k]) for k in self.sizes}
        self._tot = {s: [] for s in (*self.SIGNALS, "lr")}
        self.identical = True
        self.peak = 0.0
        self.ms_lim = 1e-6
        self.runs = [RunCounter(sr), RunCounter(sr)]

    @staticmethod
    def signals(L32, R32, stereo):
        """left, right, mix, side exactly as the viewer derives them (float32)."""
        if stereo:
            return {
                "left": core.f64(L32),
                "right": core.f64(R32),
                "mix": core.f64((L32 + R32) * np.float32(0.5)),
                "side": core.f64((L32 - R32) * np.float32(0.5)),
            }
        return {
            "left": core.f64(L32),
            "right": core.f64(L32),
            "mix": core.f64(L32),
            "side": np.zeros(len(L32)),
        }

    def feed_pair(self, L32, R32, a):
        b = a + len(L32)
        sig = self.signals(L32, R32, self.stereo)
        tot = {}

        def total(s):
            v = sig[s]
            tot[s] = float((v**2).sum())

        def lr_total():
            tot["lr"] = float((sig["left"] * sig["right"]).sum())

        def extremes():
            L, R = sig["left"], sig["right"]
            tot["peak"] = max(float(np.abs(L).max(initial=0)), float(np.abs(R).max(initial=0)))
            tot["ms"] = max(
                float(np.abs((L + R) / 2).max(initial=0)), float(np.abs((L - R) / 2).max(initial=0))
            )
            tot["same"] = bool(np.array_equal(L32, R32)) if self.stereo else True

        def block(k, B, i0, m, s):
            if s == "lr":
                self.lr[k][i0 : i0 + m] = (
                    (sig["left"][: m * B] * sig["right"][: m * B]).reshape(m, B).sum(axis=1)
                )
                return
            blk = sig[s][: m * B].reshape(m, B)
            self.ss[k][s][i0 : i0 + m] = (blk**2).sum(axis=1)
            self.pk[k][s][i0 : i0 + m] = np.abs(blk).max(axis=1)

        jobs = [lambda s=s: total(s) for s in sig] + [lr_total, extremes]
        for k, B in self.sizes.items():
            i0, m = a // B, (b - a) // B
            if m:
                jobs += [lambda k=k, B=B, i0=i0, m=m, s=s: block(k, B, i0, m, s) for s in (*sig, "lr")]
        list(core.POOL.map(lambda f: f(), jobs))
        for s in (*self.SIGNALS, "lr"):
            self._tot[s].append(tot[s])
        self.peak = max(self.peak, tot["peak"])
        self.ms_lim = max(self.ms_lim, tot["ms"])
        self.identical = self.identical and tot["same"]
        self.runs[0].feed_mask(np.abs(L32) >= np.float32(0.99997), a)
        if self.stereo:
            self.runs[1].feed_mask(np.abs(R32) >= np.float32(0.99997), a)

    def finish(self):
        self.total_ss = {s: math.fsum(v) for s, v in self._tot.items() if s != "lr"}
        self.total_lr = math.fsum(self._tot["lr"])
        c0, t0 = self.runs[0].finish()
        c1, t1 = self.runs[1].finish()
        self.clip_runs = c0 + c1
        self.clip_times = sorted(t0 + t1)
        return self


def summarize(left, right, sr):
    """Summary of whole arrays (or anything sliceable)."""
    stereo = right is not left
    sm = Summary(sr, len(left), stereo)
    for a in range(0, len(left), sm.chunk):
        L = np.asarray(left[a : a + sm.chunk], dtype=np.float32)
        R = np.asarray(right[a : a + sm.chunk], dtype=np.float32) if stereo else L
        sm.feed_pair(L, R, a)
    return sm.finish()
