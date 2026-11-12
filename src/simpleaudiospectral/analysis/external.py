"""Measurements taken from reference tools rather than computed here."""

import os
import re
import sys

import numpy as np

from .. import config, tools
from ..tools import NO_NET, OnProgress

LOUDNESS_KEYS = (
    "lufs",
    "lra",
    "truePeakDb",
    "samplePeakDb",
    "rmsDb",
    "dcOffset",
    "flatFactor",
    "noiseFloorDb",
    "effectiveBits",
)


def _num(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text)
    if not m:
        return None
    v = m.group(1)
    return None if v in ("-inf", "inf", "nan") else float(v)


def loudness(
    path: str, raw: tuple[str, int, int] | None = None, on_progress: OnProgress | None = None
) -> dict:
    """EBU R128 / BS.1770-4 via ffmpeg's ebur128 filter (K-weighting, gating,
    4x oversampled true peak) plus astats, over the whole file. Both are
    reference implementations; a hand-rolled K-filter is where loudness tools
    drift. raw = (pcm_file, sr, channels) reads the decoded PCM instead of
    decoding the source again (a 3 h MP3 decode takes half a minute)."""
    if raw:
        src = ["-f", "f32le", "-ar", str(raw[1]), "-ac", str(raw[2]), "-i", raw[0]]
        duration = os.path.getsize(raw[0]) / (4 * raw[2] * raw[1])
    else:
        src = ["-i", path, "-vn"]
        duration = tools.ffprobe(path)["duration"] if on_progress else 0.0
    p = tools.run_tracked(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            *tools.FFMPEG_PROGRESS,
            *NO_NET,
            *src,
            "-af",
            "ebur128=peak=true:framelog=verbose,astats=measure_perchannel=none:measure_overall="
            "Peak_level+RMS_level+DC_offset+Flat_factor+Peak_count+Noise_floor+Bit_depth",
            "-f",
            "null",
            "-",
        ],
        tools.ffmpeg_fraction(duration),
        on_progress,
        config.TIMEOUT * 10,
    )
    t = p.stderr.decode(errors="replace")
    if p.returncode != 0:
        # A failed filter still prints a summary of zeros; never report that as data.
        sys.stderr.write(f"loudness: ffmpeg exit {p.returncode}: {t[-300:]}\n")
        return dict.fromkeys(LOUDNESS_KEYS)
    summary = t[t.rfind("Summary:") :] if "Summary:" in t else ""
    bd = re.search(r"Bit depth: ([\d/]+)", t)
    return {
        "lufs": _num(summary, r"I:\s+(-?[\d.]+|-inf) LUFS"),
        "lra": _num(summary, r"LRA:\s+(-?[\d.]+) LU"),
        "truePeakDb": _num(summary, r"Peak:\s+(-?[\d.]+|-inf) dBFS"),
        "samplePeakDb": _num(t, r"Peak level dB: (-?[\d.]+|-inf)"),
        "rmsDb": _num(t, r"RMS level dB: (-?[\d.]+|-inf)"),
        "dcOffset": _num(t, r"DC offset: (-?[\d.e-]+)"),
        "flatFactor": _num(t, r"Flat factor: (-?[\d.]+)"),
        "noiseFloorDb": _num(t, r"Noise floor dB: (-?[\d.]+|-inf)"),
        "effectiveBits": bd.group(1) if bd else None,
    }


def bit_usage(path: str, meta: dict, on_progress: OnProgress | None = None) -> dict | None:
    """Fraction of ones per bit over every integer sample of the file, LSB first.

    Real 24-bit audio sits near 0.5 on every bit; a 16-bit master padded to 24
    leaves the low 8 bits at exactly 0. A dithered 16-to-24 conversion fills
    them with noise, so the quiet-passage noise floor is the second check.

    Counted per byte: one 256-bin histogram of each byte of the 32-bit sample
    gives the ones of its eight bits exactly, in four passes over the samples
    instead of one shift-and-count pass per bit.
    """
    declared = meta.get("bits")
    bits = declared if declared in (16, 20, 24, 32) else 24
    expected = meta.get("duration", 0) * meta.get("sampleRate", 0) * meta.get("channels", 0)
    proc = tools.s32_stream(path)
    hist = np.zeros((4, 256), dtype=np.int64)
    total = 0
    rest = b""
    try:
        while True:
            buf = tools.stdout(proc).read(1 << 24)
            if not buf:
                break
            buf = rest + buf
            cut_at = len(buf) - len(buf) % 4
            rest = buf[cut_at:]
            b = np.frombuffer(buf[:cut_at], dtype="<u4").view(np.uint8).reshape(-1, 4)
            for j in range(4):
                hist[j] += np.bincount(b[:, j], minlength=256)
            total += len(b)
            if on_progress and expected > 0:
                on_progress(min(0.999, total / expected))
    finally:
        tools.stdout(proc).close()
        proc.wait(timeout=config.TIMEOUT)
    if not total:
        return None
    values = np.arange(256)
    ones32 = [int(hist[p // 8][(values >> (p % 8)) & 1 == 1].sum()) for p in range(32)]
    ones = ones32[32 - bits :]  # the declared bits are the top of the 32-bit sample
    zero_low = 0
    for o in ones:
        if o:
            break
        zero_low += 1
    return {
        "bits": bits,
        "ones": [round(o / total, 6) for o in ones],
        "unusedLowBits": zero_low,
        "samples": total,
    }
