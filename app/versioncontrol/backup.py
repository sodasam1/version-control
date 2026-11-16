"""Backup and restore. Standard library only, no Flask.

  <backup folder>/db/versioncontrol-YYYYMMDD-HHMMSS.db   one per run, integrity-checked; the newest `keep` are kept
  <backup folder>/audio/                                 every original audio file, never deleted by this program
Audio is HARD-LINKED when the backup folder is on the same disk as the data (the normal case: both on the big volume), so a backup costs no
extra space and still survives "Delete forever" in the app (a file is only gone when its last link is). On a different disk it is copied.
Neither protects against losing the volume itself: pull the backup folder to your computer with FreeFileSync too.
restore() works only into an EMPTY library and never changes the backup it reads.
"""
import datetime as dt
import hashlib
import os
import shutil
import sqlite3
from pathlib import Path


def _place(source, copy):
    """Hard link if the same disk, else copy. Returns True if something new was placed."""
    if copy.is_file() and copy.stat().st_size == source.stat().st_size:
        return False
    tmp = copy.with_name(copy.name + ".partial")
    tmp.unlink(missing_ok=True)
    try:
        os.link(source, tmp)
    except OSError:
        shutil.copy2(source, tmp)
    tmp.replace(copy)
    return True


def backup(data_dir, dest, keep=14, now=None):
    """Returns (database_copy_path, new_audio_files, problems)."""
    data_dir, dest = Path(data_dir), Path(dest)
    db_file = data_dir / "versioncontrol.db"
    if not db_file.is_file():
        raise ValueError(f"no versioncontrol.db in {data_dir}")
    (dest / "db").mkdir(parents=True, exist_ok=True)
    (dest / "audio").mkdir(parents=True, exist_ok=True)
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y%m%d-%H%M%S")
    target = dest / "db" / f"versioncontrol-{stamp}.db"
    partial = target.with_name(target.name + ".partial")
    src, snap = sqlite3.connect(db_file), sqlite3.connect(partial)
    try:
        src.backup(snap)
        check = snap.execute("PRAGMA integrity_check").fetchone()[0]
        names = [r[0] for r in snap.execute("SELECT filename FROM versions")]
    finally:
        snap.close()
        src.close()
    if check != "ok":
        partial.unlink(missing_ok=True)
        raise ValueError(f"database copy failed its integrity check: {check}")
    partial.replace(target)
    placed, problems = 0, []
    for name in names:
        source = data_dir / "audio" / name
        if not source.is_file():
            problems.append(f"audio file missing in the data folder: {name}")
            continue
        placed += _place(source, dest / "audio" / name)
    for old in sorted((dest / "db").glob("versioncontrol-*.db"))[:-max(1, keep)]:
        old.unlink()
    for leftover in (dest / "audio").glob("*.partial"):
        leftover.unlink(missing_ok=True)
    return target, placed, problems


def status(dest):
    dest = Path(dest)
    copies = sorted((dest / "db").glob("versioncontrol-*.db")) if (dest / "db").is_dir() else []
    return {"copies": len(copies), "newest": copies[-1].name if copies else None,
            "audio_files": len(list((dest / "audio").glob("*"))) if (dest / "audio").is_dir() else 0}


def inspect(source):
    source = Path(source)
    dbs = sorted((source / "db").glob("versioncontrol-*.db")) if (source / "db").is_dir() else []
    if not dbs:
        return {"ok": False, "error": "no db/versioncontrol-*.db found in that folder"}
    conn = sqlite3.connect(f"file:{dbs[-1]}?mode=ro&immutable=1", uri=True)
    try:
        n = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        v = conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0]
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"not a usable database: {exc}"}
    finally:
        conn.close()
    return {"ok": True, "songs": n, "versions": v, "db": str(dbs[-1])}


def restore(source, data_dir):
    """Rebuild the library from a backup folder into an empty data folder. Returns (versions_restored, problems).
    Every audio file is checked against the checksum in the database; a mismatch or a missing file is reported, not hidden."""
    source, data_dir = Path(source), Path(data_dir)
    info = inspect(source)
    if not info["ok"]:
        raise ValueError(info["error"])
    live = data_dir / "versioncontrol.db"
    if live.is_file():
        c = sqlite3.connect(live)
        try:
            if c.execute("SELECT COUNT(*) FROM songs").fetchone()[0]:
                raise ValueError("the library is not empty: restore only works into an empty library")
        except sqlite3.OperationalError:
            pass
        finally:
            c.close()
    src = sqlite3.connect(f"file:{info['db']}?mode=ro&immutable=1", uri=True)
    src.row_factory = sqlite3.Row
    try:
        rows = src.execute("SELECT id, filename, sha256, label FROM versions").fetchall()
        (data_dir / "audio").mkdir(parents=True, exist_ok=True)
        problems = []
        for r in rows:
            f = source / "audio" / r["filename"]
            if not f.is_file():
                problems.append(f"missing audio for version '{r['label']}' ({r['filename']})")
                continue
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != r["sha256"]:
                problems.append(f"checksum mismatch for version '{r['label']}' ({r['filename']}): copied anyway, listed here")
            target = data_dir / "audio" / r["filename"]
            if not target.exists():
                shutil.copy2(f, target)
        dst = sqlite3.connect(live)
        try:
            src.backup(dst)
            dst.execute("UPDATE versions SET play_filename = NULL")
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()
    return len(rows), problems
