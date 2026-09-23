"""DSP regression pins on synthetic signals - no files, no network."""

import importlib
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    root = tmp_path_factory.mktemp("lib")
    os.environ["LIBRARY_ROOT"] = str(root)
    os.environ["CACHE_DIR"] = str(tmp_path_factory.mktemp("cache"))
    import app as mod

    return importlib.reload(mod)


def noise(sr, seconds=20, seed=1):
    rng = np.random.default_rng(seed)
    # pink-ish: music has falling spectrum; -3 dB/oct keeps the top band audible
    x = rng.standard_normal(sr * seconds)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / sr)
    X /= np.sqrt(np.maximum(f, 20) / 20)
    y = np.fft.irfft(X, n=len(x))
    return (0.3 * y / np.abs(y).max()).astype(np.float32)


def lowpass(x, sr, fc):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / sr)
    X[f > fc] *= 1e-4  # -80 dB, like an encoder lowpass
    return np.fft.irfft(X, n=len(x)).astype(np.float32)


def run(app, x, sr, side=None):
    return app.analyse_pcm(x, side if side is not None else x * 0.3, sr)


def test_fullband_is_lossless(app):
    a = run(app, noise(44100), 44100)
    assert a["level"] == "ok"
    assert a["cutoffHz"] is None


@pytest.mark.parametrize("fc", [16000, 17300, 18600, 20100])
def test_lowpass_detected(app, fc):
    a = run(app, lowpass(noise(44100), 44100, fc), 44100)
    assert a["level"] == "bad"
    assert abs(a["cutoffHz"] - fc) < 250
    assert a["family"]


def sfb21(x, sr, fc, seed=2):
    """MP3-like: lowpass at fc, and the band above 16 kHz only present in
    random frames (LAME codes sfb21 when bits are left over)."""
    y = lowpass(x, sr, fc)
    X = np.fft.rfft(y)
    f = np.fft.rfftfreq(len(y), 1 / sr)
    hi = np.fft.irfft(np.where(f > 16000, X, 0), n=len(y))
    base = y - hi
    rng = np.random.default_rng(seed)
    n = 1152
    gate = np.repeat(rng.random(len(y) // n + 1) < 0.35, n)[: len(y)]
    return (base + hi * gate).astype(np.float32)


def test_mp3_vs_steady_codec_family(app):
    sr = 44100
    mp3 = run(app, sfb21(noise(sr), sr, 20100), sr)
    opus = run(app, lowpass(noise(sr), sr, 20200), sr)
    assert mp3["hfSd"] >= 10 and "MP3" in mp3["family"]
    assert opus["hfSd"] < 8 and "Opus" in opus["family"]


def test_resampled_from_lower_rate(app):
    sr = 48000
    a = run(app, lowpass(noise(sr), sr, 21800), sr)
    assert a["resampledFrom"] == 44100 and a["level"] == "bad"


def test_crt_tone_flagged(app):
    sr = 44100
    x = noise(sr)
    t = np.arange(len(x)) / sr
    x = (x + 0.01 * np.sin(2 * np.pi * 15625 * t)).astype(np.float32)
    assert run(app, x, sr)["crtTone"] == 15625


def test_upsampled_hires(app):
    sr = 96000
    x = lowpass(noise(sr, 10), sr, 21000)
    a = run(app, x, sr)
    assert a["level"] == "bad"
    assert "upsampled" in a["verdict"]
    assert a["hiresDb"] < -45


def test_genuine_hires_ok(app):
    sr = 96000
    a = run(app, noise(sr, 10), sr)
    assert a["level"] == "ok"
    assert a["hiresDb"] > -45


def test_mono_in_stereo(app):
    x = noise(44100)
    a = run(app, x, 44100, side=np.zeros_like(x))
    assert a["sideDb"] < -100


def test_stft_shape_and_scale(app):
    sr = 44100
    t = np.arange(sr * 2) / sr
    x = (0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    body, meta = app.stft_view(x, sr, 0, 2, 200, 100, 0, sr / 2, 4096, "blackman-harris", "linear")
    img = np.frombuffer(body, np.uint8).reshape(100, 200)
    row = img[:, 100].argmax()
    # row 0 = top = 22.05 kHz; 1 kHz sits near the bottom
    f = sr / 2 * (1 - (row + 0.5) / 100)
    assert abs(f - 1000) < sr / 2 / 100
    db = meta["dbFloor"] + img[row, 100] / 255 * -meta["dbFloor"]
    assert -9 < db < -3  # 0.5 amplitude sine = -6 dBFS


def test_resolve_blocks_traversal(app):
    with pytest.raises(PermissionError):
        app.resolve("../../etc/passwd")
    assert app.resolve("") == app.ROOT


def test_dr_meter_sine_vs_compressed(app):
    sr = 44100
    t = np.arange(sr * 30) / sr
    # full-scale sine: peak/RMS -> DR 0 (the sqrt(2) cancels the crest factor)
    sine = (0.9 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    d = app.dynamics(sine, sine.copy(), sr)
    assert d["dr"] == 0 and d["identicalChannels"] and d["correlation"] == 1.0
    # sparse loud hits over quiet noise: large dynamic range
    x = noise(sr, 30) * 0.05
    x[:: sr * 3] = 0.95
    d = app.dynamics(x, x.copy(), sr)
    assert d["dr"] >= 12


def test_clip_events(app):
    x = np.zeros(44100 * 6, np.float32)
    x[1000:1005] = 1.0  # 5-sample run: counts
    x[5000:5002] = -1.0  # 2-sample run: does not
    assert app.dynamics(x, x * 0 + x, 44100)["clipEvents"] == 2  # both channels


def test_loudness_parses_ffmpeg(app, tmp_path):
    import subprocess

    f = tmp_path / "s.flac"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=997:duration=4",
            "-af",
            "volume=0.5",
            "-ac",
            "2",
            str(f),
        ],
        check=True,
    )
    L = app.loudness(str(f))
    assert L["lufs"] is not None and -40 < L["lufs"] < -10
    assert L["samplePeakDb"] is not None and L["lra"] is not None  # true peak: true_peak()


def test_clicks_isolated_vs_dense_transients(app):
    sr = 44100
    quiet = noise(sr, 60) * 0.05
    clicky = quiet.copy()
    clicky[:: sr // 2] += 0.8  # 120 isolated 1-sample clicks per minute
    d_click = app.dynamics(clicky, clicky.copy(), sr)
    # dense loud material: every sample is a "transient", none is isolated
    dense = noise(sr, 60)
    d_dense = app.dynamics(dense, dense.copy(), sr)
    assert d_click["clicksPerMin"] > 60
    assert d_dense["clicksPerMin"] < 5


def test_chunked_passes_match_whole_array(app, monkeypatch):
    """Chunking is how long DJ sets fit in memory; results must not depend on it."""
    sr = 44100
    left = noise(sr, 40, seed=3)
    right = noise(sr, 40, seed=4)
    left[5000:5010] = 1.0
    whole_dyn = app.dynamics(left, right, sr)
    whole_peaks = app.peaks(left, sr, 0, 40, 300)
    whole_floor = app.quiet_floor(left, sr)
    monkeypatch.setattr(app, "CHUNK", 7919)  # prime: never aligned with any block
    small_dyn = app.dynamics(left, right, sr)
    assert small_dyn["dr"] == whole_dyn["dr"]
    assert small_dyn["drPerChannel"] == whole_dyn["drPerChannel"]
    assert small_dyn["clipEvents"] == whole_dyn["clipEvents"] == 1
    assert abs(small_dyn["correlation"] - whole_dyn["correlation"]) < 1e-9
    assert app.peaks(left, sr, 0, 40, 300) == whole_peaks
    assert app.quiet_floor(left, sr) == whole_floor


def test_derived_mix_side_match_numpy(app):
    rng = np.random.default_rng(5)
    mm = rng.standard_normal((10000, 2)).astype(np.float32)
    mix, side = app.Derived(mm, "mix"), app.Derived(mm, "side")
    np.testing.assert_allclose(mix[100:200], (mm[100:200, 0] + mm[100:200, 1]) / 2, rtol=1e-6)
    np.testing.assert_allclose(side[::7], (mm[::7, 0] - mm[::7, 1]) / 2, rtol=1e-6)
    idx = np.array([[-5, 0, 9999, 20000]])
    np.testing.assert_allclose(
        mix.take(idx), (mm[[0, 0, 9999, 9999], 0] + mm[[0, 0, 9999, 9999], 1])[None] / 2, rtol=1e-6
    )
    assert len(mix) == 10000


def test_summary_peaks_match_sample_peaks(app):
    sr = 44100
    x = noise(sr, 30, seed=6)
    sm = app.Summary(x, x.copy(), sr)
    a = np.frombuffer(app.summary_peaks(sm, "left", 0, 30, 60), np.float32).reshape(-1, 2)
    b = np.frombuffer(app.peaks(x, sr, 0, 30, 60), np.float32).reshape(-1, 2)
    np.testing.assert_allclose(a, b, atol=1e-6)


def test_true_peak_finds_intersample_peak(app):
    # A sine at fs/4 with a 45 degree phase: every sample sits at 0.707 of the
    # amplitude, so the sample peak under-reads the true peak by 3.01 dB.
    sr = 48000
    t = np.arange(sr * 10)
    x = (0.5 * np.sin(2 * np.pi * t / 4 + np.pi / 4)).astype(np.float32)
    sm = app.Summary(x, x.copy(), sr)
    sample_peak = 20 * np.log10(np.abs(x).max())
    tp = app.true_peak(sm, x, x.copy(), sr)
    assert abs(sample_peak - (-9.03)) < 0.05
    assert abs(tp - (-6.02)) < 0.2


def test_mp3_lowpass_in_48k_file_is_not_called_a_resample(app):
    # A 320k MP3 decoded at 48 kHz: wall at 20.2 kHz with sfb21 variability.
    sr = 48000
    a = run(app, sfb21(noise(sr), sr, 20200), sr)
    assert a["resampledFrom"] is None and "MP3" in a["family"]
