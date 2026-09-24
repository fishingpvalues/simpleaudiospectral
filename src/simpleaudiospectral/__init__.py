"""simpleaudiospectral: spectral analysis for verifying lossless audio.

The browser renders; this process decodes and does the DSP. Modules by job:

    config      settings from the environment
    library     path confinement, listings, the search index
    pcm         decoded audio, memory-mapped from disk
    dsp         exact whole-file measurements, streamed in chunks
    analysis    lowpass, codec, levels and the verdict; the analysis jobs
    views       what the viewer draws: spectrogram, waveform, goniometer
    soxpng      the SoX spectrogram image
    tools       the ffmpeg, ffprobe and SoX commands
    server      HTTP handler, auth, routes, and the server process
"""
