# Storage for Version Control

Version Control keeps **all of its data** (audio, database, backups, restore folder) on the shared plain data volume, at `/mnt/data/version-control/{data,backup,restore}`; its program files stay on the boot disk.
The set-up of the volume itself (partitioning, `/etc/fstab`, the `.volume-ok` marker, moving data, expanding later, rebuilding after a wipe) is the same for every app and lives in one place:
**`docs/STORAGE.md` in the `personal-site` repo** (and `RESTORE.html`, section B3). It replaces the earlier version of this file, which described a 40 GB volume mounted at `/var/version-control`.

What is specific to Version Control:
- **The installer** (`doas sh ~/version-control/deploy/install.sh --check`, then without `--check`) stops before creating anything unless `/mnt/data` is mounted and holds `/mnt/data/.volume-ok`. The service script
  refuses to start without it (`rc_pre`), and so does the app itself (`VERSIONCONTROL_REQUIRE_VOLUME=1` with `VERSIONCONTROL_VOLUME_MARKER=/mnt/data/.volume-ok`), so audio can never silently fill the 25 GB boot disk.
- **Backups hard-link the audio** into `/mnt/data/version-control/backup`: no extra space, and the audio survives "Delete forever". This needs `data` and `backup` on the **same filesystem**, which is why they sit side by side
  under `/mnt/data`. It does **not** protect against losing the volume: pull `/mnt/data/version-control/backup` to your computer with FreeFileSync.
- **Capacity (my arithmetic):** 24-bit/96 kHz stereo WAV is about 34.6 MB/min, so a 4-minute version is about 138 MB and five versions of one song about 0.7 GB. On the 100 GB volume (about 85 GB for apps after a 15 GB `/pub/`
  partition, shared with Riffbox and music-share) that is roughly 120 such songs if it had the volume to itself, about 250 at 44.1 kHz/24-bit. Expanding later: see the shared guide.
- This app was never installed on the old 40 GB volume, so there is nothing to migrate: install it after the volume is set up.
