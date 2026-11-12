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


def _fresh(library_root: str, name: str, seconds: int = 30) -> str:
    """A file no test has analysed yet, so its analysis really runs."""
    from conftest import ffmpeg

    src = f"anoisesrc=d={seconds}:c=pink:a=0.3,aformat=channel_layouts=stereo"
    ffmpeg("-f", "lavfi", "-i", src, "-sample_fmt", "s16", os.path.join(library_root, name))
    return name


def test_progress_streams_until_done(server):
    """Server-Sent Events: progress events whose overall fraction never goes
    back, each with every stage's own fraction, then one done event."""
    import urllib.request

    name = _fresh(config.ROOT, "sse.flac")
    req = urllib.request.Request(
        f"{server}/api/progress?path={name}", headers={"Accept": "text/event-stream"}
    )
    events = []
    with urllib.request.urlopen(req, timeout=120) as r:
        assert r.headers["Content-Type"] == "text/event-stream"
        ev = None
        for raw in r:
            line = raw.decode().strip()
            if line.startswith("event:"):
                ev = line[7:]
            elif line.startswith("data:"):
                events.append((ev, json.loads(line[6:])))
    kinds = [e for e, _ in events]
    assert kinds[-1] == "done" and set(kinds[:-1]) <= {"progress"}
    done = [d["done"] for _, d in events]
    assert done == sorted(done) and done[-1] == 1.0
    assert all(0 <= x < 1 for x in done[:-1])
    stages = {s["key"] for _, d in events[:-1] for s in d["stages"]}
    assert {"decode", "levels", "spectra", "percentiles", "loudness", "bits"} <= stages
    code, d = jget(server, f"/api/info?path={name}")
    assert code == 200 and d["analysis"]["level"] == "ok"


def test_progress_json_and_202_document(server):
    name = _fresh(config.ROOT, "poll.flac")
    code, _, body = get(server, f"/api/info?path={name}")
    if code == 202:
        p = json.loads(body)
        assert p["pending"] is True and 0 <= p["done"] < 1 and p["stage"] and "stages" in p
    code, d = jget(server, f"/api/info?path={name}")
    assert code == 200
    code, d = jget(server, f"/api/progress?path={name}")
    assert code == 200 and d["done"] == 1.0 and d["pending"] is False


def test_analysis_waits_for_the_whole_document(server):
    """wait=<s> holds the request until the result is ready: one call, no polling."""
    name = _fresh(config.ROOT, "wait.flac")
    code, _, body = get(server, f"/api/analysis?path={name}&wait=120")
    d = json.loads(body)
    assert code == 200 and set(d) == {"path", "meta", "analysis", "stats"}
    assert d["path"] == name and d["meta"]["sampleRate"] == 48000
    assert d["analysis"]["level"] == "ok" and d["stats"]["loudness"]["lufs"] is not None


def test_analysis_failure_is_reported(server):
    with open(os.path.join(config.ROOT, "broken.flac"), "wb") as f:
        f.write(b"not audio at all")
    code, _, body = get(server, "/api/analysis?path=broken.flac&wait=60")
    assert code == 500 and "analysis failed" in json.loads(body)["error"]


def test_stored_analysis_loads_without_decoding(server):
    """After a restart (memory caches empty) and with the decoded PCM evicted,
    a stored analysis is answered without decoding the file again."""
    from simpleaudiospectral.analysis import jobs

    name = "Artist/Album/01 real.flac"
    full = os.path.join(config.ROOT, name)
    assert jget(server, f"/api/info?path={name.replace(' ', '%20')}")[0] == 200
    pcm_file = pcm.PCM.file_for(full)
    jobs.ANALYSES.clear()
    pcm.PCM.maps.clear()
    os.unlink(pcm_file)
    code, _, _ = get(server, f"/api/info?path={name.replace(' ', '%20')}")
    assert code == 200 and not os.path.exists(pcm_file)
