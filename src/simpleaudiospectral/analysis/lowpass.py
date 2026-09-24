"""The brick-wall search.

A lossy encoder's lowpass is a wall: 30-60 dB lost within a few hundred Hz,
in every frame. Genuine lossless content rolls off gently into a noise floor
that reaches Nyquist.

- Lowpass: the 90th percentile over frames. It pins the edge even for VBR,
  where quiet frames are cut lower and a mean smears the wall.
- 16 kHz shelf: the median over frames. LAME's sfb21 band above 16 kHz is
  only coded when bits are left over, so a typical frame steps down there.
- Hi-res: an 88.2/96/192 kHz file whose top octave is empty is an upsample.
"""

import numpy as np

SPEC_N = 8192  # lowpass analysis frame (hop SPEC_N/2)
HF_N = 2048  # sfb21 frame: under two MP3 granules (hop HF_N/2)
HF_REF_BAND = (12000, 15800)  # sfb21 variability: energy above 16 kHz relative to this band
HF_BAND_START = 16200


def largest_drop(sm: np.ndarray, lo_i: int, hi_i: int, span: int) -> tuple[float, int | None, float, float]:
    """(drop, bin, level above, level below): the largest step down between
    the `span` bins below and above each bin in [lo_i, hi_i)."""
    c = np.concatenate([[0.0], np.cumsum(sm)])
    idx = np.arange(max(span, lo_i), min(len(sm) - span, hi_i))
    if not len(idx):
        return 0.0, None, 0.0, 0.0
    above = (c[idx] - c[idx - span]) / span
    below = (c[idx + span] - c[idx]) / span
    d = above - below
    j = int(np.argmax(d))
    return float(d[j]), int(idx[j]), float(above[j]), float(below[j])


def lowpass(p90_raw: np.ndarray, med_raw: np.ndarray | None, sr: int, n: int = SPEC_N) -> dict:
    """Cut-off, drop, 16 kHz shelf, hi-res level and extent from the exact
    per-bin 90th percentile and median of the dB spectrum."""
    freqs = np.fft.rfftfreq(n, 1 / sr)
    bin_hz = freqs[1]
    nyq = sr / 2
    k = max(1, int(100 / bin_hz))
    kern = np.ones(k) / k
    p90 = np.convolve(p90_raw, kern, mode="same")
    med = np.convolve(med_raw, kern, mode="same") if med_raw is not None else None
    ref = float(np.median(p90[(freqs > 1000) & (freqs < 8000)]))
    span = max(2, int(500 / bin_hz))

    # Search up to 24 kHz: covers 44.1/48 kHz sources inside 48/88.2/96 kHz
    # files; the empty top octave of a hi-res upsample is judged below.
    top = min(nyq, 24000) - 600
    drop, i, above, below = largest_drop(p90, int(12000 / bin_hz), int(top / bin_hz), span)
    cutoff_hz = None
    if i is not None and drop >= 20:
        mid = (above + below) / 2
        seg = np.arange(i - span, i + span)
        hit = seg[p90[seg] > mid]
        cutoff_hz = float(freqs[hit[-1]] if len(hit) else freqs[i])

    # Shelf: a step of >= 10 dB at 16 kHz in the median, above a lowpass that
    # itself sits well above 16 kHz (at 128k the wall is at 16 kHz).
    sdrop, shelf16 = 0.0, False
    if med is not None:
        sdrop, si, _, _ = largest_drop(
            med, int(15300 / bin_hz), int(16700 / bin_hz), max(2, int(400 / bin_hz))
        )
        shelf16 = si is not None and sdrop >= 10 and (cutoff_hz is None or cutoff_hz > 17500)

    hires_db = None
    if sr > 48000:

        def band(a, b):
            m = (freqs >= a) & (freqs < b)
            return float(p90[m].mean())

        hires_db = round(band(24000, min(nyq, 40000)) - band(10000, 20000), 1)

    above80 = np.where(p90 > ref - 80)[0]
    extent_hz = float(freqs[above80[-1]]) if len(above80) else 0.0

    return {
        "freqs": freqs,
        "k": k,
        "p90": p90,
        "med": med,
        "ref": ref,
        "cutoff_hz": cutoff_hz,
        "drop": drop,
        "sdrop": sdrop,
        "shelf16": shelf16,
        "hires_db": hires_db,
        "extent_hz": extent_hz,
        "crt": crt_tone(p90_raw, bin_hz),
        "nyq": nyq,
    }


def crt_tone(p90_raw: np.ndarray, bin_hz: float) -> int | None:
    """CRT line whine (15.625 kHz PAL, 15.734 kHz NTSC): a narrow tone that
    reads like an artifact on a spectrogram and is not one."""
    crt = None
    for tone in (15625, 15734):
        t = round(tone / bin_hz)
        if t + 40 < len(p90_raw):
            around = np.median(np.r_[p90_raw[t - 40 : t - 4], p90_raw[t + 4 : t + 40]])
            if p90_raw[t - 2 : t + 3].max() - around > 15:
                crt = tone
    return crt


def hf_band_top(cutoff_hz: float | None, nyq: float) -> float | None:
    """Upper edge of the sfb21 band, or None when there is no band to measure."""
    top_hz = min(cutoff_hz or nyq, 19000) - 300
    return top_hz if top_hz > 16800 else None
