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
