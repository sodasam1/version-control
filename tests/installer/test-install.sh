#!/bin/sh
# Runs deploy/install.sh in test mode against a copy of your real relayd.conf (no OpenBSD needed).
#   VENV_PY=/path/to/python-with-flask sh tests/installer/test-install.sh
set -eu
cd "$(dirname "$0")/../.."
FIX=$(pwd)/tests/installer/fixtures; W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
fail=0; ok() { echo "PASS: $*"; }; bad() { echo "FAIL: $*"; fail=1; }
export DOAS_USER=me APPKIT_TEST_PYTHON="${VENV_PY:-python3}"
mkdir -p "$W/up"; cp -R app static deploy "$W/up/"; find "$W/up" -name __pycache__ -prune -exec rm -rf {} +
R="$W/root"; mkdir -p "$R/etc"; cp "$FIX/relayd.pristine.conf" "$R/etc/relayd.conf"; export APPKIT_TEST_ROOT="$R"
A="sh $W/up/deploy/install.sh"
$A --check > "$R/c0" 2>&1 && bad "--check passed with no volume mounted" || { grep -q 'does not exist' "$R/c0" && ok "no volume: it stops and says so, even in --check"; }
mkdir -p "$R/mnt/data"
$A --yes > "$R/o0" 2>&1 && bad "installed without the .volume-ok file" || { grep -q '.volume-ok' "$R/o0" && [ ! -e "$R/etc/versioncontrol.conf" ] && [ ! -e "$R/etc/rc.d/versioncontrol" ] && [ ! -d "$R/mnt/data/apps/version-control" ] && ok "volume without .volume-ok: stops before creating anything (no files land on the boot disk)"; }
touch "$R/mnt/data/.volume-ok"
$A --check > "$R/c" 2>&1; [ ! -e "$R/etc/versioncontrol.conf" ] && ok "--check writes nothing" || bad "--check wrote something"
$A --yes > "$R/o1" 2>&1 || { bad "install failed"; cat "$R/o1"; }
[ -d "$R/mnt/data/apps/version-control/data" ] && [ -d "$R/mnt/data/apps/version-control/backup" ] && [ -d "$R/mnt/data/apps/version-control/restore" ] && ok "data, backup and restore folders are created on the volume" || bad "folders"
grep -q '^rc_pre() {$' "$R/etc/rc.d/versioncontrol" && grep -q ' on /mnt/data type ' "$R/etc/rc.d/versioncontrol" && ok "service script refuses to start unless /mnt/data is mounted and holds .volume-ok" || bad "rc_pre guard"
grep -q 'daemon_flags="-m waitress --listen=127.0.0.1:8102 --threads=4 wsgi:app"' "$R/etc/rc.d/versioncontrol" && grep -q 'daemon_user="_versioncontrol"' "$R/etc/rc.d/versioncontrol" && grep -q 'daemon_execdir="/usr/local/version-control/app"' "$R/etc/rc.d/versioncontrol" && ok "service script: port 8102, user _versioncontrol" || bad "rc.d"
grep -q '^VERSIONCONTROL_REQUIRE_VOLUME=1$' "$R/etc/versioncontrol.conf" && grep -q '^VERSIONCONTROL_DATA_DIR=/mnt/data/apps/version-control/data$' "$R/etc/versioncontrol.conf" && grep -q '^VERSIONCONTROL_VOLUME_MARKER=/mnt/data/.volume-ok$' "$R/etc/versioncontrol.conf" && ok "conf: data on the volume, and the app itself refuses to start without it" || bad "conf"
for need in '<versioncontrol> { 127.0.0.1 }' 'path "/version-control" forward to <versioncontrol>' 'path "/version-control/\*" forward to <versioncontrol>' 'forward to <versioncontrol> port 8102'; do
  [ "$(grep -c "$need" "$R/etc/relayd.conf")" = 1 ] && ok "relayd has exactly one: $need" || bad "relayd: $need"
done
grep -q 'site login is not installed yet' "$R/o1" && ok "without the login service it holds back and says so" || bad "missing login handling"
"$APPKIT_TEST_PYTHON" app/siteauth/keys.py init --dir "$R/etc/site-auth" --no-chown >/dev/null
$A --yes > "$R/o2" 2>&1 || { bad "second install failed"; cat "$R/o2"; }
grep -qx 'versioncontrol /version-control' "$R/etc/site-auth/apps.conf" && [ -f "$R/etc/site-auth/keys/versioncontrol.key" ] && ok "once the login exists the app registers itself with its own key" || bad "registration"
cp "$R/etc/relayd.conf" "$R/r1"; cp "$R/etc/site-auth/keys/versioncontrol.key" "$R/k1"; $A --yes > "$R/o3" 2>&1
cmp -s "$R/r1" "$R/etc/relayd.conf" && cmp -s "$R/k1" "$R/etc/site-auth/keys/versioncontrol.key" && ok "a third run changes nothing" || bad "not idempotent"
[ -z "$(find "$W/up" -name __pycache__)" ] && ok "the upload folder stays free of __pycache__" || bad "pycache"
[ "$fail" = 0 ] && echo "ALL PASSED" || { echo "SOME FAILED"; exit 1; }
