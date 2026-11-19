# Version Control

Keep every version of a song, flip between them instantly while it plays, loop a section and keep flipping, and let people leave
timestamped comments. For your professional work: lossless originals, no accounts for listeners. Built on the shared kit from the
`personal-site` repo (installer, one site-wide login, the Minimal look, waveforms). Tech Independence rules: audio stays as plain files,
metadata in one SQLite file, Flask + waitress + ffmpeg only, uploaded by hand with FreeFileSync.

## What it does
- **Songs and versions** (owner, site login): upload each version (WAV, FLAC, MP3, M4A, AIFF, ...). Originals are never modified. Each version gets a
  waveform, its format (rate, channels), and its integrated loudness (LUFS, EBU R128). A per-version **offset** (ms) lines up files that start at different moments.
- **Instant A/B**: all versions play in lockstep; switching changes which one you hear with a ~10 ms ramp, no gap and no click. Keys: space, 1-9, L (loop), M (match loudness).
  **Match loudness** turns the louder versions down to the quietest (never boosts, so nothing clips): louder usually sounds better, which hides real differences.
  **Blind** hides the names and shuffles the order.
- **Loops**: Shift-drag on the waveform, or Set A / Set B. Normal loop: about 20-50 ms of slack at the seam. **Exact loop** downloads the looped section of every
  version (30 s at most, as 24-bit WAV) and loops them sample-locked; switching still works.
- **Share links** (no account): one link per person if you like, with a note of who it is for; allow comments or not; show all versions or only the latest; turn a link off for good.
  You see how often each link was opened (your own visits are not counted).
- **Comments**: a name asked when posting (remembered in the browser), a time in the song, plain text. Everyone holding the link sees them as markers on the waveform and in a list.
  A commenter can edit or delete their own comment for 15 minutes; you can delete any. The name "Owner" is reserved for you.
- **Backup / restore**: "Back up now" (database copy, audio hard-linked); restore into an **empty** library from the restore folder, every file checksummed.

## Be honest about the limits
- Browsers do not play bit-perfectly: audio goes through the device's sample rate and the browser's mixer. The original file is always downloadable.
- Comment names are self-asserted: anyone can type any name (except yours). Per-person links tell you who is who more reliably.
- Not tested here: how it sounds, iPhone Safari (it falls back to a "swap" mode with a short gap if the phone refuses several players at once), Firefox, and large uploads through relayd (timeouts unverified).

## Storage and install
Audio, database, backup and restore folders live on the shared data volume at `/mnt/data/apps/version-control/{data,backup,restore}`; the program files stay on the boot disk. The volume's own set-up is in
personal-site `docs/STORAGE.md` (and `docs/STORAGE.md` here lists what is specific to this app).
Install (after the data volume is mounted and the site login is installed: personal-site `RESTORE.html`): upload this folder to `~/staging/version-control`,
`doas sh ~/staging/version-control/deploy/install.sh --check`, then without `--check`. Everyday updates: `--app-files-only`. Settings: `/etc/versioncontrol.conf`
(`VERSIONCONTROL_DATA_DIR`, `_BASE_PATH`, `_BACKUP_DIR`, `_RESTORE_DIR`, `_MAX_UPLOAD_MB` (1024), `_OWNER_NAME`, `_REQUIRE_VOLUME`, `_VOLUME_MARKER`).

## Tests (offline)
```
python3 -m venv /tmp/v && /tmp/v/bin/pip install flask==3.1.3 werkzeug==3.1.9 itsdangerous==2.2.0 waitress==3.0.2 pytest
/tmp/v/bin/python -m pytest -q tests                              # 54 tests (ffmpeg needed for the audio ones)
VENV_PY=/tmp/v/bin/python sh tests/installer/test-install.sh      # installer in test mode, incl. the "volume not mounted" refusals
VC_PY=/tmp/v/bin/python node tests/e2e/smoke.cjs                  # real Chromium: owner page, share page, A/B, loop, exact loop, match, blind, comments
```
The kit under `app/siteauth`, `app/kitaudio`, `static/minimal`, `static/wave`, `deploy/appkit.sh` is vendored from personal-site (`kit.use`).

## Look and feel
Version Control shares its look with music-share: the same header, logo and favicon, round play buttons, chunky waveforms with the times at the ends, the same cards and spacing, light/dark and the accent choices.
`static/listen.css` is that shared look: **the same file lives in both repos (music-share and version-control); keep them identical** (TODO: move it into the shared kit). Nothing social: no accounts, likes or follows; comments are the point of this app and need only a name.
Speed: the Owner page's menu and placeholders are in the HTML (nothing waits for data); static files are cached for a year by content address and served gzipped from memory; the JSON and HTML answers are gzipped; every answer carries a `Server-Timing: app` header
(browser developer tools, Network, Timing) so a slow page can be told apart as slow server or slow network.
Deploying: `docs/DEPLOY.md`.
