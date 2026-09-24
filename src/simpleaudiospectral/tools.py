"""ffmpeg, ffprobe and SoX: every external command the app runs.

Commands are argv lists, never a shell. Library files can come from anywhere
(downloads, rips), so ffmpeg and ffprobe only open local files and pipes: a
file that is really a playlist or concat script cannot make them fetch URLs.
"""

import json
import subprocess
from typing import IO

from . import config

NO_NET = ("-protocol_whitelist", "file,pipe")


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


def stream_layout(path: str) -> tuple[int, int]:
    """(sample rate, channels capped at 2) of the first audio stream."""
    p = run(
        [
            "ffprobe",
            "-v",
            "error",
            *NO_NET,
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels",
            "-of",
            "json",
            path,
        ]
    )
    st = (json.loads(p.stdout or b"{}").get("streams") or [{}])[0]
    return int(st.get("sample_rate") or 44100), max(1, min(2, int(st.get("channels") or 1)))


def decode_f32(path: str, channels: int, out) -> subprocess.CompletedProcess:
    """Decode to raw float32 straight into the open file `out`. Capturing stdout
    instead would hold the whole decode in memory."""
    return subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            *NO_NET,
            "-i",
            path,
            "-map",
            "0:a:0",
            "-ac",
            str(channels),
            "-f",
            "f32le",
            "-",
        ],
        stdout=out,
        stderr=subprocess.PIPE,
        timeout=config.TIMEOUT * 10,
        check=False,
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


def sox_bitdepth(path: str) -> str | None:
    """SoX `stats` bit depth as used/declared, e.g. "16/24" for a padded 24-bit file."""
    p = run(["sox", path, "-n", "stats"])
    for line in p.stderr.decode(errors="replace").splitlines():
        if line.startswith("Bit-depth"):
            return line.split()[1]
    return None
