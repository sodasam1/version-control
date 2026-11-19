#!/bin/sh
# doas sh ~/staging/version-control/deploy/install.sh --check   (then without --check). Needs the storage volume mounted (RESTORE.html) and the site login installed first.
. "$(dirname "$0")/appkit.sh"
appkit_main "$@"
