#!/bin/bash
# Weekly integrity check of postgres backups.
#
# Remote mode (RESTIC_REPOSITORY_BASE set), two passes per DB:
#   1. `restic check --read-data-subset=1/10` — samples 10% of pack files and
#      fully decodes them, catching bit-rot in the restic repo itself.
#   2. Restore round-trip of the latest snapshot (see below).
# Local mode (no remote configured): round-trip the newest local dump in
# BACKUP_DIR instead, so restores are still proven before remote is enabled.
#
# The round-trip restores into a throwaway `pg_check_<db>` database, asserts
# at least one user table, then drops it — catches the failure mode where the
# dump exists but is unusable (schema drift, pg_restore version mismatch,
# empty backup, etc.).
#
# Skips DBs whose name starts with `pg_check_` (our own temp restore targets)
# so verify artifacts from a mid-run crash don't themselves get verified.
#
# Logs per-DB progress via `logger -t <db>`; aggregate stderr lands under
# SyslogIdentifier=postgres-backup-check. A failure in any pass sets FAIL=1
# and the unit exits non-zero, which systemd surfaces to journald.
set -u

: "${BACKUP_DIR:?}"

FAIL=0

notify() {
    /usr/bin/logger -t "$1" -p user.info "check: $2"
}

is_excluded() {
    # Same EXCLUDE_DBS contract as pg-backup.sh: DBs excluded from backup
    # have nothing to verify — checking them would fail every run.
    case " ${EXCLUDE_DBS:-} " in
        *" $1 "*) return 0 ;;
    esac
    return 1
}

check_repo() {
    local db="$1"
    export RESTIC_REPOSITORY="$RESTIC_REPOSITORY_BASE/$db"
    notify "$db" "restic check -> $RESTIC_REPOSITORY"
    if ! /usr/bin/restic check --read-data-subset=1/10; then
        notify "$db" "restic check FAILED"
        return 1
    fi
    notify "$db" "check ok"
}

# No `trap ... RETURN` for cleanup anywhere here: a RETURN trap set inside a
# function stays registered globally after it returns, re-fires on the next
# function return where the trapped locals are out of scope, and `set -u`
# then aborts the whole script. Cleanup is explicit wrapper code instead.
restore_dump() {
    # Round-trip $dump into a throwaway pg_check_<db> and assert it has tables.
    # Wrapper guarantees the temp DB is dropped on every exit path.
    local rc=0
    restore_dump_inner "$1" "$2" || rc=1
    /usr/bin/dropdb --if-exists "pg_check_$1" >/dev/null 2>&1
    return "$rc"
}

restore_dump_inner() {
    local db="$1" dump="$2"
    local tmpdb="pg_check_$db"

    # The round-trip transiently materializes a full copy of the DB inside
    # PGDATA — filling that filesystem would crash the live cluster. Require
    # 5x the compressed dump size free (custom-format dumps expand several-
    # fold on restore); a skip is a FAILED verify, so it stays loud instead
    # of rotting silently.
    local pgdata avail_kb need_kb
    pgdata=$(/usr/bin/psql -tAc "SHOW data_directory")
    avail_kb=$(/usr/bin/df -Pk "$pgdata" | /usr/bin/awk 'NR==2 {print $4}')
    need_kb=$(( $(/usr/bin/stat -c %s "$dump") * 5 / 1024 ))
    if [ "${avail_kb:-0}" -lt "$need_kb" ]; then
        notify "$db" "restore-verify SKIPPED: ${avail_kb}kB free on $pgdata, need ${need_kb}kB"
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

verify_remote() {
    # Wrapper guarantees the staging dir is removed on every exit path.
    local rc=0
    verify_remote_inner "$1" || rc=1
    rm -rf "/var/tmp/pg-backup-verify-$1"
    return "$rc"
}

verify_remote_inner() {
    local db="$1"
    local staging="/var/tmp/pg-backup-verify-$db"

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

    restore_dump "$db" "$dump"
}

verify_local() {
    local db="$1"
    local dump
    # Timestamped names sort lexically = chronologically; `$db-*` can't match
    # another DB whose name merely starts with $db (the dash pins the boundary).
    dump=$(/usr/bin/find "$BACKUP_DIR" -name "$db-*.dump" -type f | sort | tail -1)
    if [ -z "$dump" ]; then
        notify "$db" "restore-verify: no local dump in $BACKUP_DIR"
        return 1
    fi
    notify "$db" "restore-verify: newest local dump $dump"
    restore_dump "$db" "$dump"
}

DBS=$(/usr/bin/psql -tAc "SELECT datname FROM pg_database WHERE datistemplate = false AND datname != 'postgres' AND datname NOT LIKE 'pg_check_%'")

for db in $DBS; do
    if is_excluded "$db"; then
        notify "$db" "excluded (EXCLUDE_DBS), skipping"
        continue
    fi
    if [ -n "${RESTIC_REPOSITORY_BASE:-}" ]; then
        check_repo "$db" || FAIL=1
        verify_remote "$db" || FAIL=1
    else
        verify_local "$db" || FAIL=1
    fi
done

# Dead-man's switch, same semantics as pg-backup.sh: absence of the success
# ping means the check stopped running. No-op when the URL is unset.
if [ -n "${CHECK_HEALTHCHECK_URL:-}" ]; then
    [ "$FAIL" -eq 0 ] && HC_URL="$CHECK_HEALTHCHECK_URL" || HC_URL="$CHECK_HEALTHCHECK_URL/fail"
    /usr/bin/curl -fsS -m 10 --retry 3 -o /dev/null "$HC_URL" \
        || /usr/bin/logger -t postgres-backup-check -p user.warning "healthcheck ping failed"
fi

exit "$FAIL"
