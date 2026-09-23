# syntax=docker/dockerfile:1.7
# simpleaudiospectral - spectral analysis for verifying lossless audio.
#
# Stage 1 builds the UI (React, Vite, Tailwind, Radix). Everything, fonts
# included, is bundled into web/dist; the page loads nothing from a CDN. It
# runs on the BUILD platform: the output is static files, so a multi-arch
# build does not emulate Node under QEMU.
# Stage 2 is the API: numpy does the DSP (installed from uv.lock), ffmpeg
# decodes any format, SoX renders the exportable spectral PNG.
FROM --platform=$BUILDPLATFORM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.12 AS uv

FROM python:3.14-slim-trixie
ARG VERSION=dev
LABEL org.opencontainers.image.title="simpleaudiospectral" \
      org.opencontainers.image.description="Spectral analysis for verifying lossless audio" \
      org.opencontainers.image.source="https://github.com/fishingpvalues/simpleaudiospectral" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends sox libsox-fmt-mp3 libsox-fmt-base ffmpeg wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
# System interpreter, no venv: the image IS the environment.
ENV UV_PROJECT_ENVIRONMENT=/usr/local UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev --no-install-project && rm /usr/local/bin/uv

# Decoded audio is cached here as memory-mapped float32 (about 1.3 GB per hour
# of stereo 48 kHz). Mount a disk volume on it; a named volume inherits this
# ownership on first use.
RUN mkdir -p /pcm && chown 1000:1000 /pcm
VOLUME ["/pcm"]

COPY app.py ./
COPY --from=web /web/dist ./web
ENV APP_VERSION=${VERSION}

EXPOSE 4748
HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
    CMD ["wget", "-q", "-T", "8", "-O", "/dev/null", "http://127.0.0.1:4748/api/health"]

USER 1000:1000
CMD ["python3", "/app/app.py"]
