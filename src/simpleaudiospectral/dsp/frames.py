"""Frame slicing across chunk boundaries, and frame loudness."""

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from . import core


class Frames:
    """Turns consecutive chunks into every frame x[k*hop : k*hop+n], each
    exactly once and in order, whatever the chunk boundaries."""

    def __init__(self, n, hop):
        self.n, self.hop = n, hop
        self.buf = np.zeros(0)
        self.k = 0  # global index of the next frame

    def push(self, seg):
        """Returns (k0, frames[m, n]) for the frames completed by seg."""
        self.buf = np.concatenate([self.buf, core.f64(seg)])
        m = core.n_frames(len(self.buf), self.n, self.hop)
        k0 = self.k
        if not m:
            return k0, np.zeros((0, self.n))
        # A view, not a copy: self.buf is replaced below, never written, so the
        # frames stay valid for as long as the caller holds them.
        frames = sliding_window_view(self.buf, self.n)[:: self.hop][:m]
        self.buf = self.buf[m * self.hop :]
        self.k += m
        return k0, frames


class FrameRMS:
    """rms[k] = sqrt(mean(x[k*hop : k*hop+n]**2)) for every frame."""

    def __init__(self, n, hop):
        self.fr = Frames(n, hop)
        self.out = []

    def feed(self, seg, _offset=0):
        _, frames = self.fr.push(seg)
        if len(frames):
            self.out.extend(core.parallel_rows(frames, lambda b: np.sqrt((b**2).mean(axis=1))))

    def finish(self):
        return np.concatenate(self.out) if self.out else np.zeros(0)


def loud_mask(rms):
    """Frames louder than the 30th percentile (and -80 dBFS): the analysed set.
    With fewer than 4 such frames, all frames are used."""
    if not len(rms):
        return np.zeros(0, bool)
    m = rms > max(1e-4, float(np.percentile(rms, 30)))
    return m if m.sum() >= 4 else np.ones(len(rms), bool)
