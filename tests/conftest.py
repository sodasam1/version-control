import io
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from versioncontrol import create_app  # noqa: E402
from siteauth import keys, make_token  # noqa: E402

NOW = time.time()                        # the tests' clock starts at the real time: comments are stamped with real UTC time


class Wall:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


def wav_bytes(seconds=1.0, rate=8000, seed=0):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(bytes(((i + seed) % 251) for i in range(int(seconds * rate) * 2)))
    return buf.getvalue()


@pytest.fixture
def site(tmp_path):
    d = tmp_path / "site-auth"
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "app" / "siteauth" / "keys.py"), *a, "--no-chown"], check=True, capture_output=True)   # noqa: E731
    run("init", "--dir", str(d))
    run("ensure-app", "--dir", str(d), "--app", "versioncontrol", "--path", "/version-control")
    run("ensure-app", "--dir", str(d), "--app", "riffbox", "--path", "/ideas")
    return d


@pytest.fixture
def app(tmp_path, site):
    return create_app({"TESTING": True, "JOBS_SYNC": True, "VERSIONCONTROL_DATA_DIR": str(tmp_path / "data"), "VERSIONCONTROL_BASE_PATH": "/version-control",
                       "VERSIONCONTROL_STATIC_DIR": str(ROOT / "static"), "VERSIONCONTROL_SITE_KEY_FILE": str(site / "keys" / "versioncontrol.key"),
                       "VERSIONCONTROL_INSECURE_COOKIES": "1", "VERSIONCONTROL_BACKUP_DIR": str(tmp_path / "backup"),
                       "VERSIONCONTROL_RESTORE_DIR": str(tmp_path / "restore"), "clock": Wall()})


def owner_cookie(site, app_name="versioncontrol"):
    master = keys.read_first_line(str(site / "master"))
    return make_token(keys.derive(master, app_name, keys.read_first_line(str(site / "generation"))), NOW)


@pytest.fixture
def owner(app, site):
    c = app.test_client()
    c.set_cookie("site_versioncontrol", owner_cookie(site))
    return c


@pytest.fixture
def guest(app):
    return app.test_client()


def upload(client, sid, name="mix.wav", data=None, label=None, **form):
    fields = {"file": (io.BytesIO(data or wav_bytes()), name), **form}
    if label:
        fields["label"] = label
    return client.post(f"/version-control/api/songs/{sid}/versions", data=fields, content_type="multipart/form-data")


@pytest.fixture
def tone(tmp_path):
    """tone(name, seconds, hz, volume_db) -> a stereo 44.1 kHz 16-bit WAV file made with ffmpeg."""
    def make(name="a.wav", seconds=2, hz=440, vol=0):
        p = tmp_path / name
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={hz}:duration={seconds}:sample_rate=44100",
                        "-af", f"volume={vol}dB,pan=stereo|c0=c0|c1=c0", str(p)], check=True)
        return p
    return make
