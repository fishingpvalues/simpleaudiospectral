"""File analysis and album scans. An analysis runs in the background; until it
is ready these routes answer 202 with its progress."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from ... import library
from ...analysis import jobs

if TYPE_CHECKING:
    from ..handler import Handler, Query


def _pending(h: Handler, full: str) -> None:
    key = jobs.key_of(full)
    if key in jobs.ERRORS:
        return h.send(500, {"error": "analysis failed: " + jobs.ERRORS.pop(key)})
    progress = jobs.PROGRESS.get(key, {"stage": "queued", "done": 0})
    return h.send(
        202, dict(progress, pending=True), headers={"Retry-After": "1", "Cache-Control": "no-store"}
    )


def info(h: Handler, q: Query) -> None:
    """Metadata and the lowpass/codec analysis."""
    full = library.resolve_file(q.get("path"))
    res = jobs.start(full)
    if res is None:
        return _pending(h, full)
    return h.send(200, dict(res["meta"], analysis=res["analysis"], path=q.get("path", "")), compress=True)


def stats(h: Handler, q: Query) -> None:
    """Loudness, dynamics, bit usage, per-channel cut-offs."""
    full = library.resolve_file(q.get("path"))
    res = jobs.start(full)
    if res is None:
        return _pending(h, full)
    return h.send(200, res["stats"], compress=True)


def scan(h: Handler, q: Query) -> None:
    """Album scan: NDJSON, a {"total": n} line, then one row per track as it finishes."""
    files = library.audio_files(library.resolve_dir(q.get("path", "")))
    h.start_chunked("application/x-ndjson", {"Cache-Control": "no-store"})

    def line(obj: dict) -> None:
        h.write_chunk((json.dumps(obj) + "\n").encode())
        h.wfile.flush()

    line({"total": len(files)})
    for f in files:
        try:
            row = jobs.scan_row(f)
        except Exception as e:
            row = {"name": os.path.basename(f), "error": str(e)[-200:]}
        line(row)
    h.end_chunked()
