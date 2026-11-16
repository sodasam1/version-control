"""Extra ffmpeg helpers for the Version Control app. Every call forces the input container (no format guessing) and forbids
network protocols, exactly as media.analyze_audio does."""
import json
import re
import subprocess
from pathlib import Path

from .media import INPUT_FORMAT

_LUFS = re.compile(r"^\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", re.M)
_NET = ["-protocol_whitelist", "file"]


def _fmt(src):
    return INPUT_FORMAT.get(Path(src).suffix.lower())


def probe_audio(ffprobe, src, timeout=60):
    """(ok, {"sample_rate", "channels", "duration_s", "codec"}, error)."""
    fmt = _fmt(src)
    if fmt is None:
        return False, {}, "unsupported file type"
    cmd = [ffprobe, "-v", "error", *_NET, "-f", fmt, "-select_streams", "a:0",
           "-show_entries", "stream=sample_rate,channels,codec_name,duration:format=duration", "-of", "json", str(src)]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True, errors="replace")
        data = json.loads(done.stdout or "{}")
        s = (data.get("streams") or [{}])[0]
        dur = float(s.get("duration") or data.get("format", {}).get("duration") or 0)
        info = {"sample_rate": int(s["sample_rate"]), "channels": int(s["channels"]), "codec": s.get("codec_name", ""), "duration_s": round(dur, 3)}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
        return False, {}, f"probe failed: {exc}"
    return (done.returncode == 0), info, "" if done.returncode == 0 else (done.stderr or "ffprobe failed")[-300:]


def measure_loudness(ffmpeg, src, timeout=900):
    """(ok, integrated LUFS or None, error). Uses ffmpeg's ebur128 filter (EBU R128); no files are written."""
    fmt = _fmt(src)
    if fmt is None:
        return False, None, "unsupported file type"
    cmd = [ffmpeg, "-nostdin", "-hide_banner", "-nostats", *_NET, "-f", fmt, "-i", str(src),
           "-map", "0:a:0", "-vn", "-filter:a", "ebur128", "-f", "null", "-"]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True, errors="replace")
    except subprocess.TimeoutExpired:
        return False, None, "loudness measurement timed out"
    except OSError as exc:
        return False, None, f"could not run ffmpeg: {exc}"
    found = _LUFS.findall(done.stderr or "")
    if done.returncode != 0 or not found:
        return False, None, (done.stderr or "ffmpeg failed")[-300:]
    return True, float(found[-1]), ""          # the summary block at the end repeats the final integrated value


def slice_wav(ffmpeg, src, dst, start_s, end_s, bits=24, timeout=300):
    """Write [start_s, end_s) of src as PCM WAV (bits 16 or 24) to dst. Returns (ok, error). The region is capped at 10 minutes."""
    fmt = _fmt(src)
    if fmt is None:
        return False, "unsupported file type"
    if not (0 <= start_s < end_s) or end_s - start_s > 600 or bits not in (16, 24):
        return False, "bad region"
    codec = "pcm_s24le" if bits == 24 else "pcm_s16le"
    cmd = [ffmpeg, "-nostdin", "-v", "error", "-y", *_NET, "-f", fmt, "-ss", f"{start_s:.4f}", "-t", f"{end_s - start_s:.4f}",
           "-i", str(src), "-map", "0:a:0", "-vn", "-map_metadata", "-1", "-threads", "1", "-c:a", codec, "-f", "wav", str(dst)]
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True, errors="replace")
    except subprocess.TimeoutExpired:
        return False, "slice timed out"
    except OSError as exc:
        return False, f"could not run ffmpeg: {exc}"
    return (True, "") if done.returncode == 0 else (False, (done.stderr or "ffmpeg failed")[-300:])
