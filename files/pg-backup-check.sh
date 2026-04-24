#!/bin/bash
# Weekly integrity check of remote postgres backup repositories.
#
# Two passes per DB:
#   1. `restic check --read-data-subset=1/10` — samples 10% of pack files and
#      fully decodes them, catching bit-rot in the restic repo itself.
#   2. Real restore round-trip into a throwaway `pg_check_<db>` database:
#      fetch the latest snapshot, pg_restore it, assert the restored DB has
#      at least one user table, then drop it. Catches the failure mode where
#      the restic repo is intact but the dump is unusable (schema drift,
#      pg_restore version mismatch, empty backup, etc.).
#
# Skips DBs whose name starts with `pg_check_` (our own temp restore targets)
# so verify artifacts from a mid-run crash don't themselves get verified.
#
# Logs per-DB progress via `logger -t <db>`; aggregate stderr lands under
# SyslogIdentifier=postgres-backup-check. A failure in either pass sets
# FAIL=1 and the unit exits non-zero, which systemd surfaces to journald.
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

verify_restore() {
    local db="$1"
    local staging="/var/tmp/pg-backup-verify-$db"
    local tmpdb="pg_check_$db"

    # Always clean up the temp DB and staging dir on function exit
    # (early-return on failure OR normal completion).
    trap '/usr/bin/dropdb --if-exists "$tmpdb" >/dev/null 2>&1; rm -rf "$staging"' RETURN

    export RESTIC_REPOSITORY="$RESTIC_REPOSITORY_BASE/$db"
    rm -rf "$staging"
    mkdir -p "$staging"

    notify "$db" "restore-verify: restic restore latest -> $staging"
    if ! /usr/bin/restic restore latest --target "$staging"; then
        notify "$db" "restore-verify: restic restore FAILED"
        return 1
    fi

    local dump
    dump=$(/usr/bin/find "$staging" -name "*.dump" -type f | head -1)
    if [ -z "$dump" ]; then
        notify "$db" "restore-verify: no .dump in snapshot"
        return 1
    fi

    /usr/bin/dropdb --if-exists "$tmpdb"
    if ! /usr/bin/createdb "$tmpdb"; then
        notify "$db" "restore-verify: createdb FAILED"
        return 1
    fi

    if ! /usr/bin/pg_restore --no-owner -d "$tmpdb" "$dump"; then
        notify "$db" "restore-verify: pg_restore FAILED"
        return 1
    fi

    local tbl_count
    tbl_count=$(/usr/bin/psql -tAc \
        "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')" \
        "$tmpdb")
    if [ "${tbl_count:-0}" -lt 1 ]; then
        notify "$db" "restore-verify: restored DB has 0 user tables"
        return 1
    fi

    notify "$db" "restore-verify ok ($tbl_count tables)"
}

DBS=$(/usr/bin/psql -tAc "SELECT datname FROM pg_database WHERE datistemplate = false AND datname != 'postgres' AND datname NOT LIKE 'pg_check_%'")

for db in $DBS; do
    check_db "$db" || FAIL=1
    verify_restore "$db" || FAIL=1
done

exit "$FAIL"
