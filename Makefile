.PHONY: dev web test build run
PY ?= .venv/bin/python

test:            ## DSP + API regression tests (synthetic signals)
	$(PY) -m pytest -q tests

web:             ## build the UI into web/dist
	cd web && npm ci && npm run build

dev:             ## API on :4748 against ./library, UI dev server on :5173
	LIBRARY_ROOT=$${LIBRARY_ROOT:-./library} WEB_DIR=web/dist $(PY) app.py & cd web && npm run dev

build:           ## container image
	docker build -t simpleaudiospectral .

run: build       ## run against MUSIC=/path/to/music
	docker run --rm -p 127.0.0.1:4748:4748 --read-only --tmpfs /cache --tmpfs /tmp \
	  -v "$${MUSIC:?set MUSIC=/path/to/music}:/library:ro" simpleaudiospectral
