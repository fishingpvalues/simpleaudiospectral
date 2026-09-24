"""What the viewer draws, for the visible range at the display size."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import numpy as np

from ... import config, library, pcm, views
from ...analysis import jobs
from .params import channel, num, time_range

if TYPE_CHECKING:
    from ..handler import Handler, Query

BINARY = "application/octet-stream"
CACHEABLE = {"Cache-Control": "private, max-age=600"}


def stft(h: Handler, q: Query) -> None:
    """uint8 dB matrix, rows x cols with row 0 the highest frequency; metadata in X-Meta."""
    full = library.resolve_file(q.get("path"))
    fft = 1 << round(np.log2(num(q, "fft", 4096, 256, 32768, int)))
    scale = "log" if q.get("scale") == "log" else "linear"
    with config.JOBS:
        x, sr = pcm.PCM.get(full, channel(q))
        dur = len(x) / sr
        t0, t1 = time_range(q, dur)
        body, meta = views.stft_view(
            x,
            sr,
            t0,
            t1,
            num(q, "cols", 1200, 16, 4096, int),
            num(q, "rows", 600, 16, 2048, int),
            num(q, "f0", 0, 0, sr / 2),
            num(q, "f1", sr / 2, 1, sr / 2),
            fft,
            q.get("win", "blackman-harris"),
            scale,
        )
    meta["duration"] = dur
    h.send(200, body, BINARY, {"X-Meta": json.dumps(meta), **CACHEABLE}, compress=True)


def wave(h: Handler, q: Query) -> None:
    """Min and max per column as float32 [min0, max0, ...]."""
    full = library.resolve_file(q.get("path"))
    ch = channel(q)
    with config.JOBS:
        x, sr = pcm.PCM.get(full, ch)
        t0, t1 = time_range(q, len(x) / sr)
        cols = num(q, "cols", 1200, 16, 8192, int)
        index = (jobs.cached(full) or {}).get("index", {}).get(ch)
        body = views.waveform(x, sr, t0, t1, cols, index)
    h.send(200, body, BINARY, CACHEABLE, compress=True)


def gonio(h: Handler, q: Query) -> None:
    """Goniometer density, uint8 size x size; correlation in X-Meta."""
    full = library.resolve_file(q.get("path"))
    with config.JOBS:
        left, sr = pcm.PCM.get(full, "left")
        right, _ = pcm.PCM.get(full, "right")
        dur = len(left) / sr
        t0, t1 = time_range(q, dur)
        size = num(q, "size", 160, 32, 512, int)
        whole = (jobs.cached(full) or {}).get("gonio")
        if whole is not None and size == 160 and t0 == 0 and t1 >= dur - 1e-6:
            body, corr = views.goniometer_image(*whole)
        else:
            body, corr = views.goniometer(left, right, sr, t0, t1, size)
    h.send(200, body, BINARY, {"X-Meta": json.dumps({"size": size, "correlation": corr})}, compress=True)
