"""Exact whole-file measurements, streamed.

Every measurement is a consumer that is fed consecutive chunks of the signal
and returns exactly what its whole-array definition (in its docstring)
returns: the same frames, the same blocks, the same percentiles. Nothing is
sampled, capped or approximated. Consumers share one sequential read of a
file (analysis.passes), so a whole analysis costs two reads of the decoded
audio regardless of how many measurements it makes.

Where a result needs every value at once (the percentile of each frequency
bin over all frames), the values are spilled to a float64 file on disk and
read back per bin.

tests/test_exact.py runs each consumer against a literal whole-array
reference with a deliberately awkward chunk size.

Whole-file sums (total energy, correlation, Welch means) are accumulated per
chunk and combined with math.fsum or float64 addition; they agree with a
single numpy sum over the whole array to about 1e-15 relative, which is the
rounding of float64 itself.
"""

from . import core
from .clicks import IsolatedClicks
from .core import f64, feed_all, n_frames
from .direct import (
    band_ratio_std,
    count_runs,
    frame_rms,
    isolated_clicks,
    mean_power_spectrum,
    spectrum_percentiles,
)
from .frames import FrameRMS, Frames, loud_mask
from .runs import LevelRuns, RunCounter
from .spectrum import BandRatioStd, SpectrumPercentiles, WelchMean
from .stereo import Goniometer, goniometer
from .stft import stft_columns
from .summary import Summary, summarize
from .waveform import BlockExtremes, column_extremes

__all__ = [
    "BandRatioStd",
    "BlockExtremes",
    "FrameRMS",
    "Frames",
    "Goniometer",
    "IsolatedClicks",
    "LevelRuns",
    "RunCounter",
    "SpectrumPercentiles",
    "Summary",
    "WelchMean",
    "band_ratio_std",
    "column_extremes",
    "core",
    "count_runs",
    "f64",
    "feed_all",
    "frame_rms",
    "goniometer",
    "isolated_clicks",
    "loud_mask",
    "mean_power_spectrum",
    "n_frames",
    "spectrum_percentiles",
    "stft_columns",
    "summarize",
]
