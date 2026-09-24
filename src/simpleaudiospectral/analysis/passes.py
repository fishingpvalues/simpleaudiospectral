"""The file analysis: three sequential passes over the decoded PCM, each exact
over the whole file (see dsp).

A: block statistics, frame loudness of every signal, waveform index
B: per-bin percentile spectra (mix, and left/right/side for the per-channel
   cut-off), Welch spectrum, clicks, flat tops, goniometer
C: sfb21 variability, whose band depends on the cut-off found in B

ffmpeg's EBU R128 and true-peak pass, the bit-usage count and SoX's bit depth
run concurrently in threads.
"""

import os
import threading
from collections.abc import Callable

import numpy as np

from .. import config, dsp, formats, tools
from ..pcm import filename, read_rows
from ..views import WAVE_BLOCK
from .external import bit_usage, loudness
from .levels import FULL_SCALE, dynamics, quiet_floor, side_level_db
from .lowpass import HF_BAND_START, HF_N, HF_REF_BAND, SPEC_N, hf_band_top, lowpass
from .report import analysis_result

Progress = Callable[[str, float], None]


def signals(L32: np.ndarray, R32: np.ndarray, stereo: bool) -> dict[str, np.ndarray]:
    """The analysed signals of one chunk (float32, as the viewer derives them)."""
    if not stereo:
        return {"mix": L32, "left": L32}
    return {
        "mix": (L32 + R32) * np.float32(0.5),
        "left": L32,
        "right": R32,
        "side": (L32 - R32) * np.float32(0.5),
    }


def chunks(mm: np.memmap, step: int):
    """(offset, left, right) of consecutive chunks; right is left for mono."""
    n, stereo = mm.shape[0], mm.shape[1] > 1
    for a in range(0, n, step):
        rows = read_rows(mm, a, min(n, a + step))
        yield a, rows[:, 0], (rows[:, 1] if stereo else rows[:, 0])


class SideJobs:
    """External-tool measurements, run in threads alongside the passes."""

    def __init__(self, path: str, mm: np.memmap, sr: int, meta: dict) -> None:
        ext = os.path.splitext(path)[1].lower()
        jobs = {"loudness": lambda: loudness(path, (filename(mm), sr, mm.shape[1]))}
        if formats.is_lossless(meta["codecName"]):
            jobs["bits"] = lambda: bit_usage(path, meta["bits"])
        if ext in formats.SOX_BITDEPTH:
            jobs["soxbits"] = lambda: tools.sox_bitdepth(path)
        self.out: dict = {}
        self.threads = [
            threading.Thread(target=lambda k=k, f=f: self.out.__setitem__(k, f()), daemon=True)
            for k, f in jobs.items()
        ]
        for t in self.threads:
            t.start()

    def join(self) -> dict:
        for t in self.threads:
            t.join(config.TIMEOUT * 20)
        return self.out


def pass_a(mm, sr, progress):
    """Block statistics, frame RMS of every signal, waveform index."""
    n, stereo = mm.shape[0], mm.shape[1] > 1
    names = ("mix", "left", "right", "side") if stereo else ("mix",)
    sm = dsp.Summary(sr, n, stereo)
    rms = {s: dsp.FrameRMS(SPEC_N, SPEC_N // 2) for s in names}
    rms_hf = dsp.FrameRMS(HF_N, HF_N // 2)
    index = {
        s: dsp.BlockExtremes(WAVE_BLOCK)
        for s in ("mix", "left", "right", "side")
        if stereo or s in ("mix", "left")
    }
    for a, L32, R32 in chunks(mm, sm.chunk):
        progress("levels and blocks", a / max(1, n))
        sm.feed_pair(L32, R32, a)
        sig = signals(L32, R32, stereo)
        for s in names:
            rms[s].feed(sig[s], a)
        rms_hf.feed(sig["mix"], a)
        for s, e in index.items():
            e.feed(sig[s], a)
    sm.finish()
    keeps = {s: dsp.loud_mask(rms[s].finish()) for s in names}
    return sm, keeps, dsp.loud_mask(rms_hf.finish()), index


def pass_b(mm, sr, sm, keeps, progress):
    """Per-bin percentiles, Welch spectrum, clicks, flat tops, goniometer."""
    n, stereo = mm.shape[0], mm.shape[1] > 1
    spec = {"mix": dsp.SpectrumPercentiles(SPEC_N, SPEC_N // 2, keeps["mix"], (50, 90))}
    for s in list(keeps)[1:]:
        if float(sm.pk["b3"][s].max(initial=0)) > 1e-6:
            spec[s] = dsp.SpectrumPercentiles(SPEC_N, SPEC_N // 2, keeps[s], (90,))
    welch = dsp.WelchMean(1 << 16, 1 << 15)
    clicks = dsp.IsolatedClicks(sr)
    flat = (
        [dsp.LevelRuns(sr, sm.peak, True) for _ in range(2 if stereo else 1)]
        if 0 < sm.peak < FULL_SCALE
        else None
    )
    gonio = dsp.Goniometer(160, sm.ms_lim) if stereo else None
    for a, L32, R32 in chunks(mm, dsp.core.CHUNK):
        progress("spectra of every frame", a / max(1, n))
        sig = signals(L32, R32, stereo)
        for s, c in spec.items():
            c.feed(sig[s], a)
        welch.feed(sig["mix"], a)
        clicks.feed(sig["mix"], a)
        if flat:
            flat[0].feed(L32, a)
            if stereo:
                flat[1].feed(R32, a)
        if gonio:
            gonio.feed_pair(L32, R32, a)
    progress("sorting per-bin percentiles", 0)
    pct = {s: c.finish() for s, c in spec.items()}
    flat_res = None
    if flat:
        cs = [f.finish() for f in flat]
        flat_res = (sum(c for c, _ in cs), sorted(t for _, ts in cs for t in ts))
    return pct, welch.finish(), clicks.finish(), flat_res, gonio.finish() if gonio else None


def pass_c(mm, sr, keep_hf, top_hz, progress) -> float | None:
    """sfb21 variability: spread of the 16 kHz-to-cut-off band over loud frames."""
    n, stereo = mm.shape[0], mm.shape[1] > 1
    hf = dsp.BandRatioStd(sr, HF_N, HF_N // 2, keep_hf, HF_REF_BAND, (HF_BAND_START, top_hz))
    for a, L32, R32 in chunks(mm, dsp.core.CHUNK):
        progress("sfb21 variability", a / max(1, n))
        hf.feed(signals(L32, R32, stereo)["mix"], a)
    return hf.finish()


def measure(path: str, mm: np.memmap, sr: int, progress: Progress) -> dict:
    """Everything the UI shows about a file."""
    meta = tools.ffprobe(path)
    n, stereo = mm.shape[0], mm.shape[1] > 1
    side_jobs = SideJobs(path, mm, sr, meta)

    sm, keeps, keep_hf, index = pass_a(mm, sr, progress)
    pct, welch, clicks, flat, gonio = pass_b(mm, sr, sm, keeps, progress)
    (med_raw, p90_raw), used = pct["mix"]
    lp = lowpass(p90_raw, med_raw, sr)
    top_hz = hf_band_top(lp["cutoff_hz"], lp["nyq"])
    hf_sd = pass_c(mm, sr, keep_hf, top_hz, progress) if top_hz and n >= SPEC_N * 4 else None

    side_db = side_level_db(sm.total_ss["mix"] / max(1, n), sm.total_ss["side"] / max(1, n))
    analysis = (
        analysis_result(lp, sr, n, hf_sd, side_db, sm.ss["b05"]["mix"], used) if n >= SPEC_N * 4 else None
    )

    per = {"left": None, "right": None, "side": None}
    if stereo:
        for s in ("left", "right", "side"):
            if s in pct:
                per[s] = lowpass(pct[s][0][0], None, sr)["cutoff_hz"]
    else:
        per["left"] = per["right"] = analysis["cutoffHz"] if analysis else None
    left = mm[:, 0]
    right = mm[:, 1] if stereo else left
    dyn = dynamics(left, right, sr, sm, welch=welch, clicks=clicks, flat=flat)
    progress("loudness and true peak (ffmpeg)", 1)
    side = side_jobs.join()
    meta["bitDepthUsed"] = side.get("soxbits")
    meta["duration"] = n / sr
    stats = {
        "loudness": side.get("loudness") or {},
        "dynamics": dyn,
        "quietFloorDb": quiet_floor(None, sr, sm),
        "channelCutoffs": per,
        "bitUsage": side.get("bits"),
    }
    return {
        "meta": meta,
        "analysis": analysis,
        "stats": stats,
        "index": {s: e.finish() for s, e in index.items()},
        "gonio": gonio,
    }
