"""SQLite: one file, plain tables. Standard library only."""
import datetime as dt
import secrets
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS songs (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  archived_at TEXT
);
CREATE TABLE IF NOT EXISTS versions (
  id INTEGER PRIMARY KEY,
  song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  filename TEXT NOT NULL UNIQUE,                    -- the stored original (random name), never modified
  orig_filename TEXT NOT NULL,
  mime TEXT NOT NULL,
  size INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  duration_s REAL,
  sample_rate INTEGER,
  channels INTEGER,
  codec TEXT,
  peaks TEXT,                                       -- JSON list of 0-255, or '[]' = could not measure
  lufs REAL,                                        -- integrated loudness (EBU R128), for loudness-matched comparison
  offset_ms INTEGER NOT NULL DEFAULT 0,             -- where this file's "time zero" sits against the others, in milliseconds
  analysis_status TEXT NOT NULL DEFAULT 'pending',  -- pending | ready | failed
  play_filename TEXT,                               -- a FLAC copy for browsers that cannot play the original (ALAC)
  play_status TEXT NOT NULL DEFAULT 'none'
);
CREATE INDEX IF NOT EXISTS versions_song ON versions (song_id, created_at);
CREATE TABLE IF NOT EXISTS links (
  id INTEGER PRIMARY KEY,
  song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
  token TEXT NOT NULL UNIQUE,                       -- the secret in the link (128 random bits)
  label TEXT NOT NULL DEFAULT '',                   -- who it is for, your note ("Dana")
  allow_comments INTEGER NOT NULL DEFAULT 1,
  versions_mode TEXT NOT NULL DEFAULT 'all' CHECK (versions_mode IN ('all', 'latest')),
  created_at TEXT NOT NULL,
  open_count INTEGER NOT NULL DEFAULT 0,
  first_opened_at TEXT,
  last_opened_at TEXT
);
CREATE TABLE IF NOT EXISTS comments (
  id INTEGER PRIMARY KEY,
  song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
  version_id INTEGER REFERENCES versions(id) ON DELETE SET NULL,
  t_ms INTEGER NOT NULL,
  name TEXT NOT NULL,
  body TEXT NOT NULL,
  key_hash TEXT,                                    -- sha256 of a random key the commenter's browser keeps: lets them edit or delete their own comment
  is_owner INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  edited_at TEXT,
  link_id INTEGER REFERENCES links(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS comments_song ON comments (song_id, t_ms);
"""
VERSION = 1


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_token():
    return secrets.token_urlsafe(16)


def connect(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")       # safe with WAL, and fewer disk syncs on the slow volume
    return conn


def init(path):
    conn = connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    have = conn.execute("PRAGMA user_version").fetchone()[0]
    if have > VERSION:
        raise RuntimeError(f"{path} was made by a newer version of this app (schema {have} > {VERSION})")
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {VERSION}")
    conn.commit()
    conn.close()
