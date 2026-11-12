"""File analysis and album scans. An analysis runs in the background; until it
is ready these routes answer 202 with its progress, or, with `wait=<seconds>`,
hold the request until it is ready.

/api/progress follows one analysis: a JSON snapshot, or with
`Accept: text/event-stream` a stream of them until the result is ready.
"""

from __future__ import annotations

import collections
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from ... import config, library
from ...analysis import jobs
from .params import num

if TYPE_CHECKING:
    from ..handler import Handler, Query

MAX_WAIT = 600  # seconds a request may hold for a result
TICK = 0.25  # seconds between progress events


def _failed(h: Handler, full: str) -> bool:
    key = jobs.key_of(full)
    if key in jobs.ERRORS:
        h.send(
            500, {"error": "analysis failed: " + jobs.ERRORS.pop(key)}, headers={"Cache-Control": "no-store"}
        )
        return True
    return False


def _result(h: Handler, q: Query) -> dict | None:
    """The analysis of q["path"], or None after answering 202 (still running)
    or 500 (failed). Starts the analysis when needed; waits up to q["wait"]."""
    full = library.resolve_file(q.get("path"))
    res = jobs.start(full)
    deadline = time.monotonic() + num(q, "wait", 0, 0, MAX_WAIT)
    while res is None and time.monotonic() < deadline:
        key = jobs.key_of(full)
        if key in jobs.ERRORS:
            break
        ev = jobs.RUNNING.get(key)
        if ev is not None:
            ev.wait(min(1.0, max(0.0, deadline - time.monotonic())))
        else:
            time.sleep(0.05)
        res = jobs.cached(full) or (None if key in jobs.RUNNING else jobs.start(full))
    if res is not None:
        return res
    if not _failed(h, full):
        snap = jobs.progress(full) or {"stage": "Queued", "stageKey": "queued", "done": 0.0, "pending": True}
        h.send(202, snap, headers={"Retry-After": "1", "Cache-Control": "no-store"})
    return None


def info(h: Handler, q: Query) -> None:
    """Metadata and the lowpass/codec analysis."""
    res = _result(h, q)
    if res is not None:
        h.send(200, dict(res["meta"], analysis=res["analysis"], path=q.get("path", "")), compress=True)


def stats(h: Handler, q: Query) -> None:
    """Loudness, dynamics, bit usage, per-channel cut-offs."""
    res = _result(h, q)
    if res is not None:
        h.send(200, res["stats"], compress=True)


def analysis(h: Handler, q: Query) -> None:
    """Everything about one file in one document: metadata, the verdict and
    the whole-file statistics (what /api/info and /api/stats return)."""
    res = _result(h, q)
    if res is not None:
        h.send(
            200,
            {
                "path": q.get("path", ""),
                "meta": res["meta"],
                "analysis": res["analysis"],
                "stats": res["stats"],
            },
            compress=True,
        )


def progress(h: Handler, q: Query) -> None:
    """How far the analysis of a file is; starts it when it is not running.
    JSON by default; Server-Sent Events (one `progress` event per change,
    then `done` or `failed`) when the client accepts text/event-stream."""
    full = library.resolve_file(q.get("path"))
    jobs.start(full)
    if "text/event-stream" not in (h.headers.get("Accept") or ""):
        if _failed(h, full):
            return None
        return h.send(
            200, jobs.progress(full) or {"done": 0.0, "pending": True}, headers={"Cache-Control": "no-store"}
        )

    h.start_chunked("text/event-stream", {"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    def event(name: str, data: dict) -> None:
        h.write_chunk(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
        h.wfile.flush()

    key = jobs.key_of(full)
    last, quiet_since = None, time.monotonic()
    deadline = time.monotonic() + config.TIMEOUT * 20
    while time.monotonic() < deadline:
        if key in jobs.ERRORS:
            event("failed", {"error": "analysis failed: " + jobs.ERRORS.pop(key)})
            break
        snap = jobs.progress(full)
        if snap is None:  # neither running nor ready: evicted from memory meanwhile
            jobs.start(full)
            snap = jobs.progress(full)
        if snap is not None and not snap.get("pending"):
            event("done", snap)
            break
        if snap is not None:
            # elapsed and eta change every tick; send when the work moved, or every 5 s.
            moved = (snap["done"], snap["stageKey"]) != last
            if moved or time.monotonic() - quiet_since >= 5:
                event("progress", snap)
                last, quiet_since = (snap["done"], snap["stageKey"]), time.monotonic()
        time.sleep(TICK)
    h.end_chunked()
    return None


def scan(h: Handler, q: Query) -> None:
    """Album scan: NDJSON, a {"total": n} line, then one row per track in
    folder order. MAX_JOBS tracks are analysed at once, so one track's decode
    (library disk) overlaps another's passes (CPU)."""
    files = library.audio_files(library.resolve_dir(q.get("path", "")))
    h.start_chunked("application/x-ndjson", {"Cache-Control": "no-store"})

    def line(obj: dict) -> None:
        h.write_chunk((json.dumps(obj) + "\n").encode())
        h.wfile.flush()

    line({"total": len(files)})
    pending = iter(files)
    inflight: collections.deque = collections.deque()
    # A client that goes away stops the scan: at most MAX_JOBS tracks still finish.
    with ThreadPoolExecutor(config.MAX_JOBS, thread_name_prefix="scan") as pool:

        def fill() -> None:
            while len(inflight) < config.MAX_JOBS and (f := next(pending, None)) is not None:
                inflight.append((f, pool.submit(jobs.scan_row, f)))

        fill()
        while inflight:
            f, fut = inflight.popleft()
            try:
                row = fut.result()
            except Exception as e:
                row = {"name": os.path.basename(f), "error": str(e)[-200:]}
            fill()
            line(row)
    h.end_chunked()
