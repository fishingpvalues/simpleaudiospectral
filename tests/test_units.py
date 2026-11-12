"""Small pure pieces: request parsing, file types, search ranking, proxies."""

import ipaddress

import pytest

from simpleaudiospectral import config, formats
from simpleaudiospectral.library import LibraryIndex
from simpleaudiospectral.server import auth
from simpleaudiospectral.server.routes.media import parse_range
from simpleaudiospectral.server.routes.params import channel, num, time_range


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("", (0, 999)),
        ("bytes=0-", (0, 999)),
        ("bytes=100-199", (100, 199)),
        ("bytes=900-5000", (900, 999)),  # clamped to the end
        ("bytes=-100", (900, 999)),  # the last 100 bytes
        ("bytes=10-20,30-40", (10, 20)),  # only the first range
        ("bytes=1000-", None),  # past the end
        ("bytes=abc-", None),  # malformed: unsatisfiable, not a crash
        ("bytes=10-20-30", None),
        ("bytes=-5-", None),
    ],
)
def test_parse_range(header, expected):
    assert parse_range(header, 1000) == expected


def test_num_clamps_and_falls_back():
    assert num({"x": "5"}, "x", 1, 0, 10) == 5
    assert num({"x": "50"}, "x", 1, 0, 10) == 10
    assert num({"x": "nope"}, "x", 3, 0, 10, int) == 3
    assert num({}, "x", 3, 0, 10) == 3


def test_time_range_is_at_least_a_millisecond():
    assert time_range({"t0": "5", "t1": "5"}, 10) == (5, 5.001)
    assert time_range({}, 10) == (0, 10)


def test_channel_whitelist():
    assert channel({"ch": "side"}) == "side"
    assert channel({"ch": "; rm -rf /"}) == "mix"


def test_is_audio():
    assert formats.is_audio("01 Track.FLAC")
    assert not formats.is_audio(".hidden.flac")
    assert not formats.is_audio("cover.jpg")
    assert formats.is_lossless("pcm_s24le") and formats.is_lossless("flac")
    assert not formats.is_lossless("mp3") and not formats.is_lossless(None)


def test_client_ip_trusts_only_configured_proxies(monkeypatch):
    monkeypatch.setattr(config, "TRUSTED_PROXIES", [])
    assert auth.client_ip("203.0.113.5", "1.2.3.4") == "203.0.113.5"
    monkeypatch.setattr(config, "TRUSTED_PROXIES", [ipaddress.ip_network("10.0.0.0/8")])
    assert auth.client_ip("10.0.0.2", "1.2.3.4, 198.51.100.7") == "198.51.100.7"
    assert auth.client_ip("10.0.0.2", "198.51.100.7, 10.0.0.9") == "198.51.100.7"  # skips proxy hops
    assert auth.client_ip("10.0.0.2", None) == "10.0.0.2"


def test_lockout_buckets_ipv6_by_64():
    assert auth.Lockout.bucket("2001:db8::1") == auth.Lockout.bucket("2001:db8::ffff") == "2001:db8::/64"
    assert auth.Lockout.bucket("192.0.2.1") == "192.0.2.1"


def test_search_ranks_name_matches_and_folders_first():
    index = LibraryIndex()
    index.entries = [
        ("a/album/track.flac", "A/Album/Track.flac", False),
        ("a/album", "A/Album", True),
        ("b/album notes/other.flac", "B/Album Notes/Other.flac", False),
    ]
    index.ready = True
    assert [h["path"] for h in index.search("album", 10)] == [
        "A/Album",
        "A/Album/Track.flac",
        "B/Album Notes/Other.flac",
    ]
    assert index.search("   ", 10) == []


def test_progress_tracker_is_monotonic_and_ends_at_one(monkeypatch):
    from simpleaudiospectral.analysis import progress as pr

    now = [0.0]
    monkeypatch.setattr(pr.time, "monotonic", lambda: now[0])
    t = pr.Tracker()
    assert t.snapshot()["done"] == 0 and t.snapshot()["eta"] is None
    seen = []
    # decode fast, then a stage far slower than its prior: the estimate bends,
    # the reported fraction must not go back.
    for k, steps, secs in (("decode", 10, 1.0), ("levels", 10, 1.0), ("spectra", 10, 30.0)):
        for i in range(1, steps + 1):
            now[0] += secs / steps
            t.update(k, i / steps)
            if k == "levels" and i == 1:
                t.update("loudness", 0.0)
            seen.append(t.snapshot()["done"])
    t.complete("percentiles")
    t.complete("sfb21")
    t.update("loudness", 0.5)
    seen.append(t.snapshot()["done"])
    assert seen == sorted(seen) and seen[-1] < 1  # loudness still running
    assert t.snapshot()["eta"] > 0
    t.update("loudness", 1.0)
    assert t.snapshot()["done"] == 0.999  # all stages done, result not yet stored
    t.finish()
    s = t.snapshot()
    assert s["done"] == 1.0 and s["eta"] == 0 and s["stageKey"] == "done"


def test_progress_unknown_stage_is_ignored():
    from simpleaudiospectral.analysis.progress import Tracker

    t = Tracker()
    t.update("no such stage", 0.5)
    assert {s["key"] for s in t.snapshot()["stages"]} == {
        "decode",
        "levels",
        "spectra",
        "percentiles",
        "sfb21",
    }


def test_ffmpeg_and_sox_progress_parsers():
    from simpleaudiospectral import tools

    parse = tools.ffmpeg_fraction(10.0)
    assert parse("out_time_us=2500000") == 0.25
    assert parse("out_time_us=N/A") is None and parse("frame=1") is None
    assert parse("progress=end") == 1.0
    assert tools.ffmpeg_fraction(0)("out_time_us=5") is None
    assert tools.sox_fraction("In:45.20% 00:01:23.45 [00:01:40.00] Out:3.6M") == 0.452
    assert tools.sox_fraction("Bit-depth      16/16") is None


def test_progress_learns_this_machines_speed(monkeypatch):
    """After one analysis, the next one estimates its not yet started stages
    from the speed measured before: the bar is not stuck behind a slow decode."""
    from simpleaudiospectral.analysis import progress as pr

    now = [0.0]
    monkeypatch.setattr(pr.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(pr, "LEARNED", {})

    def run(t, decode_s, compute_s):
        for k, secs in (("decode", decode_s), ("levels", compute_s), ("spectra", compute_s * 3)):
            for i in range(1, 11):
                now[0] += secs / 10
                t.update(k, i / 10)
        for k in ("percentiles", "sfb21"):
            t.complete(k)

    first = pr.Tracker(mrows=10.0)
    run(first, decode_s=30.0, compute_s=4.0)
    first.finish(learn=True)
    assert set(pr.LEARNED) == {"decode", "compute"}

    second = pr.Tracker(mrows=10.0)
    for i in range(1, 6):  # half the decode at the same speed
        now[0] += 3.0
        second.update("decode", i / 10)
    s = second.snapshot()
    # 15 s of about 15 + 30 left (15 decode + 16 compute): about a third, not a few percent
    assert 0.25 < s["done"] < 0.45 and 20 < s["eta"] < 45
