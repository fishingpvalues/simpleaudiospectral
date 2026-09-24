"""Whole-array forms of the streamed measurements, for tests and small inputs."""

from . import core
from .clicks import IsolatedClicks
from .frames import FrameRMS, loud_mask
from .runs import LevelRuns
from .spectrum import BandRatioStd, SpectrumPercentiles, WelchMean


def frame_rms(x, n, hop):
    return core.feed_all(x, FrameRMS(n, hop))[0]


def spectrum_percentiles(x, sr, n=8192, hop=4096, qs=(50, 90)):
    keep = loud_mask(frame_rms(x, n, hop))
    return core.feed_all(x, SpectrumPercentiles(n, hop, keep, qs))[0]


def band_ratio_std(x, sr, lo_band, hi_band, n=2048, hop=1024):
    keep = loud_mask(frame_rms(x, n, hop))
    return core.feed_all(x, BandRatioStd(sr, n, hop, keep, lo_band, hi_band))[0]


def mean_power_spectrum(x, n, hop):
    return core.feed_all(x, WelchMean(n, hop))[0]


def isolated_clicks(x, sr, window_s=60):
    return core.feed_all(x, IsolatedClicks(sr, window_s))[0]


def count_runs(x, level, sr, exact_equal=False):
    return core.feed_all(x, LevelRuns(sr, level, exact_equal))[0]
