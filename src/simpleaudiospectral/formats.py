"""File types the library shows and how each is read and served."""

import os

AUDIO_EXT = frozenset(
    {
        ".flac",
        ".mp3",
        ".wav",
        ".m4a",
        ".alac",
        ".aac",
        ".ogg",
        ".oga",
        ".opus",
        ".aif",
        ".aiff",
        ".wv",
        ".ape",
        ".dsf",
        ".dff",
        ".mka",
        ".wma",
    }
)

# SoX reads these itself; everything else reaches it through an ffmpeg pipe.
SOX_NATIVE = frozenset({".flac", ".mp3", ".wav", ".aif", ".aiff", ".ogg"})

# SoX `stats` reports a used/declared bit depth for these.
SOX_BITDEPTH = frozenset({".flac", ".wav", ".aif", ".aiff"})

LOSSLESS_CODECS = frozenset({"flac", "alac", "wavpack", "ape", "tta"})

# Served as-is for playback; anything else is transcoded to FLAC on request.
CONTENT_TYPES = {
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".aif": "audio/aiff",
    ".aiff": "audio/aiff",
}

CHANNELS = frozenset({"mix", "left", "right", "side"})


def is_audio(name: str) -> bool:
    """An audio file the library lists (hidden files never are)."""
    return not name.startswith(".") and os.path.splitext(name)[1].lower() in AUDIO_EXT


def is_lossless(codec_name: str | None) -> bool:
    return codec_name in LOSSLESS_CODECS or (codec_name or "").startswith("pcm_")
