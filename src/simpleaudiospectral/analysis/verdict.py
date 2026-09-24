"""From measurements to a verdict: the likely codec and one sentence of evidence.

The cut-off bands come from the encoders' own lowpass tables and were checked
by measurement (README, "Reference lines"). HF variability is the spread of
the 16-19 kHz band energy over short frames: LAME codes that band (sfb21)
only when bits are left over, so it jumps from frame to frame; AAC, Opus and
Vorbis keep it steady.
"""

MP3_HF_SD = 10  # dB: above this the sfb21 band behaves like LAME's
STEADY_HF_SD = 8  # dB: below this it behaves like AAC, Opus, Vorbis or lossless
LOSSY_MAX_KHZ = 20.8  # a wall below this is an encoder, not an anti-alias filter
ANTI_ALIAS_KHZ = 21.4  # a wall above this is a lossless source's anti-alias filter
UPSAMPLE_HIRES_DB = -45  # top octave this far below the midrange: nothing is there
STANDARD_RATES = (16000, 22050, 32000, 44100, 48000)


def codec_family(cutoff_hz: float | None, hf_sd: float | None, drop: float) -> str | None:
    """The likely source codec from the cut-off and the sfb21 behaviour."""
    if not cutoff_hz or drop < 20:
        return None
    k = cutoff_hz / 1000
    mp3ish = hf_sd is not None and hf_sd >= MP3_HF_SD
    steady = hf_sd is not None and hf_sd < STEADY_HF_SD
    if k < 17.1:  # LAME 128k: transition band 16.5-17.07 kHz, lower on dense music
        return "AAC ~128k or low-rate lossy" if steady else "MP3 128k"
    if k < 17.9:
        return "MP3 V4/160k" if mp3ish else ("AAC ~128k" if steady else "MP3 V4 or AAC 128k")
    if k < 19.0:
        return "MP3 V2/192k" if mp3ish else ("Vorbis q3 / AAC" if steady else "MP3 V2 or Vorbis")
    if k < 19.8:
        return "MP3 256k / V0 (older LAME)" if not steady else "AAC/Vorbis ~192k"
    if k < 20.6:
        if mp3ish:
            return "MP3 320k/V0"
        return "Opus (20 kHz band limit) or AAC" if steady else "MP3 320k/V0 or Opus"
    if k < ANTI_ALIAS_KHZ:
        return "Vorbis q6+ or high-rate AAC" if not mp3ish else "MP3 320k (wide lowpass)"
    return None


def resampled_source(cutoff_hz: float | None, hf_sd: float | None, nyq: float) -> int | None:
    """The standard rate a file was resampled from: a wall within 5% under that
    rate's Nyquist, which is where a resampler's anti-alias filter sits. An
    MP3 lowpass can land in the same place (320k at 20.2 kHz is 92% of 22.05),
    so an MP3-style sfb21 signature wins: that wall is the encoder."""
    if not cutoff_hz or (hf_sd is not None and hf_sd >= MP3_HF_SD):
        return None
    found = None
    for src_sr in STANDARD_RATES:
        if src_sr / 2 < nyq - 1000 and 0.94 * src_sr / 2 <= cutoff_hz <= src_sr / 2 + 100:
            found = src_sr
    return found


def verdict_for(
    cutoff_hz: float | None,
    drop: float,
    extent_hz: float,
    nyq: float,
    sr: int,
    hires_db: float | None,
    family: str | None = None,
    resampled_from: int | None = None,
) -> tuple[str, str]:
    """(sentence, level) where level is "ok", "warn" or "bad"."""
    khz = cutoff_hz / 1000 if cutoff_hz else None
    if sr > 48000 and hires_db is not None and hires_db < UPSAMPLE_HIRES_DB:
        text = f"Nothing above 22 kHz (top octave {hires_db:.0f} dB): upsampled from 44.1 or 48 kHz."
        if khz is not None and khz < LOSSY_MAX_KHZ:
            text += f" Source lowpass at {khz:.1f} kHz: {family or 'lossy'}."
        return text, "bad"
    if resampled_from and khz is not None:
        return (
            f"Lowpass at {khz:.1f} kHz, the anti-alias filter of {resampled_from / 1000:g} kHz audio: "
            f"resampled to {sr / 1000:g} kHz.",
            "bad",
        )
    if khz is None:
        return f"No lowpass. Content reaches {extent_hz / 1000:.1f} of {nyq / 1000:.2f} kHz.", "ok"
    if khz >= ANTI_ALIAS_KHZ:
        return f"Lowpass at {khz:.1f} kHz: the anti-alias filter of a lossless source.", "ok"
    if family:
        level = "bad" if khz < LOSSY_MAX_KHZ else "warn"
        return f"Lowpass at {khz:.1f} kHz, {drop:.0f} dB drop: {family}.", level
    return f"Lowpass at {khz:.1f} kHz, {drop:.0f} dB drop: no known encoder setting.", "warn"
