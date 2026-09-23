#!/bin/bash
# pg-restore — DESTRUCTIVE: drop a database and recreate it from a backup.
#
# Usage (as postgres): pg-restore <db> <owner> [<file.dump> | <restic snapshot>]
#   sudo -u postgres pg-restore krcg krcg                  # latest remote snapshot
#   sudo -u postgres pg-restore krcg krcg 3a1b9f2c         # a given snapshot
#   sudo -u postgres pg-restore krcg krcg /tmp/krcg.dump   # a local dump
set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: pg-restore <db> <owner> [<file.dump> | <restic snapshot>]" >&2
    exit 2
fi
db=$1
owner=$2
source=${3:-latest}

if [[ $source == *.dump ]]; then
    dump=$source
else
    staging=$(mktemp -d "/tmp/pg-restore-$db.XXXXXX")
    trap 'rm -rf "$staging"' EXIT
    set -a
    . /etc/postgres-backup/remote.env
    set +a
    RESTIC_REPOSITORY="$RESTIC_REPOSITORY_BASE/$db" restic restore "$source" --target "$staging"
    mapfile -t dumps < <(find "$staging" -name '*.dump')
    if [[ ${#dumps[@]} -ne 1 ]]; then
        echo "expected exactly one .dump in snapshot $source, found ${#dumps[@]}" >&2
        exit 1
    fi
    dump=${dumps[0]}
fi

echo "Dropping and recreating $db from $dump"
dropdb --if-exists "$db"
createdb --owner "$owner" "$db"
pg_restore --no-owner --role "$owner" -d "$db" "$dump"
