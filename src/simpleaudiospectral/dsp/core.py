"""Chunking, the worker pool and memory limits shared by every measurement."""

import math
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np

CHUNK = 1 << 22  # target samples per chunk (~16 MB of float32 per channel)


def available_cpus() -> int:
    """CPUs this process may really use: the affinity mask, capped by a cgroup
    v2 CPU quota (docker --cpus). os.cpu_count() reports the host's cores, so
    a container limited to 3 CPUs on a 12-core host would start 8 workers and
    spend the quota on throttled context switches."""
    n = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            quota, period = f.read().split()[:2]
        if quota != "max":
            n = min(n, max(1, math.ceil(int(quota) / int(period))))
    except (OSError, ValueError):
        pass
    return max(1, n)


THREADS = max(1, min(8, available_cpus()))
SPILL_DIR = tempfile.gettempdir()  # the app points this at the PCM volume
SPILL_RAM_BYTES = 256 * 1024 * 1024  # below this the per-bin matrix stays in RAM
STFT_GROUP_BYTES = 32 * 1024 * 1024  # full-resolution columns held at once in the viewer
POOL = ThreadPoolExecutor(THREADS, thread_name_prefix="dsp")


def f64(a):
    return np.asarray(a, dtype=np.float64)


def chunk_len(multiple, target=None):
    target = target or CHUNK
    return max(multiple, (target // multiple) * multiple)


def n_frames(length, n, hop):
    """Frames x[k*hop : k*hop + n] for k = 0 .. n_frames-1 (full frames only)."""
    return 0 if length < n else 1 + (length - n) // hop


def feed_all(x, *consumers, chunk=None):
    """Feed x to consumers in consecutive chunks, then finish them."""
    step = chunk or CHUNK
    for a in range(0, len(x), step):
        seg = np.asarray(x[a : a + step], dtype=np.float32)
        for c in consumers:
            c.feed(seg, a)
    return [c.finish() for c in consumers]


def spec_power(frames, win):
    s = np.fft.rfft(frames * win, axis=1)
    return s.real**2 + s.imag**2


def parallel_rows(frames, fn):
    """fn over row blocks of frames on the worker pool; results in order."""
    per = max(1, (4 * 1024 * 1024) // max(1, frames.shape[1]))
    return list(POOL.map(fn, [frames[i : i + per] for i in range(0, len(frames), per)]))
