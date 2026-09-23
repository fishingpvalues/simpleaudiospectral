# Contributing

Small fixes: open a pull request. Anything larger: open an issue first.

## Ground rules

- **Conventional Commits** are enforced by the `commit-msg` hook and decide
  the next version. `fix:` and `feat:` are patch releases while the project is
  pre-1.0; `feat!:` or a `BREAKING CHANGE:` footer is a minor. The subject
  becomes release-note text.
- **Never edit `version.txt` or create a `v*` tag.** release-please owns both.
- `make check` must pass. `make hooks-install` wires the hooks.
- A detection change needs a test that fails without it, ideally on a
  synthetic signal in `tests/test_analysis.py`, plus the measurement that
  motivated it in the commit message.

## Tooling

| Area | Tool |
|---|---|
| Python dependencies | uv (`uv sync`) |
| Python lint and format | ruff |
| Python tests | pytest |
| Web lint | eslint with typescript-eslint, react-hooks and jsx-a11y |
| Web format | prettier with the Tailwind plugin |
| Container | hadolint, Trivy |
