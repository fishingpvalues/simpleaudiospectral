"""The analysis document the UI shows, from exact measurements."""

import numpy as np

from .verdict import codec_family, resampled_source, verdict_for


def loudest_window(b05: np.ndarray, n_samples: int, sr: int, seconds: float = 8.0) -> float:
    """Start (s) of the loudest `seconds`, from 0.5 s block energies: where a
    zoomed spectrogram is most informative."""
    if len(b05) <= 2:
        return 0.0
    w = max(1, int(min(seconds, n_samples / sr) * 2))
    return float(np.argmax(np.convolve(b05, np.ones(w), mode="valid")) * 0.5)


def analysis_result(lp: dict, sr: int, n_samples: int, hf_sd, side_db, b05, used: int) -> dict:
    """lp is analysis.lowpass.lowpass(); hf_sd the sfb21 variability (dB) or None."""
    cutoff_hz, drop, nyq = lp["cutoff_hz"], lp["drop"], lp["nyq"]
    if hf_sd is not None:
        hf_sd = round(hf_sd, 1)
    resampled_from = resampled_source(cutoff_hz, hf_sd, nyq)
    family = codec_family(cutoff_hz, hf_sd, drop)
    verdict, level = verdict_for(
        cutoff_hz, drop, lp["extent_hz"], nyq, sr, lp["hires_db"], family, resampled_from
    )
    freqs, k = lp["freqs"], lp["k"]
    step = max(1, int(25 / freqs[1]))
    keep = slice(0, len(freqs) - k, step)  # "same" convolution smears the last k bins
    return {
        "cutoffHz": cutoff_hz,
        "dropDb": round(drop, 1),
        "extentHz": round(lp["extent_hz"]),
        "nyquistHz": nyq,
        "shelf16k": bool(lp["shelf16"]),
        "shelfDropDb": round(lp["sdrop"], 1),
        "hiresDb": lp["hires_db"],
        "sideDb": round(side_db, 1) if side_db is not None else None,
        "hfSd": hf_sd,
        "family": family,
        "resampledFrom": resampled_from,
        "crtTone": lp["crt"],
        "loudestAt": loudest_window(b05, n_samples, sr),
        "verdict": verdict,
        "level": level,
        "refDb": round(lp["ref"], 1),
        "framesAnalysed": used,
        "curve": {
            "hz": [round(float(f)) for f in freqs[keep]],
            "db": [round(float(v), 1) for v in lp["p90"][keep]],
            "median": [round(float(v), 1) for v in lp["med"][keep]] if lp["med"] is not None else [],
        },
    }
