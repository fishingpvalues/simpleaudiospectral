"""Every measurement against a literal whole-array reference.

Each reference below is the textbook definition computed on the complete
array in one go. The chunked, memory-bounded implementation must return the
same result: bit-identical where the computation is per block or per frame
(percentiles, block statistics, run counts, histograms), and equal to float64
rounding (rtol 1e-12) where a whole-file sum is accumulated in a different
order.
"""

import importlib
import math
import os
import subprocess
import sys

import numpy as np
import pytest
from numpy.lib.stride_tricks import sliding_window_view

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SR = 8000
SECONDS = 40


@pytest.fixture(scope="module")
def mods(tmp_path_factory):
    os.environ["LIBRARY_ROOT"] = str(tmp_path_factory.mktemp("lib"))
    os.environ["CACHE_DIR"] = str(tmp_path_factory.mktemp("cache"))
    import app as app_mod
    import dsp as dsp_mod

    return importlib.reload(dsp_mod), importlib.reload(app_mod)


@pytest.fixture
def small_chunks(mods, monkeypatch, tmp_path):
    """An awkward chunk size (not a multiple of any frame or hop) and forced
    spilling to disk, so every chunk seam and the memmap path are exercised."""
    dsp, app = mods
    monkeypatch.setattr(dsp, "CHUNK", 30011)
    monkeypatch.setattr(dsp, "SPILL_RAM_BYTES", 0)
    monkeypatch.setattr(dsp, "SPILL_DIR", str(tmp_path))
    monkeypatch.setattr(dsp, "STFT_GROUP_BYTES", 257 * 8 * 5)  # 5 columns per group at FFT 512
    return dsp, app


def signal(seed=0):
    rng = np.random.default_rng(seed)
    n = SR * SECONDS
    t = np.arange(n) / SR
    env = 0.2 + 0.8 * (np.sin(2 * np.pi * t / 7) > 0)  # loud and quiet stretches
    left = (0.3 * env * rng.standard_normal(n)).astype(np.float32)
    right = (0.8 * left + 0.2 * (0.3 * rng.standard_normal(n))).astype(np.float32)
    # clipped runs, one straddling what would be a chunk seam
    for a in (1000, 30009, 150000):
        left[a : a + 5] = 1.0
    left[70000:70002] = -1.0  # too short to count
    return left, right


def ref_frames(x, n, hop):
    return sliding_window_view(np.asarray(x, np.float64), n)[::hop]


def ref_loud(fr):
    rms = np.sqrt((fr**2).mean(axis=1))
    m = rms > max(1e-4, float(np.percentile(rms, 30)))
    return m if m.sum() >= 4 else np.ones(len(rms), bool)


def test_spectrum_percentiles_identical(small_chunks):
    dsp, _ = small_chunks
    x, _ = signal()
    n, hop = 1024, 512
    fr = ref_frames(x, n, hop)
    fr = fr[ref_loud(fr)]
    win = np.hanning(n)
    sp = np.fft.rfft(fr * win, axis=1)
    db = 10 * np.log10((sp.real**2 + sp.imag**2) / (win.sum() / 2) ** 2 + 1e-30)
    ref = np.percentile(db, (50, 90), axis=0)
    got, used = dsp.spectrum_percentiles(x, SR, n=n, hop=hop)
    assert used == len(fr)
    np.testing.assert_array_equal(got, ref)


def test_band_ratio_std_identical(small_chunks):
    dsp, _ = small_chunks
    x, _ = signal(1)
    n, hop = 256, 128
    fr = ref_frames(x, n, hop)
    fr = fr[ref_loud(fr)]
    sp = np.fft.rfft(fr * np.hanning(n), axis=1)
    p = sp.real**2 + sp.imag**2
    f = np.fft.rfftfreq(n, 1 / SR)
    hi, lo = (f > 3000) & (f < 3800), (f > 1500) & (f < 2900)
    ref = float((10 * np.log10(p[:, hi].sum(1) / (p[:, lo].sum(1) + 1e-30) + 1e-12)).std())
    got = dsp.band_ratio_std(x, SR, (1500, 2900), (3000, 3800), n=n, hop=hop)
    assert got == ref


def test_mean_power_spectrum_matches(small_chunks):
    dsp, _ = small_chunks
    x, _ = signal(2)
    n = 4096
    fr = ref_frames(x, n, n // 2)
    sp = np.fft.rfft(fr * np.hanning(n), axis=1)
    ref = (sp.real**2 + sp.imag**2).mean(axis=0)
    np.testing.assert_allclose(dsp.mean_power_spectrum(x, n, n // 2), ref, rtol=1e-12)


def ref_runs(x, level, equal=False):
    a = np.abs(np.asarray(x, np.float32))
    hot = a == np.float32(level) if equal else a >= np.float32(level)
    d = np.diff(np.concatenate([[0], hot.astype(np.int8), [0]]))
    st, en = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return st[(en - st) >= 3]


def test_summary_blocks_and_runs_identical(small_chunks):
    dsp, _ = small_chunks
    left, right = signal(3)
    sm = dsp.summarize(left, right, SR)
    L, R = left.astype(np.float64), right.astype(np.float64)
    mix = ((left + right) * np.float32(0.5)).astype(np.float64)
    side = ((left - right) * np.float32(0.5)).astype(np.float64)
    for key, B in sm.sizes.items():
        nb = len(L) // B
        for name, v in (("left", L), ("right", R), ("mix", mix), ("side", side)):
            blk = v[: nb * B].reshape(nb, B)
            np.testing.assert_array_equal(sm.ss[key][name], (blk**2).sum(axis=1))
            np.testing.assert_array_equal(sm.pk[key][name], np.abs(blk).max(axis=1))
        np.testing.assert_array_equal(sm.lr[key], (L[: nb * B] * R[: nb * B]).reshape(nb, B).sum(axis=1))
    for name, v in (("left", L), ("right", R), ("mix", mix), ("side", side)):
        assert math.isclose(sm.total_ss[name], float((v**2).sum()), rel_tol=1e-12)
    assert math.isclose(sm.total_lr, float((L * R).sum()), rel_tol=1e-12)
    ref = np.sort(np.r_[ref_runs(left, 0.99997), ref_runs(right, 0.99997)])
    assert sm.clip_runs == len(ref) == 3
    np.testing.assert_allclose(sm.clip_times, ref / SR)
    assert sm.peak == max(float(np.abs(L).max()), float(np.abs(R).max()))


def test_count_runs_across_every_seam(small_chunks):
    dsp, _ = small_chunks
    x = np.zeros(200000, np.float32)
    for a in range(29995, 200000, 30011):  # runs straddling each chunk seam
        x[a : a + 30] = 0.5
    c, t = dsp.count_runs(x, 0.5, SR, exact_equal=True)
    ref = ref_runs(x, 0.5, equal=True)
    assert c == len(ref) and np.allclose(t, ref / SR)


def ref_clicks(x, sr, window_s=60):
    half, excl = max(8, int(sr * 0.0015)), 4
    win = max(sr, int(window_s * sr))
    events = 0
    for a in range(0, len(x), win):
        w = np.asarray(x[a : a + win], np.float64)
        if len(w) < 3:
            continue
        d2 = np.abs(np.diff(w, 2))
        mad = np.median(d2) + 1e-12
        iso = []
        for i in np.flatnonzero(d2 > 40 * mad):
            lo, hi = max(0, i - half), min(len(d2), i + half + 1)
            around = max(
                d2[lo : max(lo, i - excl)].max(initial=0), d2[min(hi, i + excl + 1) : hi].max(initial=0)
            )
            if d2[i] > 4 * around:
                iso.append(i)
        if iso:
            events += int((np.r_[True, np.diff(np.array(iso)) > sr // 200]).sum())
    return round(events / (len(x) / sr / 60), 1)


def test_isolated_clicks_identical(small_chunks):
    dsp, _ = small_chunks
    rng = np.random.default_rng(4)
    x = (0.01 * rng.standard_normal(SR * 130)).astype(np.float32)
    x[:: SR // 3] += 0.7
    assert dsp.isolated_clicks(x, SR) == ref_clicks(x, SR)


def test_stft_columns_every_frame(small_chunks):
    dsp, _ = small_chunks
    x, _ = signal(5)
    fft, cols = 512, 37
    t0, t1 = 3.3, 31.7
    win = np.hanning(fft)
    got = dsp.stft_columns(x, SR, t0, t1, cols, fft, win)
    hop = fft // 2
    a, b = t0 * SR, t1 * SR
    slot = (b - a) / cols
    ref = np.zeros_like(got)
    cnt = np.zeros(cols)
    for k in range(math.ceil(a / hop), math.ceil(b / hop)):
        c = k * hop
        j = min(cols - 1, int((c - a) / slot))
        seg = np.zeros(fft)
        lo = c - fft // 2
        src = np.asarray(x[max(0, lo) : lo + fft], np.float64)
        seg[max(0, -lo) : max(0, -lo) + len(src)] = src
        s = np.fft.rfft(seg * win)
        ref[j] += s.real**2 + s.imag**2
        cnt[j] += 1
    ref /= cnt[:, None]
    np.testing.assert_allclose(got, ref, rtol=1e-10, atol=1e-18)
    # zoomed in: one frame centred on each column
    z = dsp.stft_columns(x, SR, 10.0, 10.1, 23, fft, win)
    for j in range(23):
        c = int(10.0 * SR + (j + 0.5) * (0.1 * SR / 23))
        s = np.fft.rfft(np.asarray(x[c - fft // 2 : c + fft // 2], np.float64) * win)
        np.testing.assert_allclose(z[j], s.real**2 + s.imag**2, rtol=1e-12, atol=1e-18)


def test_goniometer_identical(small_chunks):
    dsp, _ = small_chunks
    left, right = signal(6)
    L, R = left.astype(np.float64), right.astype(np.float64)
    m, s = (L + R) / 2, (L - R) / 2
    lim = max(1e-6, float(np.abs(m).max()), float(np.abs(s).max()))
    ref, _, _ = np.histogram2d(-m / lim, s / lim, bins=64, range=[[-1, 1], [-1, 1]])
    h, corr = dsp.goniometer(left, right, 0, len(left), 64)
    np.testing.assert_array_equal(h, ref)
    assert math.isclose(corr, float((L * R).sum() / np.sqrt((L * L).sum() * (R * R).sum())), rel_tol=1e-12)


def test_dr_and_quiet_floor_identical(small_chunks):
    _, app = small_chunks
    left, right = signal(7)
    got = app.dynamics(left, right, SR)
    drs = []
    for x in (left, right):
        blk = 3 * SR
        nb = len(x) // blk
        b = x[: nb * blk].astype(np.float64).reshape(nb, blk)
        rms = np.sqrt(2 * np.mean(b**2, axis=1))
        pk = np.sort(np.abs(b).max(axis=1))
        top = np.sort(rms)[-max(1, round(nb * 0.2)) :]
        drs.append(20 * np.log10(pk[-2] / np.sqrt(np.mean(top**2))))
    assert got["drPerChannel"] == [round(float(d), 1) for d in drs]
    assert got["dr"] == round(float(np.mean(drs)))
    L, R = left.astype(np.float64), right.astype(np.float64)
    n = len(L) // SR
    Ls, Rs = L[: n * SR].reshape(n, SR), R[: n * SR].reshape(n, SR)
    ser = (Ls * Rs).sum(1) / np.sqrt((Ls**2).sum(1) * (Rs**2).sum(1))
    assert got["correlationSeries"] == [round(float(v), 3) for v in ser]
    mix = ((left + right) * np.float32(0.5)).astype(np.float64)
    blk = int(0.4 * SR)
    nb = len(mix) // blk
    r = np.sqrt((mix[: nb * blk].reshape(nb, blk) ** 2).mean(1))
    ref_floor = round(float(20 * np.log10(np.percentile(r[r > 1e-9], 5))), 1)
    assert app.quiet_floor(None, SR, dsp_summary(small_chunks, left, right)) == ref_floor


def dsp_summary(small_chunks, left, right):
    dsp, _ = small_chunks
    return dsp.summarize(left, right, SR)


def test_bit_usage_counts_every_sample(small_chunks, tmp_path):
    _, app = small_chunks
    f = tmp_path / "t.flac"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=d=5:a=0.3",
            "-ac",
            "2",
            "-sample_fmt",
            "s16",
            str(f),
        ],
        check=True,
    )
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(f), "-f", "s32le", "-acodec", "pcm_s32le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    v = np.frombuffer(raw, np.int32)
    u = (v >> 16).astype(np.int64) & 0xFFFF
    ref = [round(int(np.count_nonzero((u >> i) & 1)) / len(v), 6) for i in range(16)]
    got = app.bit_usage(str(f), 16)
    assert got["samples"] == len(v) and got["ones"] == ref


def test_column_extremes_identical(small_chunks):
    dsp, _ = small_chunks
    x, _ = signal(8)
    B = 512
    idx = dsp.feed_all(x, dsp.BlockExtremes(B))[0]
    a, b, cols = 1234, len(x) - 777, 97
    got = dsp.column_extremes(x, a, b, cols, idx, B)
    edges = np.linspace(a, b, cols + 1).astype(np.int64)
    for j in range(cols):
        seg = x[edges[j] : max(edges[j + 1], edges[j] + 1)]
        assert got[j, 0] == seg.min() and got[j, 1] == seg.max()


def test_pipeline_equals_direct_functions(small_chunks, tmp_path, monkeypatch):
    """run_analysis (three shared sequential passes) must give exactly what the
    direct whole-signal functions give."""
    dsp, app = small_chunks
    lib = tmp_path / "lib"
    lib.mkdir()
    f = lib / "t.flac"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=d=20:c=pink:a=0.4,aformat=channel_layouts=stereo",
            "-sample_fmt",
            "s16",
            "-ar",
            "44100",
            str(f),
        ],
        check=True,
    )
    monkeypatch.setattr(app, "ROOT", str(lib))
    monkeypatch.setattr(app.PCM, "dir", str(tmp_path))
    res = app._run(str(f), *app.PCM.open(str(f)))
    mix, sr = app.PCM.get(str(f), "mix")
    side, _ = app.PCM.get(str(f), "side")
    left, _ = app.PCM.get(str(f), "left")
    right, _ = app.PCM.get(str(f), "right")
    sm = dsp.summarize(left, right, sr)
    direct = app.analyse_pcm(mix, side, sr, summary=sm)
    assert res["analysis"] == direct
    assert res["stats"]["dynamics"] == app.dynamics(left, right, sr, sm)
    for ch in ("left", "right", "side"):
        (p90,), _ = dsp.spectrum_percentiles(app.PCM.get(str(f), ch)[0], sr, qs=(90,))
        assert res["stats"]["channelCutoffs"][ch] == app.lowpass(p90, None, sr)["cutoff_hz"]
