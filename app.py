#!/usr/bin/env python3
"""simpleaudiospectral - spectral analysis for verifying lossless audio.

The browser renders; this process decodes and does the DSP.

GET /api/ls?path=<rel>          directory listing (dirs + audio files, size, mtime)
GET /api/roots                  top-level folders (volumes) with disk usage
GET /api/search?q=&limit=       search the background index of every folder and track
GET /api/info?path=<rel>        ffprobe metadata, sox bit-depth, cutoff analysis
GET /api/stats?path=<rel>       EBU R128 loudness, true peak, DR, clipping, stereo,
                                bit usage, quiet floor, per-channel cutoffs, vinyl hints
GET /api/scan?path=<dir>        album scan, NDJSON streamed one track at a time
GET /api/gonio?path=&t0=&t1=&size=  goniometer density (uint8 size x size)
GET /api/stft?path=&ch=&t0=&t1=&f0=&f1=&cols=&rows=&fft=&win=&scale=
                                viewport spectrogram, uint8 dB matrix (rows x cols,
                                row 0 = highest frequency), metadata in X-Meta
GET /api/wave?path=&ch=&t0=&t1=&cols=
                                min/max peaks per column, float32 [min0,max0,...]
GET /api/audio?path=            the file itself, Range-capable, for playback
GET /api/spectrogram?path=&ch=&z=&start=&dur=&w=&x=
                                SoX PNG, the classic spectral to post with an upload
GET /*                          the bundled UI (web/dist)

Everything under LIBRARY_ROOT is read-only. Paths are resolved with realpath
and must stay inside the root, so a symlink cannot escape it.
"""

import collections
import gzip
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

ROOT = os.path.realpath(os.environ.get("LIBRARY_ROOT", "/library"))
CACHE = os.environ.get("CACHE_DIR", "/cache")
PORT = int(os.environ.get("PORT", "4748"))
WEB = os.path.realpath(
    os.environ.get("WEB_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))
)
# Decoded audio lives on DISK as memory-mapped float32, never in the heap: a
# 3 h DJ set is 1.9 GB per channel, and holding one in RAM OOM-killed the
# container (measured 2026-09-23: 1.46 GB anon at a 1.5 GB limit). Page cache
# of a memmap is reclaimable, so memory stays bounded whatever the length.
PCM_DIR = os.environ.get("PCM_DIR", "/pcm")
PCM_DISK_BUDGET = int(float(os.environ.get("PCM_DISK_GB", "20")) * 1024**3)
CHUNK = 1 << 22  # samples per chunk in whole-track passes (~16 MB float32)


def _version():
    """Image builds pass VERSION as a build arg; a checkout reads version.txt."""
    if os.environ.get("APP_VERSION"):
        return os.environ["APP_VERSION"]
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.txt")) as f:
            return f.read().strip()
    except OSError:
        return "dev"


VERSION = _version()
JOBS = threading.BoundedSemaphore(int(os.environ.get("MAX_JOBS", "3")))
TIMEOUT = 180

AUDIO_EXT = {
    ".flac",
    ".mp3",
    ".wav",
    ".m4a",
    ".alac",
    ".aac",
    ".ogg",
    ".oga",
    ".opus",
    ".aif",
    ".aiff",
    ".wv",
    ".ape",
    ".dsf",
    ".dff",
    ".mka",
    ".wma",
}
# sox reads these itself; everything else is decoded by ffmpeg into a pipe.
SOX_NATIVE = {".flac", ".mp3", ".wav", ".aif", ".aiff", ".ogg"}
SOX_WINDOWS = {"Kaiser", "Hann", "Hamming", "Bartlett", "Rectangular", "Dolph"}
CHANNELS = {"mix", "left", "right", "side"}
DB_FLOOR = -160.0  # uint8 0 = DB_FLOOR dBFS, 255 = 0 dBFS


def resolve(rel):
    rel = (rel or "").lstrip("/")
    full = os.path.realpath(os.path.join(ROOT, rel))
    if full != ROOT and not full.startswith(ROOT + os.sep):
        raise PermissionError(rel)
    return full


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, timeout=TIMEOUT, check=False, **kw)


# --------------------------------------------------------------------------- PCM


class Derived:
    """Mix or side of a stereo memmap, computed per slice so the whole track
    is never materialised. Supports what the DSP uses: len, slicing and take."""

    def __init__(self, mm, kind):
        self.mm, self.kind = mm, kind
        self.shape = (mm.shape[0],)
        self.dtype = np.dtype(np.float32)

    def __len__(self):
        return self.mm.shape[0]

    def _f(self, a):
        a = np.asarray(a, dtype=np.float32)
        if a.shape[-1] < 2:
            return a[..., 0] if self.kind == "mix" else np.zeros(a.shape[:-1], np.float32)
        if self.kind == "mix":
            return (a[..., 0] + a[..., 1]) * np.float32(0.5)
        return (a[..., 0] - a[..., 1]) * np.float32(0.5)

    def __getitem__(self, key):
        return self._f(self.mm[key])

    def take(self, idx, mode="clip"):
        return self._f(self.mm[np.clip(idx, 0, len(self) - 1)])


def _pcm_dir():
    for d in (PCM_DIR, os.path.join(CACHE, "pcm")):
        try:
            os.makedirs(d, exist_ok=True)
            if os.access(d, os.W_OK):
                return d
        except OSError:
            continue
    raise RuntimeError("no writable PCM_DIR")


class PcmCache:
    """One decode per file, streamed to disk and memory-mapped."""

    def __init__(self):
        self.maps = collections.OrderedDict()
        self.lock = threading.Lock()
        self.decoding = {}
        self.dir = None

    def get(self, path, ch):
        mm, sr = self.open(path)
        if ch == "left":
            return mm[:, 0], sr
        if ch == "right":
            return (mm[:, 1] if mm.shape[1] > 1 else mm[:, 0]), sr
        return Derived(mm, "side" if ch == "side" else "mix"), sr

    def open(self, path):
        key = (path, os.path.getmtime(path))
        with self.lock:
            if key in self.maps:
                self.maps.move_to_end(key)
                return self.maps[key]
            ev = self.decoding.get(key)
            owner = ev is None
            if owner:
                ev = self.decoding[key] = threading.Event()
        if not owner:
            ev.wait(TIMEOUT * 10)
            with self.lock:
                if key in self.maps:
                    return self.maps[key]
            raise RuntimeError("decode failed")
        try:
            val = self._decode(path, key)
            with self.lock:
                self.maps[key] = val
                while len(self.maps) > 32:
                    self.maps.popitem(last=False)
            return val
        finally:
            with self.lock:
                self.decoding.pop(key, None)
            ev.set()

    def _decode(self, path, key):
        if self.dir is None:
            self.dir = _pcm_dir()
        p = run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate,channels",
                "-of",
                "json",
                path,
            ]
        )
        st = (json.loads(p.stdout or b"{}").get("streams") or [{}])[0]
        sr = int(st.get("sample_rate") or 44100)
        nch = max(1, min(2, int(st.get("channels") or 1)))
        name = hashlib.sha256(repr(key).encode()).hexdigest()[:32]
        fn = os.path.join(self.dir, f"{name}.{sr}.{nch}.f32")
        if not os.path.exists(fn):
            tmp = f"{fn}.{threading.get_ident()}.tmp"
            # Streamed straight to the file: capturing stdout would hold the
            # whole decode in memory, which is the OOM this layer exists for.
            with open(tmp, "wb") as out:
                r = subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-i",
                        path,
                        "-map",
                        "0:a:0",
                        "-ac",
                        str(nch),
                        "-f",
                        "f32le",
                        "-",
                    ],
                    stdout=out,
                    stderr=subprocess.PIPE,
                    timeout=TIMEOUT * 10,
                    check=False,
                )
            if r.returncode != 0 or os.path.getsize(tmp) == 0:
                os.unlink(tmp)
                raise RuntimeError("decode failed: " + r.stderr.decode(errors="replace")[-300:])
            os.replace(tmp, fn)
            self._evict(keep=fn)
        os.utime(fn)  # mtime marks last use; atime is usually noatime
        n = os.path.getsize(fn) // (4 * nch)
        return np.memmap(fn, dtype=np.float32, mode="r", shape=(n, nch)), sr

    def _evict(self, keep):
        files = []
        for e in os.scandir(self.dir):
            if e.name.endswith(".f32"):
                st = e.stat()
                files.append((st.st_mtime, st.st_size, e.path))
        total = sum(f[1] for f in files)
        for _, size, fpath in sorted(files):
            if total <= PCM_DISK_BUDGET:
                break
            if fpath != keep:
                os.unlink(fpath)  # an open memmap keeps its inode until closed
                total -= size


def chunks(n, size=CHUNK):
    for a in range(0, n, size):
        yield a, min(n, a + size)


def block_sums(x, blk):
    """Sum of squares and absolute peak per block of `blk` samples, chunked."""
    nb = len(x) // blk
    ss = np.zeros(nb)
    pk = np.zeros(nb)
    per = max(1, CHUNK // blk)
    for b0 in range(0, nb, per):
        b1 = min(nb, b0 + per)
        seg = np.asarray(x[b0 * blk : b1 * blk], dtype=np.float64).reshape(b1 - b0, blk)
        ss[b0:b1] = (seg**2).sum(1)
        pk[b0:b1] = np.abs(seg).max(1)
    return ss, pk


PCM = PcmCache()
STATS = {}
SCAN = {}


# --------------------------------------------------------------------------- DSP


def window(name, n):
    if name == "blackman-harris":
        k = np.arange(n) / (n - 1) * 2 * np.pi
        w = 0.35875 - 0.48829 * np.cos(k) + 0.14128 * np.cos(2 * k) - 0.01168 * np.cos(3 * k)
    elif name == "kaiser":
        w = np.kaiser(n, 14.0)  # ~ sox's default Kaiser: -120 dB sidelobes
    elif name == "hamming":
        w = np.hamming(n)
    elif name == "blackman":
        w = np.blackman(n)
    else:
        w = np.hanning(n)
    return w.astype(np.float32)


def stft_view(x, sr, t0, t1, cols, rows, f0, f1, fft, win, scale):
    """Spectrogram of exactly the viewport, at exactly the display size.

    Each column is the mean power of up to 4 FFT frames spread across its time
    slot, so a zoomed-out view is an average rather than a random sample. Each
    row is the MAX over the FFT bins it covers - a thin lowpass edge or a
    single tone must never be pooled away at a small display height.
    """
    n = len(x)
    w = window(win, fft)
    norm = (w.sum() / 2) ** 2  # a full-scale sine reads 0 dBFS
    span = (t1 - t0) * sr
    hop = span / cols
    sub = int(min(4, max(1, hop // fft)))
    # A full view of a long set would read cols x 4 x fft samples; past ~64 M
    # samples one frame per column is enough, the view is averaging anyway.
    while sub > 1 and cols * sub * fft > 64_000_000:
        sub -= 1
    centers = t0 * sr + (np.arange(cols) + 0.5) * hop
    offs = (np.arange(sub) - (sub - 1) / 2) * (hop / sub)
    starts = (centers[:, None] + offs[None, :] - fft / 2).astype(np.int64).ravel()

    nb = fft // 2 + 1
    bin_hz = sr / fft
    nyq = sr / 2
    f1 = min(f1, nyq)
    f0 = max(0.0, min(f0, f1 - bin_hz))
    edges = np.geomspace(max(f0, 10.0), f1, rows + 1) if scale == "log" else np.linspace(f0, f1, rows + 1)
    starts_b = np.clip(np.floor(edges[:-1] / bin_hz).astype(np.int64), 0, nb - 1)
    end_b = int(min(nb, np.ceil(f1 / bin_hz) + 1))
    starts_b = np.minimum(starts_b, end_b - 1)

    # Columns are processed in groups and pooled to display rows at once, so
    # memory is bounded by the group (~64 MB of frames), never by
    # cols x frames x bins - at FFT 32768 that product is over 1 GB.
    pooled = np.empty((cols, rows), dtype=np.float32)
    ar = np.arange(fft, dtype=np.int64)
    per = max(1, (64 * 1024 * 1024) // (fft * 16 * sub))
    for c0 in range(0, cols, per):
        c1 = min(cols, c0 + per)
        idx = starts[c0 * sub : c1 * sub, None] + ar[None, :]
        frames = np.asarray(x.take(idx, mode="clip"), dtype=np.float32)
        frames[(idx < 0) | (idx >= n)] = 0.0
        spec = np.fft.rfft(frames * w, axis=1)
        power = (spec.real**2 + spec.imag**2).reshape(c1 - c0, sub, nb).mean(axis=1)
        pooled[c0:c1] = np.maximum.reduceat(power[:, :end_b], starts_b, axis=1)

    db = 10 * np.log10(pooled / norm + 1e-30)
    q = np.clip((db - DB_FLOOR) * (255.0 / -DB_FLOOR), 0, 255).astype(np.uint8)
    img = np.ascontiguousarray(q.T[::-1])  # rows x cols, top row = f1
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
        "framesPerCol": sub,
    }
    return img.tobytes(), meta


def summary_peaks(sm, ch, t0, t1, cols):
    """Coarse waveform from the Summary's per-block min/max: a full view of a
    3 h set in milliseconds instead of a pass over the whole file."""
    b0 = max(0, int(t0 / SUMMARY_BLOCK))
    b1 = min(sm.nb, max(b0 + 1, int(np.ceil(t1 / SUMMARY_BLOCK))))
    out = np.zeros((cols, 2), dtype=np.float32)
    if b1 <= b0:
        return out.tobytes()
    st = np.clip(np.linspace(b0, b1, cols + 1).astype(np.int64)[:-1] - b0, 0, b1 - b0 - 1)
    out[:, 0] = np.minimum.reduceat(sm.mn[ch][b0:b1], st)
    out[:, 1] = np.maximum.reduceat(sm.mx[ch][b0:b1], st)
    return out.tobytes()


def peaks(x, sr, t0, t1, cols):
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
        while c1 < cols and edges[c1 + 1] - edges[c] <= CHUNK:
            c1 += 1
        lo, hi = int(edges[c]), int(max(edges[c1], edges[c] + 1))
        seg = np.asarray(x[lo:hi], dtype=np.float32)
        st = np.clip(edges[c:c1] - lo, 0, len(seg) - 1)
        out[c:c1, 0] = np.minimum.reduceat(seg, st)
        out[c:c1, 1] = np.maximum.reduceat(seg, st)
        c = c1
    return out.tobytes()


# ------------------------------------------------------------------- analysis


def ffprobe(path):
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    try:
        data = json.loads(p.stdout or b"{}")
    except ValueError:
        data = {}
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    tags.update({k.lower(): v for k, v in (audio.get("tags") or {}).items()})
    bits = audio.get("bits_per_raw_sample") or audio.get("bits_per_sample") or None
    return {
        "codec": audio.get("codec_long_name") or audio.get("codec_name"),
        "codecName": audio.get("codec_name"),
        "sampleRate": int(audio.get("sample_rate") or 0),
        "channels": int(audio.get("channels") or 0),
        "bits": int(bits) if bits and str(bits).isdigit() and int(bits) > 0 else None,
        "duration": float(fmt.get("duration") or audio.get("duration") or 0),
        "bitrate": int(fmt.get("bit_rate") or 0),
        "size": int(fmt.get("size") or 0),
        "encoder": tags.get("encoder") or tags.get("encoded_by") or tags.get("encoder_settings"),
        "artist": tags.get("artist"),
        "title": tags.get("title"),
        "album": tags.get("album"),
        "date": tags.get("date"),
    }


def sox_bitdepth(path):
    """sox 'stats' Bit-depth is used/declared, e.g. 16/24 = padded 24-bit."""
    p = run(["sox", path, "-n", "stats"])
    for line in p.stderr.decode(errors="replace").splitlines():
        if line.startswith("Bit-depth"):
            return line.split()[1]
    return None


def _step(sm, lo_i, hi_i, span):
    """Largest level drop between the `span` bins below and above each bin."""
    c = np.concatenate([[0.0], np.cumsum(sm)])
    idx = np.arange(max(span, lo_i), min(len(sm) - span, hi_i))
    if not len(idx):
        return 0.0, None, 0.0, 0.0
    above = (c[idx] - c[idx - span]) / span
    below = (c[idx + span] - c[idx]) / span
    d = above - below
    j = int(np.argmax(d))
    return float(d[j]), int(idx[j]), float(above[j]), float(below[j])


def analyse(path):
    """Brick-wall search on per-frame spectra.

    A lossy encoder's lowpass is a wall: 30-60 dB lost within a few hundred Hz,
    in EVERY frame. Genuine lossless content rolls off gently into a noise floor
    that reaches Nyquist.
    - lowpass: the 90th percentile over frames. Pins the edge even for VBR,
      where quiet frames are cut lower and a mean smears the wall.
    - 16 kHz shelf: the MEDIAN over frames. LAME's sfb21 band above 16 kHz is
      only coded when bits are left, so a typical frame steps down at 16 kHz.
    - hi-res: a 88.2/96/192 kHz file whose top octave is empty is an upsample.
    """
    x, sr = PCM.get(path, "mix")
    side, _ = PCM.get(path, "side")
    return analyse_pcm(x, side, sr, summary=summary_for(path))


def analyse_pcm(x, side, sr, summary=None, levels=True):
    """analyse() on decoded samples: mono mix, side channel, sample rate."""
    n = 8192
    if len(x) < n * 4:
        return None
    hops = np.linspace(0, len(x) - n, num=min(600, len(x) // n)).astype(int)
    frames = np.stack([x[h : h + n] for h in hops])
    rms = np.sqrt((frames**2).mean(axis=1))
    loud = frames[rms > max(1e-4, np.percentile(rms, 30))]
    if len(loud) < 4:
        loud = frames
    win = np.hanning(n).astype(np.float32)
    spec = np.fft.rfft(loud * win, axis=1)
    db = 10 * np.log10((spec.real**2 + spec.imag**2) / (win.sum() / 2) ** 2 + 1e-30)
    freqs = np.fft.rfftfreq(n, 1 / sr)
    bin_hz = freqs[1]
    nyq = sr / 2
    k = max(1, int(100 / bin_hz))
    kern = np.ones(k) / k
    p90_raw = np.percentile(db, 90, axis=0)
    p90 = np.convolve(p90_raw, kern, mode="same")
    med = np.convolve(np.median(db, axis=0), kern, mode="same")
    ref = float(np.median(p90[(freqs > 1000) & (freqs < 8000)]))
    span = max(2, int(500 / bin_hz))

    # Search up to 24 kHz: covers 44.1/48 kHz sources inside 48/88.2/96 kHz
    # files; the empty top octave of a hi-res upsample is judged below.
    top = min(nyq, 24000) - 600
    drop, i, above, below = _step(p90, int(12000 / bin_hz), int(top / bin_hz), span)
    cutoff_hz = None
    if i is not None and drop >= 20:
        mid = (above + below) / 2
        seg = np.arange(i - span, i + span)
        hit = seg[p90[seg] > mid]
        cutoff_hz = float(freqs[hit[-1]] if len(hit) else freqs[i])

    # Shelf: a step of >= 10 dB at 16 kHz in the median, above a lowpass that
    # itself sits well above 16 kHz (at 128k the wall IS at 16 kHz).
    sdrop, si, _, _ = _step(med, int(15300 / bin_hz), int(16700 / bin_hz), max(2, int(400 / bin_hz)))
    shelf16 = si is not None and sdrop >= 10 and (cutoff_hz is None or cutoff_hz > 17500)

    hires_db = None
    if sr > 48000:

        def band(a, b):
            m = (freqs >= a) & (freqs < b)
            return float(p90[m].mean())

        hires_db = round(band(24000, min(nyq, 40000)) - band(10000, 20000), 1)

    above70 = np.where(p90 > ref - 80)[0]
    extent_hz = float(freqs[above70[-1]]) if len(above70) else 0.0

    # Whole-track levels: from the Summary when there is one, skipped when the
    # caller only wants a cut-off (per-channel comparison).
    if summary is not None:
        k5 = round(0.5 / SUMMARY_BLOCK)
        mid_ss, side_ss = summary.group(summary.ss["mix"], k5), summary.group(summary.ss["side"], k5)
    elif levels:
        mid_ss, _ = block_sums(x, int(sr * 0.5))
        side_ss, _ = block_sums(side, int(sr * 0.5))
    else:
        mid_ss = side_ss = np.zeros(0)
    mid_rms = float(np.sqrt(mid_ss.sum() / max(1, len(mid_ss)))) + 1e-12
    side_rms = float(np.sqrt(side_ss.sum() / max(1, len(side_ss)))) + 1e-12
    side_db = 20 * np.log10(side_rms / mid_rms) if len(mid_ss) else None

    # sfb21 variability: LAME codes the band above 16 kHz only when bits are
    # left, so its level jumps frame to frame (std 13-23 dB measured), while
    # AAC, Opus, Vorbis and lossless keep it steady (3.7-6.4 dB).
    # Frames must be SHORT (2048 = under two MP3 granules): an 8192 frame
    # averages ~7 granules and hides exactly the variance being measured.
    hf_sd = None
    top_hz = min(cutoff_hz or nyq, 19000) - 300
    if top_hz > 16800:
        ns = 2048
        sh = np.linspace(0, len(x) - ns, num=min(1500, len(x) // ns)).astype(int)
        sf = np.stack([x[h : h + ns] for h in sh])
        srms = np.sqrt((sf**2).mean(axis=1))
        sf = sf[srms > max(1e-4, np.percentile(srms, 30))]
        sw = np.hanning(ns).astype(np.float32)
        sp = np.fft.rfft(sf * sw, axis=1)
        p_lin = sp.real**2 + sp.imag**2
        fs_ = np.fft.rfftfreq(ns, 1 / sr)
        m_hi = (fs_ > 16200) & (fs_ < top_hz)
        m_lo = (fs_ > 12000) & (fs_ < 15800)
        r = 10 * np.log10(p_lin[:, m_hi].sum(1) / (p_lin[:, m_lo].sum(1) + 1e-30) + 1e-12)
        hf_sd = round(float(r.std()), 1)

    # Resampled from a lower rate: a wall just under a standard Nyquist.
    # A resampler's anti-alias filter sits within ~5% of the source Nyquist.
    # An MP3 lowpass can land in the same place (320k at 20.2 kHz is 92% of
    # 22.05), so an MP3-style sfb21 signature wins: that wall is the encoder.
    resampled_from = None
    mp3_like = hf_sd is not None and hf_sd >= 10
    if cutoff_hz and not mp3_like:
        for src_sr in (16000, 22050, 32000, 44100, 48000):
            if src_sr / 2 < nyq - 1000 and 0.94 * src_sr / 2 <= cutoff_hz <= src_sr / 2 + 100:
                resampled_from = src_sr

    # CRT / TV line whine (15.625 kHz PAL, 15.734 kHz NTSC): a narrow tone that
    # reads like an artifact on a spectral and is not one.
    crt = None
    for tone in (15625, 15734):
        b = round(tone / bin_hz)
        if b + 40 < len(p90_raw):
            around = np.median(np.r_[p90_raw[b - 40 : b - 4], p90_raw[b + 4 : b + 40]])
            if p90_raw[b - 2 : b + 3].max() - around > 15:
                crt = tone

    # Loudest 8 s: where a zoomed spectral is most informative.
    win_s = min(8.0, len(x) / sr)
    loudest = 0.0
    if len(mid_ss) > 2:
        w = max(1, int(win_s * 2))
        c = np.convolve(mid_ss, np.ones(w), mode="valid")
        loudest = float(np.argmax(c) * 0.5)

    family = codec_family(cutoff_hz, hf_sd, drop)
    verdict, level = verdict_for(cutoff_hz, drop, extent_hz, nyq, sr, hires_db, family, resampled_from)
    step = max(1, int(25 / bin_hz))
    keep = slice(0, len(freqs) - k, step)  # "same" convolution smears the last k bins
    return {
        "cutoffHz": cutoff_hz,
        "dropDb": round(drop, 1),
        "extentHz": round(extent_hz),
        "nyquistHz": nyq,
        "shelf16k": bool(shelf16),
        "shelfDropDb": round(sdrop, 1),
        "hiresDb": hires_db,
        "sideDb": round(side_db, 1) if side_db is not None else None,
        "hfSd": hf_sd,
        "family": family,
        "resampledFrom": resampled_from,
        "crtTone": crt,
        "loudestAt": loudest,
        "verdict": verdict,
        "level": level,
        "refDb": round(ref, 1),
        "curve": {
            "hz": [round(float(f)) for f in freqs[keep]],
            "db": [round(float(v), 1) for v in p90[keep]],
            "median": [round(float(v), 1) for v in med[keep]],
        },
    }


def codec_family(cutoff_hz, hf_sd, drop):
    """Name the likely source codec from lowpass + sfb21 behaviour.

    Measured on one master with ffmpeg's encoders (libmp3lame, aac, libopus,
    libvorbis): MP3 V4 17.5k / V2 18.8k / 256k 19.5k / V0+320k 20.1k; AAC 128k
    17.3k; Opus 20.2-20.3k (hard 20 kHz band limit); Vorbis q3 18.3k, q6 21.2k.
    ffmpeg's AAC at 256k has NO lowpass and cannot be caught spectrally.
    """
    if not cutoff_hz or drop < 20:
        return None
    k = cutoff_hz / 1000
    mp3ish = hf_sd is not None and hf_sd >= 10
    steady = hf_sd is not None and hf_sd < 8
    if k < 17.1:  # LAME 128k: transition band 16.5-17.07 kHz, lower on dense music
        return "AAC ~128k or low-rate lossy" if steady else "MP3 128k"
    if k < 17.9:
        return "MP3 V4/160k" if mp3ish else ("AAC ~128k" if steady else "MP3 V4 or AAC 128k")
    if k < 19.0:
        return "MP3 V2/192k" if mp3ish else ("Vorbis q3 / AAC" if steady else "MP3 V2 or Vorbis")
    if k < 19.8:
        return "MP3 256k / V0 (older LAME)" if not steady else "AAC/Vorbis ~192k"
    if k < 20.6:
        return (
            "MP3 320k/V0"
            if mp3ish
            else ("Opus (20 kHz band limit) or AAC" if steady else "MP3 320k/V0 or Opus")
        )
    if k < 21.4:
        return "Vorbis q6+ or high-rate AAC" if not mp3ish else "MP3 320k (wide lowpass)"
    return None


def verdict_for(cutoff_hz, drop, extent_hz, nyq, sr, hires_db, family=None, resampled_from=None):
    khz = cutoff_hz / 1000 if cutoff_hz else None
    if sr > 48000 and hires_db is not None and hires_db < -45:
        src = (
            (" - and that source itself carries a {:.1f} kHz wall ({})".format(khz, family or "lossy?"))
            if khz is not None and khz < 20.8
            else ""
        )
        return (
            f"Hi-res container, but nothing above 22 kHz ({hires_db:.0f} dB below the midrange): "
            f"upsampled from 44.1/48 kHz{src}.",
            "bad",
        )
    if resampled_from and khz is not None:
        return (
            f"Wall at {khz:.1f} kHz, just under the Nyquist of {resampled_from // 2} Hz: resampled "
            f"from {resampled_from / 1000:.1f} kHz into a {sr} Hz file.",
            "bad",
        )
    if khz is None:
        return (
            f"No brick-wall lowpass; content reaches {extent_hz / 1000:.1f} kHz "
            f"(Nyquist {nyq / 1000:.1f}). Consistent with lossless - but a high-rate AAC "
            "(e.g. ffmpeg 256k) has no lowpass either, so check for holes when in doubt.",
            "ok",
        )
    if khz >= 21.4:
        return (f"Wall at {khz:.1f} kHz close to Nyquist: the anti-alias filter of a lossless source.", "ok")
    if family:
        tail = "" if khz < 20.8 else " A CD's anti-alias filter usually sits at 21.5-22 kHz."
        return (
            f"Brick wall at {khz:.1f} kHz ({drop:.0f} dB drop): looks like {family}. "
            f"If this file claims to be lossless it is a transcode.{tail}",
            "bad" if khz < 20.8 else "warn",
        )
    return (
        f"Brick wall at {khz:.1f} kHz ({drop:.0f} dB drop). Not a known codec lowpass - a low "
        "bitrate, or a band-limited master (old ADD CDs can top out near 16 kHz). "
        "Zoom in: a codec wall is flat and constant, a master rolls off softly.",
        "warn",
    )


def _num(text, pattern):
    m = re.search(pattern, text)
    if not m:
        return None
    v = m.group(1)
    return None if v in ("-inf", "inf", "nan") else float(v)


def true_peak(sm, left, right, sr, blocks=96):
    """True peak (dBTP) per ITU-R BS.1770-4 Annex 2: oversample 4x (2x at
    88.2/96 kHz, none above), take the absolute maximum.

    Only the loudest summary blocks are oversampled - an inter-sample peak
    sits next to a large sample peak, so the global maximum is among them.
    That turns a 28 s pass over a 3 h set (ffmpeg peak=true) into well under
    a second.
    """
    over = 4 if sr <= 48000 else 2 if sr <= 96000 else 1
    taps = 48
    k = np.arange(-taps * over, taps * over + 1)
    h = np.sinc(k / over) * np.kaiser(len(k), 8.0)
    best = 0.0
    for ch, x in (("left", left), ("right", right)) if sm.stereo else (("left", left),):
        am = sm.absmax(ch)
        if not len(am):
            continue
        for b in np.argsort(am)[-blocks:]:
            a0 = max(0, b * sm.bs - taps)
            a1 = min(sm.n, (b + 1) * sm.bs + taps)
            seg = np.asarray(x[a0:a1], dtype=np.float64)
            if over == 1:
                best = max(best, float(np.abs(seg).max(initial=0)))
                continue
            up = np.zeros(len(seg) * over)
            up[::over] = seg
            y = np.convolve(up, h, mode="same")
            best = max(best, float(np.abs(y).max(initial=0)))
    return round(20 * np.log10(best), 1) if best > 0 else None


def loudness(path, raw=None):
    """raw = (pcm_file, sr, channels): read the decoded PCM instead of
    decoding the source again (a 3 h MP3 decode is half a minute)."""
    """EBU R128 / BS.1770-4 via ffmpeg's ebur128 (K-weighting, gating, 4x
    oversampled true peak) plus astats. Both are reference implementations,
    which is the point: a hand-rolled K-filter is where loudness tools drift."""
    src = (
        ["-f", "f32le", "-ar", str(raw[1]), "-ac", str(raw[2]), "-i", raw[0]] if raw else ["-i", path, "-vn"]
    )
    p = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            *src,
            "-af",
            "ebur128=framelog=verbose,astats=measure_perchannel=none:measure_overall="
            "Peak_level+RMS_level+DC_offset+Flat_factor+Peak_count+Noise_floor+Bit_depth",
            "-f",
            "null",
            "-",
        ]
    )
    t = p.stderr.decode(errors="replace")
    empty = dict.fromkeys(
        [
            "lufs",
            "lra",
            "truePeakDb",
            "samplePeakDb",
            "rmsDb",
            "dcOffset",
            "flatFactor",
            "noiseFloorDb",
            "effectiveBits",
        ]
    )
    if p.returncode != 0:
        # A failed filter still prints a summary of zeros; never report that as data.
        sys.stderr.write(f"loudness: ffmpeg exit {p.returncode}: {t[-300:]}\n")
        return empty
    summary = t[t.rfind("Summary:") :] if "Summary:" in t else ""
    bd = None
    m = re.search(r"Bit depth: ([\d/]+)", t)
    if m:
        bd = m.group(1)
    return {
        "lufs": _num(summary, r"I:\s+(-?[\d.]+|-inf) LUFS"),
        "lra": _num(summary, r"LRA:\s+(-?[\d.]+) LU"),
        "truePeakDb": _num(summary, r"Peak:\s+(-?[\d.]+|-inf) dBFS"),
        "samplePeakDb": _num(t, r"Peak level dB: (-?[\d.]+|-inf)"),
        "rmsDb": _num(t, r"RMS level dB: (-?[\d.]+|-inf)"),
        "dcOffset": _num(t, r"DC offset: (-?[\d.e-]+)"),
        "flatFactor": _num(t, r"Flat factor: (-?[\d.]+)"),
        "noiseFloorDb": _num(t, r"Noise floor dB: (-?[\d.]+|-inf)"),
        "effectiveBits": bd,
    }


def _runs(hot, offset, sr, times):
    d = np.diff(np.concatenate([[0], hot.astype(np.int8), [0]]))
    st, en = np.where(d == 1)[0], np.where(d == -1)[0]
    runs = st[(en - st) >= 3]
    if len(times) < 500:
        times.extend(((runs + offset) / sr).tolist())
    return len(runs)


def _isolated_clicks(seg, sr):
    """Isolated spikes in the 2nd difference. A vinyl click is a few samples
    wide and stands far above its neighbourhood; a drum hit or a dense passage
    raises the whole neighbourhood with it, so a candidate must beat the max
    of the surrounding +-1.5 ms by 4x."""
    d2 = np.abs(np.diff(seg, 2))
    mad = np.median(d2) + 1e-12
    cand = np.where(d2 > 40 * mad)[0]
    if len(cand) > 5000:
        cand = np.sort(cand[np.argsort(d2[cand])[-5000:]])
    half, excl = max(8, int(sr * 0.0015)), 4
    iso = []
    for i in cand:
        a, b = max(0, i - half), min(len(d2), i + half)
        around = max(d2[a : max(a, i - excl)].max(initial=0), d2[min(b, i + excl) : b].max(initial=0))
        if d2[i] > 4 * around:
            iso.append(i)
    if not iso:
        return 0
    iso = np.array(iso)
    return int((np.r_[True, np.diff(iso) > sr // 200]).sum())


SUMMARY_BLOCK = 0.1  # seconds


class Summary:
    """Per-0.1 s block statistics of a whole track, from ONE chunked pass.

    Everything length-proportional (DR, RMS, correlation, quiet floor, the
    loudest window, clip runs, coarse waveform views) reads these arrays
    instead of the samples. Measured on a 3 h set: ten passes over a 4.2 GB
    memmap took 168 s; one pass is what is left.
    """

    def __init__(self, left, right, sr):
        self.sr = sr
        self.bs = bs = max(1, int(sr * SUMMARY_BLOCK))
        self.stereo = right is not left
        n = len(left)
        self.n = n
        nb = n // bs
        self.nb = nb
        z = lambda: np.zeros(nb)
        self.ss = {k: z() for k in ("left", "right", "mix", "side")}
        self.mn = {k: z() for k in ("left", "right", "mix", "side")}
        self.mx = {k: z() for k in ("left", "right", "mix", "side")}
        self.lr = z()
        self.clip_runs = 0
        self.clip_times = []
        self.identical = True
        per = max(1, CHUNK // bs)
        for b0 in range(0, nb, per):
            b1 = min(nb, b0 + per)
            a, b = b0 * bs, b1 * bs
            L = np.asarray(left[a:b], dtype=np.float64)
            R = np.asarray(right[a:b], dtype=np.float64) if self.stereo else L
            sig = {"left": L, "right": R, "mix": (L + R) * 0.5, "side": (L - R) * 0.5}
            for k, v in sig.items():
                blk = v.reshape(b1 - b0, bs)
                self.ss[k][b0:b1] = (blk * blk).sum(1)
                self.mn[k][b0:b1] = blk.min(1)
                self.mx[k][b0:b1] = blk.max(1)
            self.lr[b0:b1] = (L * R).reshape(b1 - b0, bs).sum(1)
            if self.stereo and self.identical:
                self.identical = bool(np.array_equal(L, R))
            for v in (L, R) if self.stereo else (L,):
                self.clip_runs += _runs(np.abs(v) >= 0.99997, a, sr, self.clip_times)
        self.peak = max(
            float(np.max(np.abs(self.mn["left"]), initial=0)),
            float(np.max(self.mx["left"], initial=0)),
            float(np.max(np.abs(self.mn["right"]), initial=0)),
            float(np.max(self.mx["right"], initial=0)),
        )

    def group(self, arr, k, how="sum"):
        """Fold blocks into groups of k (e.g. 30 blocks = 3 s)."""
        m = len(arr) // k
        g = arr[: m * k].reshape(m, k)
        return {"sum": g.sum, "max": g.max, "min": g.min}[how](1)

    def absmax(self, ch):
        return np.maximum(np.abs(self.mn[ch]), np.abs(self.mx[ch]))


SUMMARIES = collections.OrderedDict()
SUMMARY_LOCK = threading.Lock()


def summary_for(path):
    key = (path, os.path.getmtime(path))
    with SUMMARY_LOCK:
        if key in SUMMARIES:
            SUMMARIES.move_to_end(key)
            return SUMMARIES[key]
    left, sr = PCM.get(path, "left")
    right, _ = PCM.get(path, "right")
    mm, _ = PCM.open(path)
    sm = Summary(left, right if mm.shape[1] > 1 else left, sr)
    with SUMMARY_LOCK:
        SUMMARIES[key] = sm
        while len(SUMMARIES) > 16:
            SUMMARIES.popitem(last=False)
    return sm


def dynamics(left, right, sr, summary=None):
    """DR meter (TT/foobar 'DR14' algorithm) and stereo statistics.

    DR per channel: 3 s blocks; block RMS = sqrt(2 * mean(x^2)); block peak.
    DR = 20*log10( 2nd-highest block peak / sqrt(mean of the loudest 20% of
    block RMS^2) ). The reported value is the channel mean, rounded. Block
    statistics come from the one-pass Summary, so length does not matter.
    """
    sm = summary or Summary(left, right, sr)
    stereo = sm.stereo
    n = sm.n
    k3 = round(3 / SUMMARY_BLOCK)
    nb = sm.nb // k3
    if nb < 1:
        return None
    out = {}
    drs = []
    for ch in ("left", "right") if stereo else ("left",):
        ss = sm.group(sm.ss[ch], k3)
        pk = sm.group(sm.absmax(ch), k3, "max")
        rms = np.sqrt(2 * ss / (k3 * sm.bs))
        pks = np.sort(pk)
        pk2 = pks[-2] if nb >= 2 else pks[-1]
        top = np.sort(rms)[-max(1, round(nb * 0.2)) :]
        r = np.sqrt(np.mean(top**2))
        drs.append(20 * np.log10(pk2 / r) if r > 0 and pk2 > 0 else 0.0)
    out["dr"] = round(float(np.mean(drs)))
    out["drPerChannel"] = [round(float(d), 1) for d in drs]

    # Clipping: runs of >= 3 consecutive samples at digital full scale, from
    # the Summary pass. "Flat tops" - the same runs at the file's own peak when
    # that peak is below full scale (clipped, then normalised down) - need the
    # peak first, so they cost a second pass, and only when the peak is < FS.
    times = list(sm.clip_times)
    flat = 0
    if 0 < sm.peak < 0.99997:
        level = np.float32(sm.peak)
        for x in (left, right) if stereo else (left,):
            for c0, c1 in chunks(n):
                flat += _runs(np.abs(np.asarray(x[c0:c1], dtype=np.float32)) == level, c0, sr, times)
    out["clipEvents"] = sm.clip_runs
    out["flatTopEvents"] = flat
    out["clipTimes"] = [round(t, 3) for t in sorted({round(t, 2) for t in times})[:500]]

    def mix_slice(a, b):
        seg_l = np.asarray(left[a:b], dtype=np.float64)
        return (seg_l + np.asarray(right[a:b], dtype=np.float64)) * 0.5 if stereo else seg_l

    # Vinyl / analogue-chain hints from sampled windows. Neither proves
    # anything alone.
    fr = 1 << 16
    if n > fr * 2:
        hops = np.linspace(0, n - fr, 24).astype(int)
        w = np.hanning(fr)
        P = np.mean([np.abs(np.fft.rfft(mix_slice(h, h + fr) * w)) ** 2 for h in hops], axis=0)
        f = np.fft.rfftfreq(fr, 1 / sr)
        sub = P[(f >= 5) & (f < 20)].mean()
        body = P[(f >= 40) & (f < 400)].mean()
        out["rumbleDb"] = round(float(10 * np.log10(sub / (body + 1e-30) + 1e-30)), 1)
    else:
        out["rumbleDb"] = None

    # Clicks in up to 10 windows of 60 s spread over the track.
    win = min(n, 60 * sr)
    starts = np.linspace(0, n - win, max(1, min(10, n // max(1, win)))).astype(int)
    events = sum(_isolated_clicks(mix_slice(s0, s0 + win), sr) for s0 in starts)
    seconds = len(starts) * win / sr
    out["clicksPerMin"] = round(events / (seconds / 60), 1) if seconds else 0.0

    if stereo:
        ll, rr, lr = sm.ss["left"].sum(), sm.ss["right"].sum(), sm.lr.sum()
        den = np.sqrt(ll * rr)
        out["correlation"] = round(float(lr / den), 3) if den > 0 else 1.0
        k1 = round(1 / SUMMARY_BLOCK)
        num = sm.group(sm.lr, k1)
        d = np.sqrt(sm.group(sm.ss["left"], k1) * sm.group(sm.ss["right"], k1))
        per_sec = np.where(d > 0, num / np.maximum(d, 1e-30), 1.0)
        # A long set is folded to at most 2000 points, keeping each bucket's
        # minimum so a short phase dip survives.
        step = max(1, len(per_sec) // 2000)
        out["correlationSeries"] = [
            round(float(per_sec[i : i + step].min()), 3) for i in range(0, len(per_sec), step)
        ]
        out["identicalChannels"] = sm.identical
    else:
        out["correlation"] = None
        out["identicalChannels"] = True
    return out


def bit_usage(path, declared):
    """Per-bit 'ones' fraction of the integer samples, LSB first.

    Real 24-bit audio sits near 0.5 on every bit; a 16-bit master padded to 24
    leaves the low 8 bits at exactly 0. A dithered 16->24 conversion fills
    them with noise, so the quiet-passage noise floor is the second check:
    16-bit masters bottom out near -96 dBFS, real 24-bit ones well below.
    """
    bits = declared if declared in (16, 20, 24, 32) else 24
    p = run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            path,
            "-map",
            "0:a:0",
            "-t",
            "300",
            "-f",
            "s32le",
            "-acodec",
            "pcm_s32le",
            "-",
        ]
    )
    v = np.frombuffer(p.stdout, dtype=np.int32)
    if not len(v):
        return None
    v = v[:: max(1, len(v) // 4_000_000)]
    shifted = (v >> (32 - bits)).astype(np.int64) & ((1 << bits) - 1)
    ones = [round(float(((shifted >> i) & 1).mean()), 4) for i in range(bits)]
    zero_low = 0
    for o in ones:
        if o != 0:
            break
        zero_low += 1
    return {"bits": bits, "ones": ones, "unusedLowBits": zero_low}


def quiet_floor(x, sr, summary=None):
    """Noise floor in the quietest non-silent 400 ms blocks (5th percentile)."""
    if summary is not None:
        k4 = round(0.4 / SUMMARY_BLOCK)
        ss = summary.group(summary.ss["mix"], k4)
        blk = k4 * summary.bs
    else:
        blk = int(0.4 * sr)
        if len(x) // blk < 4:
            return None
        ss, _ = block_sums(x, blk)
    if len(ss) < 4:
        return None
    rms = np.sqrt(ss / blk)
    rms = rms[rms > 1e-9]  # digital silence says nothing about the master
    if not len(rms):
        return None
    return round(float(20 * np.log10(np.percentile(rms, 5))), 1)


def gonio(left, right, sr, t0, t1, size):
    """Goniometer density: M = (L+R)/2 up, S = (L-R)/2 across, log-scaled."""
    a, b = int(t0 * sr), int(t1 * sr)
    # At most ~400k points, read as contiguous 4096-sample windows spread over
    # the range: a strided read of a long memmap touches every page anyway.
    if b - a <= 400_000:
        L = np.asarray(left[a:b], dtype=np.float64)
        R = np.asarray(right[a:b], dtype=np.float64)
    else:
        w = 4096
        starts = np.linspace(a, b - w, 100).astype(np.int64)
        L = np.concatenate([np.asarray(left[s0 : s0 + w], dtype=np.float64) for s0 in starts])
        R = np.concatenate([np.asarray(right[s0 : s0 + w], dtype=np.float64) for s0 in starts])
    m, sd = (L + R) / 2, (L - R) / 2
    lim = max(1e-6, float(np.abs(np.r_[m, sd]).max()))
    h, _, _ = np.histogram2d(-m / lim, sd / lim, bins=size, range=[[-1, 1], [-1, 1]])
    h = np.log1p(h)
    h = (255 * h / (h.max() or 1)).astype(np.uint8)
    den = np.sqrt((L**2).sum() * (R**2).sum())
    corr = float((L * R).sum() / den) if den > 0 else 1.0
    return h.tobytes(), round(corr, 3)


def scan_one(path):
    meta = ffprobe(path)
    mix, sr = PCM.get(path, "mix")
    side, _ = PCM.get(path, "side")
    left, _ = PCM.get(path, "left")
    right, _ = PCM.get(path, "right")
    sm = summary_for(path)
    a = analyse_pcm(mix, side, sr, summary=sm) or {}
    dyn = dynamics(left, right if meta["channels"] > 1 else left, sr, sm) or {}
    loud = measure_loudness(path)
    return {
        "name": os.path.basename(path),
        "codec": meta["codecName"],
        "sampleRate": sr,
        "bits": meta["bits"],
        "duration": round(len(mix) / sr, 2),
        "bitrate": meta["bitrate"],
        "cutoffHz": a.get("cutoffHz"),
        "level": a.get("level"),
        "family": a.get("family"),
        "shelf16k": a.get("shelf16k"),
        "hfSd": a.get("hfSd"),
        "verdict": a.get("verdict"),
        "dr": dyn.get("dr"),
        "clipEvents": dyn.get("clipEvents"),
        "lufs": loud.get("lufs"),
        "truePeakDb": loud.get("truePeakDb"),
    }


def measure_loudness(path):
    """EBU R128 from ffmpeg on the decoded PCM, true peak from true_peak()."""
    mm, sr = PCM.open(path)
    left, _ = PCM.get(path, "left")
    right, _ = PCM.get(path, "right")
    out = loudness(path, (mm.filename, sr, mm.shape[1]))
    out["truePeakDb"] = true_peak(summary_for(path), left, right, sr)
    return out


def sox_png(path, q):
    ch = q.get("ch", "mix")
    z = min(150, max(60, int(q.get("z", "120"))))
    x = min(4000, max(400, int(q.get("x", "1800"))))
    y = 513 if ch == "all" else 1025
    w = q.get("w", "Kaiser")
    if w not in SOX_WINDOWS:
        w = "Kaiser"
    start, dur = q.get("start"), q.get("dur")
    key = hashlib.sha256(
        json.dumps([path, os.path.getmtime(path), ch, z, x, w, start, dur]).encode()
    ).hexdigest()
    out = os.path.join(CACHE, key + ".png")
    if os.path.exists(out):
        return out
    effects = []
    if start is not None:
        effects += ["trim", f"{max(0.0, float(start)):.3f}", f"{min(60.0, max(0.1, float(dur or 2))):.3f}"]
    if ch == "mix":
        effects += ["remix", "-"]
    elif ch in ("left", "right"):
        effects += ["remix", "1" if ch == "left" else "2"]
    zoom = "" if start is None else f"  zoom {start}s +{dur or 2}s"
    comment = f"{ch}  {w} window  {z} dB{zoom}"
    spec = [
        "spectrogram",
        "-x",
        str(x),
        "-y",
        str(y),
        "-z",
        str(z),
        "-w",
        w,
        "-t",
        os.path.basename(path)[:90],
        "-c",
        comment,
        "-o",
        out + ".tmp",
    ]
    if os.path.splitext(path)[1].lower() in SOX_NATIVE:
        p = run(["sox", path, "-n", *effects, *spec])
    else:
        dec = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-i", path, "-f", "wav", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        p = subprocess.run(
            ["sox", "-t", "wav", "-", "-n", *effects, *spec],
            stdin=dec.stdout,
            capture_output=True,
            timeout=TIMEOUT,
            check=False,
        )
        dec.stdout.close()
        dec.wait(timeout=10)
    if p.returncode != 0 or not os.path.exists(out + ".tmp"):
        raise RuntimeError(p.stderr.decode(errors="replace")[-400:])
    os.replace(out + ".tmp", out)
    return out


# ---------------------------------------------------------------------- index


class LibraryIndex:
    """Every folder and audio file under ROOT, for instant search. Built in a
    background thread and refreshed periodically; a walk of a large library
    on spinning disks takes seconds, which is too slow per keystroke."""

    def __init__(self, interval):
        self.interval = interval
        self.entries = []  # (lower-case rel path, rel path, is_dir)
        self.ready = False
        self.lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="index").start()

    def _loop(self):
        while True:
            try:
                self._build()
            except Exception as e:
                sys.stderr.write(f"index: {e}\n")
            time.sleep(self.interval)

    def _build(self):
        out = []
        first = not self.ready
        for dirpath, dirnames, filenames in os.walk(ROOT):
            if first and len(out) - len(self.entries) > 5000:
                with self.lock:  # first build: publish as we go, search works early
                    self.entries = list(out)
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            rel = os.path.relpath(dirpath, ROOT)
            rel = "" if rel == "." else rel
            for d in dirnames:
                r = os.path.join(rel, d) if rel else d
                out.append((r.lower(), r, True))
            for f in filenames:
                if not f.startswith(".") and os.path.splitext(f)[1].lower() in AUDIO_EXT:
                    r = os.path.join(rel, f) if rel else f
                    out.append((r.lower(), r, False))
        with self.lock:
            self.entries, self.ready = out, True

    def search(self, query, limit):
        terms = [t for t in query.lower().split() if t]
        if not terms:
            return []
        with self.lock:
            entries = self.entries
        hits = []
        for low, rel, is_dir in entries:
            if all(t in low for t in terms):
                # rank: name matches first, folders before files, shorter paths first
                name = low.rsplit("/", 1)[-1]
                score = (0 if all(t in name for t in terms) else 1, 0 if is_dir else 1, len(rel))
                hits.append((score, rel, is_dir))
                if len(hits) > limit * 20:
                    break
        hits.sort()
        return [
            {"path": r, "name": os.path.basename(r), "dir": os.path.dirname(r), "isDir": d}
            for _, r, d in hits[:limit]
        ]


INDEX = LibraryIndex(int(os.environ.get("INDEX_INTERVAL", "900")))


# ----------------------------------------------------------------------- HTTP


def num(q, k, default, lo, hi, cast=float):
    try:
        v = cast(q.get(k, default))
    except (TypeError, ValueError):
        v = cast(default)
    return min(hi, max(lo, v))


class Handler(BaseHTTPRequestHandler):
    server_version = "spectrals"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("ACCESS_LOG"):
            sys.stderr.write(f"{self.address_string()} {fmt % args}\n")

    def send(self, code, body, ctype="application/json", headers=None, compress=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        if compress and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            body = gzip.compress(body, compresslevel=1)
            headers = dict(headers or {}, **{"Content-Encoding": "gzip"})
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            route = {
                "/api/health": self.health,
                "/api/ls": self.ls,
                "/api/roots": self.roots,
                "/api/search": self.search,
                "/api/info": self.info,
                "/api/stats": self.stats,
                "/api/scan": self.scan,
                "/api/gonio": self.gonio,
                "/api/stft": self.stft,
                "/api/wave": self.wave,
                "/api/audio": self.audio,
                "/api/spectrogram": self.png,
            }.get(u.path)
            if route:
                return route(q)
            if u.path.startswith("/api/"):
                return self.send(404, {"error": "not found"})
            return self.static(u.path)
        except PermissionError:
            return self.send(403, {"error": "outside library"})
        except FileNotFoundError:
            return self.send(404, {"error": "no such file"})
        except (ValueError, KeyError) as e:
            return self.send(400, {"error": str(e)})
        except (BrokenPipeError, ConnectionResetError):
            return None
        except Exception as e:
            return self.send(500, {"error": str(e)[-400:]})

    def static(self, path):
        rel = urllib.parse.unquote(path).lstrip("/") or "index.html"
        full = os.path.realpath(os.path.join(WEB, rel))
        if not full.startswith(WEB + os.sep) or not os.path.isfile(full):
            full = os.path.join(WEB, "index.html")  # SPA fallback
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            body = f.read()
        cache = "no-cache" if full.endswith("index.html") else "public, max-age=31536000, immutable"
        return self.send(
            200,
            body,
            ctype,
            {"Cache-Control": cache},
            compress=ctype.startswith(("text/", "application/javascript")),
        )

    def file(self, q):
        full = resolve(q.get("path", ""))
        if not os.path.isfile(full):
            raise FileNotFoundError(q.get("path"))
        return full

    def health(self, q):
        return self.send(200, {"status": "ok", "version": VERSION, "indexed": INDEX.ready})

    def ls(self, q):
        full = resolve(q.get("path", ""))
        if not os.path.isdir(full):
            raise FileNotFoundError(q.get("path"))
        dirs, files = [], []
        with os.scandir(full) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    if e.is_dir():
                        dirs.append({"name": e.name, "mtime": int(e.stat().st_mtime)})
                    elif os.path.splitext(e.name)[1].lower() in AUDIO_EXT:
                        st = e.stat()
                        files.append({"name": e.name, "size": st.st_size, "mtime": int(st.st_mtime)})
                except OSError:
                    continue  # broken symlink, vanished file
        path = "" if full == ROOT else os.path.relpath(full, ROOT)
        key = lambda x: x["name"].lower()
        return self.send(
            200, {"path": path, "dirs": sorted(dirs, key=key), "files": sorted(files, key=key)}, compress=True
        )

    def roots(self, q):
        """Top-level folders of the library (normally one per mounted volume)."""
        out = []
        with os.scandir(ROOT) as it:
            for e in sorted(it, key=lambda e: e.name.lower()):
                if e.name.startswith(".") or not e.is_dir():
                    continue
                try:
                    v = os.statvfs(e.path)
                    out.append(
                        {"name": e.name, "total": v.f_blocks * v.f_frsize, "free": v.f_bavail * v.f_frsize}
                    )
                except OSError:
                    out.append({"name": e.name, "total": None, "free": None})
        return self.send(200, {"roots": out, "indexed": INDEX.ready, "entries": len(INDEX.entries)})

    def search(self, q):
        limit = num(q, "limit", 100, 1, 500, int)
        return self.send(
            200, {"ready": INDEX.ready, "results": INDEX.search(q.get("q", ""), limit)}, compress=True
        )

    def info(self, q):
        full = self.file(q)
        with JOBS:
            meta = ffprobe(full)
            ext = os.path.splitext(full)[1].lower()
            meta["bitDepthUsed"] = sox_bitdepth(full) if ext in {".flac", ".wav", ".aif", ".aiff"} else None
            meta["analysis"] = analyse(full)
            x, sr = PCM.get(full, "mix")
            meta["duration"] = len(x) / sr  # decoded length beats container metadata
        meta["path"] = q.get("path", "")
        return self.send(200, meta, compress=True)

    def stats(self, q):
        full = self.file(q)
        key = (full, os.path.getmtime(full))
        hit = STATS.get(key)
        if hit is None:
            with JOBS:
                left, sr = PCM.get(full, "left")
                right, _ = PCM.get(full, "right")
                side, _ = PCM.get(full, "side")
                mix, _ = PCM.get(full, "mix")
                meta = ffprobe(full)
                per = {}
                stereo = meta["channels"] > 1
                for name, arr in (("left", left), ("right", right), ("side", side)):
                    if not stereo and name != "left":
                        per[name] = per["left"] if name == "right" else None
                        continue
                    live = float(summary_for(full).absmax(name).max(initial=0)) > 1e-6
                    r = analyse_pcm(arr, side, sr, levels=False) if live else None
                    per[name] = r["cutoffHz"] if r else None
                lossless = meta["codecName"] in ("flac", "alac", "wavpack", "ape", "tta") or (
                    meta["codecName"] or ""
                ).startswith("pcm_")
                hit = {
                    "loudness": measure_loudness(full),
                    "dynamics": dynamics(left, right if stereo else left, sr, summary_for(full)),
                    "quietFloorDb": quiet_floor(mix, sr, summary_for(full)),
                    "channelCutoffs": per,
                    "bitUsage": bit_usage(full, meta["bits"]) if lossless else None,
                }
            STATS[key] = hit
            while len(STATS) > 256:
                STATS.pop(next(iter(STATS)))
        return self.send(200, hit, compress=True)

    def scan(self, q):
        """Album scan: one NDJSON line per track, streamed as each finishes."""
        full = resolve(q.get("path", ""))
        if not os.path.isdir(full):
            raise FileNotFoundError(q.get("path"))
        files = sorted(
            (
                e.path
                for e in os.scandir(full)
                if e.is_file()
                and not e.name.startswith(".")
                and os.path.splitext(e.name)[1].lower() in AUDIO_EXT
            ),
            key=str.lower,
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        def chunk(obj):
            data = (json.dumps(obj) + "\n").encode()
            self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
            self.wfile.flush()

        chunk({"total": len(files)})
        for f in files:
            key = (f, os.path.getmtime(f))
            row = SCAN.get(key)
            if row is None:
                try:
                    with JOBS:
                        row = scan_one(f)
                    SCAN[key] = row
                    while len(SCAN) > 2000:
                        SCAN.pop(next(iter(SCAN)))
                except Exception as e:
                    row = {"name": os.path.basename(f), "error": str(e)[-200:]}
            chunk(row)
        self.wfile.write(b"0\r\n\r\n")

    def gonio(self, q):
        full = self.file(q)
        with JOBS:
            left, sr = PCM.get(full, "left")
            right, _ = PCM.get(full, "right")
            dur = len(left) / sr
            t0 = num(q, "t0", 0, 0, dur)
            t1 = num(q, "t1", dur, t0 + 1e-3, dur)
            size = num(q, "size", 160, 32, 512, int)
            body, corr = gonio(left, right, sr, t0, t1, size)
        return self.send(
            200,
            body,
            "application/octet-stream",
            {"X-Meta": json.dumps({"size": size, "correlation": corr})},
            compress=True,
        )

    def stft(self, q):
        full = self.file(q)
        ch = q.get("ch", "mix")
        if ch not in CHANNELS:
            ch = "mix"
        fft = 1 << round(np.log2(num(q, "fft", 4096, 256, 32768, int)))
        win = q.get("win", "blackman-harris")
        scale = "log" if q.get("scale") == "log" else "linear"
        with JOBS:
            x, sr = PCM.get(full, ch)
            dur = len(x) / sr
            t0 = num(q, "t0", 0, 0, dur)
            t1 = num(q, "t1", dur, t0 + 1e-3, dur)
            body, meta = stft_view(
                x,
                sr,
                t0,
                t1,
                num(q, "cols", 1200, 16, 4096, int),
                num(q, "rows", 600, 16, 2048, int),
                num(q, "f0", 0, 0, sr / 2),
                num(q, "f1", sr / 2, 1, sr / 2),
                fft,
                win,
                scale,
            )
        meta["duration"] = dur
        return self.send(
            200,
            body,
            "application/octet-stream",
            {"X-Meta": json.dumps(meta), "Cache-Control": "private, max-age=600"},
            compress=True,
        )

    def wave(self, q):
        full = self.file(q)
        ch = q.get("ch", "mix")
        if ch not in CHANNELS:
            ch = "mix"
        with JOBS:
            x, sr = PCM.get(full, ch)
            dur = len(x) / sr
            t0 = num(q, "t0", 0, 0, dur)
            t1 = num(q, "t1", dur, t0 + 1e-3, dur)
            cols = num(q, "cols", 1200, 16, 8192, int)
            if (t1 - t0) / cols >= 4 * SUMMARY_BLOCK:
                body = summary_peaks(summary_for(full), ch, t0, t1, cols)
            else:
                body = peaks(x, sr, t0, t1, cols)
        return self.send(
            200, body, "application/octet-stream", {"Cache-Control": "private, max-age=600"}, compress=True
        )

    def audio(self, q):
        full = self.file(q)
        if q.get("format") == "flac":
            return self.audio_transcoded(full)
        size = os.path.getsize(full)
        ctype = {
            ".flac": "audio/flac",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
            ".ogg": "audio/ogg",
            ".opus": "audio/ogg",
            ".aif": "audio/aiff",
            ".aiff": "audio/aiff",
        }.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range", "")
        if rng.startswith("bytes="):
            a, _, b = rng[6:].split(",")[0].partition("-")
            if a:
                start, end = int(a), int(b) if b else size - 1
            elif b:
                start = max(0, size - int(b))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return None
        with open(full, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                buf = f.read(min(1 << 20, left))
                if not buf:
                    break
                self.wfile.write(buf)
                left -= len(buf)
        return None

    def audio_transcoded(self, full):
        """WavPack, APE, DSD, ALAC-in-Chrome...: decode to FLAC on the fly so the
        browser can play what it cannot open. Not seekable before it is buffered."""
        self.send_response(200)
        self.send_header("Content-Type", "audio/flac")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        proc = subprocess.Popen(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                full,
                "-map",
                "0:a:0",
                "-c:a",
                "flac",
                "-compression_level",
                "0",
                "-f",
                "flac",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            while True:
                buf = proc.stdout.read(1 << 16)
                if not buf:
                    break
                self.wfile.write(b"%x\r\n%s\r\n" % (len(buf), buf))
            self.wfile.write(b"0\r\n\r\n")
        finally:
            proc.kill()
            proc.wait()

    def png(self, q):
        full = self.file(q)
        with JOBS:
            out = sox_png(full, q)
        with open(out, "rb") as f:
            data = f.read()
        name = os.path.splitext(os.path.basename(full))[0] + (".zoom" if q.get("start") else "") + ".png"
        return self.send(
            200,
            data,
            "image/png",
            {
                "Cache-Control": "private, max-age=3600",
                "Content-Disposition": "inline; filename*=UTF-8''" + urllib.parse.quote(name),
            },
        )


def main():
    os.makedirs(CACHE, exist_ok=True)
    INDEX.start()
    # 0.0.0.0 inside the container only; compose publishes it on loopback.
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)  # noqa: S104
    srv.daemon_threads = True
    print(f"simpleaudiospectral on :{PORT}, library {ROOT}, ui {WEB}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
