#!/bin/bash
# Cluster-wide postgres backup — iterates every non-template database in the
# cluster, dumps each to its own file (pg_dump -F c), optionally uploads to
# S3-compatible storage via restic (one repo per DB), and prunes locally.
#
# Per-DB progress is logged via `logger -t <db>` so `applog <db>` picks it up
# alongside the app's other syslog streams. pg_dump / restic stderr lands
# under SyslogIdentifier=postgres-backup for a cluster-wide view.
#
# Inputs (env):
#   BACKUP_DIR, RETENTION_DAYS — required
#   Remote upload is enabled by the presence of RESTIC_REPOSITORY_BASE, which
#   comes (along with AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY /
#   RESTIC_PASSWORD / REMOTE_KEEP_{DAILY,WEEKLY,MONTHLY}) from
#   /etc/postgres-backup/remote.env, loaded via the service unit's
#   EnvironmentFile= when remote_backup_enabled is true.
set -u

: "${BACKUP_DIR:?}"
: "${RETENTION_DAYS:?}"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
FAIL=0

notify() {
    /usr/bin/logger -t "$1" -p user.info "backup: $2"
}

backup_db() {
    local db="$1"
    local dump="$BACKUP_DIR/$db-$STAMP.dump"

    notify "$db" "pg_dump -> $dump"
    if ! /usr/bin/pg_dump -F c -f "$dump" "$db"; then
        notify "$db" "pg_dump FAILED"
        return 1
    fi

    if [ -n "${RESTIC_REPOSITORY_BASE:-}" ]; then
        export RESTIC_REPOSITORY="$RESTIC_REPOSITORY_BASE/$db"
        if ! /usr/bin/restic cat config >/dev/null 2>&1; then
            if ! /usr/bin/restic init; then
                notify "$db" "restic init FAILED"
                return 1
            fi
        fi
        notify "$db" "restic backup -> $RESTIC_REPOSITORY"
        if ! /usr/bin/restic backup "$dump"; then
            notify "$db" "restic backup FAILED"
            return 1
        fi
        if ! /usr/bin/restic forget \
               --keep-daily "$REMOTE_KEEP_DAILY" \
               --keep-weekly "$REMOTE_KEEP_WEEKLY" \
               --keep-monthly "$REMOTE_KEEP_MONTHLY" --prune; then
            notify "$db" "restic forget FAILED"
            return 1
        fi
    fi

    # Local prune runs regardless of remote outcome (disk-full prevention).
    /usr/bin/find "$BACKUP_DIR" -name "$db-*.dump" -mtime "+$RETENTION_DAYS" -delete
    notify "$db" "complete"
}

DBS=$(/usr/bin/psql -tAc "SELECT datname FROM pg_database WHERE datistemplate = false AND datname != 'postgres'")

for db in $DBS; do
    backup_db "$db" || FAIL=1
done

exit "$FAIL"
