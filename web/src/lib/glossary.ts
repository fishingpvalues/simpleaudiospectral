// One sentence or two per term, shown on hover and focus. Written for
// someone checking a rip, not for a DSP engineer: what it measures, and what
// a suspicious value looks like.
export const GLOSSARY = {
  // file
  codec: "The audio format inside the file, as reported by ffprobe. The container extension can lie; this cannot.",
  sampleRate:
    "Samples per second. Half of it (the Nyquist frequency) is the highest frequency the file can hold: 22.05 kHz for CD audio.",
  bitDepth:
    "Bits per sample. In brackets: bits actually used / bits declared, from SoX. 16/24 means a 16-bit master padded into a 24-bit file.",
  channels: "Number of audio channels in the file.",
  duration: "Length of the decoded audio, measured from the samples rather than the container header.",
  bitrate:
    "Average data rate of the file. For lossless audio this varies with the music; it says nothing about quality on its own.",
  size: "File size on disk.",
  encoder: "Encoder tag written into the file. Missing or rewritten tags are common, so treat it as a hint.",
  sideLevel:
    "Level of the side signal (L-R) relative to the mid (L+R). Around -100 dB or lower means both channels are identical: mono in a stereo file.",
  // lowpass
  cutoff:
    "Frequency of the steepest level drop above 10 kHz in the loudest frames. Lossy encoders remove everything above a fixed frequency; lossless audio has no such wall.",
  drop: "How far the level falls across the cut-off, over about 500 Hz. Codec walls drop 25-60 dB; a natural roll-off is gentle.",
  extent: "Highest frequency still carrying content within 80 dB of the midrange.",
  hfVar:
    "Frame-to-frame spread of the 16-19 kHz band, in dB. LAME MP3 codes that band only when bits are left over, so it jumps around (13-23 dB). AAC, Opus, Vorbis and lossless stay steady (under 8).",
  shelf:
    "An energy step at 16 kHz in the typical frame. Low and mid bitrate MP3 starve the band above 16 kHz, which shows as a shelf.",
  hires:
    "Level above 24 kHz relative to 10-20 kHz. A real hi-res recording has content there; an upsampled 44.1/48 kHz file is empty far below -45 dB.",
  crt: "A steady tone at 15.625 or 15.734 kHz is the line whine of a CRT or TV in the room. It is part of the recording, not a codec artifact.",
  // loudness
  dr: "Dynamic range score (TT DR Meter, as in the foobar2000 DR database): the second-highest 3 s peak against the RMS of the loudest 20% of blocks. DR14 and up is dynamic; DR7 and below is heavily compressed.",
  lufs: "Integrated loudness per EBU R128 / ITU-R BS.1770: K-weighted and gated. Streaming services normalise to about -14 LUFS; modern masters often sit at -8 or louder.",
  lra: "Loudness range per EBU Tech 3342: the spread between quiet and loud passages, in LU.",
  truePeak:
    "Peak level between samples, estimated by 4x oversampling (dBTP). Above 0 means the signal clips when converted to analogue or re-encoded.",
  samplePeak: "Highest sample value in dBFS. 0.0 means at least one sample hits digital full scale.",
  rms: "Average signal power in dBFS.",
  noiseFloor: "Lowest RMS level of the file's quietest analysis window, from ffmpeg astats.",
  quietFloor:
    "Noise level in the quietest non-silent 400 ms blocks. A 16-bit master bottoms out near -96 dBFS; a real 24-bit one goes lower.",
  clipping:
    "Runs of three or more consecutive samples at digital full scale. Each run is audible distortion unless it is intentional.",
  flatTop:
    "Runs of three or more samples at the file's own peak when that peak is below full scale: clipped, then turned down.",
  dcOffset:
    "Average sample value. Digital masters sit at 0; a visible offset points at an analogue capture chain or a faulty converter.",
  correlation:
    "Pearson correlation of left and right. +1 is mono, 0 is unrelated channels, negative means one channel is out of phase.",
  effectiveBits: "Bit depth actually exercised by the samples, from ffmpeg astats.",
  drPerChannel:
    "DR score of each channel before averaging. A large difference means the channels were processed differently.",
  rumble:
    "Energy from 5 to 20 Hz relative to 40-400 Hz. Turntable rumble raises it; together with clicks it points at a vinyl source.",
  clicks:
    "Isolated spikes per minute that stand far above their neighbourhood: vinyl clicks and digital glitches, not drum hits.",
  channelCutoffs:
    "Cut-off measured on left, right and side separately. A side channel cut lower than L/R is typical of joint-stereo lossy coding.",
  bitUsage:
    "How often each bit of the integer samples is set, most significant bit on the left. Real audio uses every bit about half the time; bits that are always 0 were never recorded.",
  goniometer:
    "Density plot of mid (vertical) against side (horizontal) for the current view. A vertical line is mono, a horizontal one is out of phase, a wide cloud is real stereo.",
  corrSeries: "Correlation of left and right per second across the track. Dips below zero are phase problems.",
  // viewer controls
  channel:
    "Which signal the spectrogram shows: the mix of both channels, one channel, or the side signal (L-R), which is silent for mono content.",
  scale:
    "Frequency axis: linear spreads the top octave out, where lossy cut-offs live; logarithmic matches how pitch is heard.",
  fft: "FFT window length. Larger values give finer frequency resolution and coarser time resolution. 4096 at 44.1 kHz is 10.8 Hz per bin and 93 ms per frame.",
  window:
    "Taper applied to each FFT frame. Blackman-Harris and Kaiser suppress leakage best, which keeps a codec wall sharp.",
  colormap:
    "Colour mapping from level to colour. The colour-blind safe maps are perceptually uniform and readable with deuteranopia and protanopia.",
  range:
    "Levels mapped to the colour scale. Everything below the floor is black; lowering the floor reveals quieter detail and noise.",
  refs: "Where common encoder settings stop coding, from the encoders' source code and verified by measurement. Choose the encoders in Display settings; a cut-off that sits on one of these lines names its likely source.",
  cutoffLine: "Draws the automatically detected cut-off on the spectrogram.",
  holes:
    "Marks cells in the 16 kHz-to-cut-off band that drop far below what that row usually carries. Lossy codecs drop whole bands per frame, which shows as rectangles.",
  rolloff:
    "Frequency below which 99% of each frame's energy lies. A flat line is an encoder lowpass; a line that moves with the music is a real top end.",
  follow: "Scroll the view to keep the playhead visible during playback.",
  redZoom:
    "Zoom to the loudest 8 seconds and the top of the band, where encoder lowpasses, shelves and holes are easiest to see.",
  exportPng: "Download exactly what is on screen, with title, ruler, waveform and frequency axis.",
  sox: "Render the widely used SoX spectrogram (1800x1025, Kaiser window, 120 dB range), comparable across tools and files.",
  hzPerBin: "Frequency resolution of the current FFT size, and the length of one analysis frame.",
  // album scan
  scanLikely: "Most likely source codec from the cut-off and HF variability, or lossless when there is no wall.",
} as const

export type Term = keyof typeof GLOSSARY
