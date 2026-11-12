"""How far an analysis is: one overall fraction from every stage's real
position, never a timer.

Each stage reports the fraction of its work done, measured where the work
happens: ffmpeg's read position for the decode and the loudness pass, rows
read for the passes over the decoded audio, bins sorted for the percentiles,
samples counted for the bit usage, SoX's own meter for its bit depth.

The overall fraction weighs the remaining work of each stage by its expected
cost. The main passes run one after another; the external measurements run in
threads beside them after the decode, so what remains is

    decode + max(main passes, slowest external measurement).

Expected costs start as per-sample priors (relative, measured on real tracks)
and are replaced by each stage's measured rate once it has done enough work to
measure, so a slow disk or a busy CPU bends the estimate instead of stalling
the bar. The overall fraction never moves backwards and reaches 1 only when the
result is ready.
"""

import threading
import time
from dataclasses import dataclass, field

# Relative cost of each stage per sample (seconds per million stereo samples
# on the reference machine; every stage scales with the length). Only the
# ratios matter for the fraction; seconds per unit are learnt from the stages
# measured so far, for the time estimate.
PRIORS = {
    "decode": 0.03,  # FLAC about 0.02, MP3 and Opus about 0.04
    "levels": 0.03,
    "spectra": 0.09,
    "percentiles": 0.01,
    "sfb21": 0.01,
    "loudness": 0.1,
    "bits": 0.03,
    "soxbits": 0.06,
}
LABELS = {
    "queued": "Waiting for a free analysis slot",
    "decode": "Decoding",
    "levels": "Levels, loudness blocks and waveform",
    "spectra": "Spectrum of every frame",
    "percentiles": "Per-bin percentiles",
    "sfb21": "sfb21 variability",
    "loudness": "EBU R128 loudness and true peak",
    "bits": "Bit usage of every sample",
    "soxbits": "SoX bit depth",
    "done": "Done",
}
MAIN = ("decode", "levels", "spectra", "percentiles", "sfb21")
MIN_MEASURE = 0.05  # a stage's own rate is trusted from this fraction on


@dataclass
class Stage:
    key: str
    prior: float
    done: float = 0.0
    started: float | None = None
    ended: float | None = None

    def cost(self, scale: float) -> float:
        """Expected seconds for the whole stage."""
        if self.ended is not None and self.started is not None:
            return self.ended - self.started
        if self.started is not None and self.done >= MIN_MEASURE:
            return (time.monotonic() - self.started) / self.done
        return self.prior * scale


@dataclass
class Tracker:
    """Thread-safe: stages report from the analysis thread and the external
    measurement threads at once."""

    stages: dict[str, Stage] = field(default_factory=dict)
    t0: float = field(default_factory=lambda: time.monotonic())  # noqa: PLW0108 - late-bound, so tests can patch the clock
    best: float = 0.0
    current: str = "queued"
    finished: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        for k in MAIN:
            self.add(k)

    def add(self, key: str) -> None:
        """Count a stage that this file needs (the external ones depend on the format)."""
        with self.lock:
            self._add(key)

    def _add(self, key: str) -> Stage:
        return self.stages.setdefault(key, Stage(key, PRIORS[key]))

    def update(self, key: str, done: float) -> None:
        """Stage `key` has done this fraction of its work; an unknown stage
        of PRIORS is added on its first report."""
        if key not in PRIORS:
            return
        with self.lock:
            st = self._add(key)
            if st.ended is not None:
                return
            now = time.monotonic()
            if st.started is None:
                st.started = now
            st.done = max(st.done, min(1.0, float(done)))
            if st.done >= 1.0:
                st.ended = now
            if key in MAIN:
                self.current = key

    def complete(self, key: str) -> None:
        """A stage that is finished, or skipped for this file."""
        self.update(key, 1.0)

    def finish(self) -> None:
        with self.lock:
            self.finished = True
            self.best = 1.0
            self.current = "done"

    def _scale(self) -> float:
        """Seconds per prior unit, from the stages that have been measured."""
        num = den = 0.0
        for st in self.stages.values():
            if st.started is not None and (st.ended is not None or st.done >= MIN_MEASURE):
                num += st.cost(1.0)
                den += st.prior
        return num / den if den else 1.0

    def _remaining(self, scale: float, fresh: bool) -> float:
        """Expected seconds left (fresh: as if nothing had been done)."""

        def left(st: Stage) -> float:
            return st.cost(scale) * (1.0 if fresh else 1.0 - st.done)

        main = [st for k, st in self.stages.items() if k in MAIN and k != "decode"]
        side = [st for k, st in self.stages.items() if k not in MAIN]
        decode = self.stages["decode"]
        return left(decode) + max(sum(map(left, main)), max(map(left, side), default=0.0))

    def snapshot(self) -> dict:
        """The progress document of the 202 response and the event stream."""
        with self.lock:
            elapsed = time.monotonic() - self.t0
            if self.finished:
                overall, eta = 1.0, 0.0
            else:
                scale = self._scale()
                total = self._remaining(scale, fresh=True)
                rem = self._remaining(scale, fresh=False)
                overall = 0.0 if total <= 0 else min(0.999, max(0.0, 1.0 - rem / total))
                self.best = overall = max(self.best, overall)
                measured = any(
                    st.started is not None and (st.ended is not None or st.done >= MIN_MEASURE)
                    for st in self.stages.values()
                )
                eta = round(rem, 1) if measured and elapsed >= 1.0 else None
            stages = [
                {"key": k, "label": LABELS[k], "done": round(st.done, 4)} for k, st in self.stages.items()
            ]
            return {
                "stage": LABELS[self.current],
                "stageKey": self.current,
                "done": round(overall, 4),
                "elapsed": round(elapsed, 1),
                "eta": eta,
                "stages": stages,
            }
