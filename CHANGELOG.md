# Changelog

## [0.0.8](https://github.com/fishingpvalues/simpleaudiospectral/compare/v0.0.7...v0.0.8) (2026-11-12)


### Bug Fixes

* **progress:** estimate unstarted stages from this machine's speed ([6398b17](https://github.com/fishingpvalues/simpleaudiospectral/commit/6398b1713499f20815a7e5afcc78f06b0db5a453))

## [0.0.7](https://github.com/fishingpvalues/simpleaudiospectral/compare/v0.0.6...v0.0.7) (2026-11-12)


### Bug Fixes

* **progress:** learn the time scale from computing stages ([d1855b8](https://github.com/fishingpvalues/simpleaudiospectral/commit/d1855b8aabd6ab4fb5a572a971dad5cf6746921f))


### Performance

* one probe per file, bit usage from the decoded PCM ([c0a34b0](https://github.com/fishingpvalues/simpleaudiospectral/commit/c0a34b0b8c2b6eb9bd91a36254c10098f835aeb7))

## [0.0.6](https://github.com/fishingpvalues/simpleaudiospectral/compare/v0.0.5...v0.0.6) (2026-11-12)


### Features

* real analysis progress, event stream and one-call analysis API ([8a8e86a](https://github.com/fishingpvalues/simpleaudiospectral/commit/8a8e86ad8ae0cfbad1bf9b23c02d90c131467358))
* two-factor authentication for browser logins ([2b7b4b1](https://github.com/fishingpvalues/simpleaudiospectral/commit/2b7b4b1992a3b2b1e24e46c05dbf2608d000cc29))


### Bug Fixes

* 416 on malformed Range, refuse proxy trust without a key ([165135f](https://github.com/fishingpvalues/simpleaudiospectral/commit/165135fbfb467377ad08ac288904126d3bea8cc2))
* **docker:** install Debian security updates over the base image ([9798b1c](https://github.com/fishingpvalues/simpleaudiospectral/commit/9798b1c91f521e234b3da519afdd1ba59759d62c))
* trust forwarded proto only from trusted proxies, throttle TOTP ([7740ff4](https://github.com/fishingpvalues/simpleaudiospectral/commit/7740ff44831a9dab3dc34a43e36fe6420e1928b1))


### Performance

* sequential spill blocks, workers sized to the CPU quota ([9e03d6d](https://github.com/fishingpvalues/simpleaudiospectral/commit/9e03d6d6249de04f156c24c58e43316fe39095f9))

## [0.0.5](https://github.com/fishingpvalues/simpleaudiospectral/compare/v0.0.4...v0.0.5) (2026-09-24)


### Features

* **analysis:** verdicts state the measured evidence in one short sentence ([dfb1cbd](https://github.com/fishingpvalues/simpleaudiospectral/commit/dfb1cbd8367fc0909227553965dfea4b57196e35))


### Bug Fixes

* concurrent requests for one SoX image no longer fail with 500 ([dfb1cbd](https://github.com/fishingpvalues/simpleaudiospectral/commit/dfb1cbd8367fc0909227553965dfea4b57196e35))


### Refactoring

* src/ package for the backend, small modules for the UI ([dfb1cbd](https://github.com/fishingpvalues/simpleaudiospectral/commit/dfb1cbd8367fc0909227553965dfea4b57196e35))

## [0.0.4](https://github.com/fishingpvalues/simpleaudiospectral/compare/v0.0.3...v0.0.4) (2026-09-24)


### Features

* **security:** optional API key with login, lockout and hardened HTTP ([f5215f1](https://github.com/fishingpvalues/simpleaudiospectral/commit/f5215f1a08ee9c4b042f8132aa1544aad3201de3))
* **ui:** encoder lowpass lines from encoder sources, chosen per encoder ([f5215f1](https://github.com/fishingpvalues/simpleaudiospectral/commit/f5215f1a08ee9c4b042f8132aa1544aad3201de3))


### Bug Fixes

* keep 24-bit precision when piping non-native formats to SoX ([f5215f1](https://github.com/fishingpvalues/simpleaudiospectral/commit/f5215f1a08ee9c4b042f8132aa1544aad3201de3))
* stop the API when make dev exits ([f5215f1](https://github.com/fishingpvalues/simpleaudiospectral/commit/f5215f1a08ee9c4b042f8132aa1544aad3201de3))
* **ui:** report playback that fails even after the FLAC transcode ([f5215f1](https://github.com/fishingpvalues/simpleaudiospectral/commit/f5215f1a08ee9c4b042f8132aa1544aad3201de3))

## [0.0.3](https://github.com/fishingpvalues/simpleaudiospectral/compare/v0.0.2...v0.0.3) (2026-09-23)


### Features

* every measurement is exact over the whole file ([4fb0cbe](https://github.com/fishingpvalues/simpleaudiospectral/commit/4fb0cbec3d1826a560d342d7af4d28c4611a426f))
* **ui:** analysis progress for long files ([98d2bf0](https://github.com/fishingpvalues/simpleaudiospectral/commit/98d2bf0075826108a7fe01f00f8fc0ca6cccdffa))

## [0.0.2](https://github.com/fishingpvalues/simpleaudiospectral/compare/v0.0.1...v0.0.2) (2026-09-23)


### Bug Fixes

* MP3 lowpass in a 48 kHz file was reported as a resample ([2128022](https://github.com/fishingpvalues/simpleaudiospectral/commit/2128022d328c8d021ff3bb0cb7fabaf38b687758))

## 0.0.1 (2026-09-23)


### Features

* **ui:** explanations for every parameter and metric, version in header ([7b29d45](https://github.com/fishingpvalues/simpleaudiospectral/commit/7b29d45257e4bc21e799ca9ce31b17c08de1879d))


### Bug Fixes

* bound memory for long files (disk-backed PCM, one-pass summary) ([d56f71a](https://github.com/fishingpvalues/simpleaudiospectral/commit/d56f71a743e9f0d75b0ee3d5bd1a7eff96401c59))
* **docker:** drop pip, ensurepip and the uv cache from the runtime image ([ac2c077](https://github.com/fishingpvalues/simpleaudiospectral/commit/ac2c077f40816731dceaa162e0a3083e6ddbaf68))

## Changelog
