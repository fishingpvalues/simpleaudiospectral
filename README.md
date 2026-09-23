# simpleaudiospectral

[![CI](https://github.com/fishingpvalues/simpleaudiospectral/actions/workflows/ci.yml/badge.svg)](https://github.com/fishingpvalues/simpleaudiospectral/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/fishingpvalues/simpleaudiospectral?sort=semver)](https://github.com/fishingpvalues/simpleaudiospectral/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

simpleaudiospectral is a self-hosted web application for checking whether
audio files are what they claim to be. It shows a spectrogram, waveform and
loudness analysis of any track in a mounted music library, and flags lossy
transcodes, upsampled "hi-res" files, padded bit depths and clipped masters.

The analysis follows the spectral guidance used by lossless-only music
trackers such as Redacted and Orpheus. The viewer draws a zoomable
spectrogram in the style of Adobe Audition, and the tool exports the classic
SoX spectral image that uploaders attach to a release.

Licensed under the MIT license. See [LICENSE](LICENSE).

![Overview: a genuine lossless track](docs/overview.png)

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [How the verdict is reached](#how-the-verdict-is-reached)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Accessibility](#accessibility)
- [HTTP API](#http-api)
- [Development](#development)
- [Security](#security)

## Features

**Viewer**

- Waveform and spectrogram with a time ruler, frequency axis and grid,
  rendered at the display's exact resolution for the visible range.
- Box zoom, wheel zoom around the cursor, separate frequency zoom, pan, an
  overview strip of the whole track, and a view history.
- Linear and logarithmic frequency scales. FFT sizes 512 to 32768.
  Blackman-Harris, Kaiser, Hann, Hamming and Blackman windows. An adjustable
  dB range.
- Mix, left, right and side (L-R) channel views.
- Reference lines at the MP3 lowpass frequencies from the RED spectral guide,
  and the detected cut-off drawn on the plot.
- One-key zoom preset to the loudest 8 seconds of the top band, the zoomed
  spectral reviewers ask for.
- Overlays for spectral holes (bands a lossy encoder dropped in single
  frames) and the 99% spectral rolloff per frame.
- Cursor readout of time, frequency and level in dBFS, plus a live spectrum
  slice under the cursor.
- Playback with a playhead that follows the view. Formats the browser cannot
  play are transcoded to FLAC on the fly.
- PNG export of the current view, and SoX spectral export of the full track
  or the visible time range.

**Analysis**

- Brick-wall lowpass detection on the 90th-percentile spectrum, with the
  likely source codec named: MP3 by bitrate class, AAC, Opus or Vorbis.
- MP3 identification through sfb21 behaviour. This is the frame-to-frame
  variability of the band above 16 kHz, which separates MP3 from AAC, Opus
  and Vorbis at similar cut-offs.
- 16 kHz shelf detection.
- Detection of upsampled hi-res files, and of files resampled from a lower
  rate.
- Fake bit-depth checks: a per-bit usage histogram, SoX used/declared bit
  depth, and the noise floor of quiet passages.
- EBU R128 integrated loudness and loudness range, true peak and sample peak.
- DR score (TT DR Meter algorithm), including per channel.
- Clipping and flat-top detection with a clickable list of positions.
- DC offset, stereo correlation over time, a goniometer for the current
  view, and a per-channel cut-off comparison that exposes joint-stereo lossy
  coding.
- Hints for vinyl and other analogue sources: rumble and isolated clicks.
- CRT line-whine detection at 15.625 and 15.734 kHz, so a TV tone is not
  mistaken for a codec artifact.

**Library**

- Browses the mounted volumes and shows the disk usage of each.
- Searches the whole library instantly from a background index.
- Recently opened files, keyboard navigation and deep links to a file.
- Album scan streams a per-track table of verdicts, cut-offs, DR, loudness
  and true peak. It flags tracks that differ from the rest of the album,
  which is the usual sign of a mixed-source release.

![RED zoom preset with spectral holes highlighted on an MP3 V2 file](docs/zoom-holes.png)

## Quick start

Multi-arch images (linux/amd64, linux/arm64) are published to the GitHub
Container Registry for every release.

```sh
docker run -d --name simpleaudiospectral \
  --read-only --tmpfs /cache --tmpfs /tmp \
  -p 127.0.0.1:4748:4748 \
  -v simpleaudiospectral-pcm:/pcm \
  -v /path/to/music:/library/music:ro \
  ghcr.io/fishingpvalues/simpleaudiospectral:latest
```

Open `http://127.0.0.1:4748`.

| Tag | Meaning |
|---|---|
| `0.0.2`, `0.0` | A release, and the newest release of that line |
| `latest` | The newest release |
| `beta`, `sha-<commit>` | The current `main` branch, built on every push |

To build from source instead:

```sh
docker build -t simpleaudiospectral https://github.com/fishingpvalues/simpleaudiospectral.git#main
```

### Docker Compose

```yaml
services:
  simpleaudiospectral:
    image: ghcr.io/fishingpvalues/simpleaudiospectral:latest
    container_name: simpleaudiospectral
    user: "1000:1000"
    read_only: true
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    tmpfs:
      - /cache:size=256m,uid=1000,gid=1000
      - /tmp:size=64m,mode=1777
    ports:
      - "127.0.0.1:4748:4748"
    environment:
      PCM_DISK_GB: "20"
    volumes:
      - pcm:/pcm
      - /path/to/music:/library/music:ro
      - /path/to/rips:/library/rips:ro
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1536M

volumes:
  pcm:
```

```sh
docker compose up -d
```

Each directory mounted under `/library` appears as a volume in the library
browser. All mounts can and should be read-only; the application never
writes to the library.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `LIBRARY_ROOT` | `/library` | Root of the browsable library. |
| `PORT` | `4748` | Listening port inside the container. |
| `CACHE_DIR` | `/cache` | SoX PNG cache. A tmpfs is sufficient. |
| `PCM_DIR` | `/pcm` | Disk cache of decoded audio, memory-mapped. Mount a volume here. |
| `PCM_DISK_GB` | `20` | Size limit of that cache; the least recently used files go first. |
| `MAX_JOBS` | `3` | Concurrent decode and analysis jobs. |
| `INDEX_INTERVAL` | `900` | Seconds between rebuilds of the search index. |
| `ACCESS_LOG` | unset | Set to any value to log requests. |

Every file is decoded once to 32-bit float PCM on disk (about 1.3 GB per
hour of 48 kHz stereo) and memory-mapped. Whole-track statistics come from a
single chunked pass, so memory stays flat regardless of length: a three-hour
DJ set peaks at about 330 MB of heap in a 1.5 GB container. Without a volume
on `/pcm` the cache falls back to `/cache`, which is usually a tmpfs and
therefore RAM.

## How the verdict is reached

![Album scan of reference encodes](docs/scan.png)

A lossy encoder removes everything above a fixed lowpass in every frame. On
a spectrogram this shows as a flat, constant edge. A lossless recording
tapers into a noise floor that reaches the Nyquist frequency. The tool finds
the steepest level drop above 10 kHz in the 90th-percentile spectrum, then
uses further evidence to name the source:

| Measured on one master | Cut-off | HF variability |
|---|---|---|
| Lossless (CD) | none, reaches 22.05 kHz | 3.2 dB |
| MP3 V4 (LAME) | 17.5 kHz | 23.5 dB |
| MP3 V2 | 18.8 kHz | 15.3 dB |
| MP3 256 kbps | 19.5 kHz | 11.2 dB |
| AAC 128 kbps | 17.3 kHz | 3.4 dB |
| Opus 96 and 160 kbps | 20.2 to 20.3 kHz | 3.2 to 4.3 dB |
| Vorbis q3 | 18.3 kHz | 3.3 dB |
| Vorbis q6 | 21.2 kHz | 3.3 dB |

HF variability is the standard deviation, over short frames, of the energy
from 16 to 19 kHz relative to 12 to 16 kHz. LAME codes that band (sfb21)
only when bits are left over, so its level jumps from frame to frame. Other
codecs keep it steady.

Limits worth knowing:

- A spectrum cannot identify every lossy source. ffmpeg's AAC encoder at
  256 kbps applies no lowpass at all and looks lossless on a spectrogram.
- V0 and 320 kbps MP3 share a cut-off near 20 kHz with current LAME
  versions and cannot be told apart by lowpass alone.
- Old ADD masters can top out near 16 kHz. A master rolls off softly, while
  a codec edge is flat and constant; the zoom view shows the difference.

The verdict is evidence for a human reviewer, not a replacement for one.

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Space` | Play or pause |
| `/` | Search the library |
| `Up` `Down` `Enter` `Backspace` | Move, open, go up a level in the library |
| drag, `Shift`+drag | Box zoom, pan |
| wheel, `Alt`+wheel | Zoom time, zoom frequency |
| `+` `-` `F` | Zoom in, zoom out, fit the whole track |
| `Left` `Right` | Pan |
| `Backspace` or `U` | Previous view |
| `Z` | RED zoom preset |
| `L` | Linear or logarithmic frequency scale |
| `1` `2` `3` `4` | Mix, left, right, side |
| `R` `G` `H` `O` | Reference lines, grid, holes, rolloff |
| `E` | Export the view as PNG |

## Accessibility

**Colour vision.** The default map reproduces Adobe Audition's spectral
display: black, indigo, violet, magenta-red, orange, yellow, white. Maps
chosen for colour-vision deficiency are available as well:

- cividis, designed for deuteranopia and protanopia;
- viridis, magma and inferno, which are perceptually uniform;
- grayscale.

Overlay accents switch colour to stay visible on the selected map.
Verdicts never rely on colour alone; every state carries a text label and
an icon.

![The cividis colour map](docs/cividis.png)

**Screen readers.** The layout uses landmarks: library navigation, the
spectrogram, the analysis panel and the cursor readout. Every canvas is
exposed as an image with a text description of what it shows, including the
visible range and the detected cut-off. A polite live region announces the
verdict when a file loads and the view once a zoom or pan settles. All icon
buttons are labelled. The spectrogram, library rows and album scan rows are
keyboard focusable, and a skip link leads straight to the spectrogram.

## HTTP API

The web interface is a client of a small JSON and binary API that can also
be scripted. Every `path` parameter is relative to `LIBRARY_ROOT`.

| Endpoint | Returns |
|---|---|
| `GET /api/ls?path=` | Folders and audio files, with size and modification time |
| `GET /api/roots` | Top-level volumes and their disk usage |
| `GET /api/search?q=&limit=` | Matches from the library index |
| `GET /api/info?path=` | Metadata and the lowpass, codec and hi-res analysis |
| `GET /api/stats?path=` | Loudness, true peak, DR, clipping, bit usage, stereo and per-channel data |
| `GET /api/scan?path=` | One NDJSON line per track in a folder, streamed as each finishes |
| `GET /api/stft?path=&t0=&t1=&f0=&f1=&cols=&rows=&fft=&win=&scale=&ch=` | A uint8 dB matrix for a viewport, with metadata in `X-Meta` |
| `GET /api/wave?path=&t0=&t1=&cols=&ch=` | Min and max peaks per column as float32 |
| `GET /api/gonio?path=&t0=&t1=&size=` | Goniometer density |
| `GET /api/audio?path=[&format=flac]` | The file with Range support, or a FLAC transcode |
| `GET /api/spectrogram?path=&start=&dur=&ch=` | SoX spectral PNG |

```sh
curl -s 'http://127.0.0.1:4748/api/info?path=music/Artist/Album/01.flac' | jq .analysis.verdict
curl -sN 'http://127.0.0.1:4748/api/scan?path=music/Artist/Album'
```

## Development

The backend is a single Python file using numpy, ffmpeg and SoX, managed with
[uv](https://docs.astral.sh/uv/). The frontend is React, TypeScript, Vite and
Tailwind CSS with Radix-based components. Everything is bundled into the
image, fonts included, so the page loads nothing from third-party hosts.

```sh
uv sync                 # Python dependencies from uv.lock
make web                # build the UI into web/dist
make dev                # API on :4748 against ./library, Vite dev server on :5173
make check              # ruff, prettier, eslint, tsc and the test suite
make hooks-install      # lefthook: format on commit, Conventional Commits, check on push
```

The tests need `ffmpeg` and `sox` on the path. They generate their own audio
and need no network.

| Area | Tool |
|---|---|
| Python dependencies | uv |
| Python lint and format | ruff |
| Python tests | pytest |
| Web lint | eslint (typescript-eslint, react-hooks, jsx-a11y) |
| Web format | prettier with the Tailwind plugin |
| Container | hadolint, Trivy, multi-arch buildx |
| Dependencies | Renovate |

### Releases

Versions follow `0.0.x` while the project is pre-1.0. Commits on `main` use
[Conventional Commits](https://www.conventionalcommits.org/).
[release-please](https://github.com/googleapis/release-please) collects them
into a release pull request that updates `CHANGELOG.md` and the version.
Merging that pull request tags the release. The tag builds and pushes the
GHCR image with an SBOM and build provenance attestation. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Security

The application has no authentication. Bind it to loopback and put a reverse
proxy with authentication, or a private network such as Tailscale, in front
of it. Do not publish it on `0.0.0.0`.

Paths are resolved with `realpath` and confined to `LIBRARY_ROOT`, so a
symbolic link cannot escape it. The container runs as a non-root user on a
read-only root filesystem with all capabilities dropped, and the library
mounts are read-only. The only writable locations are the two tmpfs mounts.
