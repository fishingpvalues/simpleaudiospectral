"""End to end over HTTP against a temporary library of ffmpeg-generated files."""

import json
import os

import numpy as np

from helpers import get, jget
from simpleaudiospectral import config, pcm
from simpleaudiospectral.library import INDEX


def test_info_is_202_then_200(server):
    code, _, body = get(server, "/api/info?path=Artist/Album/02%20transcode.flac")
    assert code in (200, 202)
    if code == 202:
        assert json.loads(body)["pending"] is True
    code, d = jget(server, "/api/info?path=Artist/Album/02%20transcode.flac")
    assert code == 200 and d["analysis"]["level"] == "bad"


def test_ls(server):
    code, d = jget(server, "/api/ls?path=Artist/Album")
    assert code == 200 and [f["name"] for f in d["files"]] == ["01 real.flac", "02 transcode.flac"]
    assert d["files"][0]["size"] > 0


def test_roots_and_search(server):
    INDEX.build()
    code, r = jget(server, "/api/roots")
    assert code == 200 and [x["name"] for x in r["roots"]] == ["Artist"]
    code, r = jget(server, "/api/search?q=album%20transcode")
    assert r["ready"] and [x["path"] for x in r["results"]] == ["Artist/Album/02 transcode.flac"]
    code, r = jget(server, "/api/search?q=album")
    assert r["results"][0] == {"path": "Artist/Album", "name": "Album", "dir": "Artist", "isDir": True}


def test_traversal_blocked(server):
    for p in (
        "/api/ls?path=../..",
        "/api/info?path=../../../etc/passwd",
        "/api/audio?path=%2e%2e/%2e%2e/etc/passwd",
    ):
        assert get(server, p)[0] == 403


def test_info_verdicts(server):
    _, real = jget(server, "/api/info?path=Artist/Album/01%20real.flac")
    _, fake = jget(server, "/api/info?path=Artist/Album/02%20transcode.flac")
    assert real["analysis"]["level"] == "ok"
    assert fake["analysis"]["level"] == "bad" and 15500 < fake["analysis"]["cutoffHz"] < 17100


def test_stats_padded_24bit(server):
    code, st = jget(server, "/api/stats?path=padded24.flac")
    assert code == 200
    assert st["bitUsage"]["bits"] == 24 and st["bitUsage"]["unusedLowBits"] == 8
    assert st["loudness"]["lufs"] is not None and st["dynamics"]["dr"] >= 0


def test_scan_streams_every_track(server):
    code, _h, body = get(server, "/api/scan?path=Artist/Album")
    lines = [json.loads(x) for x in body.decode().splitlines() if x.strip()]
    assert code == 200 and lines[0] == {"total": 2}
    rows = {r["name"]: r for r in lines[1:]}
    assert rows["01 real.flac"]["level"] == "ok"
    assert rows["02 transcode.flac"]["level"] == "bad"


def test_stft_binary(server):
    code, h, body = get(server, "/api/stft?path=Artist/Album/01%20real.flac&cols=300&rows=200&fft=2048")
    meta = json.loads(h["X-Meta"])
    assert code == 200 and len(body) == meta["cols"] * meta["rows"] == 300 * 200


def test_gonio(server):
    code, h, body = get(server, "/api/gonio?path=Artist/Album/01%20real.flac&size=64")
    assert code == 200 and len(body) == 64 * 64
    assert -1 <= json.loads(h["X-Meta"])["correlation"] <= 1


def test_audio_range(server):
    code, h, body = get(server, "/api/audio?path=Artist/Album/01%20real.flac", {"Range": "bytes=0-99"})
    assert code == 206 and len(body) == 100 and h["Content-Range"].startswith("bytes 0-99/")
    assert get(server, "/api/audio?path=Artist/Album/01%20real.flac", {"Range": "bytes=999999999-"})[0] == 416


def test_sox_png(server):
    code, _h, body = get(server, "/api/spectrogram?path=Artist/Album/01%20real.flac&x=600")
    assert code == 200 and body[:8] == b"\x89PNG\r\n\x1a\n"


def test_spa_fallback_and_404(server):
    assert get(server, "/some/client/route")[0] == 200
    assert get(server, "/api/nope")[0] == 404


def test_audio_transcode_stream(server):
    code, _h, body = get(server, "/api/audio?path=Artist/Album/01%20real.flac&format=flac")
    assert code == 200 and body[:4] == b"fLaC"


def test_health_reports_version(server):
    code, d = jget(server, "/api/health")
    assert code == 200 and d["status"] == "ok" and d["version"]


def test_pcm_is_disk_backed_memmap(server):
    mm, sr = pcm.PCM.open(os.path.join(config.ROOT, "Artist/Album/01 real.flac"))
    assert isinstance(mm, np.memmap) and mm.shape[1] == 2 and sr == 48000


def test_concurrent_sox_renders_of_one_image(server):
    """Two requests for the same, not yet cached image render it side by side."""
    from concurrent.futures import ThreadPoolExecutor

    path = "/api/spectrogram?path=Artist/Album/02%20transcode.flac&x=640"
    with ThreadPoolExecutor(4) as pool:
        codes = [r[0] for r in pool.map(lambda _: get(server, path), range(4))]
    assert codes == [200, 200, 200, 200]
