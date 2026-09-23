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
import math
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

import dsp

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
            dsp.SPILL_DIR = self.dir  # large per-bin matrices spill next to the PCM
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

    Each column is the mean power of EVERY FFT frame (hop fft/2) centred in
    its time slot (dsp.stft_columns). Each row is the MAX over the FFT bins
    it covers, so a thin lowpass edge or a single tone is never pooled away
    at a small display height.
    """
    w = window(win, fft).astype(np.float64)
    norm = (w.sum() / 2) ** 2  # a full-scale sine reads 0 dBFS
    nb = fft // 2 + 1
    bin_hz = sr / fft
    nyq = sr / 2
    f1 = min(f1, nyq)
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
        "framesPerCol": "all",
    }
    return img.tobytes(), meta


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


def whole_levels(x, side, sr):
    """Exact totals when no Summary exists: mean square of x and side over the
    whole file, and 0.5 s block energies of x for the loudest window."""
    ssx, sss = [], []
    for c0 in range(0, len(x), dsp.CHUNK):
        ssx.append(float((dsp.f64(x[c0 : c0 + dsp.CHUNK]) ** 2).sum()))
        sss.append(float((dsp.f64(side[c0 : c0 + dsp.CHUNK]) ** 2).sum()))
    b05, _ = block_sums(x, int(sr * 0.5))
    return math.fsum(ssx) / max(1, len(x)), math.fsum(sss) / max(1, len(x)), b05


SPEC_N = 8192  # lowpass analysis frame (hop SPEC_N/2)
HF_N = 2048  # sfb21 frame: under two MP3 granules (hop HF_N/2)


def lowpass(p90_raw, med_raw, sr, n=SPEC_N):
    """Cut-off, drop, 16 kHz shelf, hi-res and extent from the exact per-bin
    90th percentile and median of the dB spectrum."""
    freqs = np.fft.rfftfreq(n, 1 / sr)
    bin_hz = freqs[1]
    nyq = sr / 2
    k = max(1, int(100 / bin_hz))
    kern = np.ones(k) / k
    p90 = np.convolve(p90_raw, kern, mode="same")
    med = np.convolve(med_raw, kern, mode="same") if med_raw is not None else None
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
    sdrop, shelf16 = 0.0, False
    if med is not None:
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

    # CRT / TV line whine (15.625 kHz PAL, 15.734 kHz NTSC): a narrow tone that
    # reads like an artifact on a spectral and is not one.
    crt = None
    for tone in (15625, 15734):
        t = round(tone / bin_hz)
        if t + 40 < len(p90_raw):
            around = np.median(np.r_[p90_raw[t - 40 : t - 4], p90_raw[t + 4 : t + 40]])
            if p90_raw[t - 2 : t + 3].max() - around > 15:
                crt = tone
    return {
        "freqs": freqs,
        "k": k,
        "p90": p90,
        "med": med,
        "ref": ref,
        "cutoff_hz": cutoff_hz,
        "drop": drop,
        "sdrop": sdrop,
        "shelf16": shelf16,
        "hires_db": hires_db,
        "extent_hz": extent_hz,
        "crt": crt,
        "nyq": nyq,
    }


def hf_band_top(cutoff_hz, nyq):
    """Upper edge of the sfb21 band, or None when there is no band to measure."""
    top_hz = min(cutoff_hz or nyq, 19000) - 300
    return top_hz if top_hz > 16800 else None


def analysis_result(lp, sr, n_samples, hf_sd, side_db, b05, used):
    """The analysis dict from exact measurements (see analyse_pcm)."""
    cutoff_hz, drop, nyq = lp["cutoff_hz"], lp["drop"], lp["nyq"]
    if hf_sd is not None:
        hf_sd = round(hf_sd, 1)

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

    # Loudest 8 s: where a zoomed spectral is most informative.
    win_s = min(8.0, n_samples / sr)
    loudest = 0.0
    if len(b05) > 2:
        w = max(1, int(win_s * 2))
        c = np.convolve(b05, np.ones(w), mode="valid")
        loudest = float(np.argmax(c) * 0.5)

    family = codec_family(cutoff_hz, hf_sd, drop)
    verdict, level = verdict_for(
        cutoff_hz, drop, lp["extent_hz"], nyq, sr, lp["hires_db"], family, resampled_from
    )
    freqs, k = lp["freqs"], lp["k"]
    step = max(1, int(25 / freqs[1]))
    keep = slice(0, len(freqs) - k, step)  # "same" convolution smears the last k bins
    return {
        "cutoffHz": cutoff_hz,
        "dropDb": round(drop, 1),
        "extentHz": round(lp["extent_hz"]),
        "nyquistHz": nyq,
        "shelf16k": bool(lp["shelf16"]),
        "shelfDropDb": round(lp["sdrop"], 1),
        "hiresDb": lp["hires_db"],
        "sideDb": round(side_db, 1) if side_db is not None else None,
        "hfSd": hf_sd,
        "family": family,
        "resampledFrom": resampled_from,
        "crtTone": lp["crt"],
        "loudestAt": loudest,
        "verdict": verdict,
        "level": level,
        "refDb": round(lp["ref"], 1),
        "framesAnalysed": used,
        "curve": {
            "hz": [round(float(f)) for f in freqs[keep]],
            "db": [round(float(v), 1) for v in lp["p90"][keep]],
            "median": [round(float(v), 1) for v in lp["med"][keep]] if lp["med"] is not None else [],
        },
    }


def analyse_pcm(x, side, sr, summary=None, levels=True):
    """Lowpass, codec and level analysis of the WHOLE signal.

    Every loud 8192-sample frame (hop 4096) enters the per-bin 90th percentile
    (the lowpass) and median (the 16 kHz shelf); every loud 2048-sample frame
    (hop 1024) enters the sfb21 variability. See dsp.py for the definitions.
    The file analysis (run_analysis) computes the same quantities in shared
    sequential passes; this is the direct form used for arrays and tests.
    """
    if len(x) < SPEC_N * 4:
        return None
    (med_raw, p90_raw), used = dsp.spectrum_percentiles(x, sr, n=SPEC_N, hop=SPEC_N // 2, qs=(50, 90))
    lp = lowpass(p90_raw, med_raw, sr)
    side_db, b05 = None, np.zeros(0)
    if summary is not None:
        ms_x = summary.total_ss["mix"] / max(1, summary.n)
        ms_s = summary.total_ss["side"] / max(1, summary.n)
        b05 = summary.ss["b05"]["mix"]
        side_db = 20 * np.log10((math.sqrt(ms_s) + 1e-12) / (math.sqrt(ms_x) + 1e-12))
    elif levels:
        ms_x, ms_s, b05 = whole_levels(x, side, sr)
        side_db = 20 * np.log10((math.sqrt(ms_s) + 1e-12) / (math.sqrt(ms_x) + 1e-12))
    hf_sd = None
    top_hz = hf_band_top(lp["cutoff_hz"], lp["nyq"])
    if top_hz:
        hf_sd = dsp.band_ratio_std(x, sr, (12000, 15800), (16200, top_hz), n=HF_N, hop=HF_N // 2)
    return analysis_result(lp, sr, len(x), hf_sd, side_db, b05, used)


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
            "ebur128=peak=true:framelog=verbose,astats=measure_perchannel=none:measure_overall="
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


SUMMARIES = collections.OrderedDict()
SUMMARY_LOCK = threading.Lock()


def summary_for(path):
    key = (path, os.path.getmtime(path))
    with SUMMARY_LOCK:
        if key in SUMMARIES:
            SUMMARIES.move_to_end(key)
            return SUMMARIES[key]
    mm, sr = PCM.open(path)
    left, _ = PCM.get(path, "left")
    right, _ = PCM.get(path, "right")
    sm = dsp.summarize(left, right if mm.shape[1] > 1 else left, sr)
    with SUMMARY_LOCK:
        SUMMARIES[key] = sm
        while len(SUMMARIES) > 16:
            SUMMARIES.popitem(last=False)
    return sm


def dynamics(left, right, sr, summary=None, mix=None, welch=None, clicks=None, flat=None):
    """DR meter (TT/foobar 'DR14' algorithm) and stereo statistics over the
    whole file.

    DR per channel: every full 3 s block; block RMS = sqrt(2 * mean(x^2));
    block peak = max |x|. DR = 20*log10(2nd-highest block peak / sqrt(mean of
    the loudest 20% of block RMS^2)); the reported value is the channel mean,
    rounded.
    """
    sm = summary or dsp.summarize(left, right, sr)
    stereo = sm.stereo
    if mix is None and (welch is None or clicks is None):
        mix = Derived(np.stack([np.asarray(left), np.asarray(right)], axis=1), "mix") if stereo else left
    B = sm.sizes["b3"]
    nb = len(sm.ss["b3"]["left"])
    if nb < 1:
        return None
    out = {}
    drs = []
    for ch in ("left", "right") if stereo else ("left",):
        rms = np.sqrt(2 * sm.ss["b3"][ch] / B)
        pks = np.sort(sm.pk["b3"][ch])
        pk2 = pks[-2] if nb >= 2 else pks[-1]
        top = np.sort(rms)[-max(1, round(nb * 0.2)) :]
        r = np.sqrt(np.mean(top**2))
        drs.append(20 * np.log10(pk2 / r) if r > 0 and pk2 > 0 else 0.0)
    out["dr"] = round(float(np.mean(drs)))
    out["drPerChannel"] = [round(float(d), 1) for d in drs]

    # Clipping: runs of >= 3 consecutive samples at digital full scale, and
    # "flat tops": the same runs at the file's own peak when that peak is
    # below full scale (clipped, then normalised down). Runs are counted across
    # chunk boundaries, so the counts are exact.
    flat_n, flat_times = 0, []
    if flat is not None:
        flat_n, flat_times = flat
    elif 0 < sm.peak < 0.99997:
        for x in (left, right) if stereo else (left,):
            c, t = dsp.count_runs(x, sm.peak, sr, exact_equal=True)
            flat_n += c
            flat_times += t
    times = sorted(sm.clip_times + flat_times)
    out["clipEvents"] = sm.clip_runs
    out["flatTopEvents"] = flat_n
    out["clipTimesTotal"] = len(times)
    out["clipTimes"] = [round(t, 3) for t in times[:500]]  # list for the UI; counts above are complete

    # Vinyl / analogue-chain hints over the whole file.
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

    if stereo:
        den = math.sqrt(sm.total_ss["left"] * sm.total_ss["right"])
        out["correlation"] = round(sm.total_lr / den, 3) if den > 0 else 1.0
        # Every full second of the track; nothing folded.
        d = np.sqrt(sm.ss["b1"]["left"] * sm.ss["b1"]["right"])
        per_sec = np.where(d > 0, sm.lr["b1"] / np.maximum(d, 1e-300), 1.0)
        out["correlationSeries"] = [round(float(v), 3) for v in per_sec]
        out["identicalChannels"] = sm.identical
    else:
        out["correlation"] = None
        out["identicalChannels"] = True
    return out


def bit_usage(path, declared):
    """Per-bit 'ones' fraction over EVERY integer sample of the file, LSB first.

    Real 24-bit audio sits near 0.5 on every bit; a 16-bit master padded to 24
    leaves the low 8 bits at exactly 0. A dithered 16->24 conversion fills
    them with noise, so the quiet-passage noise floor is the second check.
    """
    bits = declared if declared in (16, 20, 24, 32) else 24
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0:a:0", "-f", "s32le", "-acodec", "pcm_s32le", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    ones = np.zeros(bits, dtype=np.int64)
    total = 0
    rest = b""
    try:
        while True:
            buf = proc.stdout.read(1 << 24)
            if not buf:
                break
            buf = rest + buf
            cut_at = len(buf) - len(buf) % 4
            rest = buf[cut_at:]
            v = np.frombuffer(buf[:cut_at], dtype=np.int32)
            u = (v >> (32 - bits)).astype(np.int64) & ((1 << bits) - 1)
            for i in range(bits):
                ones[i] += int(np.count_nonzero((u >> i) & 1))
            total += len(v)
    finally:
        proc.stdout.close()
        proc.wait(timeout=TIMEOUT)
    if not total:
        return None
    zero_low = 0
    for o in ones:
        if o:
            break
        zero_low += 1
    return {
        "bits": bits,
        "ones": [round(int(o) / total, 6) for o in ones],
        "unusedLowBits": zero_low,
        "samples": total,
    }


def quiet_floor(x, sr, summary=None):
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


def gonio(left, right, sr, t0, t1, size):
    """Goniometer density over every sample of the range (dsp.goniometer)."""
    a, b = int(t0 * sr), int(min(len(left), t1 * sr))
    h, corr = dsp.goniometer(left, right, a, b, size)
    h = np.log1p(h)
    h = (255 * h / (h.max() or 1)).astype(np.uint8)
    return h.tobytes(), round(corr, 3)


def scan_one(path):
    res = run_analysis(path)
    meta, a, st = res["meta"], res["analysis"] or {}, res["stats"]
    dyn, loud = st["dynamics"] or {}, st["loudness"] or {}
    return {
        "name": os.path.basename(path),
        "codec": meta["codecName"],
        "sampleRate": meta["sampleRate"],
        "bits": meta["bits"],
        "duration": round(meta["duration"], 2),
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


# ------------------------------------------------------------------ pipeline

WAVE_BLOCK = 4096
ANALYSES = collections.OrderedDict()
ANALYSIS_LOCK = threading.Lock()
ANALYSIS_RUNNING = {}


def _read_rows(mm, a, b):
    """Rows [a, b) of the decoded PCM with a plain buffered read: sequential
    reads of a file larger than the page cache are several times faster than
    faulting a memmap in 4 KB pages."""
    nch = mm.shape[1]
    return np.fromfile(mm.filename, dtype=np.float32, count=(b - a) * nch, offset=a * nch * 4).reshape(
        -1, nch
    )


def _signals32(L32, R32, stereo):
    if not stereo:
        return {"mix": L32, "left": L32}
    return {
        "mix": (L32 + R32) * np.float32(0.5),
        "left": L32,
        "right": R32,
        "side": (L32 - R32) * np.float32(0.5),
    }


def _persist_path(mm):
    return os.path.splitext(mm.filename)[0] + f".analysis-{VERSION}.json"


PROGRESS = {}  # key -> {"stage": str, "done": 0..1}


def _progress(key, stage, done):
    PROGRESS[key] = {"stage": stage, "done": round(float(done), 3)}


def start_analysis(path):
    """Start the analysis in the background if needed. Returns the result
    when it is ready, else None (see PROGRESS for how far it is)."""
    key = (path, os.path.getmtime(path))
    with ANALYSIS_LOCK:
        if key in ANALYSES:
            ANALYSES.move_to_end(key)
            return ANALYSES[key]
        if key in ANALYSIS_RUNNING:
            return None
    t = threading.Thread(target=lambda: _safe_run(path), daemon=True, name="analysis")
    t.start()
    time.sleep(0.05)  # a persisted result is usually back before the first poll
    with ANALYSIS_LOCK:
        return ANALYSES.get(key)


ANALYSIS_ERRORS = {}


def _safe_run(path):
    key = (path, os.path.getmtime(path))
    try:
        run_analysis(path)
        ANALYSIS_ERRORS.pop(key, None)
    except Exception as e:  # reported to the client on the next poll
        ANALYSIS_ERRORS[key] = str(e)[-300:]


def run_analysis(path):
    """Everything the UI shows about a file, from three sequential passes over
    the decoded PCM, each exact over the whole file (see dsp.py):

    A: block statistics, frame loudness of every signal, waveform index
    B: per-bin percentile spectra (mix, and left/right/side for the
       per-channel cut-off), Welch spectrum, clicks, flat tops, goniometer
    C: sfb21 variability, whose band depends on the cut-off found in B

    ffmpeg's EBU R128 / true-peak pass and the bit-usage count run
    concurrently. The result is cached in memory and persisted next to the
    PCM, so a file is analysed once per app version.
    """
    key = (path, os.path.getmtime(path))
    with ANALYSIS_LOCK:
        if key in ANALYSES:
            ANALYSES.move_to_end(key)
            return ANALYSES[key]
        ev = ANALYSIS_RUNNING.get(key)
        owner = ev is None
        if owner:
            ev = ANALYSIS_RUNNING[key] = threading.Event()
    if not owner:
        ev.wait(TIMEOUT * 20)
        with ANALYSIS_LOCK:
            if key in ANALYSES:
                return ANALYSES[key]
        raise RuntimeError("analysis failed")
    try:
        res = _load_or_run(path)
        with ANALYSIS_LOCK:
            ANALYSES[key] = res
            while len(ANALYSES) > 16:
                ANALYSES.popitem(last=False)
        return res
    finally:
        with ANALYSIS_LOCK:
            ANALYSIS_RUNNING.pop(key, None)
        ev.set()


def _load_or_run(path):
    _progress((path, os.path.getmtime(path)), "decoding", 0)
    mm, sr = PCM.open(path)
    fn = _persist_path(mm)
    npz = fn[:-5] + ".npz"
    if os.path.exists(fn) and os.path.exists(npz):
        try:
            with open(fn) as f:
                res = json.load(f)
            with np.load(npz) as z:
                res["index"] = {k[3:]: (z[k], z["mx_" + k[3:]]) for k in z.files if k.startswith("mn_")}
                res["gonio"] = (z["gonio"], res["goniometerCorrelation"]) if "gonio" in z.files else None
            return res
        except (OSError, ValueError, KeyError):
            pass
    res = _run(path, mm, sr, key=(path, os.path.getmtime(path)))
    body = {k: v for k, v in res.items() if k not in ("index", "gonio")}
    body["goniometerCorrelation"] = res["gonio"][1] if res["gonio"] else None
    tmp = fn + ".tmp"
    with open(tmp, "w") as f:
        json.dump(body, f)
    arrays = {f"mn_{k}": v[0] for k, v in res["index"].items()}
    arrays.update({f"mx_{k}": v[1] for k, v in res["index"].items()})
    if res["gonio"]:
        arrays["gonio"] = res["gonio"][0]
    np.savez(npz[:-4] + ".tmp.npz", **arrays)
    os.replace(npz[:-4] + ".tmp.npz", npz)
    os.replace(tmp, fn)
    return res


def _run(path, mm, sr, key=None):
    def prog(stage, done):
        if key is not None:
            _progress(key, stage, done)

    meta = ffprobe(path)
    n, stereo = mm.shape[0], mm.shape[1] > 1
    ext = os.path.splitext(path)[1].lower()
    lossless = meta["codecName"] in ("flac", "alac", "wavpack", "ape", "tta") or (
        meta["codecName"] or ""
    ).startswith("pcm_")
    side_jobs = {
        "loudness": lambda: loudness(path, (mm.filename, sr, mm.shape[1])),
        "bits": (lambda: bit_usage(path, meta["bits"])) if lossless else (lambda: None),
        "soxbits": (lambda: sox_bitdepth(path))
        if ext in {".flac", ".wav", ".aif", ".aiff"}
        else (lambda: None),
    }
    side_out = {}
    threads = [
        threading.Thread(target=lambda k=k, f=f: side_out.__setitem__(k, f()), daemon=True)
        for k, f in side_jobs.items()
    ]
    for t in threads:
        t.start()

    names = ("mix", "left", "right", "side") if stereo else ("mix",)
    sm = dsp.Summary(sr, n, stereo)
    rms = {s: dsp.FrameRMS(SPEC_N, SPEC_N // 2) for s in names}
    rms_hf = dsp.FrameRMS(HF_N, HF_N // 2)
    ext_idx = {
        s: dsp.BlockExtremes(WAVE_BLOCK)
        for s in ("mix", "left", "right", "side")
        if stereo or s in ("mix", "left")
    }

    # pass A
    for a in range(0, n, sm.chunk):
        prog("levels and blocks", a / max(1, n))
        rows = _read_rows(mm, a, min(n, a + sm.chunk))
        L32 = rows[:, 0]
        R32 = rows[:, 1] if stereo else L32
        sm.feed_pair(L32, R32, a)
        sig = _signals32(L32, R32, stereo)
        for s in names:
            rms[s].feed(sig[s], a)
        rms_hf.feed(sig["mix"], a)
        for s, e in ext_idx.items():
            e.feed(sig[s], a)
    sm.finish()
    keeps = {s: dsp.loud_mask(rms[s].finish()) for s in names}

    # pass B
    spec = {"mix": dsp.SpectrumPercentiles(SPEC_N, SPEC_N // 2, keeps["mix"], (50, 90))}
    for s in names[1:]:
        if float(sm.pk["b3"][s].max(initial=0)) > 1e-6:
            spec[s] = dsp.SpectrumPercentiles(SPEC_N, SPEC_N // 2, keeps[s], (90,))
    welch = dsp.WelchMean(1 << 16, 1 << 15)
    clicks = dsp.IsolatedClicks(sr)
    flat = None
    if 0 < sm.peak < 0.99997:
        flat = [dsp.LevelRuns(sr, sm.peak, True) for _ in range(2 if stereo else 1)]
    gonio = dsp.Goniometer(160, sm.ms_lim) if stereo else None
    for a in range(0, n, dsp.CHUNK):
        prog("spectra of every frame", a / max(1, n))
        rows = _read_rows(mm, a, min(n, a + dsp.CHUNK))
        L32 = rows[:, 0]
        R32 = rows[:, 1] if stereo else L32
        sig = _signals32(L32, R32, stereo)
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
    prog("sorting per-bin percentiles", 0)
    pct = {s: c.finish() for s, c in spec.items()}
    (med_raw, p90_raw), used = pct["mix"]
    lp = lowpass(p90_raw, med_raw, sr)

    # pass C
    hf_sd = None
    top_hz = hf_band_top(lp["cutoff_hz"], lp["nyq"])
    if top_hz and n >= SPEC_N * 4:
        hf = dsp.BandRatioStd(
            sr, HF_N, HF_N // 2, dsp.loud_mask(rms_hf.finish()), (12000, 15800), (16200, top_hz)
        )
        for a in range(0, n, dsp.CHUNK):
            prog("sfb21 variability", a / max(1, n))
            rows = _read_rows(mm, a, min(n, a + dsp.CHUNK))
            L32 = rows[:, 0]
            hf.feed(_signals32(L32, rows[:, 1] if stereo else L32, stereo)["mix"], a)
        hf_sd = hf.finish()

    ms_x = sm.total_ss["mix"] / max(1, n)
    ms_s = sm.total_ss["side"] / max(1, n)
    side_db = 20 * np.log10((math.sqrt(ms_s) + 1e-12) / (math.sqrt(ms_x) + 1e-12))
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
    flat_res = None
    if flat:
        cs = [f.finish() for f in flat]
        flat_res = (sum(c for c, _ in cs), sorted(t for _, ts in cs for t in ts))
    left = mm[:, 0]
    right = mm[:, 1] if stereo else left
    dyn = dynamics(left, right, sr, sm, welch=welch.finish(), clicks=clicks.finish(), flat=flat_res)
    prog("loudness and true peak (ffmpeg)", 1)
    for t in threads:
        t.join(TIMEOUT * 20)
    meta["bitDepthUsed"] = side_out.get("soxbits")
    meta["duration"] = n / sr
    stats = {
        "loudness": side_out.get("loudness") or {},
        "dynamics": dyn,
        "quietFloorDb": quiet_floor(None, sr, sm),
        "channelCutoffs": per,
        "bitUsage": side_out.get("bits"),
    }
    index = {s: e.finish() for s, e in ext_idx.items()}
    return {
        "meta": meta,
        "analysis": analysis,
        "stats": stats,
        "index": index,
        "gonio": gonio.finish() if gonio else None,
    }


def measure_loudness(path):
    """EBU R128 integrated loudness, LRA and true peak (4x oversampled, over
    the whole file) from ffmpeg's ebur128 reference filter, read from the
    decoded PCM rather than decoding the source again."""
    mm, sr = PCM.open(path)
    return loudness(path, (mm.filename, sr, mm.shape[1]))


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

    def pending(self, full):
        key = (full, os.path.getmtime(full))
        if key in ANALYSIS_ERRORS:
            return self.send(500, {"error": "analysis failed: " + ANALYSIS_ERRORS.pop(key)})
        return self.send(
            202,
            dict(PROGRESS.get(key, {"stage": "queued", "done": 0}), pending=True),
            {"Retry-After": "1", "Cache-Control": "no-store"},
        )

    def info(self, q):
        full = self.file(q)
        res = start_analysis(full)
        if res is None:
            return self.pending(full)
        out = dict(res["meta"], analysis=res["analysis"], path=q.get("path", ""))
        return self.send(200, out, compress=True)

    def stats(self, q):
        full = self.file(q)
        res = start_analysis(full)
        if res is None:
            return self.pending(full)
        return self.send(200, res["stats"], compress=True)

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
            cached = ANALYSES.get((full, os.path.getmtime(full)))
            if cached and cached.get("gonio") is not None and size == 160 and t0 == 0 and t1 >= dur - 1e-6:
                h, corr = cached["gonio"]
                h = np.log1p(h)
                body, corr = (255 * h / (h.max() or 1)).astype(np.uint8).tobytes(), round(corr, 3)
            else:
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
            cached = ANALYSES.get((full, os.path.getmtime(full)))
            idx = (cached or {}).get("index", {}).get(ch)
            span = (t1 - t0) * sr / cols
            if idx is not None and span >= 4 * WAVE_BLOCK:
                a0 = int(max(0, t0 * sr))
                b0 = int(min(len(x), max(a0 + 1, t1 * sr)))
                body = dsp.column_extremes(x, a0, b0, cols, idx, WAVE_BLOCK).tobytes()
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
