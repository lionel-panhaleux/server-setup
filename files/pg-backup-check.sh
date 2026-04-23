#!/bin/bash
# Weekly integrity check of remote postgres backup repositories.
# Runs `restic check --read-data-subset=1/10` per-DB — samples 10% of pack
# files and fully decodes them, catching bit-rot without downloading
# everything. Scheduled weekly via postgres-backup-check.timer.
#
# Logs per-DB progress via `logger -t <db>`; aggregate stderr lands under
# SyslogIdentifier=postgres-backup-check.
set -u

if [ -z "${RESTIC_REPOSITORY_BASE:-}" ]; then
    /usr/bin/logger -t postgres-backup-check -p user.warning \
        "remote backup disabled; nothing to check"
    exit 0
fi

FAIL=0

notify() {
    /usr/bin/logger -t "$1" -p user.info "check: $2"
}

check_db() {
    local db="$1"
    export RESTIC_REPOSITORY="$RESTIC_REPOSITORY_BASE/$db"
    notify "$db" "restic check -> $RESTIC_REPOSITORY"
    if ! /usr/bin/restic check --read-data-subset=1/10; then
        notify "$db" "restic check FAILED"
        return 1
    fi
    notify "$db" "check ok"
}

DBS=$(/usr/bin/psql -tAc "SELECT datname FROM pg_database WHERE datistemplate = false AND datname != 'postgres'")

for db in $DBS; do
    check_db "$db" || FAIL=1
done

exit "$FAIL"
