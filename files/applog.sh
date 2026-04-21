#!/usr/bin/env bash
# applog — merged journal view for a single app.
#
# Usage: applog <app-name> [journalctl-args...]
#   applog krcg                       # follow mode (default)
#   applog krcg --since '1h ago'      # any journalctl flags pass through
#
# Merges two journalctl streams (parallel followers):
#   journalctl -t <app>                         # SYSLOG_IDENTIFIER — app service, nginx site, db backup
#   journalctl -u postgresql -g '@<app>'        # engine lines scoped to this app's database
#
# A single journalctl can OR two match groups, but -g applies to the union,
# so two followers are needed to keep the postgres-side regex scoped.

set -eu

if [[ $# -lt 1 ]]; then
    echo "Usage: applog <app-name> [journalctl-args...]" >&2
    exit 2
fi

app=$1
shift

args=("$@")
[[ ${#args[@]} -eq 0 ]] && args=(-f)

journalctl "${args[@]}" -t "$app" &
p1=$!
journalctl "${args[@]}" -u postgresql -g "@${app}" &
p2=$!

trap 'kill "$p1" "$p2" 2>/dev/null || true' INT TERM EXIT
wait
