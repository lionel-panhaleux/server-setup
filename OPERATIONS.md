# Fleet operations notes

Things that are true about the running fleet and are not derivable from this
repo alone. Kept here because the traps below have each cost real time.

## This repo is not the whole picture

Two ansible repos deploy to these hosts:

- **`server-setup`** (this one) — the foundation: base packages, SSH hardening,
  UFW, the postgres cluster and its backup/verify timers, observability, plus the
  `nginx_site` / `postgres_db` roles shipped as the `lionel_panhaleux.server_setup`
  collection.
- **`myserver`** — a **legacy repo that still owns live deployments**. Do not
  conclude a service is undeployed because it is absent from this repo.

The migration direction is per-app `ansible/` directories that consume the
collection (`krcg-bot` is the model: it was retired from `myserver` once its own
deploy converged). A playbook still in `myserver` is one not yet migrated.

### What still deploys from `myserver`

| Playbook | Group | Host |
|---|---|---|
| `krcg-rulings.yml` | `krcg_gra` | gravelines |
| `v2-krcg-api.yml` | `krcg_gra` | gravelines |
| `timer-bot.yml` | `krcg_gra` | gravelines |
| `archon-website.yml` | `krcg_lim` | frankfurt |
| `codex.yml`, `codex-beta.yml`, `krcg-api.yml`, `krcg-static.yml`, `lackey-static.yml`, `warroom.yml` | `krcg_sbg` | strasbourg |
| `add-pubkey.yml`, `initial.yml`, `setup.yml` | `all` | — |

Its group names differ from this repo's inventory hostnames:

| `myserver` group | here | IP |
|---|---|---|
| `krcg_gra` | gravelines | 152.228.170.51 |
| `krcg_sbg` | strasbourg | 51.178.45.139 |
| `krcg_lim` | frankfurt | 57.129.110.107 |

`krcg_lim` was once `krcg_mun` — the group was renamed, the host did not change.
When reading its git history, a playbook "moving hosts" may be a rename or a real
move; check the IP.

## What the legacy `python-worker` deploys look like on the host

Anything still deployed from `myserver` follows this shape, and it differs from
the collection's conventions in ways that matter:

- venv at `/home/lpanhaleux/projects/<app>`, unit at
  `/etc/systemd/system/<app>.service`, `User=lpanhaleux`, package installed from
  **PyPI** (not a shipped wheel).
- **Secrets are inline `Environment=` lines.** The unit file is a cleartext
  credential store readable by anyone who can run `systemctl cat`. Deleting the
  unit *is* the secret cleanup; rotating means editing the vault and re-running.
- `ExecStart` is `/bin/bash -c 'source venv/bin/activate && <cmd>'`, so **journald
  files these under `SYSLOG_IDENTIFIER=bash`, not the app name**. `journalctl -t
  <app>` returns nothing and reads as "no logs". Use `-u <app>.service`, and key
  Grafana queries on `unit=`, never `tag=`.
- The legacy `postgresql-database` role adds a `local <db> <user> scram-sha-256`
  line to `pg_hba.conf` per (user, database) pair — so one role can appear on
  several lines.

## Backup layout (restic)

`files/pg-backup.sh` builds `RESTIC_REPOSITORY="$RESTIC_REPOSITORY_BASE/<dbname>"`
— **one repo per database name, with no host segment**, and every host shares one
bucket.

- Two hosts with a same-named database **share one repo**. Before treating a repo
  as one host's archive — or deleting it — run
  `restic snapshots --group-by host` and read every group.
- **Never delete the `globals/` prefix.** It holds `pg_dumpall --globals-only` for
  the cluster: every login role and password hash the apps connect with. It is the
  one prefix with no owning database, so an orphan-style sweep can mistake it for
  garbage; `pg-backup.sh` skips it explicitly for that reason.
- Dropping a database does **not** prune its repo. Local dumps age out by date, but
  the bucket prefix stays forever and the nightly run logs an orphan-repo warning
  until it is deleted by hand.
- The hosts have **no named rclone remote**. `pg-backup.sh` builds an on-the-fly
  `:s3,provider=Other,env_auth:` remote from `/etc/postgres-backup/remote.env`;
  mirror that for any manual `rclone` call rather than expecting a config file.

## Retiring a service — the order that bites

1. **Remove its entry from `deploy-targets.yml` first.** `just sync` and
   `just sync-key` re-create each listed repo's GitHub environment and re-push
   `DEPLOY_HOST` / `DEPLOY_HOST_KEY` / `DEPLOY_SSH_KEY`. Deleting the environment
   while the line remains is silently undone by the next sync.
2. **Stop and `disable` the unit before revoking its credential.** These units are
   `Restart=always`; revoking a token first turns the service into a
   `RestartSec=5` auth-failure loop.
3. **For a Discord bot, the slash commands live on Discord, not the host.** Once
   the process is stopped nothing can clear them — delete the application (or
   clear its global commands) or they linger in every guild as dead entries.
4. **Dump and copy off-host before dropping the database.** Use
   `DROP DATABASE <db> WITH (FORCE)` when a connection pool holds idle
   connections (psycopg_pool keeps `min_size=4` open, which blocks a plain drop —
   and those idle connections are not evidence of use).
5. **A postgres role shared by several databases drops only after the last one.**
   Dropping a role that still holds grants elsewhere either fails on dependent
   privileges or succeeds and silently breaks the other app.
6. Edit `pg_hba.conf` with `sed`, not `sudo -e`, if you are driving the host over
   `ssh '… sh -s'`; validate with
   `select * from pg_hba_file_rules where error is not null` **before**
   `pg_reload_conf()`.

## `backup: true` keeps superseded secrets on disk

`krcg-bot/ansible/deploy.yml` sets `backup: true` on the token file, deliberately
— on the first converge the hand-made unit held the only copy of that token.

The backup is **not** more exposed than the live file: `backup_local` copies via
`preserved_copy`, which is `shutil.copy2` plus an explicit `chown`, so mode and
owner carry over (and mtime, which is why a backup can look older than the
converge that made it). The trap is lifecycle, not permissions — **a rotation is
not finished until `/etc/krcg-bot/env.*~` is deleted.** That directory is clean
today only because the token has never been rotated.

## Known, not yet done

Nothing outstanding.
