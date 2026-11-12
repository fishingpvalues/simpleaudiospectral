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

    Large matrices go to disk as a sequence of blocks: an in-RAM buffer of
    `bw` frames, bin-major, is appended with one sequential write when full.
    A bin range is read back as one contiguous slice per block. One large
    write per block replaces one small strided write per bin (4097 syscalls
    per flush at FFT 8192), which made the spill most of the cost of a long
    file; the values, and so the percentiles, are the same.
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
            self.fd = fd
            self.bw = max(1, self.BUF_BYTES // (self.nb * 8))  # frames per buffer
            self.buf = np.empty((self.nb, self.bw))
            self.b0 = 0  # column of buf[:, 0]
            self.fill = 0
            self.blocks: list[tuple[int, int, int]] = []  # (file offset, first column, width)
            self.end = 0  # bytes written
        else:
            self.mat = np.empty((self.nb, cols))

    def _flush(self):
        fd = self.fd
        if not self.fill or fd is None:
            return
        # A full buffer is written as is; only the last, partial one is copied.
        block = self.buf if self.fill == self.bw else np.ascontiguousarray(self.buf[:, : self.fill])
        view = memoryview(block).cast("B")
        pos = 0
        while pos < len(view):
            pos += os.pwrite(fd, view[pos:], self.end + pos)
        self.blocks.append((self.end, self.b0, self.fill))
        self.end += len(view)
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

    def finish(self, progress=None):
        """Per-bin percentiles and the number of frames used. progress(f) is
        called with the fraction of bins done."""
        try:
            out = np.full((len(self.qs), self.nb), np.nan)
            if not self.used:
                return out, 0
            if self.fd is not None:
                self._flush()
            step = max(1, (64 * 1024 * 1024) // (self.used * 8))

            def rows_of(b0, b1):
                if self.fd is None:
                    return self.mat[b0:b1, : self.used]
                rows = np.empty((b1 - b0, self.used))
                for off, c0, w in self.blocks:
                    raw = os.pread(self.fd, (b1 - b0) * w * 8, off + b0 * w * 8)
                    rows[:, c0 : c0 + w] = np.frombuffer(raw, dtype=np.float64).reshape(b1 - b0, w)
                return rows

            def pct(b0):
                b1 = min(self.nb, b0 + step)
                return b0, np.percentile(rows_of(b0, b1), self.qs, axis=1)

            for b0, p in core.POOL.map(pct, range(0, self.nb, step)):
                out[:, b0 : b0 + p.shape[1]] = p
                if progress:
                    progress((b0 + p.shape[1]) / self.nb)
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
