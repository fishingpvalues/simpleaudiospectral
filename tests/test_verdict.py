"""The verdict and codec naming, as pure functions of the measurements."""

from typing import Any

import pytest

from simpleaudiospectral.analysis.verdict import codec_family, resampled_source, verdict_for


@pytest.mark.parametrize(
    ("khz", "hf_sd", "family"),
    [
        (16.8, 21.0, "MP3 128k"),
        (16.8, 4.0, "AAC ~128k or low-rate lossy"),
        (17.5, 23.0, "MP3 V4/160k"),
        (17.3, 3.4, "AAC ~128k"),
        (18.8, 15.3, "MP3 V2/192k"),
        (18.3, 3.3, "Vorbis q3 / AAC"),
        (19.5, 11.2, "MP3 256k / V0 (older LAME)"),
        (20.2, 12.0, "MP3 320k/V0"),
        (20.3, 3.2, "Opus (20 kHz band limit) or AAC"),
        (21.2, 3.3, "Vorbis q6+ or high-rate AAC"),
        (21.5, 3.3, None),  # anti-alias filter of a lossless source
    ],
)
def test_codec_family_bands(khz, hf_sd, family):
    assert codec_family(khz * 1000, hf_sd, 40) == family


def test_no_family_without_a_wall():
    assert codec_family(None, 20, 40) is None
    assert codec_family(18000, 20, 15) is None  # a 15 dB step is not a brick wall


def test_resampled_source():
    assert resampled_source(21800, 3.0, 24000) == 44100  # 44.1 kHz audio in a 48 kHz file
    assert resampled_source(20200, 12.0, 24000) is None  # an MP3 320k wall, not a resampler
    assert resampled_source(21800, 3.0, 22050) is None  # at its own Nyquist: no lower source


CASES: list[dict[str, Any]] = [
    {"cutoff_hz": None, "drop": 5, "extent_hz": 22000, "nyq": 22050, "sr": 44100, "hires_db": None},
    {"cutoff_hz": 21800, "drop": 50, "extent_hz": 21800, "nyq": 22050, "sr": 44100, "hires_db": None},
    {
        "cutoff_hz": 18800,
        "drop": 49,
        "extent_hz": 18800,
        "nyq": 22050,
        "sr": 44100,
        "hires_db": None,
        "family": "MP3 V2/192k",
    },
    {"cutoff_hz": 18000, "drop": 30, "extent_hz": 18000, "nyq": 22050, "sr": 44100, "hires_db": None},
    {
        "cutoff_hz": 21800,
        "drop": 40,
        "extent_hz": 21800,
        "nyq": 24000,
        "sr": 48000,
        "hires_db": None,
        "resampled_from": 44100,
    },
    {
        "cutoff_hz": 19000,
        "drop": 40,
        "extent_hz": 19000,
        "nyq": 48000,
        "sr": 96000,
        "hires_db": -70,
        "family": "MP3 V2/192k",
    },
]


@pytest.mark.parametrize("case", CASES)
def test_verdicts_are_short_statements(case):
    text, level = verdict_for(**case)
    assert level in ("ok", "warn", "bad")
    assert len(text) <= 130, text
    dashes = (chr(0x2013), chr(0x2014))
    assert not any(d in text for d in dashes) and " - " not in text, text


def test_verdict_levels():
    assert verdict_for(**CASES[0]) == ("No lowpass. Content reaches 22.0 of 22.05 kHz.", "ok")
    assert verdict_for(**CASES[1])[1] == "ok"
    assert verdict_for(**CASES[2]) == ("Lowpass at 18.8 kHz, 49 dB drop: MP3 V2/192k.", "bad")
    assert verdict_for(**CASES[3])[1] == "warn"
    assert "resampled to 48 kHz" in verdict_for(**CASES[4])[0]
    text, level = verdict_for(**CASES[5])
    assert level == "bad" and "upsampled" in text and "19.0 kHz: MP3 V2/192k" in text
