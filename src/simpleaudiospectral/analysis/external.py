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


def _bytes_histogram(words: np.ndarray) -> np.ndarray:
    """(4, 256) counts of each byte value of uint32 words, LSB byte first."""
    b = words.astype("<u4", copy=False).view(np.uint8).reshape(-1, 4)
    return np.stack([np.bincount(b[:, j], minlength=256) for j in range(4)])


def _usage(hist: np.ndarray, total: int, bits: int) -> dict | None:
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


def _declared_bits(meta: dict) -> int:
    declared = meta.get("bits")
    return declared if declared in (16, 20, 24, 32) else 24


def pcm_exact_for_bits(meta: dict) -> bool:
    """Whether the decoded float32 PCM holds every integer sample of the file
    exactly: integer sources up to 24 bits (float32 has a 24-bit mantissa),
    with no downmix (the PCM keeps at most two channels)."""
    return (
        meta.get("bits") in (16, 20, 24)
        and meta.get("channels") in (1, 2)
        and not (meta.get("codecName") or "").startswith("pcm_f")
    )


def bit_usage(path: str, meta: dict, on_progress: OnProgress | None = None) -> dict | None:
    """Fraction of ones per bit over every integer sample of the file, LSB first.

    Real 24-bit audio sits near 0.5 on every bit; a 16-bit master padded to 24
    leaves the low 8 bits at exactly 0. A dithered 16-to-24 conversion fills
    them with noise, so the quiet-passage noise floor is the second check.

    Counted per byte: one 256-bin histogram of each byte of the 32-bit sample
    gives the ones of its eight bits exactly, in four passes over the samples
    instead of one shift-and-count pass per bit.
    """
    bits = _declared_bits(meta)
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
            hist += _bytes_histogram(np.frombuffer(buf[:cut_at], dtype="<u4"))
            total += cut_at // 4
            if on_progress and expected > 0:
                on_progress(min(0.999, total / expected))
    finally:
        tools.stdout(proc).close()
        proc.wait(timeout=config.TIMEOUT)
    return _usage(hist, total, bits)


def bit_usage_pcm(pcm_file: str, meta: dict, on_progress: OnProgress | None = None) -> dict | None:
    """bit_usage() from the decoded PCM instead of a second decode of the
    source (which sits on the library disk); only where pcm_exact_for_bits().
    Each float32 sample times 2^31 is the 32-bit integer ffmpeg's s32 decode
    gives, exactly."""
    bits = _declared_bits(meta)
    words = os.path.getsize(pcm_file) // 4
    hist = np.zeros((4, 256), dtype=np.int64)
    step = 1 << 22
    for a in range(0, words, step):
        x = np.fromfile(pcm_file, dtype="<f4", count=min(step, words - a), offset=a * 4)
        v = (x * np.float32(2**31)).astype(np.int64)  # exact: a power-of-two scale of a 24-bit value
        hist += _bytes_histogram((v & 0xFFFFFFFF).astype(np.uint32))
        if on_progress:
            on_progress(min(0.999, (a + len(x)) / max(1, words)))
    return _usage(hist, words, bits)
