# Upload and deploy: music-share update, then Version Control (first install)

Written for the day you come back. Everything here is **ready to do, nothing has been done to your server.** Commands are explained; each destructive or system-file step asks you first.
Not verified by me (no server here): OpenBSD commands, FreeFileSync menus. Every install step starts with `--check`, which changes nothing.

## 0. What you are about to do
| # | Where | What |
|---|---|---|
| 1 | GitHub | Merge **two** branches (the only merges): music-share `music-share-soundcloud-style-polish-and-speed` and version-control `version-control-visual-cohesion-and-deploy-docs` |
| 2 | your computer | Refresh two folders in `server-mirror` from the merged code, run your FreeFileSync deploy job |
| 3 | server | Update music-share (its address becomes `/music-share`; you sign in again once) |
| 4 | server | Install Version Control for the first time |
| 5 | server | Reboot rehearsal, then the checklists |

Already in place (per `docs/TODO.md`): the site login, the data volume at `/mnt/data` (holds `.volume-ok`), upload staging under `~/staging/<app>`.

## 1. Merge the two branches on GitHub
- **music-share:** open `https://github.com/sodasam1/music-share/pull/new/music-share-soundcloud-style-polish-and-speed`, base `main`, create the pull request, merge it. (It is based on today's `main`, so it is a clean merge.)
- **version-control:** open a pull request from `version-control-visual-cohesion-and-deploy-docs` into the repo's default branch and merge it. That one branch **already contains** `version-control-data-on-shared-volume` (your earlier work), so this single merge also finishes TODO T-05.
  This repo has no `main` yet: the default is whichever branch was pushed first. After merging you may rename the default branch to `main` (GitHub: Settings, Branches), as the other repos have (TODO D-04). Either way, the ZIP in step 2 is "the default branch".

## 2. Refresh your mirror folders and upload
1. Download each repo's default branch as a ZIP (Code, Download ZIP). Unpacked, rename the folders to exactly `music-share` and `version-control`.
2. In `server-mirror\home\me\staging\`: delete the old `music-share` folder and put the new one there; put the new `version-control` folder next to it. (Deleting happens only on your computer; the server copy is overwritten by Update.)
3. FreeFileSync job: if pair C covers only `staging\riffbox`, **widen it to the whole `staging` folder** (this is TODO T-10), once:

| Setting | Value |
|---|---|
| Left | `server-mirror\home\me\staging` |
| Right | `/home/me/staging` (same SFTP login as the other pairs) |
| Variant | **Update** (copies new and changed files, never deletes on the server) |
| Exclude | `*\tests\*`, `*\docs\*`, `*\archive\*`, `*.git*`, `*__pycache__*`, `*\.pytest_cache\*`, `*.coverage`, `*.pyc`, `*sync.ffs_db` |

   Run **Compare** and read the preview. Expected, roughly: `music-share` about 35-40 files (a few hundred KB) mostly "update"; `version-control` about 35 files "create"; `riffbox` and `login` unchanged or a few updates. If you see `tests`, `docs`, `.git`, `__pycache__`: stop and fix the exclude list. (Filter syntax is from memory: the preview is the test.) Then **Synchronize**.
4. Confirm on the server (read-only): `ls ~/staging/version-control/deploy ~/staging/music-share/deploy` should show `install.sh`, `appkit.sh`, `app.manifest`. If FreeFileSync cannot replace files in a staging folder, a file there is owned by root: `doas chown -R me:me ~/staging/<app>`.

## 3. Update music-share (its address changes from `/music` to `/music-share`)
```
doas sh ~/staging/music-share/deploy/install.sh --check
doas sh ~/staging/music-share/deploy/install.sh --repair
```
- `--check` prints what it would do: expect "relayd.conf would change" (old `/music` routes replaced by `/music-share`), "MUSICSHARE_BASE_PATH is still /music", and the code files that changed. Nothing is written.
- the real run with `--repair` asks **y** for the relayd change (it validates the new file with `relayd -n` first and keeps `/etc/relayd.conf.pre-musicshare`) and **y** to change the one conf line (keeps `/etc/musicshare.conf.pre-urlchange`). It then copies the code and restarts music-share. The database upgrades itself on start (two new columns for played counts; your tracks are untouched).
- It ends with `PASS: Music share answers on 127.0.0.1:8101`.
- You will be signed out of music-share once (its cookie belongs to the new address): open `https://sanjaysubramanian.com/music-share/studio` and the login sends you through. Links you already sent under `/music/...` stop working (say if you want a redirect).

## 4. Install Version Control (first time)
```
doas sh ~/staging/version-control/deploy/install.sh --check
doas sh ~/staging/version-control/deploy/install.sh
```
- `--check`: expect it to say the data volume is mounted (`/mnt/data` with `.volume-ok`), then list what it would create: packages (all already there), user `_versioncontrol`, folders under `/mnt/data/apps/version-control/{data,backup,restore}`, `/etc/versioncontrol.conf`, the service script, the login registration (its own key), and the relayd routes for `/version-control`. If it stops with "volume is not mounted", mount it first (docs/STORAGE.md); it creates nothing before that check.
- the real run asks **y** before editing `/etc/relayd.conf` (validated, backup `/etc/relayd.conf.pre-versioncontrol`), and ends with `PASS: Version Control answers on 127.0.0.1:8102`.
- Uploads up to 1 GB are allowed by the app; how relayd's timeouts treat a very large upload is **unverified**: try one big file and write down the result (TODO T-15).

## 5. Reboot rehearsal
`doas reboot`, wait a minute, ssh back in: `df -h /mnt/data /var/www/htdocs/pub` (both mounted), `rcctl ls started` (lists `sitelogin`, `riffbox`, `musicshare`, `versioncontrol`), then run the checklists below. This proves the volume and the services come back without you.

## 6. If something goes wrong
- An installer prints `STOP:`: it changed nothing past that line. Read the message.
- Remove an app's routes by hand: `doas rcctl stop versioncontrol; doas rcctl disable versioncontrol`, then `doas vi /etc/relayd.conf`, delete the lines between each `# BEGIN app:version-control` and `# END app:version-control` (three small blocks), `doas relayd -n -f /etc/relayd.conf && doas rcctl reload relayd`. Data is never touched. (An automatic uninstall does not exist yet.)
- Put music-share back to `/music`: `doas cp -p /etc/musicshare.conf.pre-urlchange /etc/musicshare.conf` and `doas cp -p /etc/relayd.conf.pre-musicshare /etc/relayd.conf` (only if you have made no other relayd change since), then `doas rcctl reload relayd; doas rcctl restart musicshare`.

## 7. Version Control checklist (a few key checks, about 5 minutes)
1. `https://sanjaysubramanian.com/version-control/` sends you to the login, then shows **Songs** with the menu at once (no long blank wait).
2. New song, upload two versions (different mixes). After a few seconds each shows its length and a **LUFS** loudness number.
3. Press **Play**, then click the other version button (or press 1 / 2): the sound switches instantly, with no gap and the position keeps going. Tick **Match loudness**: the louder one gets quieter.
4. Create a link, open it in a private window (not signed in): the same round-button look as music-share, both versions switch, and a comment with a name appears on the waveform and after a reload.
5. Back on the owner page press **Back up now** (Backup tab): "Backed up ...". Then on your computer run the pull job for `/mnt/data/apps/version-control/backup` once.

## 8. music-share checklist (after step 3)
1. `/music-share/` (signed in) shows your listed tracks with round play buttons and a **Studio** link top right; signed out there is no Studio link.
2. Studio: the menu (Tracks, Archive, Playlists, Backup) appears at once; drop a file: a progress bar runs; the track appears; mark it **Listed** (Edit) and it shows on the public page.
3. Open a track link in a private window: play, a bar stays at the bottom, press space to pause. Back in the Studio the track says "played 1x".
4. Paste a link into a chat app: the preview shows the title (no image). The Studio's "opened" count does not go up for that preview.
