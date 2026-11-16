# Storage: turning the 40 GB "encrypted" Vultr volume into plain storage for Version Control

Status: **steps written from `ti.sh` and the plan; none of these OpenBSD commands could be run by the author. Run `--check`/read-only steps first; each destructive step is marked.**
Decision (yours): unencrypted for now. Version Control keeps its audio, database, backups and restore folder on this volume, mounted at `/var/version-control`.

**Do you need to change anything at Vultr? No.** The volume is already attached to your server in the same location. (Look at the Vultr portal, Block Storage, only to confirm it shows "attached" to this server. Its name stays "encrypted" there.)

**This deletes everything currently on the volume.** Do not go past step 2 until you have a copy on your computer and have decided.

| Step | Where | What | Why |
|---|---|---|---|
| 1 | server | `m` (asks your volume passphrase), then `df -h; ls -laR /mnt \| head -60; doas disklabel sd1; doas bioctl softraid0; cat /etc/fstab` | shows what is attached, what is mounted, what is on the volume, and the current `fstab` |
| 2 | server + your computer | Copy everything off `/mnt` with FreeFileSync (Update/Pull direction, not Mirror), compare file counts and `du -sh` on both sides. **STOP and decide.** | the only copy of anything on it is on this volume |
| 3 | server | `m-x` | TI's helper: unmounts and detaches the encrypted layer, freeing the raw disk |
| 4 | server | `echo '/ *' \| doas disklabel -wAT- sd1` | the pattern `ti.sh` uses on `sd2`: a template with one partition using all space (`-w` write, `-A` auto-allocate, `-T-` template from stdin). **Point of no return.** |
| 5 | server | `doas newfs sd1a` | a fresh filesystem on partition `a` |
| 6 | server | `doas disklabel sd1 \| grep duid` | prints a 16-digit hex DUID: a name for the disk that survives device renumbering |
| 7 | server | `doas mkdir /var/version-control; doas cp /etc/fstab /etc/fstab.pre-volume` | the mount point, and a backup of `fstab` |
| 8 | server | `printf '%s.a /var/version-control ffs rw,nodev,nosuid,noexec 1 2\n' YOUR-DUID \| doas tee -a /etc/fstab` | device, mount point, type, options, dump, fsck order. `nodev` no device files, `nosuid` no setuid programs, `noexec` nothing runs from it |
| 9 | server | `doas mount /var/version-control; df -h /var/version-control` | should show about 40 GB on its own device, not on `/`. **Open the Vultr "View Console" first** (step 10 reboots): a bad `fstab` line can stop boot at a prompt; restore `/etc/fstab.pre-volume` from the console |
| 10 | server | `doas touch /var/version-control/.volume-ok`, then `doas reboot` and check `df -h` shows the volume again | the sentinel file lets the installer (`REQUIRE_MOUNT`) and the app (`VERSIONCONTROL_REQUIRE_VOLUME=1`) refuse to run if the volume ever fails to mount, so audio can never silently fill the 25 GB boot disk |
| 11 | server | `doas sh ~/version-control/deploy/install.sh --check`, then without `--check` | the installer creates `_versioncontrol` and the backup/restore folders on the volume |

Housekeeping (nothing is deleted without your yes): TI's `m`, `m-x`, `/mnt` and `/root/my/storageok` stay. `m` will fail harmlessly afterwards (no encrypted layer; untested). `ti.sh` skips storage when its flag files exist.

**After a wiped server** the volume still holds your audio. Do NOT run steps 3-6 (no `disklabel`, no `newfs`). Attach the volume, read its DUID (`doas disklabel sd1 | grep duid`), then do steps 7-11. At TI's storage prompt answer `n`.

**Capacity (my arithmetic):** 24-bit/96 kHz stereo WAV is about 34.6 MB/min, so a 4-minute version is about 138 MB and five versions of one song about 0.7 GB: roughly 55 such songs in 40 GB (about 120 at 44.1 kHz/24-bit). Vultr can grow a volume but not shrink it in place (its docs snippet); growing the filesystem afterwards is untested here.
**Backups:** the in-app "Back up now" hard-links audio into `/var/version-control/backup`: no extra space, and the audio survives "Delete forever". It does **not** protect against losing the volume. Pull `/var/version-control/backup` (and the volume) to your computer with FreeFileSync.
