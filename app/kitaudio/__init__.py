"""kitaudio: shared audio helpers (ffmpeg + standard library only). Lifted from riffbox's media.py and extended.

  media.sniff_audio_ext, mp4_audio_codec, convert_to_flac, summarize_pcm, analyze_audio   (riffbox's, unchanged)
  extras.measure_loudness   integrated loudness in LUFS (ffmpeg's ebur128 filter), for loudness-matched A/B
  extras.slice_wav          cut [start, end) of any file to 16- or 24-bit WAV, for sample-accurate loop playback
  extras.probe_audio        sample rate, channels, duration via ffprobe
"""
from . import media, extras   # noqa: F401
