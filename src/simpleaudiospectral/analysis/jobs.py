"""Running analyses: one per file at a time, in the background, cached in
memory and persisted next to the decoded PCM, so a file is analysed once per
app version.
"""

import collections
import contextlib
import json
import os
import threading

import numpy as np

from .. import config, tools
from .. import pcm as pcm_cache
from .passes import measure
from .progress import Tracker

ANALYSES: collections.OrderedDict = collections.OrderedDict()  # (path, mtime) -> result
LOCK = threading.Lock()
RUNNING: dict = {}  # (path, mtime) -> Event, set when that analysis ends
PROGRESS: dict = {}  # (path, mtime) -> progress.Tracker of a running analysis
ERRORS: dict = {}  # (path, mtime) -> message, reported on the next poll
SCAN_ROWS: dict = {}  # (path, mtime) -> album-scan row
MAX_CACHED = 16


def key_of(path: str) -> tuple[str, float]:
    return path, os.path.getmtime(path)


def cached(path: str) -> dict | None:
    return ANALYSES.get(key_of(path))


def start(path: str) -> dict | None:
    """The result when it is ready; otherwise start the analysis in the
    background (if it is not running) and return None. progress() says how
    far it is, ERRORS whether it failed."""
    key = key_of(path)
    with LOCK:
        if key in ANALYSES:
            ANALYSES.move_to_end(key)
            return ANALYSES[key]
        if key in RUNNING or key in PROGRESS:
            return None  # running, or started and about to run
    stored = _load(*_persist_paths(pcm_cache.PCM.file_for(path)))  # one ffprobe, no decode
    with LOCK:
        if stored is not None:
            _remember(key, stored)
            return stored
        if key in RUNNING or key in PROGRESS:
            return None
        PROGRESS[key] = Tracker()  # visible before the thread runs: no "queued" gap
    threading.Thread(target=lambda: _run_reporting_errors(path), daemon=True, name="analysis").start()
    return None


def _remember(key: tuple, res: dict) -> None:
    """Keep a result in memory (LOCK held)."""
    ANALYSES[key] = res
    ERRORS.pop(key, None)
    while len(ANALYSES) > MAX_CACHED:
        ANALYSES.popitem(last=False)


def progress(path: str) -> dict | None:
    """The progress document of the analysis of `path`: None when no analysis
    of it is running or ready, {"done": 1, ...} when it is ready."""
    key = key_of(path)
    if key in ANALYSES:
        return {"stage": "Done", "stageKey": "done", "done": 1.0, "eta": 0.0, "pending": False}
    t = PROGRESS.get(key)
    return None if t is None else dict(t.snapshot(), pending=True)


def _run_reporting_errors(path: str) -> None:
    """run() in a background thread; a failure is left in ERRORS."""
    with contextlib.suppress(Exception):  # recorded in ERRORS by run()
        run(path)


def run(path: str) -> dict:
    """The analysis of `path`, computing it if needed; concurrent callers for
    the same file wait for one run."""
    key = key_of(path)
    with LOCK:
        if key in ANALYSES:
            ANALYSES.move_to_end(key)
            return ANALYSES[key]
        ev = RUNNING.get(key)
        owner = ev is None
        if owner:
            ev = RUNNING[key] = threading.Event()
    if not owner:
        ev.wait(config.TIMEOUT * 20)
        with LOCK:
            if key in ANALYSES:
                return ANALYSES[key]
        raise RuntimeError("analysis failed")
    ok = False
    try:
        res = _load_or_measure(path, key)
        with LOCK:
            _remember(key, res)
        ok = True
        return res
    except Exception as e:
        # Recorded before RUNNING is cleared, so a poller never sees the
        # analysis as neither running, done nor failed.
        ERRORS[key] = str(e)[-300:]
        raise
    finally:
        with LOCK:
            RUNNING.pop(key, None)
            t = PROGRESS.pop(key, None)
            if t is not None:
                t.finish(learn=ok)
        ev.set()


def _persist_paths(pcm_file: str) -> tuple[str, str]:
    base = os.path.splitext(pcm_file)[0] + f".analysis-{config.VERSION}"
    return base + ".json", base + ".npz"


def _load_or_measure(path: str, key: tuple) -> dict:
    """A stored result is found from the PCM's name alone, so it loads
    without decoding even after the PCM itself was evicted."""
    fn, npz = _persist_paths(pcm_cache.PCM.file_for(path))
    loaded = _load(fn, npz)
    if loaded is not None:
        return loaded
    with LOCK:
        tracker = PROGRESS.get(key)
        if tracker is None:
            tracker = PROGRESS[key] = Tracker()
    meta = tools.ffprobe(path)  # cached: the decode and measure() probe the same file
    tracker.mrows = meta["duration"] * meta["sampleRate"] / 1e6
    mm, sr = pcm_cache.PCM.open(path, lambda f: tracker.update("decode", f))
    tracker.complete("decode")
    res = measure(path, mm, sr, tracker.update)
    _save(res, fn, npz)
    return res


def _load(fn: str, npz: str) -> dict | None:
    if not (os.path.exists(fn) and os.path.exists(npz)):
        return None
    try:
        with open(fn) as f:
            res = json.load(f)
        with np.load(npz) as z:
            res["index"] = {k[3:]: (z[k], z["mx_" + k[3:]]) for k in z.files if k.startswith("mn_")}
            res["gonio"] = (z["gonio"], res["goniometerCorrelation"]) if "gonio" in z.files else None
        return res
    except (OSError, ValueError, KeyError):
        return None


def _save(res: dict, fn: str, npz: str) -> None:
    """JSON for the document, npz for the arrays; each written to a temporary
    name and renamed, so a crash never leaves a half-written result."""
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


def scan_row(path: str) -> dict:
    """One album-scan row, from the (cached) analysis. Only a miss takes a job slot."""
    key = key_of(path)
    row = SCAN_ROWS.get(key)
    if row is not None:
        return row
    with config.JOBS:
        res = run(path)
    meta, a, st = res["meta"], res["analysis"] or {}, res["stats"]
    dyn, loud = st["dynamics"] or {}, st["loudness"] or {}
    row = {
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
    SCAN_ROWS[key] = row
    while len(SCAN_ROWS) > 2000:
        SCAN_ROWS.pop(next(iter(SCAN_ROWS)))
    return row
