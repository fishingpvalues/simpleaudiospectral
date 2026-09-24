"""Levels over the whole file: DR, clipping, stereo, noise floor, side level."""

import math

import numpy as np

from .. import dsp
from ..pcm import Derived

FULL_SCALE = 0.99997  # |x| at or above this counts as digital full scale


def block_sums(x, blk: int) -> tuple[np.ndarray, np.ndarray]:
    """Sum of squares and absolute peak per block of `blk` samples, chunked."""
    nb = len(x) // blk
    ss = np.zeros(nb)
    pk = np.zeros(nb)
    per = max(1, dsp.core.CHUNK // blk)
    for b0 in range(0, nb, per):
        b1 = min(nb, b0 + per)
        seg = np.asarray(x[b0 * blk : b1 * blk], dtype=np.float64).reshape(b1 - b0, blk)
        ss[b0:b1] = (seg**2).sum(1)
        pk[b0:b1] = np.abs(seg).max(1)
    return ss, pk


def side_level_db(mean_square_mix: float, mean_square_side: float) -> float:
    """Side (L-R) level relative to the mix; very low means mono in stereo."""
    return float(20 * np.log10((math.sqrt(mean_square_side) + 1e-12) / (math.sqrt(mean_square_mix) + 1e-12)))


def whole_levels(x, side, sr: int) -> tuple[float, float, np.ndarray]:
    """Mean square of x and side over the whole file, and 0.5 s block energies
    of x, when no dsp.Summary exists."""
    ssx, sss = [], []
    for c0 in range(0, len(x), dsp.core.CHUNK):
        ssx.append(float((dsp.f64(x[c0 : c0 + dsp.core.CHUNK]) ** 2).sum()))
        sss.append(float((dsp.f64(side[c0 : c0 + dsp.core.CHUNK]) ** 2).sum()))
    b05, _ = block_sums(x, int(sr * 0.5))
    return math.fsum(ssx) / max(1, len(x)), math.fsum(sss) / max(1, len(x)), b05


def dynamic_range(sm: dsp.Summary, stereo: bool) -> list[float]:
    """DR per channel, TT DR Meter algorithm: every full 3 s block; block RMS
    = sqrt(2 * mean(x^2)); block peak = max |x|. DR = 20*log10(second-highest
    block peak / sqrt(mean of the loudest 20% of block RMS^2))."""
    B = sm.sizes["b3"]
    nb = len(sm.ss["b3"]["left"])
    drs = []
    for ch in ("left", "right") if stereo else ("left",):
        rms = np.sqrt(2 * sm.ss["b3"][ch] / B)
        pks = np.sort(sm.pk["b3"][ch])
        pk2 = pks[-2] if nb >= 2 else pks[-1]
        top = np.sort(rms)[-max(1, round(nb * 0.2)) :]
        r = np.sqrt(np.mean(top**2))
        drs.append(20 * np.log10(pk2 / r) if r > 0 and pk2 > 0 else 0.0)
    return drs


def dynamics(left, right, sr, summary=None, mix=None, welch=None, clicks=None, flat=None) -> dict | None:
    """DR, clipping, rumble, clicks and stereo statistics over the whole file.
    Measurements the file analysis already streamed (welch, clicks, flat) are
    passed in; otherwise they are computed here from the arrays."""
    sm = summary or dsp.summarize(left, right, sr)
    stereo = sm.stereo
    if mix is None and (welch is None or clicks is None):
        mix = Derived(np.stack([np.asarray(left), np.asarray(right)], axis=1), "mix") if stereo else left
    if len(sm.ss["b3"]["left"]) < 1:
        return None
    drs = dynamic_range(sm, stereo)
    out = {"dr": round(float(np.mean(drs))), "drPerChannel": [round(float(d), 1) for d in drs]}

    # Clipping: runs of >= 3 consecutive samples at digital full scale, and
    # flat tops: the same runs at the file's own peak when that peak is below
    # full scale (clipped, then normalised down). Counted across chunk
    # boundaries, so the counts are exact.
    flat_n, flat_times = 0, []
    if flat is not None:
        flat_n, flat_times = flat
    elif 0 < sm.peak < FULL_SCALE:
        for x in (left, right) if stereo else (left,):
            c, t = dsp.count_runs(x, sm.peak, sr, exact_equal=True)
            flat_n += c
            flat_times += t
    times = sorted(sm.clip_times + flat_times)
    out["clipEvents"] = sm.clip_runs
    out["flatTopEvents"] = flat_n
    out["clipTimesTotal"] = len(times)
    out["clipTimes"] = [round(t, 3) for t in times[:500]]  # a list for the UI; the counts are complete

    # Vinyl and analogue-chain hints: subsonic rumble relative to the bass,
    # and isolated clicks.
    fr = 1 << 16
    P = welch if welch is not None else dsp.mean_power_spectrum(mix, fr, fr // 2)
    if P is not None:
        f = np.fft.rfftfreq(fr, 1 / sr)
        sub = P[(f >= 5) & (f < 20)].mean()
        body = P[(f >= 40) & (f < 400)].mean()
        out["rumbleDb"] = round(float(10 * np.log10(sub / (body + 1e-30) + 1e-30)), 1)
    else:
        out["rumbleDb"] = None
    out["clicksPerMin"] = clicks if clicks is not None else dsp.isolated_clicks(mix, sr)
    out.update(stereo_stats(sm) if stereo else {"correlation": None, "identicalChannels": True})
    return out


def stereo_stats(sm: dsp.Summary) -> dict:
    """Whole-file correlation, and the correlation of every full second."""
    den = math.sqrt(sm.total_ss["left"] * sm.total_ss["right"])
    d = np.sqrt(sm.ss["b1"]["left"] * sm.ss["b1"]["right"])
    per_sec = np.where(d > 0, sm.lr["b1"] / np.maximum(d, 1e-300), 1.0)
    return {
        "correlation": round(sm.total_lr / den, 3) if den > 0 else 1.0,
        "correlationSeries": [round(float(v), 3) for v in per_sec],
        "identicalChannels": sm.identical,
    }


def quiet_floor(x, sr, summary=None) -> float | None:
    """Noise floor: 5th percentile of the RMS of every full 400 ms block that
    is not digital silence."""
    if summary is not None:
        ss, blk = summary.ss["b04"]["mix"], summary.sizes["b04"]
    else:
        blk = int(0.4 * sr)
        ss, _ = block_sums(x, blk)
    if len(ss) < 4:
        return None
    rms = np.sqrt(ss / blk)
    rms = rms[rms > 1e-9]  # digital silence says nothing about the master
    if not len(rms):
        return None
    return round(float(20 * np.log10(np.percentile(rms, 5))), 1)
