"""The analysis of in-memory arrays, in the direct whole-array form.

The file analysis (analysis.passes) computes the same quantities in shared
sequential passes over the decoded file; this form is for arrays and tests.
"""

import numpy as np

from .. import dsp
from .levels import side_level_db, whole_levels
from .lowpass import HF_BAND_START, HF_N, HF_REF_BAND, SPEC_N, hf_band_top, lowpass
from .report import analysis_result


def analyse_pcm(x, side, sr: int, summary: dsp.Summary | None = None, levels: bool = True) -> dict | None:
    """Lowpass, codec and level analysis of the whole signal.

    Every loud 8192-sample frame (hop 4096) enters the per-bin 90th percentile
    (the lowpass) and median (the 16 kHz shelf); every loud 2048-sample frame
    (hop 1024) enters the sfb21 variability. See dsp for the definitions.
    """
    if len(x) < SPEC_N * 4:
        return None
    (med_raw, p90_raw), used = dsp.spectrum_percentiles(x, sr, n=SPEC_N, hop=SPEC_N // 2, qs=(50, 90))
    lp = lowpass(p90_raw, med_raw, sr)
    side_db, b05 = None, np.zeros(0)
    if summary is not None:
        n = max(1, summary.n)
        side_db = side_level_db(summary.total_ss["mix"] / n, summary.total_ss["side"] / n)
        b05 = summary.ss["b05"]["mix"]
    elif levels:
        ms_x, ms_s, b05 = whole_levels(x, side, sr)
        side_db = side_level_db(ms_x, ms_s)
    hf_sd = None
    top_hz = hf_band_top(lp["cutoff_hz"], lp["nyq"])
    if top_hz:
        hf_sd = dsp.band_ratio_std(x, sr, HF_REF_BAND, (HF_BAND_START, top_hz), n=HF_N, hop=HF_N // 2)
    return analysis_result(lp, sr, len(x), hf_sd, side_db, b05, used)
