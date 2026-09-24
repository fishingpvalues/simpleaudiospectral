"""Runs of consecutive samples at a level (clipping, flat tops)."""

import numpy as np


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
