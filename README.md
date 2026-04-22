# server-setup

Ansible playbooks for Debian/Ubuntu server provisioning. Installs base packages, hardens SSH, configures UFW firewall, and sets up nginx + certbot.

## Prerequisites

- A Debian/Ubuntu server with root SSH access (for initial user setup)
- [uv](https://docs.astral.sh/uv/) installed locally, then run `uv sync` to install Ansible and dev tools
- [just](https://just.systems/) for running sync recipes
- [gh](https://cli.github.com/) CLI, authenticated, for pushing variables/secrets to GitHub

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

`deploy-targets.conf` maps GitHub repos to inventory hostnames:

```
lionel-panhaleux/krcg-api=api
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

Consumer app `requirements.yml`:

```yaml
- src: https://github.com/lionel-panhaleux/server-setup.git
  name: server-setup
  version: main
```

Consumer playbook (proxy example):

```yaml
- hosts: all
  become: true
  vars:
    service_name: krcg-api       # flows to both nginx_site_name and postgres_db_name
  roles:
    - role: server-setup/nginx_site
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

### `postgres_db`

Creates a postgres database and owning role, and installs a daily `pg_dump` systemd timer alongside it. Requires the `community.postgresql` collection (`ansible-galaxy collection install community.postgresql`).

Setup (default `tasks/main.yml`):

```yaml
- hosts: all
  become: true
  vars:
    service_name: krcg           # also used by nginx_site_name; override postgres_db_name only if they diverge
  roles:
    - role: server-setup/postgres_db
      vars:
        postgres_db_user: krcg
        postgres_db_password: "{{ vault_postgres_db_password }}"
```

The role's main task also installs `{{ postgres_db_name }}-db.service` + `{{ postgres_db_name }}-db.timer`. Unit name and `OnCalendar=` expression override via `postgres_db_backup_unit_name` and `postgres_db_backup_schedule`. Dumps land in `/var/backups/postgres/<db>-<timestamp>.dump` in pg_dump's custom format (binary, compressed, restorable with `pg_restore`); dumps older than `postgres_db_backup_retention_days` (default `7`) are pruned after each run.

Restore is destructive — it drops and recreates the DB:

```yaml
- include_role:
    name: server-setup/postgres_db
    tasks_from: restore
  vars:
    postgres_db_name: krcg
    postgres_db_user: krcg
    postgres_db_backup_file: /var/backups/postgres/krcg-20260421T030000.dump
```

Web-app timeouts are applied to the database at setup: `statement_timeout=15s`, `idle_in_transaction_session_timeout=60s`, `lock_timeout=5s`. Override per-app via the role vars, or per-transaction from the app with `SET LOCAL statement_timeout = '10min'` for batch jobs.

#### Remote backup to Scaleway Object Storage (opt-in)

Each scheduled dump can be uploaded via [restic](https://restic.net) to an S3-compatible bucket (Scaleway, R2, B2…). restic encrypts, deduplicates, and keeps its own snapshot history — so local retention (`postgres_db_backup_retention_days`, default 7) can stay short while the cloud copy covers months via `keep-daily/weekly/monthly`.

**One-time Scaleway setup.** Create an Object Storage bucket (e.g. in `fr-par`) and an IAM API key scoped to it. Generate a restic password separately (`openssl rand -base64 32`) — losing it means losing the backups. Store all three as vault-encrypted vars in `inventory/group_vars/servers/vault.yml` (create the `servers/` directory if needed; Ansible merges every `.yml` in it into the `servers` group's vars):

```yaml
vault_remote_backup_access_key: "SCWXXXXXXXXXXXXXX"
vault_remote_backup_secret_key: "..."
vault_remote_backup_restic_password: "..."
```

Encrypt with `ansible-vault encrypt inventory/group_vars/servers/vault.yml`. Configure Ansible to find the password (`vault_password_file` in `ansible.cfg`, `--vault-password-file`, or `--ask-vault-pass`); for the GitHub workflow, add `ANSIBLE_VAULT_PASSWORD` as a secret and pass `--vault-password-file` in the step.

The two sides are provisioned independently, because consumer app repos install this collection via Galaxy and never read this repo's inventory.

**Provision the shared creds on the server** by adding to `inventory/group_vars/servers/vars.yml` in *this* repo and re-running `setup.yml` — it writes `/etc/postgres-backup/remote.env` (mode 0640, `root:postgres`) from the vault secrets:

```yaml
remote_backup_enabled: true     # host-level flag, consumed only by setup.yml
```

**Opt each DB in** from the consumer app's own playbook — the `postgres_db` role reads only its own vars, so the flag must be set there explicitly:

```yaml
postgres_db_remote_backup_enabled: true
postgres_db_remote_backup_bucket: "your-bucket-name"
postgres_db_remote_backup_endpoint: "https://s3.fr-par.scw.cloud"   # or nl-ams, pl-waw
```

On the next timer run each DB's service will: `pg_dump` → `restic backup` → `restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune`, then local prune as `ExecStopPost=` — so the local prune runs regardless of whether the remote steps succeeded (disk-full prevention). restic failures are still visible via `systemctl status <db>-db` / journald. The restic repo is created on first run (`ExecStartPre` is self-initializing), one repo per DB at `s3:<endpoint>/<bucket>/<postgres_db_name>`.

Verify and restore from any host with restic installed:

```bash
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... RESTIC_PASSWORD=...
export RESTIC_REPOSITORY=s3:https://s3.fr-par.scw.cloud/your-bucket/krcg
restic snapshots
restic restore latest --target /tmp/krcg-restore
```

### Log conventions across roles

Each app uses a single identifier (e.g. `krcg`) at every layer:

- `service_name` at the play level — default for both `nginx_site_name` (nginx syslog tag) and `postgres_db_name` (database name)
- `postgres_db_name` — appears as `@krcg` in postgres engine log lines; `postgres_db_log_tag` defaults to it and becomes `SyslogIdentifier` on the backup timer
- `SyslogIdentifier=` on the app's systemd service unit (set by the app's own playbook)

Because all three land in journald under `SYSLOG_IDENTIFIER=krcg`, `journalctl -t krcg` pulls the full app surface in one view. The shared postgres cluster stays under `postgresql.service`, and `setup.yml` sets `log_line_prefix = '[%p] %q@%d '` so every session line starts with `@<dbname>` — scopeable via journald's `-g` regex without shell escaping.

#### `applog` — merged view for one app

`setup.yml` installs `/usr/local/bin/applog`, which tails both halves in parallel:

```bash
applog krcg                          # follow everything for krcg
applog krcg --since '1h ago'         # any journalctl flags pass through
```

It runs, in parallel:

```bash
journalctl -f -t krcg                         # app service + nginx site + backup
journalctl -f -u postgresql -g '@krcg'        # postgres engine lines for krcg's database
```

Narrower atomic queries (run directly when you don't want the merged stream):

```bash
journalctl -u krcg -f                         # app service only
journalctl -u nginx -t krcg -f                # this app's nginx access/error only
journalctl -u postgresql -f                   # full shared postgres engine (all DBs)
```
