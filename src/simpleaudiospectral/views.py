"""What the browser draws: spectrogram tiles, waveform peaks, goniometer.

Each view is computed for exactly the visible range at exactly the display
size, from every sample in that range.
"""

import numpy as np

from . import dsp

DB_FLOOR = -160.0  # uint8 0 = DB_FLOOR dBFS, 255 = 0 dBFS
WAVE_BLOCK = 4096  # samples per block of the waveform index


def window(name: str, n: int) -> np.ndarray:
    if name == "blackman-harris":
        k = np.arange(n) / (n - 1) * 2 * np.pi
        w = 0.35875 - 0.48829 * np.cos(k) + 0.14128 * np.cos(2 * k) - 0.01168 * np.cos(3 * k)
    elif name == "kaiser":
        w = np.kaiser(n, 14.0)  # about SoX's default Kaiser: -120 dB sidelobes
    elif name == "hamming":
        w = np.hamming(n)
    elif name == "blackman":
        w = np.blackman(n)
    else:
        w = np.hanning(n)
    return w.astype(np.float32)


def stft_view(x, sr, t0, t1, cols, rows, f0, f1, fft, win, scale) -> tuple[bytes, dict]:
    """Spectrogram of the viewport as a uint8 dB matrix (rows x cols, top row = f1).

    Each column is the mean power of every FFT frame (hop fft/2) centred in
    its time slot (dsp.stft_columns). Each row is the maximum over the FFT
    bins it covers, so a thin lowpass edge or a single tone is never pooled
    away at a small display height.
    """
    w = window(win, fft).astype(np.float64)
    norm = (w.sum() / 2) ** 2  # a full-scale sine reads 0 dBFS
    nb = fft // 2 + 1
    bin_hz = sr / fft
    f1 = min(f1, sr / 2)
    f0 = max(0.0, min(f0, f1 - bin_hz))
    edges = np.geomspace(max(f0, 10.0), f1, rows + 1) if scale == "log" else np.linspace(f0, f1, rows + 1)
    starts_b = np.clip(np.floor(edges[:-1] / bin_hz).astype(np.int64), 0, nb - 1)
    end_b = int(min(nb, np.ceil(f1 / bin_hz) + 1))
    starts_b = np.minimum(starts_b, end_b - 1)
    pooled = dsp.stft_columns(
        x, sr, t0, t1, cols, fft, w, reduce=lambda p: np.maximum.reduceat(p[:, :end_b], starts_b, axis=1)
    )
    db = 10 * np.log10(pooled / norm + 1e-30)
    q = np.clip((db - DB_FLOOR) * (255.0 / -DB_FLOOR), 0, 255).astype(np.uint8)
    img = np.ascontiguousarray(q.T[::-1])
    meta = {
        "cols": cols,
        "rows": rows,
        "t0": t0,
        "t1": t1,
        "f0": f0,
        "f1": f1,
        "scale": scale,
        "fft": fft,
        "sr": sr,
        "dbFloor": DB_FLOOR,
        "dbCeil": 0.0,
        "binHz": bin_hz,
        "framesPerCol": "all",
    }
    return img.tobytes(), meta


def peaks(x, sr, t0, t1, cols) -> bytes:
    """Exact min and max of each column's samples, float32 [min0, max0, ...]."""
    a = int(max(0, t0 * sr))
    b = int(min(len(x), max(a + 1, t1 * sr)))
    edges = np.linspace(a, b, cols + 1).astype(np.int64)
    out = np.zeros((cols, 2), dtype=np.float32)
    if b <= a:
        return out.tobytes()
    # Columns in groups spanning at most CHUNK samples: a full view of a 3 h
    # set must not materialise the whole track.
    c = 0
    while c < cols:
        c1 = c + 1
        while c1 < cols and edges[c1 + 1] - edges[c] <= dsp.core.CHUNK:
            c1 += 1
        lo, hi = int(edges[c]), int(max(edges[c1], edges[c] + 1))
        seg = np.asarray(x[lo:hi], dtype=np.float32)
        st = np.clip(edges[c:c1] - lo, 0, len(seg) - 1)
        out[c:c1, 0] = np.minimum.reduceat(seg, st)
        out[c:c1, 1] = np.maximum.reduceat(seg, st)
        c = c1
    return out.tobytes()


def waveform(x, sr, t0, t1, cols, index) -> bytes:
    """Column peaks, from the block index when a column spans many blocks
    (same result, far fewer samples read), else from the samples."""
    if index is not None and (t1 - t0) * sr / cols >= 4 * WAVE_BLOCK:
        a = int(max(0, t0 * sr))
        b = int(min(len(x), max(a + 1, t1 * sr)))
        return dsp.column_extremes(x, a, b, cols, index, WAVE_BLOCK).tobytes()
    return peaks(x, sr, t0, t1, cols)


def goniometer_image(h: np.ndarray, corr: float) -> tuple[bytes, float]:
    """Density counts to a log-scaled uint8 image."""
    h = np.log1p(h)
    return (255 * h / (h.max() or 1)).astype(np.uint8).tobytes(), round(corr, 3)


def goniometer(left, right, sr, t0, t1, size) -> tuple[bytes, float]:
    """Goniometer over every sample of the range."""
    a, b = int(t0 * sr), int(min(len(left), t1 * sr))
    return goniometer_image(*dsp.goniometer(left, right, a, b, size))
