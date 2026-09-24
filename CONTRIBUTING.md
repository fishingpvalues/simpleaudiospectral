# Contributing

Small fixes: open a pull request. Anything larger: open an issue first.

## Ground rules

- **Conventional Commits** are enforced by the `commit-msg` hook and decide
  the next version. `fix:` and `feat:` are patch releases while the project is
  pre-1.0; `feat!:` or a `BREAKING CHANGE:` footer is a minor. The subject
  becomes release-note text; keep it under 72 characters.
- **Never edit `version.txt` or create a `v*` tag.** release-please owns both.
- `make check` must pass, and `make e2e` for anything the UI touches.
  `make hooks-install` wires the hooks.
- A detection change needs a test that fails without it, ideally on a
  synthetic signal in `tests/test_analysis.py`, plus the measurement that
  motivated it in the commit message.
- A new threshold or reference value needs its source: encoder source code,
  a standard, a paper, or a measurement you describe.

## Setup

```sh
make install        # uv sync, npm ci
make dev            # API on :4748 against ./library, Vite dev server on :5173
make verify         # everything CI checks, changing nothing
make fix            # format and autofix
make test           # pytest (needs ffmpeg and sox)
make e2e            # Playwright against the built UI and a generated library
```

## Code map

### Backend: `src/simpleaudiospectral`

| Module | Job |
|---|---|
| `config.py` | Every setting from the environment. Read as `config.NAME` at call time; tests change it with `monkeypatch` or `config.reload()`. |
| `formats.py` | File extensions, content types, which codecs are lossless. |
| `library.py` | Path confinement (`resolve`), directory listings, volumes, the search index. |
| `tools.py` | Every ffmpeg, ffprobe and SoX command line. Nothing else starts a process. |
| `pcm.py` | Decoded audio cached on disk and memory-mapped; one decode per file. |
| `dsp/` | Exact whole-file measurements, each a consumer fed consecutive chunks. One module per measurement; `core.py` holds the chunk size, worker pool and spill limits. |
| `analysis/lowpass.py` | The brick-wall search, 16 kHz shelf, hi-res level. |
| `analysis/verdict.py` | Codec naming and the one-sentence verdict, with the thresholds as named constants. |
| `analysis/levels.py` | DR, clipping, stereo, noise floor. |
| `analysis/external.py` | Loudness (ffmpeg ebur128) and bit usage. |
| `analysis/passes.py` | The file analysis: three sequential passes over the PCM. |
| `analysis/jobs.py` | Background runs, caching, persistence, progress, scan rows. |
| `analysis/direct.py` | The same analysis on in-memory arrays, for tests. |
| `views.py` | Spectrogram tiles, waveform peaks, goniometer for the viewer. |
| `soxpng.py` | The SoX spectrogram image. |
| `server/handler.py` | Responses, security headers, the auth gate, error mapping, dispatch. |
| `server/auth.py` | Key check, signed sessions, lockout, trusted proxies. |
| `server/routes/` | One function per endpoint, `(handler, query) -> None`, grouped by what they serve. The table is in `routes/__init__.py`. |
| `server/app.py` | The server process and `main()`. |

### Frontend: `web/src`

| Path | Job |
|---|---|
| `App.tsx` | Layout and wiring only. |
| `hooks/` | App state: settings, view history, file info, hash route, playback, shortcuts. |
| `components/app/` | Header, toolbar, display settings, status bar, empty state. |
| `components/viewer/` | The spectrogram viewer. `draw/` holds pure canvas functions; `useInteraction.ts` the pointer and wheel handling. |
| `components/analysis/` | The analysis panel, one component per section; `charts.ts` draws its canvases. |
| `components/library/`, `components/scan/` | Library browser and album scan. |
| `lib/` | Pure modules: API client, settings, scales, references, shortcuts. Unit-tested with vitest next to the source (`*.test.ts`). |
| `e2e/` | Playwright tests; `serve.sh` generates a library and starts the real server. |

## Where a change goes

- **A new endpoint:** a function in the matching `server/routes/*.py`, a line
  in `routes/__init__.py`, a test in `tests/test_api.py`, a row in the README
  API table.
- **A new measurement:** a consumer in `dsp/` with a whole-array reference
  test in `tests/test_exact.py`, fed from `analysis/passes.py`.
- **A new detection rule:** `analysis/verdict.py` with a named constant and
  its source, and a test in `tests/test_verdict.py`.
- **A new external command:** a function in `tools.py`; keep `NO_NET` on
  every ffmpeg and ffprobe input.
- **A new setting:** `config.py` and the README configuration table.
- **A UI control:** a component under `components/`, state in a hook, an
  accessible name, and an e2e test that uses it by that name.

## Tooling

| Area | Tool |
|---|---|
| Python dependencies and build | uv, hatchling |
| Python lint, format, types | ruff, ty |
| Python tests | pytest, branch coverage via pytest-cov |
| Web lint, format, types | eslint with typescript-eslint, react-hooks and jsx-a11y; prettier with the Tailwind plugin; tsc |
| Web tests | vitest, Playwright |
| Container | hadolint, Trivy |
