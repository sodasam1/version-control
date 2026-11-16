"""Background work after an upload, one file at a time (the server has one CPU): probe the format, measure the waveform and the
loudness, and make a FLAC play copy of Apple Lossless (ALAC), which Chrome and Firefox cannot play."""
import json
import logging
import queue
import threading
from pathlib import Path

from kitaudio import extras, media

from . import db

log = logging.getLogger("versioncontrol")


def process(data_dir, ffmpeg, ffprobe, version_id):
    conn = db.connect(Path(data_dir) / "versioncontrol.db")
    try:
        row = conn.execute("SELECT * FROM versions WHERE id = ?", (version_id,)).fetchone()
        if row is None:
            return
        src = Path(data_dir) / "audio" / row["filename"]
        if row["analysis_status"] == "pending":
            if not ffmpeg:
                conn.execute("UPDATE versions SET analysis_status = 'failed', peaks = '[]' WHERE id = ?", (version_id,))
                conn.commit()
                return
            if ffprobe:
                ok, info, err = extras.probe_audio(ffprobe, src)
                if ok:
                    conn.execute("UPDATE versions SET sample_rate = ?, channels = ?, codec = ? WHERE id = ?", (info["sample_rate"], info["channels"], info["codec"], version_id))
            ok, duration, peaks, err = media.analyze_audio(ffmpeg, src)
            lufs = None
            if ok:
                good, lufs, lerr = extras.measure_loudness(ffmpeg, src)
                if not good:
                    log.warning("loudness failed for version %s: %s", version_id, lerr)
                conn.execute("UPDATE versions SET analysis_status = 'ready', duration_s = ?, peaks = ?, lufs = ? WHERE id = ?", (duration, json.dumps(peaks), lufs, version_id))
            else:
                log.warning("analysis failed for version %s: %s", version_id, err)
                conn.execute("UPDATE versions SET analysis_status = 'failed', peaks = '[]' WHERE id = ?", (version_id,))
            conn.commit()
        if not row["play_filename"] and src.suffix.lower() in (".m4a", ".mp4") and media.mp4_audio_codec(src) == "alac":
            play = row["filename"].rsplit(".", 1)[0] + ".play.flac"
            done, err = media.convert_to_flac(ffmpeg, src, Path(data_dir) / "audio" / play)
            conn.execute("UPDATE versions SET play_status = ?, play_filename = ? WHERE id = ?", ("ready" if done else "failed", play if done else None, version_id))
            conn.commit()
    finally:
        conn.close()


class Worker:
    def __init__(self, data_dir, ffmpeg, ffprobe, inline=False):
        self.data_dir, self.ffmpeg, self.ffprobe, self.inline = data_dir, ffmpeg, ffprobe, inline
        self._q = queue.Queue()
        self._thread = None

    def submit(self, version_id):
        if self.inline:
            process(self.data_dir, self.ffmpeg, self.ffprobe, version_id)
            return
        self._q.put(version_id)
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True, name="versioncontrol-jobs")
            self._thread.start()

    def _run(self):
        while True:
            try:
                vid = self._q.get(timeout=30)
            except queue.Empty:
                return
            try:
                process(self.data_dir, self.ffmpeg, self.ffprobe, vid)
            except Exception:
                log.exception("job for version %s failed", vid)

    def backfill(self):
        conn = db.connect(Path(self.data_dir) / "versioncontrol.db")
        try:
            for (vid,) in conn.execute("SELECT id FROM versions WHERE analysis_status = 'pending' OR (play_status != 'none' AND play_filename IS NULL)").fetchall():
                self.submit(vid)
        finally:
            conn.close()
