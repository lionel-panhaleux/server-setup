#!/bin/bash
# Cluster-wide postgres backup — iterates every non-template database in the
# cluster, dumps each to its own file (pg_dump -F c), dumps cluster globals
# (pg_dumpall --globals-only), optionally uploads to S3-compatible storage via
# restic (one repo per DB, plus one for globals), and prunes locally.
#
# Per-DB progress is logged via `logger -t <db>` so `applog <db>` picks it up
# alongside the app's other syslog streams. pg_dump / restic stderr lands
# under SyslogIdentifier=postgres-backup for a cluster-wide view.
#
# Inputs (env):
#   BACKUP_DIR, RETENTION_DAYS — required
#   BACKUP_HEALTHCHECK_URL — optional dead-man's-switch ping (healthchecks.io
#   style: GET on success, GET <url>/fail on failure), from healthcheck.env.
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

restic_push() {
    # Upload $file to the per-name restic repo and apply remote retention.
    local name="$1" file="$2"
    export RESTIC_REPOSITORY="$RESTIC_REPOSITORY_BASE/$name"
    if ! /usr/bin/restic cat config >/dev/null 2>&1; then
        if ! /usr/bin/restic init; then
            notify "$name" "restic init FAILED"
            return 1
        fi
    fi
    notify "$name" "restic backup -> $RESTIC_REPOSITORY"
    if ! /usr/bin/restic backup "$file"; then
        notify "$name" "restic backup FAILED"
        return 1
    fi
    if ! /usr/bin/restic forget \
           --keep-daily "$REMOTE_KEEP_DAILY" \
           --keep-weekly "$REMOTE_KEEP_WEEKLY" \
           --keep-monthly "$REMOTE_KEEP_MONTHLY" --prune; then
        notify "$name" "restic forget FAILED"
        return 1
    fi
}

backup_db() {
    local db="$1"
    local dump="$BACKUP_DIR/$db-$STAMP.dump"

    notify "$db" "pg_dump -> $dump"
    if ! /usr/bin/pg_dump -F c -f "$dump" "$db"; then
        # Drop the partial file so restic doesn't upload garbage
        # and it doesn't sit around for $RETENTION_DAYS.
        rm -f "$dump"
        notify "$db" "pg_dump FAILED"
        return 1
    fi

    if [ -n "${RESTIC_REPOSITORY_BASE:-}" ]; then
        restic_push "$db" "$dump" || return 1
    fi

    # Local prune runs regardless of remote outcome (disk-full prevention).
    /usr/bin/find "$BACKUP_DIR" -name "$db-*.dump" -mtime "+$RETENTION_DAYS" -delete
    notify "$db" "complete"
}

backup_globals() {
    # Per-DB dumps exclude cluster globals (login roles + password hashes,
    # role memberships): without them a full-cluster restore has no roles for
    # the apps to connect as. The file carries password hashes — it stays in
    # the 0750 postgres-owned BACKUP_DIR like the dumps.
    local dump="$BACKUP_DIR/globals-$STAMP.sql"

    notify globals "pg_dumpall --globals-only -> $dump"
    if ! /usr/bin/pg_dumpall --globals-only -f "$dump"; then
        rm -f "$dump"
        notify globals "pg_dumpall FAILED"
        return 1
    fi

    if [ -n "${RESTIC_REPOSITORY_BASE:-}" ]; then
        restic_push globals "$dump" || return 1
    fi

    /usr/bin/find "$BACKUP_DIR" -name "globals-*.sql" -mtime "+$RETENTION_DAYS" -delete
    notify globals "complete"
}

DBS=$(/usr/bin/psql -tAc "SELECT datname FROM pg_database WHERE datistemplate = false AND datname != 'postgres'")

for db in $DBS; do
    backup_db "$db" || FAIL=1
done
backup_globals || FAIL=1

# Dead-man's switch: a backup that silently stops running pages by ABSENCE of
# the success ping; failures ping the /fail endpoint for immediate alerting.
# No-op when the URL is unset.
if [ -n "${BACKUP_HEALTHCHECK_URL:-}" ]; then
    [ "$FAIL" -eq 0 ] && HC_URL="$BACKUP_HEALTHCHECK_URL" || HC_URL="$BACKUP_HEALTHCHECK_URL/fail"
    /usr/bin/curl -fsS -m 10 --retry 3 -o /dev/null "$HC_URL" \
        || /usr/bin/logger -t postgres-backup -p user.warning "healthcheck ping failed"
fi

exit "$FAIL"
