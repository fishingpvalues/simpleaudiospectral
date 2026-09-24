# Security Policy

## Supported versions

Only the latest `0.0.x` release is supported. There are no backports while
the project is pre-1.0.

## Reporting a vulnerability

Report privately through
[GitHub security advisories](https://github.com/fishingpvalues/simpleaudiospectral/security/advisories/new).
Do not open a public issue for anything exploitable. Expect an
acknowledgement within a week.

## Threat model

- **Exposure is opt-in.** Without `API_KEY` there is no authentication:
  publish it on loopback or a VPN, or put an authenticating proxy in front.
  With `API_KEY` it can face a LAN or the internet behind HTTPS; see
  [Security in the README](README.md#security) for what the key protects and
  how the lockout, sessions and proxy trust work.
- **It reads, never writes, the library.** Mount it read-only. The container
  runs as a non-root user on a read-only root filesystem with all
  capabilities dropped.
- **It hands files to ffmpeg and SoX.** A malformed file reaches their
  decoders, so keep the image current; Renovate and the Trivy gate in CI are
  there for that.

In scope: a way past the `API_KEY` check or the lockout, a leak of the key or
a session, path traversal out of `LIBRARY_ROOT`, command injection through any
query parameter, a way to write to the host, or denial of service from a
single request.
