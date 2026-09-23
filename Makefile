.PHONY: help check lint format test web typecheck dev build run hooks-install

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

check: lint test ## everything CI runs, except the image build

lint:            ## ruff, prettier, eslint, tsc
	uv run ruff format --check .
	uv run ruff check .
	cd web && npm run format:check && npm run lint && npx tsc -b

format:          ## rewrite Python and web sources in place
	uv run ruff format .
	uv run ruff check --fix .
	cd web && npm run format

test:            ## DSP and HTTP tests (need ffmpeg and sox)
	uv run pytest

web:             ## build the UI into web/dist
	cd web && npm ci --no-audit --no-fund && npm run build

dev:             ## API on :4748 against ./library, Vite on :5173
	LIBRARY_ROOT=$${LIBRARY_ROOT:-./library} WEB_DIR=web/dist uv run app.py & cd web && npm run dev

build:           ## container image
	docker build --build-arg VERSION=$$(cat version.txt) -t simpleaudiospectral .

run: build       ## run against MUSIC=/path/to/music
	docker run --rm -p 127.0.0.1:4748:4748 --read-only --tmpfs /cache --tmpfs /tmp \
	  -v "$${MUSIC:?set MUSIC=/path/to/music}:/library/music:ro" simpleaudiospectral

hooks-install:   ## lefthook pre-commit, commit-msg, pre-push
	lefthook install
