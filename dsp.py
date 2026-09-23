"""Exact whole-file measurements, streamed.

Every measurement is a consumer that is fed consecutive chunks of the signal
and returns exactly what its whole-array definition (in its docstring)
returns: the same frames, the same blocks, the same percentiles. Nothing is
sampled, capped or approximated. Consumers share one sequential read of a
file (Pipeline in app.py), so a whole analysis costs two reads of the decoded
audio regardless of how many measurements it makes.

Where a result needs every value at once (the percentile of each frequency
bin over all frames), the values are spilled to a float64 file on disk and
read back per bin.

tests/test_exact.py runs each consumer against a literal whole-array
reference with a deliberately awkward chunk size.

Whole-file sums (total energy, correlation, Welch means) are accumulated per
chunk and combined with math.fsum or float64 addition; they agree with a
single numpy sum over the whole array to about 1e-15 relative, which is the
rounding of float64 itself.
"""

import math
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

CHUNK = 1 << 22  # target samples per chunk (~16 MB of float32 per channel)
THREADS = max(1, min(8, os.cpu_count() or 1))
SPILL_DIR = tempfile.gettempdir()  # the app points this at the PCM volume
SPILL_RAM_BYTES = 256 * 1024 * 1024  # below this the per-bin matrix stays in RAM
STFT_GROUP_BYTES = 32 * 1024 * 1024  # full-resolution columns held at once in the viewer
_POOL = ThreadPoolExecutor(THREADS, thread_name_prefix="dsp")


def f64(a):
    return np.asarray(a, dtype=np.float64)


def _chunk_len(multiple, target=None):
    target = target or CHUNK
    return max(multiple, (target // multiple) * multiple)


def n_frames(length, n, hop):
    """Frames x[k*hop : k*hop + n] for k = 0 .. n_frames-1 (full frames only)."""
    return 0 if length < n else 1 + (length - n) // hop


def feed_all(x, *consumers, chunk=None):
    """Feed x to consumers in consecutive chunks, then finish them."""
    step = chunk or CHUNK
    for a in range(0, len(x), step):
        seg = np.asarray(x[a : a + step], dtype=np.float32)
        for c in consumers:
            c.feed(seg, a)
    return [c.finish() for c in consumers]


# ------------------------------------------------------------------ frames


class Frames:
    """Turns consecutive chunks into every frame x[k*hop : k*hop+n], each
    exactly once and in order, whatever the chunk boundaries."""

    def __init__(self, n, hop):
        self.n, self.hop = n, hop
        self.buf = np.zeros(0)
        self.k = 0  # global index of the next frame

    def push(self, seg):
        """Returns (k0, frames[m, n]) for the frames completed by seg."""
        self.buf = np.concatenate([self.buf, f64(seg)])
        m = n_frames(len(self.buf), self.n, self.hop)
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
            self.out.extend(_parallel_rows(frames, lambda b: np.sqrt((b**2).mean(axis=1))))

    def finish(self):
        return np.concatenate(self.out) if self.out else np.zeros(0)


def loud_mask(rms):
    """Frames louder than the 30th percentile (and -80 dBFS): the analysed set.
    With fewer than 4 such frames, all frames are used."""
    if not len(rms):
        return np.zeros(0, bool)
    m = rms > max(1e-4, float(np.percentile(rms, 30)))
    return m if m.sum() >= 4 else np.ones(len(rms), bool)


def _spec_power(frames, win):
    s = np.fft.rfft(frames * win, axis=1)
    return s.real**2 + s.imag**2


def _parallel_rows(frames, fn):
    """fn over row blocks of frames on the worker pool; results in order."""
    per = max(1, (4 * 1024 * 1024) // max(1, frames.shape[1]))
    return list(_POOL.map(fn, [frames[i : i + per] for i in range(0, len(frames), per)]))


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
        if self.nb * cols * 8 > SPILL_RAM_BYTES:
            fd, self.spill = tempfile.mkstemp(prefix="spec-", suffix=".f64", dir=SPILL_DIR)
            os.ftruncate(fd, self.nb * cols * 8)
            self.fd = fd
            self.bw = max(1, self.BUF_BYTES // (self.nb * 8))  # frames per buffer
            self.buf = np.empty((self.nb, self.bw))
            self.b0 = 0  # column of buf[:, 0]
            self.fill = 0
        else:
            self.mat = np.empty((self.nb, cols))

    def _flush(self):
        if not self.fill:
            return
        cols = self.used

        def write(rows):
            for r in rows:
                os.pwrite(self.fd, self.buf[r, : self.fill].tobytes(), (r * cols + self.b0) * 8)

        step = max(1, self.nb // (THREADS * 4))
        list(_POOL.map(write, [range(r, min(self.nb, r + step)) for r in range(0, self.nb, step)]))
        self.b0 += self.fill
        self.fill = 0

    def _db_blocks(self, fr):
        per = max(1, (4 * 1024 * 1024) // fr.shape[1])

        def work(i):
            p = _spec_power(fr[i : i + per], self.win)
            return i, (10 * np.log10(p / self.norm + 1e-30)).T

        return _POOL.map(work, range(0, len(fr), per))

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

            for b0, p in _POOL.map(pct, range(0, self.nb, step)):
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
            p = _spec_power(b, self.win)
            return 10 * np.log10(p[:, self.hi].sum(1) / (p[:, self.lo].sum(1) + 1e-30) + 1e-12)

        self.r.extend(_parallel_rows(frames[sel], ratio))

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
            for s in _parallel_rows(frames, lambda b: _spec_power(b, self.win).sum(axis=0)):
                self.acc += s
            self.count += len(frames)

    def finish(self):
        return self.acc / self.count if self.count else None


# ------------------------------------------------------------------ runs


class RunCounter:
    """Runs of >= 3 consecutive True samples, exact across chunk boundaries.
    Whole-array definition: diff of the boolean mask, runs with length >= 3."""

    def __init__(self, sr):
        self.sr = sr
        self.carry = 0  # length of the run still open at the last chunk end
        self.start = 0
        self.count = 0
        self.times = []

    def feed_mask(self, hot, offset):
        d = np.diff(np.concatenate([[0], hot.astype(np.int8), [0]]))
        st, en = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
        if self.carry:
            if len(st) and st[0] == 0:
                if en[0] < len(hot):
                    self._close(self.carry + en[0], self.start)
                    self.carry = 0
                    st, en = st[1:], en[1:]
                else:
                    self.carry += len(hot)
                    return
            else:
                self._close(self.carry, self.start)
                self.carry = 0
        for s0, e0 in zip(st, en, strict=True):
            if e0 == len(hot):
                self.carry, self.start = int(e0 - s0), offset + int(s0)
            else:
                self._close(int(e0 - s0), offset + int(s0))

    def _close(self, length, start):
        if length >= 3:
            self.count += 1
            self.times.append(start / self.sr)

    def finish(self):
        if self.carry:
            self._close(self.carry, self.start)
            self.carry = 0
        return self.count, self.times


class LevelRuns:
    """Runs of >= 3 consecutive samples with |x| >= level, or == level."""

    def __init__(self, sr, level, exact_equal=False):
        self.rc = RunCounter(sr)
        self.level = np.float32(level)
        self.eq = exact_equal

    def feed(self, seg, offset):
        a = np.abs(np.asarray(seg, dtype=np.float32))
        self.rc.feed_mask(a == self.level if self.eq else a >= self.level, offset)

    def finish(self):
        return self.rc.finish()


# ------------------------------------------------------------------ clicks


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
        self.buf = np.concatenate([self.buf, f64(seg)])
        full = len(self.buf) // self.win
        if full:
            windows = [self.buf[i * self.win : (i + 1) * self.win] for i in range(full)]
            self.events += sum(_POOL.map(self._window, windows))
            self.buf = self.buf[full * self.win :]

    def finish(self):
        self.events += self._window(self.buf)
        minutes = self.total / self.sr / 60
        return round(self.events / minutes, 1) if minutes else 0.0


# ------------------------------------------------------------------ blocks


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
        self.chunk = _chunk_len(lcm)
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
                "left": f64(L32),
                "right": f64(R32),
                "mix": f64((L32 + R32) * np.float32(0.5)),
                "side": f64((L32 - R32) * np.float32(0.5)),
            }
        return {"left": f64(L32), "right": f64(L32), "mix": f64(L32), "side": np.zeros(len(L32))}

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
        list(_POOL.map(lambda f: f(), jobs))
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
        L, R = f64(L32), f64(R32)
        per = 1 << 18
        for h, ll, rr, lr in _POOL.map(
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
    for c in range(a, b, CHUNK):
        L = f64(left[c : min(b, c + CHUNK)])
        R = f64(right[c : min(b, c + CHUNK)])
        lim = max(lim, float(np.abs((L + R) / 2).max(initial=0)), float(np.abs((L - R) / 2).max(initial=0)))
    g = Goniometer(size, lim)
    for c in range(a, b, CHUNK):
        g.feed_pair(np.asarray(left[c : min(b, c + CHUNK)]), np.asarray(right[c : min(b, c + CHUNK)]))
    return g.finish()


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


# ------------------------------------------------------------------ convenience (whole arrays)


def frame_rms(x, n, hop):
    return feed_all(x, FrameRMS(n, hop))[0]


def spectrum_percentiles(x, sr, n=8192, hop=4096, qs=(50, 90)):
    keep = loud_mask(frame_rms(x, n, hop))
    return feed_all(x, SpectrumPercentiles(n, hop, keep, qs))[0]


def band_ratio_std(x, sr, lo_band, hi_band, n=2048, hop=1024):
    keep = loud_mask(frame_rms(x, n, hop))
    return feed_all(x, BandRatioStd(sr, n, hop, keep, lo_band, hi_band))[0]


def mean_power_spectrum(x, n, hop):
    return feed_all(x, WelchMean(n, hop))[0]


def isolated_clicks(x, sr, window_s=60):
    return feed_all(x, IsolatedClicks(sr, window_s))[0]


def count_runs(x, level, sr, exact_equal=False):
    return feed_all(x, LevelRuns(sr, level, exact_equal))[0]


# ------------------------------------------------------------------ views


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
    group = max(1, STFT_GROUP_BYTES // (nb * 8))

    def spec(starts):
        lo, hi = int(starts[0]), int(starts[-1]) + fft
        span = np.zeros(hi - lo)
        s0, s1 = max(0, lo), min(n, hi)
        if s1 > s0:
            span[s0 - lo : s1 - lo] = f64(x[s0:s1])
        fr = sliding_window_view(span, fft)[starts - lo]
        return _spec_power(fr, win)

    if slot < hop:
        centers = (a + (np.arange(cols) + 0.5) * slot).astype(np.int64)
        parts = []
        for g0 in range(0, cols, group):
            g1 = min(cols, g0 + group)
            blocks = list(
                _POOL.map(
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

        for cids, sums in _POOL.map(work, range(f_lo, f_hi, per)):
            acc[cids] += sums
        c = counts[g0:g1]
        nz = c > 0
        acc[nz] /= c[nz][:, None]
        parts.append(reduce(acc))
    return np.concatenate(parts)
