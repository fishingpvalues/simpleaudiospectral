"""ffmpeg, ffprobe and SoX: every external command the app runs.

Commands are argv lists, never a shell. Library files can come from anywhere
(downloads, rips), so ffmpeg and ffprobe only open local files and pipes: a
file that is really a playlist or concat script cannot make them fetch URLs.
"""

import json
import os
import re
import subprocess
import threading
from collections.abc import Callable
from typing import IO

from . import config

NO_NET = ("-protocol_whitelist", "file,pipe")
# ffmpeg writes key=value progress blocks here; out_time_us is the position in
# the output, which for a decode or a filter pass is how far it has read.
FFMPEG_PROGRESS = ("-progress", "pipe:2", "-stats_period", "0.25")

OnProgress = Callable[[float], None]


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=config.TIMEOUT, check=False, **kw)


def ffprobe(path: str) -> dict:
    """Codec, format and tags of the first audio stream."""
    p = run(
        ["ffprobe", "-v", "error", *NO_NET, "-print_format", "json", "-show_format", "-show_streams", path]
    )
    try:
        data = json.loads(p.stdout or b"{}")
    except ValueError:
        data = {}
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    tags.update({k.lower(): v for k, v in (audio.get("tags") or {}).items()})
    bits = audio.get("bits_per_raw_sample") or audio.get("bits_per_sample") or None
    return {
        "codec": audio.get("codec_long_name") or audio.get("codec_name"),
        "codecName": audio.get("codec_name"),
        "sampleRate": int(audio.get("sample_rate") or 0),
        "channels": int(audio.get("channels") or 0),
        "bits": int(bits) if bits and str(bits).isdigit() and int(bits) > 0 else None,
        "duration": float(fmt.get("duration") or audio.get("duration") or 0),
        "bitrate": int(fmt.get("bit_rate") or 0),
        "size": int(fmt.get("size") or 0),
        "encoder": tags.get("encoder") or tags.get("encoded_by") or tags.get("encoder_settings"),
        "artist": tags.get("artist"),
        "title": tags.get("title"),
        "album": tags.get("album"),
        "date": tags.get("date"),
    }


def stream_layout(path: str) -> tuple[int, int, float]:
    """(sample rate, channels capped at 2, duration in seconds or 0) of the
    first audio stream."""
    p = run(
        [
            "ffprobe",
            "-v",
            "error",
            *NO_NET,
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels,duration:format=duration",
            "-of",
            "json",
            path,
        ]
    )
    data = json.loads(p.stdout or b"{}")
    st = (data.get("streams") or [{}])[0]
    dur = _float(st.get("duration")) or _float((data.get("format") or {}).get("duration"))
    return int(st.get("sample_rate") or 44100), max(1, min(2, int(st.get("channels") or 1))), dur


def _float(v) -> float:
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        return 0.0


def ffmpeg_fraction(duration: float) -> Callable[[str], float | None]:
    """A parser for ffmpeg -progress lines: the fraction of `duration` done."""

    def parse(line: str) -> float | None:
        if line.startswith("out_time_us=") and duration > 0:
            us = line[12:].strip()
            return int(us) / 1e6 / duration if us.lstrip("-").isdigit() else None
        if line == "progress=end":
            return 1.0
        return None

    return parse


_SOX_IN = re.compile(r"In:\s*([\d.]+)%")


def sox_fraction(line: str) -> float | None:
    m = _SOX_IN.search(line)
    return float(m.group(1)) / 100 if m else None


def run_tracked(
    cmd: list[str],
    parse: Callable[[str], float | None],
    on_progress: OnProgress | None,
    timeout: float,
    stdout=subprocess.DEVNULL,
) -> subprocess.CompletedProcess:
    """Run cmd like run(), reading its stderr as it is written: every line
    (split on CR or LF, as progress meters redraw with CR) goes to parse, and
    each fraction it finds to on_progress. stderr is returned whole."""
    proc = subprocess.Popen(cmd, stdout=stdout, stderr=subprocess.PIPE)
    err = proc.stderr
    if err is None:
        raise RuntimeError("process has no stderr pipe")
    parts: list[bytes] = []

    def drain() -> None:
        tail = b""
        fd = err.fileno()
        while chunk := os.read(fd, 65536):  # whatever is there, without waiting for 64 KB
            parts.append(chunk)
            if on_progress is None:
                continue
            *lines, tail = re.split(rb"[\r\n]", tail + chunk)
            for line in lines:
                f = parse(line.decode(errors="replace"))
                if f is not None:
                    on_progress(min(1.0, max(0.0, f)))

    reader = threading.Thread(target=drain, daemon=True, name="progress")
    reader.start()
    try:
        rc = proc.wait(timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    finally:
        reader.join(5)
        err.close()
    return subprocess.CompletedProcess(cmd, rc, b"", b"".join(parts))


def decode_f32(
    path: str, channels: int, out, duration: float = 0, on_progress: OnProgress | None = None
) -> subprocess.CompletedProcess:
    """Decode to raw float32 straight into the open file `out`. Capturing stdout
    instead would hold the whole decode in memory."""
    return run_tracked(
        [
            *("ffmpeg", "-v", "error", "-nostats", *FFMPEG_PROGRESS, *NO_NET, "-i", path),
            *("-map", "0:a:0", "-ac", str(channels), "-f", "f32le", "-"),
        ],
        ffmpeg_fraction(duration),
        on_progress,
        config.TIMEOUT * 10,
        stdout=out,
    )


def pipe(cmd: list[str]) -> subprocess.Popen:
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def stdout(proc: subprocess.Popen) -> IO[bytes]:
    """The stdout of a process started by pipe(), which always has one."""
    if proc.stdout is None:
        raise RuntimeError("process has no stdout pipe")
    return proc.stdout


def flac_stream(path: str) -> subprocess.Popen:
    """A fast FLAC encode of the first audio stream on stdout, for playback."""
    return pipe(
        [
            *("ffmpeg", "-v", "error", *NO_NET, "-i", path, "-map", "0:a:0"),
            *("-c:a", "flac", "-compression_level", "0", "-f", "flac", "-"),
        ]
    )


def s32_stream(path: str) -> subprocess.Popen:
    """Every sample as signed 32-bit integers on stdout."""
    return pipe(
        [
            "ffmpeg",
            "-v",
            "error",
            *NO_NET,
            "-i",
            path,
            "-map",
            "0:a:0",
            "-f",
            "s32le",
            "-acodec",
            "pcm_s32le",
            "-",
        ]
    )


def wav_s32_stream(path: str) -> subprocess.Popen:
    """A 32-bit WAV on stdout. WAV defaults to 16-bit; s32 keeps a 24-bit
    source's noise floor."""
    return pipe(
        ["ffmpeg", "-v", "error", *NO_NET, "-i", path, "-map", "0:a:0", "-c:a", "pcm_s32le", "-f", "wav", "-"]
    )


def sox_bitdepth(path: str, on_progress: OnProgress | None = None) -> str | None:
    """SoX `stats` bit depth as used/declared, e.g. "16/24" for a padded 24-bit file."""
    p = run_tracked(["sox", "-S", path, "-n", "stats"], sox_fraction, on_progress, config.TIMEOUT * 10)
    for line in p.stderr.decode(errors="replace").splitlines():
        if line.startswith("Bit-depth"):
            return line.split()[1]
    return None
