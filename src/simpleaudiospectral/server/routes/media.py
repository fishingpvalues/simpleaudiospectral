"""Files as files: playback, the SoX image, and the bundled UI."""

from __future__ import annotations

import mimetypes
import os
import urllib.parse
from typing import TYPE_CHECKING

from ... import config, library, soxpng, tools
from ...formats import CONTENT_TYPES

if TYPE_CHECKING:
    from ..handler import Handler, Query


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """(start, end) inclusive of the first range in a Range header, the whole
    file when there is none, or None when it is unsatisfiable. A malformed
    header is also unsatisfiable: browsers and proxies send them, and a 400
    is the honest answer rather than a server crash."""
    start, end = 0, size - 1
    if not header.startswith("bytes="):
        return start, end
    a, _, b = header[6:].split(",", maxsplit=1)[0].partition("-")
    try:
        if a:
            start, end = int(a), int(b) if b else size - 1
        elif b:
            start = max(0, size - int(b))
    except ValueError:
        return None
    end = min(end, size - 1)
    return (start, end) if start <= end else None


def audio(h: Handler, q: Query) -> None:
    """The file itself, Range-capable; with format=flac a FLAC transcode."""
    full = library.resolve_file(q.get("path"))
    if q.get("format") == "flac":
        return _transcoded(h, full)
    size = os.path.getsize(full)
    header = h.headers.get("Range", "")
    span = parse_range(header, size)
    if span is None:
        h.send_response(416)
        h.send_header("Content-Range", f"bytes */{size}")
        h.send_header("Content-Length", "0")
        h.end_headers()
        return None
    start, end = span
    partial = header.startswith("bytes=")
    h.send_response(206 if partial else 200)
    h.send_header(
        "Content-Type", CONTENT_TYPES.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
    )
    h.send_header("Accept-Ranges", "bytes")
    h.send_header("Content-Length", str(end - start + 1))
    if partial:
        h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    h.end_headers()
    if h.command == "HEAD":
        return None
    with open(full, "rb") as f:
        f.seek(start)
        left = end - start + 1
        while left > 0:
            buf = f.read(min(1 << 20, left))
            if not buf:
                break
            h.wfile.write(buf)
            left -= len(buf)
    return None


def _transcoded(h: Handler, full: str) -> None:
    """WavPack, APE, DSD, ALAC in Chrome: decoded to FLAC on the fly so the
    browser can play what it cannot open. Not seekable before it is buffered."""
    h.start_chunked("audio/flac")
    proc = tools.flac_stream(full)
    try:
        while buf := tools.stdout(proc).read(1 << 16):
            h.write_chunk(buf)
        h.end_chunked()
    finally:
        proc.kill()
        proc.wait()


def spectrogram(h: Handler, q: Query) -> None:
    """The SoX spectrogram PNG of the whole file or a zoomed range."""
    full = library.resolve_file(q.get("path"))
    with config.JOBS:
        out = soxpng.render(full, q)
    with open(out, "rb") as f:
        data = f.read()
    name = os.path.splitext(os.path.basename(full))[0] + (".zoom" if q.get("start") else "") + ".png"
    disposition = "inline; filename*=UTF-8''" + urllib.parse.quote(name)
    h.send(
        200, data, "image/png", {"Cache-Control": "private, max-age=3600", "Content-Disposition": disposition}
    )


def static(h: Handler, path: str) -> None:
    """The bundled UI; unknown paths get index.html (client-side routes)."""
    rel = urllib.parse.unquote(path).lstrip("/") or "index.html"
    full = os.path.realpath(os.path.join(config.WEB, rel))
    if not full.startswith(config.WEB + os.sep) or not os.path.isfile(full):
        full = os.path.join(config.WEB, "index.html")
    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
    with open(full, "rb") as f:
        body = f.read()
    cache = "no-cache" if full.endswith("index.html") else "public, max-age=31536000, immutable"
    compress = ctype.startswith(("text/", "application/javascript"))
    h.send(200, body, ctype, {"Cache-Control": cache}, compress=compress)
