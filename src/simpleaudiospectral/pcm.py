"""Decoded audio: one decode per file, streamed to disk and memory-mapped.

A three-hour DJ set is 1.9 GB of float32 per channel. Holding that in the
heap OOM-kills a small container; a memmap's page cache is reclaimable, so
memory stays bounded whatever the length of the file.
"""

import collections
import contextlib
import hashlib
import os
import threading
import time

import numpy as np

from . import config, dsp, tools


class Derived:
    """Mix or side of a stereo memmap, computed per slice so the whole track
    is never materialised. Supports what the DSP uses: len, slicing and take."""

    def __init__(self, mm: np.ndarray, kind: str) -> None:
        self.mm, self.kind = mm, kind
        self.shape = (mm.shape[0],)
        self.dtype = np.dtype(np.float32)

    def __len__(self) -> int:
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


def filename(mm: np.memmap) -> str:
    """The file behind a memmap that PcmCache opened (always file-backed)."""
    if mm.filename is None:
        raise RuntimeError("memmap is not file-backed")
    return mm.filename


def read_rows(mm: np.memmap, a: int, b: int) -> np.ndarray:
    """Rows [a, b) of the decoded PCM with a plain buffered read: sequential
    reads of a file larger than the page cache are several times faster than
    faulting a memmap in 4 KB pages."""
    nch = mm.shape[1]
    return np.fromfile(filename(mm), dtype=np.float32, count=(b - a) * nch, offset=a * nch * 4).reshape(
        -1, nch
    )


def _writable_dir() -> str:
    for d in (config.PCM_DIR, os.path.join(config.CACHE, "pcm")):
        try:
            os.makedirs(d, exist_ok=True)
            if os.access(d, os.W_OK):
                return d
        except OSError:
            continue
    raise RuntimeError("no writable PCM_DIR")


class PcmCache:
    """Memory maps of decoded files, keyed by path and mtime. Concurrent
    requests for the same file wait for one decode instead of starting their own."""

    def __init__(self) -> None:
        self.maps: collections.OrderedDict = collections.OrderedDict()
        self.lock = threading.Lock()
        self.decoding: dict = {}
        self.progress: dict = {}  # key -> fraction of a running decode
        self.dir: str | None = None

    def get(self, path: str, ch: str):
        """One channel ("left", "right", "mix" or "side") and the sample rate."""
        mm, sr = self.open(path)
        if ch == "left":
            return mm[:, 0], sr
        if ch == "right":
            return (mm[:, 1] if mm.shape[1] > 1 else mm[:, 0]), sr
        return Derived(mm, "side" if ch == "side" else "mix"), sr

    def open(self, path: str, on_progress: tools.OnProgress | None = None) -> tuple[np.memmap, int]:
        """The decoded file and its sample rate, decoding it on first use.
        on_progress(f) follows the decode, also when another request started it."""
        key = (path, os.path.getmtime(path))
        with self.lock:
            if key in self.maps:
                self.maps.move_to_end(key)
                return self.maps[key]
            ev = self.decoding.get(key)
            owner = ev is None
            if owner:
                ev = self.decoding[key] = threading.Event()
                self.progress[key] = 0.0
        if not owner:
            deadline = time.monotonic() + config.TIMEOUT * 10
            while not ev.wait(0.25) and time.monotonic() < deadline:
                if on_progress:
                    on_progress(self.progress.get(key, 0.0))
            with self.lock:
                if key in self.maps:
                    return self.maps[key]
            raise RuntimeError("decode failed")

        def report(f: float) -> None:
            self.progress[key] = f
            if on_progress:
                on_progress(f)

        try:
            val = self._decode(path, key, report)
            with self.lock:
                self.maps[key] = val
                while len(self.maps) > 32:
                    self.maps.popitem(last=False)
            return val
        finally:
            with self.lock:
                self.decoding.pop(key, None)
                self.progress.pop(key, None)
            ev.set()

    def file_for(self, path: str) -> str:
        """Where the decode of `path` lives (or will live), without decoding:
        derived results stored next to it are found even after the PCM itself
        was evicted."""
        key = (path, os.path.getmtime(path))
        with self.lock:
            if key in self.maps:
                return filename(self.maps[key][0])
        sr, nch, _ = tools.stream_layout(path)
        return self._name(key, sr, nch)

    def _name(self, key: tuple, sr: int, nch: int) -> str:
        if self.dir is None:
            self.dir = _writable_dir()
            dsp.core.SPILL_DIR = self.dir  # large per-bin matrices spill next to the PCM
        name = hashlib.sha256(repr(key).encode()).hexdigest()[:32]
        return os.path.join(self.dir, f"{name}.{sr}.{nch}.f32")

    def _decode(self, path: str, key: tuple, report: tools.OnProgress) -> tuple[np.memmap, int]:
        sr, nch, duration = tools.stream_layout(path)
        fn = self._name(key, sr, nch)
        if not os.path.exists(fn):
            tmp = f"{fn}.{threading.get_ident()}.tmp"
            with open(tmp, "wb") as out:
                r = tools.decode_f32(path, nch, out, duration, report)
            if r.returncode != 0 or os.path.getsize(tmp) == 0:
                os.unlink(tmp)
                err = "\n".join(
                    ln for ln in r.stderr.decode(errors="replace").splitlines() if "=" not in ln[:20]
                )
                raise RuntimeError("decode failed: " + err[-300:])
            os.replace(tmp, fn)
            self._evict(keep=fn)
        report(1.0)
        os.utime(fn)  # mtime marks last use; atime is usually noatime
        n = os.path.getsize(fn) // (4 * nch)
        return np.memmap(fn, dtype=np.float32, mode="r", shape=(n, nch)), sr

    def _evict(self, keep: str) -> None:
        """Delete the least recently used decodes beyond PCM_DISK_GB, and
        stored analyses of other app versions (never read again)."""
        files = []
        current = f".analysis-{config.VERSION}."
        for e in os.scandir(self.dir):
            if ".analysis-" in e.name and current not in e.name:
                with contextlib.suppress(OSError):
                    os.unlink(e.path)
            elif e.name.endswith(".f32"):
                st = e.stat()
                files.append((st.st_mtime, st.st_size, e.path))
        total = sum(f[1] for f in files)
        for _, size, fpath in sorted(files):
            if total <= config.PCM_DISK_BUDGET:
                break
            if fpath != keep:
                os.unlink(fpath)  # an open memmap keeps its inode until closed
                total -= size


PCM = PcmCache()
