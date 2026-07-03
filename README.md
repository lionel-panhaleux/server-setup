# server-setup

[![Test](https://github.com/lionel-panhaleux/server-setup/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/lionel-panhaleux/server-setup/actions/workflows/test.yml)

Ansible playbooks for Debian/Ubuntu server provisioning. Installs base packages, hardens SSH, configures UFW firewall, and sets up nginx + certbot.

## Prerequisites

- A Debian/Ubuntu server with root SSH access (for initial user setup)
- [uv](https://docs.astral.sh/uv/) installed locally, then run `uv sync` to install Ansible and dev tools
- [just](https://just.systems/) for running sync recipes
- [gh](https://cli.github.com/) CLI, authenticated, for pushing variables/secrets to GitHub
- Ansible collections: `ansible-galaxy collection install -r requirements.yml`
- (optional but recommended) [pre-commit](https://pre-commit.com/) hooks: `pre-commit install` once per clone

## Inventory

`inventory/hosts` is the single source of truth for server IPs:

```ini
[servers]
api     ansible_host=1.2.3.4
```

Each host has a `host_key` variable in `inventory/host_vars/<name>.yml`:

```yaml
host_key: "1.2.3.4 ssh-ed25519 AAAA..."
```

The setup playbook prints the ready-to-paste `host_key` value at the end of each run.

`inventory/group_vars/servers.yml` pins the default Ansible user and private key for the `[servers]` group, so day-to-day playbook runs don't need `--user` or `--private-key`:

```yaml
ansible_user: deploy
ansible_ssh_private_key_file: ~/.ssh/deploy
```

CLI flags still override these (used by `add-admin.yml` for the initial root login).

## Usage

### 1. Generate SSH keys

Generate one ed25519 keypair per identity (admin user, deploy user). `ssh-keygen` will prompt for a passphrase — leave empty for the deploy key (CI cannot type a passphrase), set one for admin keys.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/lpanhaleux -C "lpanhaleux@$(hostname)"
ssh-keygen -t ed25519 -f ~/.ssh/deploy     -C "deploy@server-setup" -N ""
```

This produces `~/.ssh/<name>` (private) and `~/.ssh/<name>.pub` (public). The `.pub` file is what `add-admin.yml` reads; the private key stays on your machine (or, for the deploy key, is uploaded as a GitHub secret — see [Sync deploy key](#sync-deploy-key-to-github)).

### 2. Add admin users (as root)

Run once per user to create a sudo user with SSH key access. The `--user`/`--private-key` flags override the defaults in `inventory/group_vars/servers.yml` for the initial root-only login:

```bash
ansible-playbook add-admin.yml --limit HOST --user root --private-key ~/.ssh/initial_root_key \
    -e "username=lpanhaleux" -e "ssh_key_file=~/.ssh/lpanhaleux.pub"

ansible-playbook add-admin.yml --limit HOST --user root --private-key ~/.ssh/initial_root_key \
    -e "username=deploy" -e "ssh_key_file=~/.ssh/deploy.pub"
```

### 3. System setup

Hardens SSH (disables root login), installs packages, configures UFW, nginx, and certbot:

```bash
ansible-playbook setup.yml --limit HOST
```

After this step, root SSH access is disabled. Subsequent `add-admin.yml` runs can drop the `--user`/`--private-key` overrides and use the inventory defaults (`deploy` user with `~/.ssh/deploy`).

The playbook also writes the server's SSH host key directly to `inventory/host_vars/<name>.yml`. Commit the change so `just sync` can push it to the deploy-target repos.

### 4. Reboot when required

If the setup playbook ends with `REBOOT REQUIRED`, trigger a graceful reboot and wait for the host to come back:

```bash
ansible HOST -m reboot -b
```

## Deploy targets

`deploy-targets.yml` maps GitHub repos to inventory hostnames:

```yaml
lionel-panhaleux/krcg-api: api
```

### Sync variables to GitHub

Push `DEPLOY_HOST` and `DEPLOY_HOST_KEY` to all repos listed in `deploy-targets.conf`:

```bash
just sync
```

### Sync deploy key to GitHub

Push `DEPLOY_SSH_KEY` as an environment secret to all repos:

```bash
just sync-key ~/.ssh/deploy_key
```

## GitHub Actions

The `setup.yml` and `upgrade.yml` workflows run via `workflow_dispatch` and take the target host as a dropdown input. They read `DEPLOY_SSH_KEY` from secrets and resolve the host key from the committed `inventory/host_vars/<host>.yml`, so no `DEPLOY_HOST_KEY` variable is needed on this repo.

## Reusable roles

### `nginx_site`

Deploys an nginx site with automatic Let's Encrypt issuance and journald logging. Supports three modes:

- `static` — serve files from a directory
- `spa` — static with `index.html` fallback + long-cache for hashed assets (Vite/TS PWAs)
- `proxy` — reverse proxy to a WSGI/ASGI upstream (gunicorn, uvicorn, Unix socket or localhost port)

The roles ship as the `lionel_panhaleux.server_setup` collection (`galaxy.yml`),
installable straight from git. Consumer app `requirements.yml`:

```yaml
collections:
  - name: https://github.com/lionel-panhaleux/server-setup.git
    type: git
    version: main   # or a tag/SHA
```

Consumer playbook (proxy example):

```yaml
- hosts: all
  become: true
  vars:
    service_name: krcg_api       # flows to both nginx_site_name and postgres_db_name (alphanumeric + underscore only — becomes an nginx syslog tag)
  roles:
    - role: lionel_panhaleux.server_setup.nginx_site
      vars:
        nginx_site_domain: api.krcg.org
        nginx_site_type: proxy
        nginx_site_upstream: http://127.0.0.1:8000
        nginx_site_open_api_paths: ["/public/"]     # permissive CORS
        nginx_site_plain_http_paths: ["/health"]    # served over plain HTTP, no redirect
```

`nginx_site_name` defaults to `service_name` — set the latter once at the play level and it flows to the postgres_db role too. Override `nginx_site_name` explicitly only when the site and DB identifiers differ.

Static site: set `nginx_site_type: static` and `nginx_site_root: /var/www/codex`. SPA: `nginx_site_type: spa` and `nginx_site_root: /var/www/warroom`.

All requests for a site are logged to journald under the tag `nginx_<nginx_site_name>`:

```bash
journalctl -t nginx_krcg_api -f
```

### Cluster-wide postgres backup

`setup.yml` installs a single `postgres-backup.timer` that runs `/usr/local/bin/pg-backup` daily. The script iterates every non-template database in the cluster, dumps each to `/var/backups/postgres/<db>-<timestamp>.dump` (pg_dump's custom format — binary, compressed, restorable with `pg_restore`), dumps cluster globals (`pg_dumpall --globals-only` — login roles, password hashes, memberships; without them a full-cluster restore has no roles for the apps to connect as), and prunes local files older than `postgres_backup_retention_days` (default `7`).

New databases created by the `postgres_db` role are picked up automatically on the next timer fire — no re-run needed.

Tune via `inventory/group_vars/servers/vars.yml`:

- `postgres_backup_dir` — default `/var/backups/postgres`
- `postgres_backup_schedule` — default `daily` (any `OnCalendar=` expression)
- `postgres_backup_retention_days` — default `7`

One DB failing doesn't stop the others; the script aggregates failures and exits nonzero so `systemctl status postgres-backup` surfaces the problem.

#### Remote backup to Scaleway Object Storage (opt-in)

Each scheduled dump can be uploaded via [restic](https://restic.net) to an S3-compatible bucket (Scaleway, R2, B2…). restic encrypts, deduplicates, and keeps its own snapshot history per DB — one repo per DB at `s3:<endpoint>/<bucket>/<db>` — so local retention (default 7 days) can stay short while the cloud copy covers months via `keep-daily/weekly/monthly`.

**One-time Scaleway setup.** Create an Object Storage bucket (e.g. in `fr-par`) and an IAM API key scoped to it. Generate a restic password separately (`openssl rand -base64 32`) — losing it means losing the backups. Store all three as vault-encrypted vars in `inventory/group_vars/servers/vault.yml` (create the `servers/` directory if needed; Ansible merges every `.yml` in it into the `servers` group's vars):

```yaml
vault_remote_backup_access_key: "SCWXXXXXXXXXXXXXX"
vault_remote_backup_secret_key: "..."
vault_remote_backup_restic_password: "..."
```

Encrypt with `ansible-vault encrypt inventory/group_vars/servers/vault.yml`. Configure Ansible to find the password (`vault_password_file` in `ansible.cfg`, `--vault-password-file`, or `--ask-vault-pass`); for the GitHub workflow, add `ANSIBLE_VAULT_PASSWORD` as a secret and pass `--vault-password-file` in the step.

**Enable uploads** by adding to `inventory/group_vars/servers/vars.yml` and re-running `setup.yml` — it writes `/etc/postgres-backup/remote.env` (mode 0640, `root:postgres`) from the vault secrets and renders the bucket into the service unit:

```yaml
remote_backup_enabled: true
postgres_remote_backup_bucket: "your-bucket-name"
postgres_remote_backup_endpoint: "https://s3.fr-par.scw.cloud"   # default; fr-par, or nl-ams, pl-waw
postgres_remote_backup_keep_daily: 7
postgres_remote_backup_keep_weekly: 4
postgres_remote_backup_keep_monthly: 12
```

On each timer fire the script loops: for every DB it runs `pg_dump` → `restic backup` → `restic forget --prune` → local prune. Local prune runs regardless of whether the remote steps succeeded (disk-full prevention). Per-DB restic repos are created on first run (`restic init` is self-triggering), isolating pruning and restore surface between DBs.

Verify and restore from any host with restic installed:

```bash
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... RESTIC_PASSWORD=...
export RESTIC_REPOSITORY=s3:https://s3.fr-par.scw.cloud/your-bucket/krcg
restic snapshots
restic restore latest --target /tmp/krcg-restore
```

#### Weekly restore-verify

`setup.yml` also installs `postgres-backup-check.timer` (weekly): with remote backup enabled it runs `restic check --read-data-subset=1/10` per repo (bit-rot detection) and restore-round-trips the latest snapshot; without remote it round-trips the newest local dump. Either way the round-trip goes into a throwaway `pg_check_<db>` database that must contain at least one user table — catching dumps that exist but don't restore. A free-space guard skips (and fails) the round-trip rather than fill the PGDATA filesystem.

#### Failure alerting (opt-in dead-man's switch)

Both scripts optionally ping a [healthchecks.io](https://healthchecks.io)-style URL: `GET <url>` on success, `GET <url>/fail` on failure. Absence of the success ping catches the failure mode logs can't — the timer that silently stopped firing. Set in `inventory/group_vars/servers/vault.yml` (ping UUIDs are capability URLs, so vault them):

```yaml
vault_postgres_backup_healthcheck_url: "https://hc-ping.com/..."         # daily backup
vault_postgres_backup_check_healthcheck_url: "https://hc-ping.com/..."  # weekly check
```

Give the daily check a ~2h grace period and the weekly one a few hours, to absorb timer jitter and run time. Unset = no pings.

### Observability (Grafana Cloud + Alloy)

`tasks/observability.yml` installs [Grafana Alloy](https://grafana.com/docs/alloy/) — a unified agent that replaces node_exporter + Promtail + any local Prometheus/Loki. Alloy ships:

- Node metrics (CPU, memory, disk, network, systemd unit status) via `prometheus.exporter.unix`
- Postgres metrics via `prometheus.exporter.postgres` (using a dedicated `alloy` DB role with `pg_monitor`, connecting over the Unix socket via peer auth — no DB password)
- journald logs via `loki.source.journal`, with per-app labels extracted from `SYSLOG_IDENTIFIER` → `tag` so dashboards can filter by service (`{tag="krcg"}`)

All traffic is outbound to Grafana Cloud endpoints — no inbound UFW port is opened.

**One-time setup.** In [Grafana Cloud](https://grafana.com/auth/sign-in/) create an Access Policy with `metrics:write` and `logs:write` scopes, then an API token (one token covers both — it goes into both `*_password` vars). From the Stack → Details page copy the Prometheus push URL + instance ID (a numeric user) and Loki push URL + instance ID (a different numeric user).

Add the URL placeholders in `inventory/group_vars/servers/vars.yml` with the real endpoints:

```yaml
grafana_cloud_prom_url: "https://prometheus-prod-XX-XXX.grafana.net/api/prom/push"
grafana_cloud_loki_url: "https://logs-prod-XXX.grafana.net/loki/api/v1/push"
```

Add the secrets to `inventory/group_vars/servers/vault.yml` (vault-encrypted):

```yaml
vault_grafana_cloud_prom_user: "NUMERIC_PROM_INSTANCE_ID"
vault_grafana_cloud_prom_password: "glc_..."
vault_grafana_cloud_loki_user: "NUMERIC_LOKI_INSTANCE_ID"
vault_grafana_cloud_loki_password: "glc_..."   # same token reused
```

**Enable** by flipping `observability_enabled: true` in `vars.yml` and re-running `setup.yml`. First run creates the `alloy` postgres role with `pg_monitor`, writes `/etc/alloy/secrets.env` (0600 alloy:alloy), renders `/etc/alloy/config.alloy`, and starts `alloy.service`.

Sanity-check on the host:

```bash
systemctl status alloy
ss -tnp | grep alloy    # outbound to Grafana Cloud only
journalctl -u alloy -f  # config parse errors surface here
```

In Grafana Cloud → Explore, metrics should appear within ~60s (`up{host="strasbourg"}`) and logs within seconds (`{host="strasbourg", tag="krcg"}`).

**Alert rules** (define in Grafana Cloud UI or via Terraform):

- `last_over_time(ALERTS_FOR_STATE{alertname!=""}[5m]) == 0` — meta-check that alert eval is working
- `time() - last_over_time(node_systemd_unit_state{name="postgres-backup.service", state="active"}[25h]) > 0` — daily backup hasn't run in 25h → P1
- `node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes < 0.15` — disk < 15% → P2
- `up{job="integrations/unix"} == 0` — host not scraping for >5m → P1
- `pg_up == 0` or `nginx_up == 0` (via postgres exporter / node exporter systemd unit) — service down → P1

#### CI telemetry (GitHub Actions → Grafana Cloud)

`.github/workflows/otel-reporter.yml` pushes one trace per CI workflow run straight from GitHub's runners to Grafana Cloud's OTLP gateway — no scraper, nothing lands on your VPSes. It's triggered by `workflow_run: completed` so every run emits a span regardless of how it ended (success, failure, cancellation).

**One-time setup.** In the Grafana Cloud portal, open your stack → click **Configure** on the OpenTelemetry tile → **Generate now**. It hands you three env vars; copy two of them into repo-level GitHub secrets verbatim:

- `GRAFANA_OTLP_ENDPOINT` ← `OTEL_EXPORTER_OTLP_ENDPOINT` (e.g. `https://otlp-gateway-prod-XX-X.grafana.net/otlp` — the workflow appends `/v1/traces` itself)
- `GRAFANA_OTLP_HEADERS` ← `OTEL_EXPORTER_OTLP_HEADERS` (already base64-encoded as `Authorization=Basic …`)

The reporter uses the third-party action [`corentinmusard/otel-cicd-action`](https://github.com/corentinmusard/otel-cicd-action) (MIT, source audited, pinned by commit SHA in the workflow). It's not a verified publisher, so if your account/org enforces **Allow specified actions and reusable workflows**, allowlist `corentinmusard/otel-cicd-action@*` under **Settings → Actions → General** (at user level to cover all repos).

Grafana Cloud's Tempo metrics generator turns the spans into `traces_spanmetrics_calls_total`, so alerting is a standard PromQL rule:

```promql
sum by (service_name, span_name) (
  increase(traces_spanmetrics_calls_total{service_name="server-setup-ci", status_code="STATUS_CODE_ERROR"}[15m])
) > 0
```

The same workflow file drops into app repos (krcg-api, codex, etc.) — only the `workflows:` list and `otelServiceName:` need updating per repo.

### `postgres_db`

Creates a postgres database and owning role, applies web-app timeouts, and gets picked up automatically by the cluster-wide backup timer. Requires the `community.postgresql` collection (`ansible-galaxy collection install community.postgresql`).

Setup (default `tasks/main.yml`):

```yaml
- hosts: all
  become: true
  vars:
    service_name: krcg           # also used by nginx_site_name; override postgres_db_name only if they diverge
  roles:
    - role: lionel_panhaleux.server_setup.postgres_db
      vars:
        postgres_db_user: krcg
        postgres_db_password: "{{ vault_postgres_db_password }}"
```

Restore is destructive — it drops and recreates the DB. Local restore takes a `.dump` path:

```yaml
- include_role:
    name: lionel_panhaleux.server_setup.postgres_db
    tasks_from: restore
  vars:
    postgres_db_name: krcg
    postgres_db_user: krcg
    postgres_db_backup_file: /var/backups/postgres/krcg-20260421T030000.dump
```

Remote restore fetches from the host's configured restic repo (requires `setup.yml` to have written `/etc/postgres-backup/remote.env`). Defaults to the latest snapshot; override via `postgres_db_restore_snapshot`:

```yaml
- include_role:
    name: lionel_panhaleux.server_setup.postgres_db
    tasks_from: restore-remote
  vars:
    postgres_db_name: krcg
    postgres_db_user: krcg
    # postgres_db_restore_snapshot: 3a1b9f2c   # optional; defaults to "latest"
```

It materializes the snapshot in a tmp dir, hands the dump to `restore.yml`, and cleans up regardless of outcome.

Web-app timeouts applied at setup: `statement_timeout=15s`, `idle_in_transaction_session_timeout=60s`, `lock_timeout=5s`. Override per-app via the role vars, or per-transaction from the app with `SET LOCAL statement_timeout = '10min'` for batch jobs.

### Log conventions across roles

Each app uses a single identifier (e.g. `krcg`) at every layer:

- `service_name` at the play level — default for both `nginx_site_name` (nginx syslog tag) and `postgres_db_name` (database name)
- `postgres_db_name` — appears as `@krcg` in postgres engine log lines; the cluster-wide `pg-backup` script tags its per-DB progress lines via `logger -t <db>` so backup activity lands under the same identifier
- `SyslogIdentifier=` on the app's systemd service unit (set by the app's own playbook)

Because all three land in journald under `SYSLOG_IDENTIFIER=krcg`, `journalctl -t krcg` pulls the full app surface in one view. The shared postgres cluster stays under `postgresql.service`, and `setup.yml` sets `log_line_prefix = '[%p] %q@%d '` so every session line starts with `@<dbname>` — scopeable via journald's `-g` regex without shell escaping. The backup service itself logs under `SyslogIdentifier=postgres-backup` for a cluster-wide view of `pg_dump` / `restic` stderr.

#### `applog` — merged view for one app

`setup.yml` installs `/usr/local/bin/applog`, which tails both halves in parallel:

```bash
applog krcg                          # follow everything for krcg
applog krcg --since '1h ago'         # any journalctl flags pass through
```

It runs, in parallel:

```bash
journalctl -f -t krcg                         # app service + nginx site + per-DB backup progress
journalctl -f -u postgresql -g '@krcg'        # postgres engine lines for krcg's database
```

Narrower atomic queries (run directly when you don't want the merged stream):

```bash
journalctl -u krcg -f                         # app service only
journalctl -u nginx -t krcg -f                # this app's nginx access/error only
journalctl -u postgresql -f                   # full shared postgres engine (all DBs)
journalctl -t postgres-backup -f              # pg_dump / restic stderr
```
