"""The SoX spectrogram image, rendered once per file and setting and cached."""

import hashlib
import json
import os
import subprocess
import threading

from . import config, tools
from .formats import SOX_NATIVE

SOX_WINDOWS = frozenset({"Kaiser", "Hann", "Hamming", "Bartlett", "Rectangular", "Dolph"})


def options(q: dict) -> dict:
    """Validated options from the query: channel, dB range, width, window, zoom."""
    w = q.get("w", "Kaiser")
    return {
        "ch": q.get("ch", "mix"),
        "z": min(150, max(60, int(q.get("z", "120")))),
        "x": min(4000, max(400, int(q.get("x", "1800")))),
        "w": w if w in SOX_WINDOWS else "Kaiser",
        "start": q.get("start"),
        "dur": q.get("dur"),
    }


def _effects(o: dict) -> list[str]:
    effects = []
    if o["start"] is not None:
        start = max(0.0, float(o["start"]))
        dur = min(60.0, max(0.1, float(o["dur"] or 2)))
        effects += ["trim", f"{start:.3f}", f"{dur:.3f}"]
    if o["ch"] == "mix":
        effects += ["remix", "-"]
    elif o["ch"] in ("left", "right"):
        effects += ["remix", "1" if o["ch"] == "left" else "2"]
    return effects


def render(path: str, q: dict) -> str:
    """Path of the PNG for `path` with the options in query `q`."""
    o = options(q)
    key = hashlib.sha256(
        json.dumps(
            [path, os.path.getmtime(path), o["ch"], o["z"], o["x"], o["w"], o["start"], o["dur"]]
        ).encode()
    ).hexdigest()
    out = os.path.join(config.CACHE, key + ".png")
    if os.path.exists(out):
        return out
    zoom = "" if o["start"] is None else f"  zoom {o['start']}s +{o['dur'] or 2}s"
    spec = ["spectrogram", "-x", str(o["x"]), "-y", "513" if o["ch"] == "all" else "1025", "-z", str(o["z"])]
    spec += [
        "-w",
        o["w"],
        "-t",
        os.path.basename(path)[:90],
        "-c",
        f"{o['ch']}  {o['w']} window  {o['z']} dB{zoom}",
    ]
    # A name per render: two requests for the same image must not share a
    # temporary file, or the second finds it already renamed away.
    tmp = f"{out}.{os.getpid()}.{threading.get_ident()}.tmp"
    spec += ["-o", tmp]
    if os.path.splitext(path)[1].lower() in SOX_NATIVE:
        p = tools.run(["sox", path, "-n", *_effects(o), *spec])
    else:
        dec = tools.wav_s32_stream(path)
        p = subprocess.run(
            ["sox", "-t", "wav", "-", "-n", *_effects(o), *spec],
            stdin=tools.stdout(dec),
            capture_output=True,
            timeout=config.TIMEOUT,
            check=False,
        )
        tools.stdout(dec).close()
        dec.wait(timeout=10)
    if p.returncode != 0 or not os.path.exists(tmp):
        raise RuntimeError(p.stderr.decode(errors="replace")[-400:])
    os.replace(tmp, out)
    return out
