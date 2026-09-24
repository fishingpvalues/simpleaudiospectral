"""Shared fixtures: an isolated library, cache and PCM directory per module."""

import os
import subprocess
import threading

import pytest

from simpleaudiospectral import config, pcm
from simpleaudiospectral.analysis import jobs
from simpleaudiospectral.server.app import Server

ENV = ("LIBRARY_ROOT", "CACHE_DIR", "PCM_DIR", "WEB_DIR")


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    """An empty library root; settings and caches point at temporary dirs."""
    root = tmp_path_factory.mktemp("library")
    web = tmp_path_factory.mktemp("web")
    (web / "index.html").write_text("<!doctype html><title>t</title>")
    old = {k: os.environ.get(k) for k in ENV}
    os.environ.update(
        LIBRARY_ROOT=str(root),
        CACHE_DIR=str(tmp_path_factory.mktemp("cache")),
        PCM_DIR=str(tmp_path_factory.mktemp("pcm")),
        WEB_DIR=str(web),
    )
    config.reload()
    pcm.PCM = pcm.PcmCache()
    for cache in (jobs.ANALYSES, jobs.PROGRESS, jobs.ERRORS, jobs.SCAN_ROWS):
        cache.clear()
    yield root
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    config.reload()


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def server(library):
    """The HTTP server on a random port, over a small library: a real FLAC, an
    MP3 transcoded to FLAC, and a 16-bit master padded to 24 bits."""
    album = library / "Artist" / "Album"
    album.mkdir(parents=True)
    src = "anoisesrc=d=12:c=pink:a=0.3,aformat=channel_layouts=stereo"
    ffmpeg("-f", "lavfi", "-i", src, "-sample_fmt", "s16", str(album / "01 real.flac"))
    ffmpeg("-f", "lavfi", "-i", src, "-c:a", "libmp3lame", "-b:a", "128k", str(library / "tmp.mp3"))
    ffmpeg("-i", str(library / "tmp.mp3"), "-sample_fmt", "s16", str(album / "02 transcode.flac"))
    padded = str(library / "padded24.flac")
    ffmpeg("-i", str(album / "01 real.flac"), "-sample_fmt", "s32", "-bits_per_raw_sample", "24", padded)
    (library / "tmp.mp3").unlink()
    srv = Server(("127.0.0.1", 0))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
