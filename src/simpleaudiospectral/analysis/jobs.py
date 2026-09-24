"""Running analyses: one per file at a time, in the background, cached in
memory and persisted next to the decoded PCM, so a file is analysed once per
app version.
"""

import collections
import json
import os
import threading
import time

import numpy as np

from .. import config
from .. import pcm as pcm_cache
from .passes import measure

ANALYSES: collections.OrderedDict = collections.OrderedDict()  # (path, mtime) -> result
LOCK = threading.Lock()
RUNNING: dict = {}  # (path, mtime) -> Event, set when that analysis ends
PROGRESS: dict = {}  # (path, mtime) -> {"stage": str, "done": 0..1}
ERRORS: dict = {}  # (path, mtime) -> message, reported on the next poll
SCAN_ROWS: dict = {}  # (path, mtime) -> album-scan row
MAX_CACHED = 16


def key_of(path: str) -> tuple[str, float]:
    return path, os.path.getmtime(path)


def cached(path: str) -> dict | None:
    return ANALYSES.get(key_of(path))


def start(path: str) -> dict | None:
    """The result when it is ready; otherwise start the analysis in the
    background (if it is not running) and return None. PROGRESS says how far
    it is, ERRORS whether it failed."""
    key = key_of(path)
    with LOCK:
        if key in ANALYSES:
            ANALYSES.move_to_end(key)
            return ANALYSES[key]
        if key in RUNNING:
            return None
    threading.Thread(target=lambda: _run_reporting_errors(path), daemon=True, name="analysis").start()
    time.sleep(0.05)  # a persisted result is usually back before the first poll
    with LOCK:
        return ANALYSES.get(key)


def _run_reporting_errors(path: str) -> None:
    key = key_of(path)
    try:
        run(path)
        ERRORS.pop(key, None)
    except Exception as e:
        ERRORS[key] = str(e)[-300:]


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
    try:
        res = _load_or_measure(path, key)
        with LOCK:
            ANALYSES[key] = res
            while len(ANALYSES) > MAX_CACHED:
                ANALYSES.popitem(last=False)
        return res
    finally:
        with LOCK:
            RUNNING.pop(key, None)
        ev.set()


def _persist_paths(mm: np.memmap) -> tuple[str, str]:
    base = os.path.splitext(pcm_cache.filename(mm))[0] + f".analysis-{config.VERSION}"
    return base + ".json", base + ".npz"


def _load_or_measure(path: str, key: tuple) -> dict:
    def progress(stage: str, done: float) -> None:
        PROGRESS[key] = {"stage": stage, "done": round(float(done), 3)}

    progress("decoding", 0)
    mm, sr = pcm_cache.PCM.open(path)
    fn, npz = _persist_paths(mm)
    loaded = _load(fn, npz)
    if loaded is not None:
        return loaded
    res = measure(path, mm, sr, progress)
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
