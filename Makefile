.PHONY: help install check verify fix type-check test test-cov e2e web dev build run hooks-install

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

install:         ## Python and web dependencies
	uv sync
	cd web && npm ci --no-audit --no-fund

check: verify test ## everything CI runs, except the image build and e2e

verify:          ## lint, format check and type check, changing nothing
	uv run ruff format --check .
	uv run ruff check .
	uv run ty check
	cd web && npm run format:check && npm run lint && npm run typecheck && npm test

fix:             ## rewrite Python and web sources in place
	uv run ruff format .
	uv run ruff check --fix .
	cd web && npm run format

type-check:      ## ty (Python) and tsc (web)
	uv run ty check
	cd web && npm run typecheck

test:            ## DSP and HTTP tests (need ffmpeg and sox)
	uv run pytest

test-cov:        ## tests with branch coverage
	uv run pytest --cov --cov-report=term-missing

e2e: web         ## browser tests: the built UI against a generated library
	cd web && npx playwright test

web:             ## build the UI into web/dist
	cd web && npm ci --no-audit --no-fund && npm run build

dev:             ## API on :4748 against ./library, Vite on :5173
	LIBRARY_ROOT=$${LIBRARY_ROOT:-./library} WEB_DIR=web/dist uv run simpleaudiospectral & api=$$!; \
	trap 'kill $$api 2>/dev/null' EXIT; cd web && npm run dev

build:           ## container image
	docker build --build-arg VERSION=$$(cat version.txt) -t simpleaudiospectral .

run: build       ## run against MUSIC=/path/to/music
	docker run --rm -p 127.0.0.1:4748:4748 --read-only --tmpfs /cache --tmpfs /tmp \
	  -v "$${MUSIC:?set MUSIC=/path/to/music}:/library/music:ro" simpleaudiospectral

hooks-install:   ## lefthook pre-commit, commit-msg, pre-push
	lefthook install
