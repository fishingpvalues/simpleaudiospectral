#!/bin/sh
# Start the real server over a freshly generated library for the browser tests.
# Usage: serve.sh PORT [API_KEY]
set -eu
PORT=$1
KEY=${2:-}
WEB_DIR=$(cd "$(dirname "$0")/.." && pwd)/dist
DIR=$(mktemp -d)
ALBUM="$DIR/library/Artist/Album"
mkdir -p "$ALBUM" "$DIR/cache" "$DIR/pcm"
ff() { ffmpeg -v error -y "$@"; }
SRC="anoisesrc=d=12:c=pink:a=0.3,aformat=channel_layouts=stereo"
ff -f lavfi -i "$SRC" -ar 44100 -sample_fmt s16 "$ALBUM/01 real.flac"
ff -f lavfi -i "$SRC" -ar 44100 -c:a libmp3lame -b:a 128k "$DIR/t.mp3"
ff -i "$DIR/t.mp3" -sample_fmt s16 "$ALBUM/02 transcode.flac"
# WavPack: no browser plays it, so playback goes through the FLAC transcode.
ff -i "$ALBUM/01 real.flac" -c:a wavpack "$ALBUM/03 wavpack.wv"
rm "$DIR/t.mp3"
export LIBRARY_ROOT="$DIR/library" CACHE_DIR="$DIR/cache" PCM_DIR="$DIR/pcm" WEB_DIR PORT
if [ -n "$KEY" ]; then export API_KEY="$KEY"; fi
cd "$(dirname "$0")/../.."
exec uv run --quiet python -m simpleaudiospectral
