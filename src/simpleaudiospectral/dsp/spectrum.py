"""Per-bin spectrum statistics over every loud frame."""

import os
import tempfile

import numpy as np

from . import core
from .frames import Frames


class SpectrumPercentiles:
    """Per-bin percentiles of the dB spectrum over every loud frame.

    Whole-array definition: frames = all x[k*hop : k*hop+n]; keep = loud_mask;
    db = 10*log10(|rfft(frame * hann(n))|^2 / (sum(hann)/2)^2 + 1e-30);
    np.percentile(db[keep], qs, axis=0).

    Large matrices go to disk bin-major (one row of all frames per bin), via
    an in-RAM buffer of frames that is written row by row with pwrite: a
    memory map written in strided blocks runs into the cgroup's dirty-page
    throttling. Each bin block is then read back contiguously.
    """

    BUF_BYTES = 64 * 1024 * 1024

    def __init__(self, n, hop, keep, qs=(50, 90)):
        self.fr = Frames(n, hop)
        self.keep = keep
        self.qs = qs
        self.win = np.hanning(n)
        self.norm = (self.win.sum() / 2) ** 2
        self.nb = n // 2 + 1
        self.used = int(keep.sum())
        self.col = np.cumsum(keep) - 1
        cols = max(1, self.used)
        self.fd = None
        if self.nb * cols * 8 > core.SPILL_RAM_BYTES:
            fd, self.spill = tempfile.mkstemp(prefix="spec-", suffix=".f64", dir=core.SPILL_DIR)
            os.ftruncate(fd, self.nb * cols * 8)
            self.fd = fd
            self.bw = max(1, self.BUF_BYTES // (self.nb * 8))  # frames per buffer
            self.buf = np.empty((self.nb, self.bw))
            self.b0 = 0  # column of buf[:, 0]
            self.fill = 0
        else:
            self.mat = np.empty((self.nb, cols))

    def _flush(self):
        fd = self.fd
        if not self.fill or fd is None:
            return
        cols = self.used

        def write(rows):
            for r in rows:
                os.pwrite(fd, self.buf[r, : self.fill].tobytes(), (r * cols + self.b0) * 8)

        step = max(1, self.nb // (core.THREADS * 4))
        list(core.POOL.map(write, [range(r, min(self.nb, r + step)) for r in range(0, self.nb, step)]))
        self.b0 += self.fill
        self.fill = 0

    def _db_blocks(self, fr):
        per = max(1, (4 * 1024 * 1024) // fr.shape[1])

        def work(i):
            p = core.spec_power(fr[i : i + per], self.win)
            return i, (10 * np.log10(p / self.norm + 1e-30)).T

        return core.POOL.map(work, range(0, len(fr), per))

    def feed(self, seg, _offset=0):
        k0, frames = self.fr.push(seg)
        if not len(frames):
            return
        sel = self.keep[k0 : k0 + len(frames)]
        if not sel.any():
            return
        fr = frames[sel]
        c0 = int(self.col[k0 : k0 + len(frames)][sel][0])
        if self.fd is None:
            for i, db in self._db_blocks(fr):
                self.mat[:, c0 + i : c0 + i + db.shape[1]] = db
            return
        pos = 0
        while pos < len(fr):
            take = min(self.bw - self.fill, len(fr) - pos)
            for i, db in self._db_blocks(fr[pos : pos + take]):
                self.buf[:, self.fill + i : self.fill + i + db.shape[1]] = db
            self.fill += take
            pos += take
            if self.fill == self.bw:
                self._flush()

    def finish(self):
        try:
            out = np.full((len(self.qs), self.nb), np.nan)
            if not self.used:
                return out, 0
            if self.fd is not None:
                self._flush()
            step = max(1, (64 * 1024 * 1024) // (self.used * 8))

            def pct(b0):
                b1 = min(self.nb, b0 + step)
                if self.fd is None:
                    rows = self.mat[b0:b1, : self.used]
                else:
                    raw = os.pread(self.fd, (b1 - b0) * self.used * 8, b0 * self.used * 8)
                    rows = np.frombuffer(raw, dtype=np.float64).reshape(b1 - b0, self.used)
                return b0, np.percentile(rows, self.qs, axis=1)

            for b0, p in core.POOL.map(pct, range(0, self.nb, step)):
                out[:, b0 : b0 + p.shape[1]] = p
            return out, self.used
        finally:
            if self.fd is not None:
                os.close(self.fd)
                os.unlink(self.spill)
                self.fd = None


class BandRatioStd:
    """Standard deviation over every loud frame of
    r = 10*log10(sum P[hi_band] / (sum P[lo_band] + 1e-30) + 1e-12),
    P = |rfft(frame * hann(n))|^2. Whole-array: np.std(r[keep])."""

    def __init__(self, sr, n, hop, keep, lo_band, hi_band):
        self.fr = Frames(n, hop)
        self.keep = keep
        f = np.fft.rfftfreq(n, 1 / sr)
        self.hi = (f > hi_band[0]) & (f < hi_band[1])
        self.lo = (f > lo_band[0]) & (f < lo_band[1])
        self.win = np.hanning(n)
        self.r = []

    def feed(self, seg, _offset=0):
        k0, frames = self.fr.push(seg)
        if not len(frames):
            return
        sel = self.keep[k0 : k0 + len(frames)]
        if not sel.any():
            return

        def ratio(b):
            p = core.spec_power(b, self.win)
            return 10 * np.log10(p[:, self.hi].sum(1) / (p[:, self.lo].sum(1) + 1e-30) + 1e-12)

        self.r.extend(core.parallel_rows(frames[sel], ratio))

    def finish(self):
        return float(np.concatenate(self.r).std()) if self.r else None


class WelchMean:
    """Mean over every frame of |rfft(frame * hann(n))|^2."""

    def __init__(self, n, hop):
        self.fr = Frames(n, hop)
        self.win = np.hanning(n)
        self.acc = np.zeros(n // 2 + 1)
        self.count = 0

    def feed(self, seg, _offset=0):
        _, frames = self.fr.push(seg)
        if len(frames):
            for s in core.parallel_rows(frames, lambda b: core.spec_power(b, self.win).sum(axis=0)):
                self.acc += s
            self.count += len(frames)

    def finish(self):
        return self.acc / self.count if self.count else None
