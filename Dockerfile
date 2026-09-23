# simpleaudiospectral - RED-grade spectral analysis over the music library.
#
# Stage 1 builds the UI (React + Vite + Tailwind + shadcn/radix); everything,
# fonts included, is bundled into web/dist - the page loads nothing from a CDN.
# Stage 2 is the DSP/API: numpy does the viewport STFT, ffmpeg decodes any
# format, SoX renders the classic exportable spectral PNG.
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.14-slim-trixie
RUN apt-get update \
    && apt-get install -y --no-install-recommends sox libsox-fmt-mp3 libsox-fmt-base ffmpeg wget \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir numpy==2.3.3

COPY app.py /app/app.py
COPY --from=web /web/dist /app/web

EXPOSE 4748
HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
    CMD wget -q -T 8 -O /dev/null http://127.0.0.1:4748/api/ls || exit 1

USER 1000:1000
CMD ["python3", "/app/app.py"]
